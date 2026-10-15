"""Quest log: a day's plan becomes quests, and memory of how past days went changes the next one.

Every closed quest is written to memory, dated by the day it was for. When Rin plans a day,
past days like it are recalled. A model reads each recalled day for the plan's items (with a
quote, which the code checks against the passage), and the code counts: "Mondays at 7:00: skipped
3 of 3". Only an item whose count says it keeps failing is changed, and the change shows the
dates it rests on. The game state (quests, XP, the chronicle) is a JSON file beside the memory.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from demokit import ROOT, Memory, llm, mode  # noqa: E402
from demokit.config import DATA  # noqa: E402
from demokit.dated import recall, remember_sessions  # noqa: E402
from demokit.memory import is_narration  # noqa: E402
from demokit.web import create_app, run, sse  # noqa: E402
from demokit.writes import BackgroundWriter  # noqa: E402

DEMO = "10-quest-log"
USER = "rin"  # one synthetic player; memory in data/10-quest-log/rin/
CONTAINER = "Quest log"
CATEGORIES = ("body", "mind", "work", "home", "social")
SLOTS = ("morning", "midday", "afternoon", "evening", "anytime")
XP = {"easy": 15, "normal": 30, "hard": 50}
LEVEL_XP = 200

READ = f"""You read a player's past days, recalled from memory, for the items of a new plan.

You get the plan and numbered passages. Each passage is one past day: its weekday and date come
first, then what memory says happened.

1. Split the plan into its items, in order. For each: "item" (short, as the player wrote it),
   "activity" (the kind of task, e.g. "gym session", "inbox", "reading"), "slot" (one of
   {", ".join(SLOTS)}, from the time the player gave or the usual time for it) and "time"
   ("7:00" style, or "").
2. For each item, go through EVERY passage and list each one that reports the same activity,
   done or skipped, on any weekday and at any time of day: for "gym at 7:00", a gym session at
   18:30 on a Wednesday counts too. The same activity means the same kind of task: a gym
   session is not a run or a walk; clearing the whole inbox is not a 15-minute inbox sweep;
   a slide deck is not research or onboarding flows. For each: "passage" (its number), "status"
   ("done" or "skipped"), "slot" and "time" of that past quest, and "quote": the exact words
   of the passage that say so, copied character for character (8-25 words).

Report only what the passages say. Do not count anything; list each outcome once.
Reply as JSON: {{"items": [{{"item": "...", "activity": "...", "slot": "...", "time": "...",
"outcomes": [{{"passage": 1, "status": "skipped", "slot": "morning", "time": "7:00",
"quote": "..."}}]}}]}}"""

QUESTS = f"""You are the quest master of a gentle productivity game. Turn each plan item into one
quest, in the same order.

Each item comes with what its past outcomes show, counted from memory. An item marked ADAPT
keeps failing in these circumstances: change it, using what has worked for it (a time slot
that worked, or a smaller first step). Every other item stays as the player planned it.

For each quest: "item" (its number), "title" (short, concrete, starts with a verb, includes the
new time when you move it), "category" (one of {", ".join(CATEGORIES)}), "difficulty" (easy,
normal or hard), "slot" (one of {", ".join(SLOTS)}), and "change": for an ADAPT item, the
scribe's note: one short sentence (at most 14 words) to the player, in a warm quest-giver's
voice, saying what changed and why, without numbers or dates (the evidence is shown beside it);
for any other item, "". No "Certainly", no restating the plan.

