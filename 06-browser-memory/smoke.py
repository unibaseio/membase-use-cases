"""End-to-end check against the real API, through the companion as the extension calls it.

    DEMO_ENV_FILE=.secrets/06-browser-memory.env uv run 06-browser-memory/smoke.py

Serves the three synthetic pages in `pages/` on localhost, reads each the way the side panel
does (title, URL, main text), remembers the trail notes and the pack review, waits until they
are learned, then asks a question on the forecast page that needs both. Also checks that the
companion refuses a web page's origin and a non-loopback Host. Exits non-zero on any failure.
"""

from __future__ import annotations

import functools
import html.parser
import http.server
import json
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import app as demo  # noqa: E402

PAGES_PORT = 18706  # 87NN ports belong to the demos
QUESTION = (
    "I want to hike the loop I saved this weekend, carrying the pack I read about. Which day "
    "should I go, and what do I need to plan for water and gear?"
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_pages() -> str:
    # A fixed port: a page's URL is its identity in memory, so the same page is the same URL
    # on every run (and remembering it again is not a second write).
    port = PAGES_PORT
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(HERE / "pages"))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}"


def serve_companion() -> str:
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(demo.app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.1)
    return f"http://127.0.0.1:{port}"


class _Text(html.parser.HTMLParser):
    """What the panel's extract() sends: the title and the text of article/main."""

    def __init__(self) -> None:
        super().__init__()
        self.title, self.text, self._in, self._tag = "", [], 0, ""

    def handle_starttag(self, tag, attrs):
        self._tag = tag
        if tag in ("article", "main"):
            self._in += 1

    def handle_endtag(self, tag):
        if tag in ("article", "main"):
            self._in -= 1

    def handle_data(self, data):
        if self._tag == "title" and not self.title:
            self.title = data.strip()
        elif self._in and data.strip():
            self.text.append(data.strip())


def read_page(url: str) -> dict:
    p = _Text()
    p.feed(httpx.get(url).raise_for_status().text)
    return {"url": url, "title": p.title, "selection": "", "text": "\n".join(p.text)}


def main() -> None:
    pages, base = serve_pages(), serve_companion()
    ext = {"Origin": demo.EXTENSION_ORIGIN}
    c = httpx.Client(base_url=base, timeout=600)
    print("base:", c.get("/api/info").json()["mode"])
    assert c.get("/").status_code == 200, "companion page did not load"

    # The companion answers the extension and nobody else.
    trail = read_page(f"{pages}/larchmere-ridge-loop.html")
    r = c.post("/api/remember", json=trail, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403, f"a web page's origin was not refused: {r.status_code}"
    r = c.get("/api/pages", headers={"Host": "evil.example"})
    assert r.status_code == 403, f"a non-loopback Host was not refused: {r.status_code}"
    pre = c.options(
        "/api/ask",
        headers={
            **ext,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert pre.headers.get("access-control-allow-origin") == demo.EXTENSION_ORIGIN, pre.headers
    print("refused: another origin (403), a non-loopback Host (403); extension preflight allowed")

    # Two pages in, once each.
    review = read_page(f"{pages}/corvid-38-review.html")
    for page in (trail, review):
        doc = c.post("/api/remember", json=page, headers=ext).raise_for_status().json()
        print(
            f"remembered: {doc['title']} ({'already there' if doc.get('already') else doc.get('status')})"
        )
    again = c.post("/api/remember", json=trail, headers=ext).raise_for_status().json()
    assert again.get("already"), f"remembering the same page twice wrote it twice: {again}"

    started, deadline = time.monotonic(), time.monotonic() + 1200
    while True:
        rows = c.get("/api/pages", headers=ext).raise_for_status().json()["pages"]
        if len(rows) >= 2 and all(
            p["learned"] or p["learning"] not in ("queued", "running", "waiting") for p in rows
        ):
            stuck = [p for p in rows if not p["learned"]]
            if stuck:
                print("WARNING: learning ended without these counting as learned:", stuck)
            break
        assert time.monotonic() < deadline, f"not learned after 20 minutes: {rows}"
        time.sleep(15)
    print(f"learned: {[p['title'] for p in rows]} ({time.monotonic() - started:.0f}s)")

    # A question on a third page that needs both remembered ones.
    forecast = read_page(f"{pages}/larchmere-forecast.html")
    events = []
    with c.stream("POST", "/api/ask", json={**forecast, "question": QUESTION}, headers=ext) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    errors = [e for e in events if e["type"] == "error"]
    assert not errors, errors
    memories = next(e for e in events if e["type"] == "memories")
    used = next(e for e in events if e["type"] == "used")["passages"]
    answer = "".join(e["text"] for e in events if e["type"] == "delta")
    print(f"recalled {len(memories['hits'])} memories in {memories['seconds']}s, cited {used}")
    for n in used:
        hit = memories["hits"][n - 1]
        print(f"  [{n}] {hit['content'][:120]}  <- {[p['title'] for p in hit['pages']]}")
    print("answer:", answer.replace("\n", " ")[:700])
    low = answer.lower()
    assert "tamsin" in low, "the answer did not use the trail notes (Tamsin Spring)"
    assert (
        "rain cover" in low
        or "corvid" in low
        or "1 litre" in low
        or "1 l " in low
        or "1-litre" in low
    ), "the answer did not use the pack review"
    assert "sunday" in low, "the answer did not use the page itself (the forecast)"
    cited = " ".join(memories["hits"][n - 1]["content"] for n in used).lower()
    assert "tamsin" in cited, f"the answer did not cite the memory it used: {used}"
    sources = {p["title"] for n in used for p in memories["hits"][n - 1]["pages"]}
    print("cited pages:", sorted(sources))
    assert "corvid" in cited or "rain cover" in cited, f"no cited memory is from the review: {used}"
    if not {trail["title"], review["title"]} <= sources:
        # Search results carry no document id; the page is read off the memory's wiki link,
        # which the learning run names (see with_pages in app.py).
        print("WARNING: not every cited memory could be traced to its page:", sorted(sources))
    print("OK")


if __name__ == "__main__":
    main()
