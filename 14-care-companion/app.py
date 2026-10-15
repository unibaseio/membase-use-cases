"""Care companion: a caregiver logs the day; the person asks simple questions about it.

Each log entry becomes one memory dated when the thing happened (pills at 08:15, a visit at
15:00, an appointment next Thursday). The person's questions ("Did I take my pills this
morning?") are answered from what memory recalls, with the date of each recalled entry spelled
out relative to now, so "this morning", "yesterday" and "next" resolve correctly. Fixing a wrong
entry forgets its memory and writes the corrected one; the next answer uses the correction.

A demo with a made-up person and made-up notes. It is not a medical device or a care service.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from demokit import Memory, llm  # noqa: E402
from demokit.dated import recall, remember_sessions  # noqa: E402
from demokit.memory import is_narration  # noqa: E402
from demokit.web import create_app, run  # noqa: E402

DEMO = "14-care-companion"
CONTAINER = "Daily log"
PERSON = "Margaret"
CAREGIVER = "Sofia"
KINDS = {
    "meds": "Medication",
    "visitor": "Visitor",
    "meal": "Meal",
    "appointment": "Appointment",
    "note": "Note",
}

mem = Memory(DEMO, user="margaret", default_mode="local")
app = create_app("Care companion", HERE, mode=mem.mode)


# ---- the log: what the caregiver wrote, and which memories each entry became ---------------


class Log:
    """Entries in `log.json` beside the person's memory. Memory holds the content; this keeps
    the caregiver's own wording, the entry's status and its memory ids (for corrections)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()

    def _read(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.is_file() else {"entries": []}

    def _write(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(self.path)

    def entries(self) -> list[dict]:
        with self.lock:
            return self._read()["entries"]

    def get(self, entry_id: str) -> dict | None:
        return next((e for e in self.entries() if e["id"] == entry_id), None)

    def put(self, *entries: dict) -> None:
        with self.lock:
            data = self._read()
            by_id = {e["id"]: i for i, e in enumerate(data["entries"])}
            for e in entries:
                if e["id"] in by_id:
                    data["entries"][by_id[e["id"]]] = e
                else:
                    data["entries"].append(e)
            self._write(data)

    def update(self, entry_id: str, **changes) -> dict:
        with self.lock:
            data = self._read()
            for e in data["entries"]:
                if e["id"] == entry_id:
                    e.update(changes)
                    self._write(data)
                    return e
        raise KeyError(entry_id)

    def by_memory(self) -> dict[str, dict]:
        return {m: e for e in self.entries() for m in e.get("memory_ids", [])}


log = Log(mem.path / "log.json")
CLOCK = mem.path / "clock.json"
# One writer, so entries reach memory in the order they were logged.
writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="care-writer")


def now() -> datetime:
    """The demo clock: the moment seed.py set (so the seeded week reads the same whenever the
    demo is opened), else the real time."""
    if CLOCK.is_file():
        return datetime.fromisoformat(json.loads(CLOCK.read_text())["now"])
    return datetime.now().replace(second=0, microsecond=0)


def set_clock(at: datetime) -> None:
    CLOCK.write_text(json.dumps({"now": at.isoformat(timespec="minutes")}))


def long_date(at: datetime) -> str:
    return f"{at:%A} {at.day} {at:%B %Y}, {at:%H:%M}"


def relative(at: datetime, ref: datetime) -> str:
    days = (at.date() - ref.date()).days
    if days == 0:
        return "today, earlier" if at <= ref else "today, later"
    if days == -1:
        return "yesterday"
    if days == 1:
        return "tomorrow"
    return f"{-days} days ago" if days < 0 else f"in {days} days"


def memory_text(entry: dict) -> str:
    at = datetime.fromisoformat(entry["when"])
    return f"{PERSON}'s care log, {long_date(at)}. {KINDS[entry['kind']]}: {entry['text'].strip()}"


def new_entry(kind: str, text: str, when: str, *, replaces: str = "") -> dict:
    if kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(KINDS)}")
    if not text.strip():
        raise HTTPException(400, "write what happened")
    try:
        at = datetime.fromisoformat(when)
    except ValueError as e:
        raise HTTPException(400, f"when must be a date and time, not {when!r}") from e
    return {
        "id": uuid.uuid4().hex[:10],
        "kind": kind,
        "text": text.strip(),
        "when": at.isoformat(timespec="minutes"),
        "status": "saving",
        "memory_ids": [],
        "replaces": replaces,
        "logged_at": datetime.now().isoformat(timespec="seconds"),
    }


def write_entries(entries: list[dict]) -> None:
    """Entries into memory (one dated session each), then their memory ids into the log."""
    sessions = [
        {
            "session_id": f"log-{e['id']}",
            "session_date": datetime.fromisoformat(e["when"]).isoformat(timespec="seconds"),
            "turns": [{"role": CAREGIVER, "content": memory_text(e)}],
        }
        for e in entries
    ]
    try:
        ids = remember_sessions(mem, sessions, container=CONTAINER)
    except Exception as exc:  # noqa: BLE001 - the entry shows why it is not in memory
        for e in entries:
            log.update(e["id"], status="error", error=f"{type(exc).__name__}: {exc}")
        raise
    for e in entries:
        got = ids.get(f"log-{e['id']}", [])
        if got:
            log.update(e["id"], status="saved", memory_ids=got)
        else:
            log.update(e["id"], status="error", error="the engine kept nothing from this entry")


