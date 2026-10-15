"""Companion: a character that remembers you and follows up.

Wren, an original persona, chats with one of two synthetic people. Each person's memory is its
own local directory, so what Maya tells Wren never reaches Theo. Before every reply Wren recalls
what fits the message and reads the person's profile; after every exchange the standing facts it
learned are written in the background. "End session" writes the conversation once and stores the
open loops ("interview on Thursday") as follow-ups, and the next session opens with one of them.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import date
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from demokit import ROOT, Memory, Recall, llm, mode  # noqa: E402
from demokit.config import DATA  # noqa: E402
from demokit.web import create_app, run, sse  # noqa: E402
from demokit.writes import BackgroundWriter  # noqa: E402

DEMO = "08-companion"
CONVERSATIONS = "Conversations"
FOLLOW_UPS = "Follow-ups"

#: Two synthetic people. Each gets its own memory directory: data/08-companion/<id>/.
USERS = {
    "maya": {"name": "Maya", "blurb": "Product designer, lives with a cat"},
    "theo": {"name": "Theo", "blurb": "Night-shift nurse, learning the cello"},
}

PERSONA = {
    "name": "Wren",
    "tagline": "Host of Saltmarsh After Dark, 98.4 FM",
}

SYSTEM = """You are Wren, an original character: the host of a late-night call-in radio show in
the small harbor town of Saltmarsh. You are talking one-to-one with a listener.

Voice: warm, a little wry, unhurried, like a radio host at 1 a.m. Plain words, the odd image
from the harbor or the studio. Keep every reply to two or three short sentences, under 45
words. Ask at most one question. Never open with "Certainly", "Of course" or by repeating what
they said back to them.

Memory: you are given what you remember about this listener (their profile and memories
recalled for this message). Use it the way a friend would: naturally, without listing it, and
only when it fits. Never invent a memory. If they ask about something you have no memory of,
say plainly that you don't remember it.

Boundaries: you are an AI character and say so if asked; you never claim to be human. You are
not a therapist, doctor or lawyer: for anything serious, you encourage real people and real
help (in a crisis, local emergency services). No romantic or sexual roleplay. You don't pressure
the listener to keep talking.

Today is {today}."""

OPENER = """Start a new conversation with this listener. You speak first.

Open with ONE specific follow-up grounded in what you remember: an open loop (an event that
should have happened by now, something they planned to try) or a fact from their profile.

Today is {today}. Check the date of the thing you follow up on against today before you write:
- its date is before today: it has happened; ask how it went.
- its date is today or later: it has NOT happened yet; wish them luck or ask how they feel
  about it. Never ask how it went.
Name the specific thing (the event, the place, the person). Two short sentences, under 35
words, and end with one question.

