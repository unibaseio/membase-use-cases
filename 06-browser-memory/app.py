"""Browser memory: the companion server for the side-panel extension in `extension/`.

The extension holds no Membase key. It sends what is on the page (title, URL, selected text, a
main-text excerpt) to this server on 127.0.0.1, which holds the key, recalls from the user's
memory and answers, or writes the page to the `Browsing` container once. Only the extension and
this server's own page may call it: requests from any other origin are refused.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from demokit import ConfigError, Memory, llm  # noqa: E402
from demokit.memory import is_narration  # noqa: E402
from demokit.web import create_app, run, sse  # noqa: E402

sys.path.insert(0, str(HERE))
from demokit.writes import HostedQueue  # noqa: E402

CONTAINER = "Browsing"
# The ID Chrome gives extension/ when it is loaded unpacked: fixed by the "key" in its manifest.
EXTENSION_ID = os.environ.get("BROWSER_MEMORY_EXTENSION_ID") or "lhojclgfedbhfpkjklfgjgnikckelabe"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}"
LOOPBACK = {"127.0.0.1", "localhost", "[::1]"}
MAX_PAGE_CHARS = 20000

mem = Memory("06-browser-memory", default_mode="hosted")
app = create_app("Browser memory", HERE, mode=mem.mode)
writer = HostedQueue(mem, CONTAINER)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[EXTENSION_ORIGIN],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def only_the_extension(request: Request, call_next):
    """The key behind this server is the user's memory, so a web page the user happens to have
    open must not be able to use it. Two checks: the Host must be loopback (a DNS-rebinding page
    arrives with its own host name), and a browser request must come from the extension or from
    this server's own page. Requests without an Origin (curl, scripts on this machine) pass."""
    host = request.headers.get("host", "")
    hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    if hostname not in LOOPBACK:
        return JSONResponse({"error": f"refused: host {host!r} is not loopback"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin not in (EXTENSION_ORIGIN, f"http://{host}"):
        return JSONResponse(
            {"error": f"refused: origin {origin!r} is not the Browser Memory extension"},
            status_code=403,
        )
    return await call_next(request)


ANSWER = (
    "You help the user with the web page they are looking at, using their own memory: notes "
    "and pages they saved earlier. The memories are numbered. Answer the question from the page "
    "and the memories together. Whenever you use a memory, cite it inline like [2] or [2][5]; "
    "facts from the page itself need no citation. Say plainly "
    "when the memories have nothing on the question rather than guessing. Keep it short, under "
    '70 words: the direct answer in one sentence, then at most three short bullets ("- "). No '
    "preamble, no restating the question, no closing advice."
)


class Page(BaseModel):
    url: str
    title: str = ""
    selection: str = ""
    text: str = ""
    question: str = ""
    icon: str = ""  # the page's own favicon URL, shown beside it in the panel


def _page(body: Page) -> Page:
    if not body.url.strip():
        raise HTTPException(400, "The extension sent no page URL.")
    body.text = re.sub(r"\s+\n", "\n", body.text).strip()[:MAX_PAGE_CHARS]
    body.selection = body.selection.strip()[:4000]
    return body


@app.post("/api/ask")
def ask(body: Page):
    page = _page(body)
    question = page.question.strip() or "What do I already know that relates to this page?"

    def events():
        # The question, the page's title and what the user selected; not the page's text. A
        # hosted search is a turn in the Memory's session, and text put in a query can come
        # back in a later search's results as if it had been remembered.
        query = f"{question}\nAbout the page: {page.title}"
        if page.selection:
            query += f"\nSelected on the page: {page.selection[:300]}"
        recall = mem.recall(query, limit=8, wait=60)
        # "I have no saved forecast…" is the search narrating a miss, not a memory
        hits = with_pages([h for h in recall.hits if not is_narration(h.content)])
        yield {"type": "memories", **recall.as_dict(), "hits": hits}
        memories = "\n".join(
            f"[{i}] {h['content']}"
            + (f" (from the saved page {h['pages'][0]['title']!r})" if h["pages"] else "")
            for i, h in enumerate(hits, 1)
        )
        prompt = (
            f"Memories:\n{memories or '(memory returned nothing)'}\n\n"
            f"The page: {page.title}\nURL: {page.url}\n"
            + (f"Selected text: {page.selection}\n" if page.selection else "")
            + f"Page text (excerpt):\n{page.text[:6000]}\n\nQuestion: {question}"
        )
        answer = ""
        for delta in llm.stream(
            [{"role": "system", "content": ANSWER}, {"role": "user", "content": prompt}]
        ):
            answer += delta
            yield {"type": "delta", "text": delta}
        cited = sorted(
            {
                int(n)
                for group in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", answer)
                for n in group.split(",")
                if 1 <= int(n) <= len(hits)
            }
        )
        yield {"type": "used", "passages": cited}
        yield {"type": "done"}

    return sse(events())


_LINK = re.compile(r"\s*\[\[([^\]]+)\]\]")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _page_for(link: str, docs: list[dict]) -> dict | None:
    """The remembered page a memory's [[link]] names, or None.

    Search results carry no document id: a learned memory ends with a link to a page in the
    Memory's own wiki, named by the learning run. Sometimes that is the document's custom_id
    ("page:ab12..." as [[page-ab12...]]), sometimes a name taken from the title
    ([[corvid-38-daypack]] for "Field test: the Corvid 38 daypack"). A link counts as a page's
    only when it is the custom_id, or every word of it is in exactly one page's title."""
    words = set(link.split("-"))
    by_title = []
    for d in docs:
        if link == _slug(d.get("custom_id") or ""):
            return d
        if len(words) >= 2 and words <= set(_slug(d.get("title") or "").split("-")):
            by_title.append(d)
    return by_title[0] if len(by_title) == 1 else None


def with_pages(hits) -> list[dict]:
    """Each hit with the remembered pages it came from, as title and URL. A link that names no
    remembered page stays in the text as the Memory wrote it."""
    try:
        docs = mem.documents(CONTAINER)
    except ConfigError:
        docs = []
    out = []
    for h in hits:
        row = h.as_dict()
        found = {link: _page_for(link, docs) for link in _LINK.findall(row["content"])}
        row["pages"] = [
            {
                "title": d.get("title") or "",
                "url": (d.get("metadata") or {}).get("url", ""),
                "icon": (d.get("metadata") or {}).get("icon", ""),
            }
            for d in found.values()
            if d
        ]
        row["content"] = _LINK.sub(
            lambda m, found=found: "" if found.get(m.group(1)) else m.group(0), row["content"]
        ).strip()
        out.append(row)
    return out


def _row(doc: dict) -> dict:
    """The list endpoint does not say whether a document is learned; the single read does."""
    one = mem.client.documents.get(doc["id"])
    run = one.get("learning_run") or {}
    return {
        "id": doc["id"],
        "title": doc.get("title") or "",
        "url": (doc.get("metadata") or {}).get("url", ""),
        "icon": (doc.get("metadata") or {}).get("icon", ""),
        "learned": bool(one.get("learned")),
        # The container's latest learning run: queued, running, succeeded or failed. A run can
        # end without the page counting as learned (failed, or more arrived mid-run).
        "learning": run.get("status"),
        "run_id": run.get("id"),
        "created_at": doc.get("created_at"),
    }


def _icon(url: str) -> str:
    """A favicon is kept only as a short http(s) URL: never a data: blob in the metadata."""
    url = url.strip()
    return url if url.startswith(("http://", "https://")) and len(url) < 500 else ""


def _custom_id(url: str) -> str:
    return "page:" + hashlib.sha256(url.strip().encode()).hexdigest()[:16]


@app.post("/api/remember")
def remember(body: Page) -> dict:
    """The page into memory as one document: one hosted write, one learning run. The same URL
    remembered twice is the same document, not a second write. Writes wait their turn behind
    the container's current learning run (see demokit/writes.py)."""
    page = _page(body)
    if not page.text and not page.selection:
        raise HTTPException(400, "The page has no text to remember.")
    custom_id = _custom_id(page.url)
    for doc in mem.documents(CONTAINER):
        if doc.get("custom_id") == custom_id:
            return {**_row(doc), "already": True}
    title = page.title.strip() or page.url
    content = (
        f"# {title}\n\nWeb page: {page.url}\nSaved from the browser on {date.today().isoformat()}.\n\n"
        + (f"Highlighted by the user: {page.selection}\n\n" if page.selection else "")
        + page.text
    )
    return writer.submit(
        custom_id,
        {"title": title, "url": page.url, "icon": _icon(page.icon)},
        lambda: mem.client.add(
            content,
            container=mem.container(CONTAINER),
            title=title,
            custom_id=custom_id,
            metadata={"url": page.url, "kind": "web-page", "icon": _icon(page.icon)},
        ),
    )


@app.get("/api/pages")
def pages() -> dict:
    """The pages in the Browsing container, newest first, with whether each is learned yet."""
    try:
        docs = mem.documents(CONTAINER)
    except ConfigError as e:  # hosted, and the container does not exist yet
        return {"pages": [], "error": str(e)}
    with ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(_row, docs))
    return {"pages": writer.rows() + rows, "extension_id": EXTENSION_ID}


if __name__ == "__main__":
    run(app, port=8706)
