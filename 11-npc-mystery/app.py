"""NPC mystery: three characters who remember what you told them, and gossip.

Each player gets a directory of their own on the local engine, and inside it each character has
its own memory container. A character answers from its own container only: what you said to it,
and what others passed on to it ("Mara told me..."). When time passes, a character who heard
something from you tells its confidant (Mara tells Elsie): that is one write into the
confidant's container. The culprit recalls its own past statements so its story stays straight.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import story  # noqa: E402

from demokit import Memory, config, llm  # noqa: E402
from demokit.web import create_app, run, sse  # noqa: E402

DEMO = "11-npc-mystery"
app = create_app("NPC mystery", HERE, mode=config.mode("local"))
_PLAYER = re.compile(r"^[a-z0-9-]{4,40}$")


def container_of(npc: str) -> str:
    """Each character's memory container, under the player's own directory."""
    return story.NPCS[npc]["name"].split()[0]


class Game:
    """One player's game: their memory directory, the visible log, and a single writer so the
    local engine takes one write at a time."""

    def __init__(self, player: str) -> None:
        self.player = player
        self.mem = Memory(DEMO, user=player, default_mode="local")
        self.state_path = self.mem.path / "game.json"
        self.lock = threading.Lock()
        self.writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"write-{player}")
        self.pending: dict[str, list[Future]] = defaultdict(list)
        self.gossip_lock = threading.Lock()  # one gossip decision at a time, so none repeats
        if self.state_path.is_file():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        else:
            self.state = {
                "player": player,
                "created": time.time(),
                "chats": {npc: [] for npc in story.NPCS},
                "gossip": [],
                "auto_gossip": False,
                "accused": None,
            }
            self.save()

    def save(self) -> None:
        with self.lock:
            self.state_path.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    def write(self, npc: str, text: str, title: str) -> Future:
        """Queue one memory write into `npc`'s container; recall on that container waits for it."""
        started = time.monotonic()

        def job() -> float:
            self.mem.remember(text, container=container_of(npc), title=title)
            return time.monotonic() - started

        fut = self.writer.submit(job)
        self.pending[npc].append(fut)
        return fut

    def settle(self, npc: str) -> None:
        """Wait out the writes still landing in `npc`'s container, so recall sees them."""
        for fut in list(self.pending[npc]):
            fut.result()
        self.pending[npc] = [f for f in self.pending[npc] if not f.done()]


_games: dict[str, Game] = {}
_games_lock = threading.Lock()


def game(player: str) -> Game:
    if not _PLAYER.match(player or ""):
        raise HTTPException(400, "player must be 4-40 characters of a-z, 0-9 and '-'")
    with _games_lock:
        if player not in _games:
            _games[player] = Game(player)
        return _games[player]


def npc_or_400(npc: str) -> dict:
    if npc not in story.NPCS:
        raise HTTPException(400, f"unknown character {npc!r}; one of {', '.join(story.NPCS)}")
    return story.NPCS[npc]


def persona(npc: str, memories: str) -> str:
    c = story.NPCS[npc]
    return (
        f"You are {c['name']}, {c['role'].lower()}, a character in a text mystery game. Stay in "
        "character; never mention being an AI, a model or a game.\n\n"
        f"{story.WORLD}\n\nYour manner: {c['voice']}\nWhat you know: {c['knows']}\n"
        f"What you keep to yourself: {c['hides']}\n\n"
        "Rules:\n"
        "- Speak only from what you know, your memories below and what is said to you now. Do not "
        "invent new evidence.\n"
        "- Your memories are things this investigator said to you, things you said back, and "
        "things "
        "other people told you. When you know something only because someone else told you, say "
        "who "
        "told you (for example 'Mara told me...').\n"
        "- Never claim the investigator told you something unless it is in your memories or in "
        "this "
        "conversation. If you have not heard about something, say so.\n"
        "- Keep what you say consistent with what your memories show you said before.\n"
        "- Speak in your own voice: one to three short sentences, under 45 words. Spoken "
        "dialogue only: no stage directions, no lists, no summing up what was asked.\n\n"
        + (memories or "You have no memories of this investigator yet; you are meeting them now.")
    )


class Talk(BaseModel):
    player: str
    npc: str
    message: str


@app.get("/api/story")
def get_story() -> dict:
    return {
        "title": story.TITLE,
        "intro": story.INTRO,
        "npcs": [
            {
                "id": k,
                "name": v["name"],
                "role": v["role"],
                "color": v["color"],
                "place": v["place"],
                "idle": v["idle"],
            }
            for k, v in story.NPCS.items()
        ],
    }


