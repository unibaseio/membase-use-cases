"""Taste journal: Sam's tastings are memories; the star map shows which ones an answer used.

Log a coffee, tea or wine with notes and a rating. The note is written to Sam's memory, dated by
the day it was tasted. A model also scores it on eight flavor dimensions, which place it as a
star on the map. "What should I try next?" and "My palate" recall tastings from memory first and
answer only from them, citing each recalled tasting by number; the page turns each citation
into the tasting it names and lights its star.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from demokit import ROOT, Memory, llm, mode  # noqa: E402
from demokit.config import DATA  # noqa: E402
from demokit.dated import recall, remember_sessions  # noqa: E402
from demokit.memory import is_narration  # noqa: E402
from demokit.web import create_app, run, sse  # noqa: E402
from demokit.writes import BackgroundWriter  # noqa: E402

DEMO = "09-taste-journal"
USER = (
    "sam"  # one synthetic taster; the local engine keeps their memory in data/09-taste-journal/sam/
)
CONTAINER = "Tastings"
# The answers need a model that knows wine, coffee and tea styles well: gpt-4.1-mini often
# described a tannic Barolo as light. Scoring flavor stays on the default model.
ANSWER_MODEL = os.environ.get("TASTE_ANSWER_MODEL") or "gpt-4.1"
KINDS = ("coffee", "tea", "wine")
DIMS = ("acidity", "sweetness", "bitterness", "body", "fruit", "floral", "earthy", "roast")

SCORE = f"""You score a tasting note on fixed flavor dimensions, each 0-10 (0 = absent,
10 = dominant): {", ".join(DIMS)}. "roast" covers roast, smoke and toast; "earthy" covers earth,
wood, leather, spice and savory; "body" is weight and texture (tannin counts toward body for
wine and tea). Judge from the notes first and the origin and kind second. Reply as JSON:
{{{", ".join(f'"{d}": 0' for d in DIMS)}}}"""

GROUND = """Every claim must rest on the numbered tastings recalled from the taster's memory.
Cite them by number in square brackets right after the claim, e.g. [3] or [3][7]. Cite only
numbers you were given. A tasting's date is the day it was tasted. No generic critic filler."""

NEXT = f"""You are the sommelier in Sam's tasting-journal app, writing Sam a short note on what
to try next, from Sam's own journal. Suggest three specific things to try: each a real,
well-known grape, style or blend from a real region (e.g. "Assyrtiko, Santorini"), never an
invented name. Each must be NEW to Sam: never any recalled tasting again, not even
another producer or vintage of it, and nothing from the same region as one. Pick things whose
typical style (body, tannin, acidity, fruit, oak, smoke) is close to what Sam rated 4-5 and far
from what Sam rated 1-2, and be accurate about each one's typical style.

Write exactly three lines and nothing else, one per suggestion, in this form:
**Name, place** — why, at most 14 words
The why speaks to Sam as "you", like a sommelier across the table: the tasting Sam loved that
it is like, and the one Sam disliked that it avoids. Cite exactly two tastings per line, each
right after the words about it, e.g. "like your Fleurie [4], none of the Shiraz's weight [9]".
No preamble, no summary, no "Certainly". Respect Sam's profile (caffeine, brewing, habits). {GROUND}"""

PALATE = f"""You are the sommelier in Sam's tasting-journal app. In three short sentences (at most
55 words in all), tell Sam what their palate is: what they love, what they avoid, and one
pattern across coffee, tea and wine they may not have noticed. Speak to Sam as "you". No
preamble. {GROUND}"""


# ---- the journal: memory for recall, a JSON file for the map --------------------------------


class Journal:
    """Each tasting's flavor scores (the star's place on the map) and its memory ids, in one
    JSON file next to the person's memory. The tasting itself lives in memory."""

    def __init__(self, user: str) -> None:
        self.path = DATA / DEMO / user / "tastings.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def all(self) -> list[dict]:
        if not self.path.is_file():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, *tastings: dict) -> None:
        with self._lock:
            ids = {t["id"] for t in tastings}
            rows = [t for t in self.all() if t["id"] not in ids] + list(tastings)
            rows.sort(key=lambda t: (t["date"], t["id"]))
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)


def memory_text(t: dict) -> str:
    """How a tasting reads in memory: what, when, how it was liked, and in the taster's words."""
    day = date.fromisoformat(t["date"])
    return (
        f"Tasting on {day.strftime('%A %Y-%m-%d')}: {t['kind']}, {t['name']}"
        + (f" ({t['origin']})" if t.get("origin") else "")
        + f". Rated {t['rating']}/5. Notes: {t['notes'].strip()}"
    )


def score(t: dict) -> dict[str, float]:
    out = llm.json_reply(
        [
            {"role": "system", "content": SCORE},
            {
                "role": "user",
                "content": f"{t['kind']}: {t['name']} ({t.get('origin') or 'origin unknown'})\n"
                f"Notes: {t['notes']}",
            },
        ]
    )
    return {d: max(0.0, min(10.0, float(out.get(d) or 0))) for d in DIMS}


mem = Memory(DEMO, user=USER, default_mode="local")
journal = Journal(USER)
writer = BackgroundWriter()


def where() -> str:
    """The memory directory, as the page shows it."""
    try:
        return str(mem.path.relative_to(ROOT)) + "/"
    except ValueError:
        return str(mem.path) + "/"