Reply as JSON: {{"quests": [{{"item": 1, "title": "...", "category": "...", "difficulty": "...",
"slot": "...", "change": "..."}}]}}"""


class Log:
    """The game state: every day's plan and quests, in one JSON file beside the memory."""

    def __init__(self, user: str) -> None:
        self.path = DATA / DEMO / user / "quests.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def days(self) -> dict[str, dict]:
        if not self.path.is_file():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, days: dict[str, dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(dict(sorted(days.items())), indent=1, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(self.path)


def weekday(day: str) -> str:
    return date.fromisoformat(day).strftime("%A")


def next_monday() -> date:
    """The day the demo plans: the next Monday (today, when today is a Monday)."""
    today = date.today()
    return today + timedelta(days=-today.weekday() % 7)


def nice(day: str) -> str:
    """'Mon 28 Sep', for a date chip."""
    d = date.fromisoformat(day)
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def day_text(day: str, quests: list[dict]) -> str:
    """How a day's outcomes read in memory: the weekday and date, then one line per quest."""
    lines = [f"Quest log for {weekday(day)} {day}."]
    for q in quests:
        when = f"{q['slot']}, {q['time']}" if q.get("time") else q["slot"]
        line = (
            f'- {q["status"].upper()}: "{q["title"]}" ({q["category"]}, {q["difficulty"]}, {when}).'
        )
        if q.get("note"):
            line += f" Note: {q['note']}"
        lines.append(line)
    return "\n".join(lines)


mem = Memory(DEMO, user=USER, default_mode="local")
log = Log(USER)
writer = BackgroundWriter()


def remember_days(days: list[tuple[str, list[dict]]]) -> dict[str, list[str]]:
    """Each day's outcomes as one memory, dated by that day (its evening, when the day is
    done). Returns the memory ids per day."""
    sessions = [
        {
            "session_id": f"{day}-{uuid.uuid4().hex[:6]}",
            "session_date": f"{day}T21:00:00",
            "turns": [{"role": "user", "content": day_text(day, quests)}],
        }
        for day, quests in days
    ]
    ids = remember_sessions(mem, sessions, container=CONTAINER)
    return {day: ids[s["session_id"]] for (day, _), s in zip(days, sessions, strict=True)}


def stats(days: dict[str, dict]) -> dict:
    xp = sum(q["xp"] for d in days.values() for q in d["quests"] if q["status"] == "done")
    done = sum(1 for d in days.values() for q in d["quests"] if q["status"] == "done")
    closed = sum(1 for d in days.values() for q in d["quests"] if q["status"] != "open")
    # A streak counts consecutive days with a quest done, back from today (or from yesterday,
    # while today is still open).
    active = {k for k, d in days.items() if any(q["status"] == "done" for q in d["quests"])}
    streak = 0
    cur = date.today()
    if cur.isoformat() not in active:
        cur -= timedelta(days=1)
    while cur.isoformat() in active:
        streak += 1
        cur -= timedelta(days=1)
    remembered = sorted(k for k, d in days.items() if d.get("memory_ids"))
    return {
        "xp": xp,
        "level": xp // LEVEL_XP + 1,
        "level_xp": xp % LEVEL_XP,
        "level_size": LEVEL_XP,
        "streak": streak,
        "done": done,
        "closed": closed,
        "days_in_memory": len(remembered),
        "first": remembered[0] if remembered else "",
        "last": remembered[-1] if remembered else "",
    }


def where() -> str:
    """The memory directory, as the page shows it."""
    try:
        return str(mem.path.relative_to(ROOT)) + "/"
    except ValueError:
        return str(mem.path) + "/"


app = create_app("Quest log", HERE, mode=mode("local"))


# ---- reading memory -------------------------------------------------------------------------


def chunks(plan: str) -> list[str]:
    """The plan's items, roughly, for the recall queries (the model splits it properly)."""
    parts = re.split(r"[,;\n]+|\band then\b", plan)
    return [p.strip(" .") for p in parts if len(p.strip(" .")) > 2][:8]


def recall_days(plan: str, wd: str, before: str) -> list[dict]:
    """Past days that bear on the plan: the same weekday, and each item at any time. Merged by
    memory id, oldest first; each hit keeps the day it happened (its session date)."""
    queries = [f"{wd} quest log: what was done and skipped", *chunks(plan)]
    # the local engine answers searches side by side; one by one they take 3-4 s each
    with ThreadPoolExecutor(max_workers=6) as pool:
        answers = list(pool.map(lambda q: recall(mem, q, container=CONTAINER, limit=10), queries))
    seen: dict[str, dict] = {}
    for hits in answers:
        for h in hits:
            if h["memory_id"] in seen or not h["date"] or is_narration(h["content"]):
                continue
            day = h["date"][:10]
            if day >= before:
                continue
            seen[h["memory_id"]] = {
                **h,
                "day": day,
                "weekday": weekday(day),
                "label": nice(day),
            }
    return sorted(seen.values(), key=lambda h: (h["day"], h["memory_id"]))


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9:]+", " ", s.lower()).strip()


def evidence(items: list[dict], passages: list[dict], day: str) -> list[dict]:
    """Per plan item, what its past outcomes show, counted here rather than by the model.

    The model only says which passages report the item, and how. An outcome counts only when
    its quote really is in that passage, and a day counts once. Then: the same weekday in the
    same slot (the habit that decides whether to change the item) and, for an item that keeps
    failing, the slot that has worked for it."""
    wd = weekday(day)
    out = []
    for i, it in enumerate(items):
        slot = it.get("slot") if it.get("slot") in SLOTS else "anytime"
        rows: dict[tuple, dict] = {}
        dropped = 0
        for o in it.get("outcomes") or []:
            try:
                p = passages[int(o.get("passage")) - 1]
            except (TypeError, ValueError, IndexError):
                dropped += 1
                continue
            quote = _norm(str(o.get("quote") or ""))
            status = o.get("status")
            if (
                status not in ("done", "skipped")
                or len(quote) < 8
                or quote not in _norm(p["content"])
            ):
                dropped += 1
                continue
            o_slot = o.get("slot") if o.get("slot") in SLOTS else "anytime"
            rows.setdefault(
                (p["day"], o_slot),
                {
                    "day": p["day"],
                    "label": p["label"],
                    "weekday": p["weekday"],
                    "slot": o_slot,
                    "time": str(o.get("time") or ""),
                    "status": status,
                    "quote": str(o.get("quote") or ""),
                    "memory_id": p["memory_id"],
                },
            )
        outcomes = sorted(rows.values(), key=lambda r: r["day"])
        same = [
            r for r in outcomes if r["weekday"] == wd and (slot == "anytime" or r["slot"] == slot)
        ]
        skipped = [r for r in same if r["status"] == "skipped"]
        adapt = len(same) >= 2 and len(skipped) * 3 >= len(same) * 2
        habit = None
        if same:
            # "the last 3 Mondays" only when they really are the three before the planned day
            last = [
                (date.fromisoformat(day) - timedelta(weeks=k)).isoformat()
                for k in range(len(same), 0, -1)
            ]
            at = it.get("time") or ("" if slot == "anytime" else f"in the {slot}")
            habit = {
                "where": f"{wd}s {'at ' + at if it.get('time') else at}".strip(),
                "skipped": len(skipped),
                "done": len(same) - len(skipped),
                "total": len(same),
                "consecutive": [r["day"] for r in same] == last,
                "days": same,
            }
        works = None
        if adapt:
            others: dict[str, list[dict]] = {}
            for r in outcomes:
                if r["slot"] != slot:
                    others.setdefault(r["slot"], []).append(r)
            best = max(
                others.values(), key=lambda rs: sum(r["status"] == "done" for r in rs), default=[]
            )
            done = [r for r in best if r["status"] == "done"]
            if len(done) >= 2 and len(done) * 4 >= len(best) * 3:
                times = {r["time"] for r in best if r["time"]}
                works = {
                    "where": f"{best[0]['slot'].capitalize()}s"
                    + (f" at {next(iter(times))}" if len(times) == 1 else ""),
                    "slot": best[0]["slot"],
                    "done": len(done),
                    "total": len(best),
                    "days": best,
                }
        out.append(
            {
                "index": i,
                "item": str(it.get("item") or "").strip(),
                "activity": str(it.get("activity") or "").strip(),
                "slot": slot,
                "time": str(it.get("time") or ""),
                "outcomes": len(outcomes),
                "unverified": dropped,
                "habit": habit,
                "adapt": adapt,
                "works": works,
            }
        )
    return out


def briefing(ev: list[dict], wd: str) -> str:
    """The counted evidence, in words, for the quest master."""
    lines = []
    for e in ev:
        planned = e["slot"] + (f", {e['time']}" if e["time"] else "")
        h, w = e["habit"], e["works"]
        line = (
            f"{e['index'] + 1}. {e['item']} (planned: {planned}){' ADAPT' if e['adapt'] else ''}: "
        )
        line += (
            f"{h['where']}: skipped {h['skipped']} of {h['total']}"
            if h
            else f"no past outcome on a {wd} at this time"
        )
        if w:
            line += f"; what has worked: {w['where']}, done {w['done']} of {w['total']}"
        lines.append(line)
    return "\n".join(lines)


@app.get("/api/state")
def state() -> dict:
    days = log.days()
    return {
        "days": days,
        "stats": stats(days),
        "pending": writer.pending,
        "error": writer.error,
        "directory": where(),
        "today": date.today().isoformat(),
        "plan_day": next_monday().isoformat(),
    }


class Plan(BaseModel):
    date: str
    plan: str


@app.post("/api/plan")
def plan(body: Plan):
    text = body.plan.strip()
    if not text:
        raise HTTPException(400, "write what you plan to do that day")
    try:
        day = date.fromisoformat(body.date).isoformat()
    except ValueError as e:
        raise HTTPException(400, f"date must be YYYY-MM-DD, not {body.date!r}") from e
    wd = weekday(day)

    def events():
        if writer.pending:
            yield {"type": "waiting", "pending": writer.pending}
        writer.flush()
        passages = recall_days(text, wd, before=day)
        yield {"type": "memories", "hits": passages, "weekday": wd}
        numbered = "\n".join(
            f"[{n}] {p['weekday']} {p['day']}: {p['content']}" for n, p in enumerate(passages, 1)
        )
        read = llm.json_reply(
            [
                {"role": "system", "content": READ},
                {
                    "role": "user",
                    "content": f"Past days recalled from memory:\n{numbered or '(none)'}\n\n"
                    f"The new plan, for {wd} {day}: {text}",
                },
            ],
            temperature=0,
        )
        items = [it for it in read.get("items") or [] if str(it.get("item") or "").strip()]
        if not items:
            raise RuntimeError(f"the model found no items in the plan: {read}")
        ev = evidence(items, passages, day)
        yield {"type": "evidence", "items": ev}

        out = llm.json_reply(
            [
                {"role": "system", "content": QUESTS},
                {
                    "role": "user",
                    "content": f"The day: {wd} {day}\nThe plan: {text}\n\nItems:\n{briefing(ev, wd)}",
                },
            ],
            temperature=0.2,
        )
        by_item: dict[int, dict] = {}
        for q in out.get("quests") or []:
            try:
                by_item.setdefault(int(q.get("item")) - 1, q)
            except (TypeError, ValueError):
                continue
        quests = []
        for e in ev:
            q = by_item.get(e["index"]) or {}
            difficulty = q.get("difficulty") if q.get("difficulty") in XP else "normal"
            quests.append(
                {
                    "id": uuid.uuid4().hex[:8],
                    "title": str(q.get("title") or "").strip() or e["item"],
                    "category": q.get("category") if q.get("category") in CATEGORIES else "work",
                    "difficulty": difficulty,
                    "xp": XP[difficulty],
                    "slot": q.get("slot") if q.get("slot") in SLOTS else e["slot"],
                    "time": "" if e["adapt"] else e["time"],
                    "planned": e["item"],
                    # only an item the counts flagged may change; the reason is the model's
                    # words, and the evidence beside it is counted here
                    "change": str(q.get("change") or "").strip() if e["adapt"] else "",
                    "evidence": e["index"] if e["adapt"] else None,
                    "status": "open",
                    "note": "",
                }
            )
        with log.lock:
            days = log.days()
            days[day] = {"plan": text, "quests": quests, "evidence": ev}
            log.save(days)
        yield {"type": "quests", "date": day, **days[day]}
        yield {"type": "done"}

    return sse(events())


class Outcome(BaseModel):
    date: str
    id: str
    status: str
    note: str = ""


@app.post("/api/quest")
def close_quest(body: Outcome) -> dict:
    """Done or skipped: the game state at once, and one memory dated by the quest's day."""
    if body.status not in ("done", "skipped"):
        raise HTTPException(400, "status must be done or skipped")
    with log.lock:
        days = log.days()
        quest = next(
            (q for q in days.get(body.date, {}).get("quests", []) if q["id"] == body.id), None
        )
        if quest is None:
            raise HTTPException(404, f"no quest {body.id} on {body.date}")
        if quest["status"] != "open":
            raise HTTPException(409, f"that quest is already {quest['status']}")
        quest.update(status=body.status, note=body.note.strip())
        log.save(days)
    closed = dict(quest)

    def write() -> None:
        ids = remember_days([(body.date, [closed])])[body.date]
        with log.lock:
            days = log.days()
            if body.date in days:
                days[body.date]["memory_ids"] = [*days[body.date].get("memory_ids", []), *ids]
                log.save(days)

    writer.submit(f"writing {quest['title']}", write)
    return state()


if __name__ == "__main__":
    run(app, port=8710)