@app.post("/api/new")
def new_game() -> dict:
    """A new player directory: every character starts with an empty memory."""
    player = "p-" + uuid.uuid4().hex[:10]
    g = game(player)
    return {"player": player, **public_state(g)}


def public_state(g: Game) -> dict:
    s = g.state
    return {
        "chats": s["chats"],
        "gossip": s["gossip"],
        "auto_gossip": s["auto_gossip"],
        "accused": s["accused"],
        "truth": story.TRUTH if s["accused"] else None,
        "culprit": story.CULPRIT if s["accused"] else None,
        "directory": str(g.mem.path),
        "memories": {npc: memory_count(g, npc) for npc in story.NPCS},
    }


def memory_count(g: Game, npc: str) -> dict:
    """What the app has written into `npc`'s container: exchanges with you, gossip heard."""
    return {
        "talks": sum(1 for m in g.state["chats"][npc] if m["role"] == "user"),
        "gossip": sum(1 for e in g.state["gossip"] if e["to"] == npc),
    }


@app.get("/api/game")
def get_game(player: str) -> dict:
    g = game(player)
    return {"player": player, **public_state(g)}


@app.post("/api/talk")
def talk(body: Talk):
    g = game(body.player)
    c = npc_or_400(body.npc)
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "say something first")
    if g.state["accused"]:
        raise HTTPException(409, "this case is closed; start a new game")

    def events():
        g.settle(body.npc)  # gossip or an earlier exchange may still be landing
        recall = g.mem.recall(message, container=container_of(body.npc), limit=6)
        yield {"type": "memories", "npc": body.npc, **recall.as_dict()}
        recent = g.state["chats"][body.npc][-4:]  # short-term: the last two exchanges only
        messages = [
            {
                "role": "system",
                "content": persona(body.npc, recall.context(f"{c['name']}'s memories")),
            },
            *[{"role": m["role"], "content": m["content"]} for m in recent],
            {"role": "user", "content": message},
        ]
        reply = ""
        for delta in llm.stream(messages, temperature=0.7):
            reply += delta
            yield {"type": "delta", "text": delta}
        reply = reply.strip()
        with g.lock:
            g.state["chats"][body.npc] += [
                {"role": "user", "content": message, "at": time.time()},
                {"role": "assistant", "content": reply, "at": time.time()},
            ]
        g.save()
        yield {"type": "reply_done"}

        exchange = (
            f'The investigator said to {c["name"]}: "{message}"\n{c["name"]} replied: "{reply}"'
        )
        seconds = g.write(body.npc, exchange, f"{c['name']} talks with the investigator").result()
        yield {"type": "saved", "npc": body.npc, "seconds": round(seconds, 1)}

        if g.state["auto_gossip"]:
            yield from gossip_round(g, body.npc, None, forced=False)
        yield {"type": "memories_now", "npc": body.npc, **memory_count(g, body.npc)}
        yield {"type": "done"}

    return sse(events())


def gossip_round(g: Game, src: str, dst: str | None, *, forced: bool):
    """`src` may pass on something the player said to it, to `dst` (by default its confidant).
    The model decides whether and what, from the character's habits; `forced` (time passes)
    makes it pass something on. Nobody is told the same thing twice."""
    with g.gossip_lock:
        yield from _gossip_round(g, src, dst, forced=forced)