If you remember nothing about them, introduce yourself in two short sentences (under 30 words)
and ask their name."""

FACTS = """From this exchange, list standing facts about the listener worth keeping across
sessions: name, people and pets in their life, work, where they live, likes and dislikes,
ongoing hobbies. Only lasting facts the listener stated about themselves. Leave out events,
appointments, plans, moods and worries (those are follow-ups, kept elsewhere): "Jordan has an
interview on Friday" or "Jordan is preparing a talk" is not a standing fact. Leave out anything
already in "Known facts". Each fact one short sentence in the third person using their
name if known (e.g. "Jordan's dog is called Pickle."). Reply as JSON: {"facts": ["..."]};
an empty list is fine."""

OPEN_LOOPS = """Read this conversation between Wren and a listener. List the open loops a good
friend would follow up on next time: upcoming events (interviews, trips, appointments,
deadlines), things they said they would try or do, worries still unresolved. Resolve relative
dates against today's date ({today}), e.g. "Thursday" -> "Thursday {example}". Each loop one
short line in Wren's notebook (at most 16 words): the listener's name, the specific thing, the
date if any, and how they feel about it if they said, e.g. "Jordan: dentist on Friday
2026-03-06, dreading the drill." Reply as JSON:
{{"loops": ["..."]}}; an empty list is fine."""


def _today() -> date:
    return date.today()


def _today_text() -> str:
    return _today().strftime("%A %Y-%m-%d")


# ---- one memory and one writer per person ---------------------------------------------


_mems: dict[str, Memory] = {}
_writers: dict[str, BackgroundWriter] = {}
_guard = threading.Lock()


def person(user: str) -> tuple[Memory, BackgroundWriter]:
    if user not in USERS:
        raise HTTPException(404, f"unknown user {user!r}; pick one of {', '.join(USERS)}")
    with _guard:
        if user not in _mems:
            _mems[user] = Memory(DEMO, user=user, default_mode="local")
            _writers[user] = BackgroundWriter()
        return _mems[user], _writers[user]


def directory(mem: Memory) -> str:
    """The person's memory directory as the page shows it: `data/08-companion/maya/`, or
    `…/08-companion/maya/` when DEMO_DATA_DIR points somewhere else."""
    if mem.path is None:
        return "hosted account (shared by every user)"
    rel = str(mem.path.relative_to(DATA)) + "/"
    return ("data/" if DATA.resolve() == (ROOT / "data").resolve() else "…/") + rel


def unique(recall: Recall) -> list[dict]:
    """Hits without repeats: the local engine keeps one copy of a conversation's episode per
    speaker, so the same text can come back twice."""
    seen: set[str] = set()
    out = []
    for h in recall.hits:
        if h.content in seen:
            continue
        seen.add(h.content)
        out.append(h.as_dict())
    return out


def profile_facts(mem: Memory) -> list[str]:
    return list(mem.profile().get("static") or [])


def memory_block(facts: list[str], hits: list[dict]) -> str:
    parts = []
    parts.append(
        "Profile (standing facts):\n" + "\n".join(f"- {f}" for f in facts)
        if facts
        else "Profile: nothing yet."
    )
    parts.append(
        "Recalled memories:\n"
        + "\n".join(f"- [{h['container_name']}] {h['content']}" for h in hits)
        if hits
        else "Recalled memories: none."
    )
    return "What you remember about this listener:\n\n" + "\n\n".join(parts)


app = create_app("Companion", HERE, mode=mode("local"))


class Turn(BaseModel):
    role: str
    content: str


class Chat(BaseModel):
    user: str
    message: str
    history: list[Turn] = Field(default_factory=list)


class Session(BaseModel):
    user: str
    history: list[Turn] = Field(default_factory=list)


class Who(BaseModel):
    user: str


@app.get("/api/users")
def users() -> dict:
    out = []
    for uid, u in USERS.items():
        mem, writer = person(uid)
        out.append({"id": uid, **u, "directory": directory(mem), "pending": writer.pending})
    return {"users": out, "persona": PERSONA, "today": _today_text()}


@app.get("/api/memory")
def memory(user: str) -> dict:
    """What the page's side panel shows: the person's profile and their writes in flight."""
    mem, writer = person(user)
    return {
        "user": user,
        "directory": directory(mem),
        "facts": profile_facts(mem),
        "containers": [c["name"] for c in mem.containers()],
        "pending": writer.pending,
        "error": writer.error,
    }


@app.post("/api/chat")
def chat(body: Chat):
    mem, writer = person(body.user)
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "message is empty")
    history = [t.model_dump() for t in body.history if t.content.strip()][-16:]

    def events():
        recall = mem.recall(message, limit=6)
        hits = unique(recall)
        facts = profile_facts(mem)
        yield {
            "type": "memories",
            "hits": hits,
            "facts": facts,
            "seconds": round(recall.seconds, 2),
        }
        messages = [
            {"role": "system", "content": SYSTEM.format(today=_today_text())},
            {"role": "system", "content": memory_block(facts, hits)},
            *history,
            {"role": "user", "content": message},
        ]
        reply = ""
        for delta in llm.stream(messages, temperature=0.7):
            reply += delta
            yield {"type": "delta", "text": delta}
        # The exchange is over: what it taught us about the person goes in the background.
        writer.submit("learning facts", lambda: learn_facts(mem, message, reply))
        yield {"type": "done", "pending": writer.pending}

    return sse(events())


def learn_facts(mem: Memory, message: str, reply: str) -> None:
    known = profile_facts(mem)
    out = llm.json_reply(
        [
            {"role": "system", "content": FACTS},
            {
                "role": "user",
                "content": "Known facts:\n"
                + ("\n".join(f"- {f}" for f in known) or "(none)")
                + f"\n\nListener: {message}\nWren: {reply}",
            },
        ]
    )
    for fact in out.get("facts") or []:
        if isinstance(fact, str) and fact.strip() and fact.strip() not in known:
            mem.remember_fact(fact.strip())


def write_follow_up(mem: Memory, loop: str, stamp: str) -> None:
    """One follow-up into the person's memory. The engine keeps its own rewrite of it ("On
    2026-10-14, the user noted…"); the notebook shows the line as Wren wrote it, so the app
    records which memories this line became."""
    out = mem.remember(
        f"To follow up next time (noted {stamp}): {loop}", container=FOLLOW_UPS, title="Follow-up"
    )
    keep_jots(mem, {m: {"text": loop, "day": stamp} for m in out.get("memory_ids") or []})


JOTS = "notebook.json"
_jot_lock = threading.Lock()


def jots(mem: Memory) -> dict[str, dict]:
    """{memory id: {text, day}}: the follow-ups this app wrote, as Wren wrote them."""
    path = mem.path / JOTS if mem.path is not None else None
    if path is None or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def keep_jots(mem: Memory, written: dict[str, dict]) -> None:
    if mem.path is None or not written:
        return
    with _jot_lock:
        (mem.path / JOTS).write_text(json.dumps(jots(mem) | written, indent=1), encoding="utf-8")


@app.post("/api/end")
def end(body: Session) -> dict:
    """Close the session: the conversation is written once, its open loops become follow-ups."""
    mem, writer = person(body.user)
    turns = [t.model_dump() for t in body.history if t.content.strip()]
    if not any(t["role"] == "user" for t in turns):
        return {"loops": [], "pending": writer.pending, "written": False}
    today = _today()
    # An example date for the prompt: the next Thursday after today.
    example = date.fromordinal(today.toordinal() + ((3 - today.weekday()) % 7 or 7))
    transcript = "\n".join(
        f"{'Listener' if t['role'] == 'user' else 'Wren'}: {t['content']}" for t in turns
    )
    out = llm.json_reply(
        [
            {
                "role": "system",
                "content": OPEN_LOOPS.format(
                    today=_today_text(), example=example.strftime("%Y-%m-%d")
                ),
            },
            {"role": "user", "content": transcript},
        ]
    )
    loops = [x.strip() for x in out.get("loops") or [] if isinstance(x, str) and x.strip()]
    stamp = today.isoformat()
    writer.submit(
        "writing the conversation",
        lambda: mem.remember_conversation(
            turns, container=CONVERSATIONS, title=f"Chat with Wren, {stamp}"
        ),
    )
    for loop in loops:
        writer.submit("writing a follow-up", lambda loop=loop: write_follow_up(mem, loop, stamp))
    return {"loops": loops, "pending": writer.pending, "written": True}


@app.post("/api/open")
def open_session(body: Who):
    """A new session: Wren speaks first, with a follow-up from what it remembers."""
    mem, writer = person(body.user)

    def events():
        if writer.pending:
            yield {"type": "waiting", "pending": writer.pending}
        writer.flush()
        recall = mem.recall(
            "upcoming events, plans and things to follow up on", container=FOLLOW_UPS, limit=5
        )
        facts = profile_facts(mem)
        recent = mem.recall("what we talked about last time", container=CONVERSATIONS, limit=2)
        hits = unique(Recall(recall.query, hits=recall.hits + recent.hits))
        mine = jots(mem)
        for h in hits:  # the line Wren wrote, for a follow-up she recalled
            h["jot"] = mine.get(h["source"].removeprefix("episode:"))
        yield {
            "type": "memories",
            "hits": hits,
            "facts": facts,
            "seconds": round(recall.seconds + recent.seconds, 2),
        }
        messages = [
            {"role": "system", "content": SYSTEM.format(today=_today_text())},
            {"role": "system", "content": memory_block(facts, hits)},
            {"role": "user", "content": OPENER.format(today=_today_text())},
        ]
        for delta in llm.stream(messages, temperature=0.7):
            yield {"type": "delta", "text": delta}
        yield {"type": "done"}

    return sse(events())


if __name__ == "__main__":
    run(app, port=8708)
