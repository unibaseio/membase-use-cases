"""Story bible: a writing surface backed by one creative memory. "Continue the scene" and "Check
consistency" read the bible from memory first and show the passages they used; "Accept scene
into canon" writes the finished scene to memory once, so what it establishes becomes canon for
every AI connected to the same Memory."""

from __future__ import annotations

import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from demokit import ConfigError, Memory, llm  # noqa: E402
from demokit.memory import is_narration  # noqa: E402
from demokit.web import create_app, run, sse  # noqa: E402

sys.path.insert(0, str(HERE))
from demokit.writes import HostedQueue  # noqa: E402

CONTAINER = "Story Bible"
mem = Memory("04-story-bible", default_mode="hosted")
app = create_app("Story bible", HERE, mode=mem.mode)
writer = HostedQueue(mem, CONTAINER)

CONTINUE = (
    "You are a co-writer continuing a scene of a novel. The story bible passages below are "
    "canon: characters, places, world rules, the style guide and scenes already written. "
    "Continue the draft from exactly where it stops, for two or three short paragraphs. Follow "
    "the style guide strictly, keep every fact consistent with the bible, and draw on specific "
    "details from it (names, objects, rules) where they fit. Give each character only the "
    "habits and traits the bible gives that character, and never use a word the style guide "
    "forbids. At most 120 words. Write only the new prose: no heading, no commentary, do not "
    "repeat the draft."
)
CHECK = (
    "You are the continuity editor for a novel. Compare the draft with the story bible passages, "
    "which are numbered. List every statement in the draft that contradicts a passage: a "
    "character fact, a world rule, a place, or the style guide. Only report contradictions you "
    "can support with a numbered passage: the passage must say something different (a fact, a "
    "habit, a rule, or a word the style guide forbids). Something the bible does not mention "
    "is not a contradiction: a new object, a number, where something is kept, or a character "
    "not doing something the bible says they do sometimes. A passage that only says the bible "
    "has no record of something "
    'supports nothing. Reply with JSON: {"issues": [{"quote": exact words from the draft, '
    '"problem": what the bible says instead, one short sentence of at most 16 words, '
    '"passages": [numbers], '
    '"fix": a corrected wording}]}. Use an empty list when the draft is consistent.'
)


class Draft(BaseModel):
    text: str


class Accept(BaseModel):
    text: str
    title: str = ""


def _draft(text: str) -> str:
    text = text.strip()
    if not text:
        raise HTTPException(400, "Write or paste some of the scene first.")
    return text


TOPICS = (
    "List what a story bible would need to be looked up for this draft: the characters, "
    "places, objects, customs and kinds of events it involves, as short neutral noun phrases "
    '("Ilse\'s drinking habits", "the compass\'s needle", "the tide-bells"). Never '
    'copy a claim from the draft. Reply with JSON: {"topics": [up to 10 phrases]}.'
)


def recall_for(text: str, *, limit: int = 8, style: bool = False) -> dict:
    """Bible passages for a draft.

    The search is asked about the draft's topics, not given the draft: a hosted search is a
    turn in the Memory's session, and text put in a query can come back in a later search's
    results as if it were memory. A draft that says the compass points north must never
    become a bible passage saying so."""
    topics = [
        str(t)
        for t in llm.json_reply(
            [{"role": "system", "content": TOPICS}, {"role": "user", "content": text[-4000:]}]
        ).get("topics")
        or []
    ][:10]
    if style:
        topics.append("the style guide")
    query = "What the story bible says about: " + "; ".join(topics or ["the main characters"])
    recall = mem.recall(query, container=CONTAINER, limit=limit, wait=60)
    seen, hits = set(), []
    for h in recall.hits:
        key = h.content.strip()
        if is_narration(key):
            continue  # "no stored memory about X" is not canon, and must never be cited as such
        if key and key not in seen:
            seen.add(key)
            hits.append(h.as_dict())
    return {
        "query": query,
        "topics": topics,
        "hits": hits,
        "seconds": round(recall.seconds, 2),
        "unheard": recall.unheard,
    }


def numbered(hits: list[dict]) -> str:
    return "\n\n".join(
        f"[{i}] ({h.get('title') or h.get('container_name') or 'bible'}) {h['content']}"
        for i, h in enumerate(hits, 1)
    )


@app.post("/api/continue")
def continue_scene(body: Draft):
    text = _draft(body.text)

    def events():
        recalled = recall_for(text, style=True)
        yield {"type": "memories", **recalled}
        if not recalled["hits"]:
            raise RuntimeError(
                "Memory returned no bible passages, so there is nothing to keep the scene "
                "consistent with. Run seed.py, and wait until the bible is learned."
            )
        prompt = f"Story bible:\n\n{numbered(recalled['hits'])}\n\nDraft so far:\n\n{text}"
        for delta in llm.stream(
            [{"role": "system", "content": CONTINUE}, {"role": "user", "content": prompt}],
            temperature=0.8,
        ):
            yield {"type": "delta", "text": delta}
        yield {"type": "done"}

    return sse(events())