def correct(old: dict, new: dict) -> None:
    """Write the corrected entry, then forget every memory of the wrong one."""
    try:
        write_entries([new])
    finally:
        if log.get(new["id"])["status"] != "saved":
            # The fix did not reach memory, so the old entry stays as it was.
            log.update(old["id"], status="saved")
    if log.get(new["id"])["status"] != "saved":
        return
    try:
        for memory_id in old["memory_ids"]:
            mem.forget(memory_id)
    except Exception as exc:  # noqa: BLE001
        log.update(old["id"], status="error", error=f"could not forget the old entry: {exc}")
        raise
    log.update(
        old["id"],
        status="replaced",
        replaced_by=new["id"],
        memory_ids=[],
        forgotten=old["memory_ids"],
    )


def _logged(future) -> None:
    if future.exception():
        print(f"care-writer: {future.exception()}", file=sys.stderr)


# ---- answering ----------------------------------------------------------------------------

ANSWER = """You are a gentle memory companion for {person}, who has memory loss. {caregiver} is
{person}'s caregiver and keeps a care log; you are given the log entries memory recalled for
this question.

It is now {now}. Each entry is labelled with when it happened and how that relates to now
(today, yesterday, in 3 days ...). All times are local; never mention time zones or UTC.

Answer {person} directly, as "you", in one or two short, warm, plain sentences (under 22
words in all), the way a kind friend would say it. Say when: give the time of what happened
(and the day, if it was not today), also when the question is a yes or no. Write clock times
in figures, like 8:15 or 2:30 in the afternoon; never say the year. Do not start with
"Certainly" or repeat the question. Get the time right: "this morning" means
today before noon; "yesterday" means the day before today; "next" means the soonest one still
to come after now. Use only the entries. If none of them answers
the question, say kindly that the log has no note about it and suggest asking {caregiver}.
Never guess.

Reply with JSON: {{"answer": "...", "used": [numbers of the entries the answer relies on]}}"""


class Ask(BaseModel):
    question: str


def answer(question: str) -> dict:
    question = question.strip()
    if not question:
        raise HTTPException(400, "ask a question")
    started = time.monotonic()
    at = now()
    yesterday = at - timedelta(days=1)
    # The question as asked, and again with today's and yesterday's dates written out: the
    # recalled entries carry their dates in words, so "yesterday" alone does not find them.
    dated_q = (
        f"{question} (today is {at:%A} {at.day} {at:%B %Y}, {at:%Y-%m-%d}; "
        f"yesterday was {yesterday:%A} {yesterday.day} {yesterday:%B}, {yesterday:%Y-%m-%d})"
    )
    hits: dict[str, dict] = {}
    for q in (question, dated_q):
        for h in recall(mem, q, container=CONTAINER, limit=12):
            if not is_narration(h["content"]):
                hits.setdefault(h["memory_id"], h)
    ordered = sorted(hits.values(), key=lambda h: h["date"])
    lines = []
    for i, h in enumerate(ordered, 1):
        when = datetime.fromisoformat(h["date"])
        lines.append(f"[{i}] {long_date(when)} ({relative(when, at)}): {h['content']}")
    reply = llm.json_reply(
        [
            {
                "role": "system",
                "content": ANSWER.format(person=PERSON, caregiver=CAREGIVER, now=long_date(at)),
            },
            {
                "role": "user",
                "content": ("\n".join(lines) or "(memory returned no entries)")
                + f"\n\n{PERSON} asks: {question}",
            },
        ]
    )
    by_memory = log.by_memory()
    cited, seen, used = [], set(), set()
    for n in reply.get("used") or []:
        if isinstance(n, int) and 1 <= n <= len(ordered):
            used.add(ordered[n - 1]["memory_id"])
            entry = by_memory.get(ordered[n - 1]["memory_id"])
            if entry and entry["id"] not in seen:
                seen.add(entry["id"])
                cited.append(entry)
    return {
        "question": question,
        "answer": str(reply.get("answer") or "").strip(),
        "cited": sorted(cited, key=lambda e: e["when"]),
        "recalled": [
            {
                **h,
                "entry": (by_memory.get(h["memory_id"]) or {}).get("id"),
                "used": h["memory_id"] in used,
                "label": long_date(datetime.fromisoformat(h["date"])),
                "relative": relative(datetime.fromisoformat(h["date"]), at),
            }
            for h in ordered
        ],
        "seconds": round(time.monotonic() - started, 2),
    }


# ---- routes -------------------------------------------------------------------------------


class EntryIn(BaseModel):
    kind: str
    text: str
    when: str


@app.get("/api/state")
def state() -> dict:
    at = now()
    return {
        "person": PERSON,
        "caregiver": CAREGIVER,
        "now": at.isoformat(timespec="minutes"),
        "now_label": long_date(at),
        "kinds": KINDS,
        "entries": sorted(log.entries(), key=lambda e: e["when"], reverse=True),
    }


@app.post("/api/entries")
def add_entry(body: EntryIn) -> dict:
    entry = new_entry(body.kind, body.text, body.when)
    log.put(entry)
    writer.submit(write_entries, [entry]).add_done_callback(_logged)
    return entry


@app.post("/api/entries/{entry_id}/correct")
def correct_entry(entry_id: str, body: EntryIn) -> dict:
    old = log.get(entry_id)
    if old is None:
        raise HTTPException(404, "no such entry")
    if old["status"] != "saved":
        raise HTTPException(
            409, f"this entry is {old['status']}; only a saved entry can be corrected"
        )
    new = new_entry(body.kind, body.text, body.when, replaces=entry_id)
    log.put(new)
    log.update(entry_id, status="correcting")
    writer.submit(correct, old, new).add_done_callback(_logged)
    return new


@app.post("/api/ask")
def ask(body: Ask) -> dict:
    return answer(body.question)


if __name__ == "__main__":
    run(app, port=8714)