def _gossip_round(g: Game, src: str, dst: str | None, *, forced: bool):
    c = story.NPCS[src]
    dst = dst or c["confidant"]
    t = story.NPCS[dst]
    told = {(e["from"], e.get("said_at"), e["to"]) for e in g.state["gossip"]}
    heard = [m for m in g.state["chats"][src] if m["role"] == "user"]
    fresh = [m for m in heard if (src, m["at"], dst) not in told][-3:]
    if not fresh:
        reason = (
            f"{c['name']} has not heard anything from you yet."
            if not heard
            else f"{c['name']} has already told {t['name']} all of that."
        )
        yield {"type": "no_gossip", "from": src, "to": dst, "reason": reason}
        return
    lines = "\n".join(f"{i + 1}. {m['content']}" for i, m in enumerate(fresh))
    decision = llm.json_reply(
        [
            {
                "role": "system",
                "content": (
                    f"You decide what {c['name']} ({c['role']}) passes on to {t['name']} "
                    f"({t['role']}) between scenes of a mystery game. {c['name']}'s gossip "
                    f"habit: {c['gossip']}.\n"
                    + (
                        f"Time has passed and they did meet {t['name']}; they DO pass something "
                        "on now.\n"
                        if forced
                        else "Most exchanges are not worth repeating; "
                        "gossip only when it fits the habit.\n"
                    )
                    + "Pass on only something the investigator actually said (below), as "
                    f"{c['name']} would say it to {t['name']}: spoken to {t['name']}, in "
                    f"{c['name']}'s own voice ({c['voice']}), one or two short sentences, "
                    "under 35 words. Say plainly that it was the investigator who said it. Keep "
                    "every concrete detail (objects, colours, places, times) exactly as the "
                    "investigator gave it.\n"
                    'Reply as JSON: {"gossip": true|false, "line": <number>, '
                    '"what": "<what is passed on>", "why": "<one short reason>"}'
                ),
            },
            {
                "role": "user",
                "content": f"What the investigator said to {c['name']} (latest last):\n{lines}",
            },
        ],
        temperature=0.5,
    )
    try:
        line = int(decision.get("line") or len(fresh)) - 1
    except (TypeError, ValueError):
        line = len(fresh) - 1
    what = str(decision.get("what") or "").strip()
    if not (forced or decision.get("gossip")) or not 0 <= line < len(fresh) or not what:
        yield {
            "type": "no_gossip",
            "from": src,
            "to": dst,
            "reason": str(decision.get("why") or "nothing worth repeating"),
        }
        return
    text = f"{c['name']} ({c['role']}) told {t['name']} this about the investigator: {what}"
    seconds = g.write(dst, text, f"Gossip from {c['name']}").result()
    entry = {
        "from": src,
        "to": dst,
        "what": what,
        "written": text,
        "said_at": fresh[line]["at"],
        "at": time.time(),
        "auto": not forced,
        "seconds": round(seconds, 1),
    }
    with g.lock:
        g.state["gossip"].append(entry)
    g.save()
    yield {"type": "gossip", **entry}


class Gossip(BaseModel):
    player: str
    src: str | None = None
    dst: str | None = None


@app.post("/api/gossip")
def gossip(body: Gossip) -> dict:
    """Time passes: one character (the chattiest who has heard from you, unless `src` is given)
    passes something on to its confidant (or to `dst`)."""
    g = game(body.player)
    if body.dst:
        npc_or_400(body.dst)
    if body.src:
        npc_or_400(body.src)
        if body.dst == body.src:
            raise HTTPException(400, "a character cannot gossip to itself")
        sources = [body.src]
    else:
        heard = [
            k
            for k in story.NPCS
            if k != body.dst
            and any(m["role"] == "user" for m in g.state["chats"][k])
            and (body.dst or story.NPCS[k]["confidant"]) != k
        ]
        if not heard:
            return {"type": "no_gossip", "reason": "Nobody has heard anything from you yet."}
        order = {"high": 0, "low": 1}
        sources = sorted(heard, key=lambda k: order.get(story.NPCS[k]["gossip"].split(":")[0], 2))
    last: dict = {}
    for src in sources:  # the chattiest first; someone who has told everything already passes
        last = list(gossip_round(g, src, body.dst, forced=True))[-1]
        if last["type"] == "gossip":
            break
    return last


class Setting(BaseModel):
    player: str
    auto_gossip: bool


@app.post("/api/settings")
def settings(body: Setting) -> dict:
    g = game(body.player)
    with g.lock:
        g.state["auto_gossip"] = body.auto_gossip
    g.save()
    return {"auto_gossip": body.auto_gossip}


class Accuse(BaseModel):
    player: str
    suspect: str


@app.post("/api/accuse")
def accuse(body: Accuse) -> dict:
    g = game(body.player)
    npc_or_400(body.suspect)
    with g.lock:
        g.state["accused"] = body.suspect
    g.save()
    return {
        "correct": body.suspect == story.CULPRIT,
        "suspect": body.suspect,
        "culprit": story.CULPRIT,
        "truth": story.TRUTH,
    }


@app.get("/api/recall")
def recall(player: str, npc: str, q: str = "the investigator") -> dict:
    """What one character's memory returns for `q`: the page's memory inspector."""
    g = game(player)
    npc_or_400(npc)
    g.settle(npc)
    return g.mem.recall(q, container=container_of(npc), limit=10).as_dict()


if __name__ == "__main__":
    run(app, port=8711)