@app.post("/api/check")
def check(body: Draft):
    text = _draft(body.text)

    def events():
        recalled = recall_for(text, limit=10)
        yield {"type": "memories", **recalled}
        if not recalled["hits"]:
            raise RuntimeError(
                "Memory returned no bible passages, so there is nothing to check against. "
                "Run seed.py, and wait until the bible is learned."
            )
        out = llm.json_reply(
            [
                {"role": "system", "content": CHECK},
                {
                    "role": "user",
                    "content": f"Story bible:\n\n{numbered(recalled['hits'])}\n\nDraft:\n\n{text}",
                },
            ]
        )
        issues = []
        for issue in out.get("issues") or []:
            cited = [
                int(n)
                for n in issue.get("passages") or []
                if str(n).isdigit() and 1 <= int(n) <= len(recalled["hits"])
            ]
            if not cited:
                continue  # an issue with no passage behind it is the model's opinion, not canon
            issues.append({**issue, "passages": cited})
        yield {"type": "issues", "issues": issues}
        yield {"type": "done"}

    return sse(events())


def _learned(doc: dict) -> dict:
    """The list endpoint does not say whether a document is learned; the single read does."""
    one = mem.client.documents.get(doc["id"])
    run = one.get("learning_run") or {}
    return {
        "id": doc["id"],
        "title": doc.get("title") or "",
        "custom_id": doc.get("custom_id") or "",
        "learned": bool(one.get("learned")),
        # The container's latest learning run: queued, running, succeeded or failed. A run can
        # end without the document counting as learned (failed, or more arrived mid-run).
        "learning": run.get("status"),
        "run_id": run.get("id"),
        "created_at": doc.get("created_at"),
    }


@app.get("/api/canon")
def canon() -> dict:
    """Everything in the Story Bible container, with whether it has been learned yet."""
    try:
        docs = mem.documents(CONTAINER)
    except ConfigError as e:  # hosted, and the container does not exist yet
        return {"documents": [], "error": str(e)}
    with ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(_learned, docs))
    return {"documents": writer.rows() + rows}


@app.post("/api/accept")
def accept(body: Accept) -> dict:
    """The scene into canon: one hosted write, which starts one learning run. The same text
    accepted twice is the same document (a custom_id from its hash), not a second write.
    Writes wait their turn behind the container's current learning run (see demokit/writes.py)."""
    text = _draft(body.text)
    custom_id = "scene:" + hashlib.sha256(text.encode()).hexdigest()[:16]
    for doc in mem.documents(CONTAINER):
        if doc.get("custom_id") == custom_id:
            return {**_learned(doc), "already": True}
    title = body.title.strip() or llm.chat(
        [
            {
                "role": "system",
                "content": "Give this scene a short title of two to five words. Reply with the title only.",
            },
            {"role": "user", "content": text[:3000]},
        ]
    ).strip().strip('"')
    out = writer.submit(
        custom_id,
        {"title": f"Scene: {title}", "custom_id": custom_id},
        lambda: mem.add_document(
            f"# Scene: {title}\n\n{text}",
            container=CONTAINER,
            title=f"Scene: {title}",
            custom_id=custom_id,
        ),
    )
    # The page follows the scene by its custom_id: a slow folder sync can drop the title and
    # list the document under its file name, scene-<hash>.md.
    return {**out, "title": f"Scene: {title}", "custom_id": custom_id}


def _binder() -> list[dict]:
    """The binder's names: the characters, places, rules and scenes of the bible files that
    seed.py wrote to memory. Names only, for the page to list; no model call ever gets them."""
    import re

    files = {p.stem: p.read_text(encoding="utf-8") for p in sorted((HERE / "bible").glob("*.md"))}
    chars = re.findall(r"^## ([^(\n]+?)\s*(?:\(|$)", files["01-characters"], re.M)
    world = files["02-world"]
    places_part = world.split("## Places", 1)[1].split("## World rules", 1)[0]
    places = re.findall(r"^- \*\*([^*]+)\*\*", places_part, re.M)
    rules = [
        r.rstrip(".").replace(" is never called the sea", ", never named")
        for r in re.findall(r"^\d+\. \*\*([^*]+)\*\*", world, re.M)
    ]
    scenes = [
        re.sub(r"^Scene \d+:\s*", "", t.splitlines()[0].lstrip("# ").strip())
        for k, t in files.items()
        if "scene" in k
    ]
    return [
        {"group": "Characters", "items": chars},
        {"group": "Places", "items": places},
        {"group": "World rules", "items": rules},
        {"group": "Style guide", "items": ["Voice and banned words"]},
        {"group": "Scenes", "items": scenes},
    ]


@app.get("/api/binder")
def binder() -> dict:
    return {"groups": _binder()}


@app.get("/api/connect")
def connect() -> dict:
    """Where another AI reads this same Memory: the hosted MCP address, or the local server."""
    if mem.mode == "hosted":
        base = (os.environ.get("MEMBASE_BASE_URL") or "https://api.app.membase.ai").rstrip("/")
        return {"mcp_url": f"{base}/mcp-http"}
    return {"mcp_url": f"membase --store {mem.path.parent} mcp   (local)"}


if __name__ == "__main__":
    run(app, port=8704)