def remember(tastings: list[dict]) -> list[dict]:
    """Tastings into memory, each dated by the day it was tasted (written side by side), and
    marked in the journal with their memory ids."""
    sessions = {
        t["id"]: {
            "session_id": f"tasting-{t['id']}",
            "session_date": f"{t['date']}T19:00:00",
            "turns": [{"role": "user", "content": memory_text(t)}],
        }
        for t in tastings
    }
    ids = remember_sessions(mem, list(sessions.values()), container=CONTAINER)
    done = [
        {**t, "in_memory": True, "memory_ids": ids[sessions[t["id"]]["session_id"]]}
        for t in tastings
    ]
    empty = [t["name"] for t in done if not t["memory_ids"]]
    if empty:
        raise RuntimeError(f"the engine kept nothing from {', '.join(empty)}")
    journal.save(*done)
    return done


app = create_app("Taste journal", HERE, mode=mode("local"))


class Tasting(BaseModel):
    kind: str
    name: str
    origin: str = ""
    notes: str
    rating: int = Field(ge=1, le=5)
    date: str = ""


@app.get("/api/tastings")
def tastings() -> dict:
    return {
        "dims": DIMS,
        "tastings": journal.all(),
        "pending": writer.pending,
        "error": writer.error,
        "directory": where(),
        "today": date.today().isoformat(),
    }


@app.post("/api/tastings")
def log_tasting(body: Tasting) -> dict:
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(KINDS)}")
    if not body.name.strip() or not body.notes.strip():
        raise HTTPException(400, "a tasting needs a name and some notes")
    try:
        day = date.fromisoformat(body.date).isoformat() if body.date else date.today().isoformat()
    except ValueError as e:
        raise HTTPException(400, f"date must be YYYY-MM-DD, not {body.date!r}") from e
    t = {
        "id": uuid.uuid4().hex[:10],
        "date": day,
        "kind": body.kind,
        "name": body.name.strip(),
        "origin": body.origin.strip(),
        "notes": body.notes.strip(),
        "rating": body.rating,
        "in_memory": False,
    }
    t["flavor"] = score(t)
    journal.save(t)
    writer.submit(f"writing {t['name']}", lambda: remember([t]))
    return {"tasting": t, "pending": writer.pending}


def recalled(queries: list[str], limit: int = 6) -> list[dict]:
    """Several recalls side by side, merged by memory id, best first. Each hit names the
    tasting it is (by its memory id) so the page can light its star."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        answers = list(
            pool.map(lambda q: recall(mem, q, container=CONTAINER, limit=limit), queries)
        )
    owner = {mid: t for t in journal.all() for mid in t.get("memory_ids", [])}
    hits, seen = [], set()
    for rank in range(max((len(a) for a in answers), default=0)):
        for a in answers:
            if rank >= len(a):
                continue
            h = a[rank]
            if h["memory_id"] in seen or is_narration(h["content"]):
                continue
            seen.add(h["memory_id"])
            t = owner.get(h["memory_id"])
            hits.append(
                {
                    "n": len(hits) + 1,
                    "memory_id": h["memory_id"],
                    "content": h["content"],
                    "date": (h["date"] or "")[:10],
                    "tasting": t["id"] if t else None,
                    "name": t["name"] if t else "",
                    "kind": t["kind"] if t else "",
                    "rating": t["rating"] if t else None,
                }
            )
    return hits


def grounded(system: str, queries: list[str], ask: str):
    """Recall, show what was recalled, then stream an answer that may only use it."""
    if writer.pending:
        yield {"type": "waiting", "pending": writer.pending}
    writer.flush()
    hits = recalled(queries)
    facts = list(mem.profile().get("static") or [])
    yield {"type": "memories", "hits": hits, "facts": facts}
    if not hits:
        yield {
            "type": "delta",
            "text": "I found nothing in your journal for that yet. Add a few tastings first.",
        }
        yield {"type": "done", "cited": []}
        return
    listing = "\n".join(f"[{h['n']}] tasted {h['date']}: {h['content']}" for h in hits)
    profile = "\n".join(f"- {f}" for f in facts) or "(nothing)"
    text = ""
    for delta in llm.stream(
        [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Profile:\n{profile}\n\nTastings recalled from memory:\n{listing}"
                f"\n\nToday is {date.today().isoformat()}. {ask}",
            },
        ],
        model=ANSWER_MODEL,
        temperature=0.3,
    ):
        text += delta
        yield {"type": "delta", "text": delta}
    numbers = {int(n) for n in re.findall(r"\[(\d+)\]", text)}
    cited = [h for h in hits if h["n"] in numbers]
    yield {"type": "done", "cited": [h["n"] for h in cited]}


class Ask(BaseModel):
    kind: str = "next"
    hint: str = ""


LOVED = "tastings I loved and rated 5/5 or 4/5"
DISLIKED = "tastings I disliked and rated 1/5 or 2/5"


@app.post("/api/ask")
def ask(body: Ask):
    hint = body.hint.strip()
    if body.kind == "palate":
        return sse(
            grounded(
                PALATE,
                [LOVED, DISLIKED, "bright floral fruity or smoky earthy roasted flavors"],
                "Describe my palate.",
            )
        )
    if body.kind != "next":
        raise HTTPException(400, "kind must be next or palate")
    queries = [LOVED, DISLIKED]
    if hint:
        queries.insert(0, hint)
    question = "What should I try next?" + (f" I'm looking for: {hint}." if hint else "")
    return sse(grounded(NEXT, queries, question))


if __name__ == "__main__":
    run(app, port=8709)
