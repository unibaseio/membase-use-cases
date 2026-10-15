"""Memory graph: what memory holds, drawn as people, places, projects, events and the links
between them.

There is no call that lists every memory, so the graph is built from what memory gives back:
the profile (standing facts and the latest memories), a set of broad searches, and one more
search per entity found (one hop out). A model then names the entities in those passages and
the links between them, each with the passages it came from. The result is cached per user;
Rebuild runs it again."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from membase.errors import MembaseError  # noqa: E402
from seed import keep_notes, own_notes  # noqa: E402

from demokit import Memory, config, llm  # noqa: E402
from demokit.memory import is_narration  # noqa: E402
from demokit.web import create_app, run, sse  # noqa: E402

DEMO = "07-memory-graph"
CONTAINER = "Life"
#: Whose notes these are, for the map's owner card (seed.py writes Lena's; another `user`
#: starts with an empty memory and goes by that name).
OWNERS = {"default": "Lena Varga"}
TYPES = ("self", "person", "place", "project", "event", "org")
BROAD = [
    "people I work with",
    "friends and family",
    "projects I am working on",
    "places I live in or travelled to",
    "events, trips and dates",
    "companies, clubs and organisations",
    "hobbies and sport",
    "what happened recently",
]
MAX_EXPAND = 24

_default = Memory(DEMO, default_mode="local")
app = create_app("Memory graph", HERE, mode=_default.mode)
_mems: dict[str, Memory] = {"default": _default}
_guard = threading.Lock()
# The local engine is one in-process store per user; one call at a time keeps a search from
# reading it while a write is half done. Hosted calls go over HTTP and can run side by side.
_locks: dict[str, threading.RLock] = {}


def memory(user: str) -> Memory:
    with _guard:
        if user not in _mems:
            _mems[user] = Memory(DEMO, user=user, default_mode="local")
        _locks.setdefault(user, threading.RLock())
        return _mems[user]


def _lock(user: str, mem: Memory):
    return _locks[user] if mem.mode == "local" else contextlib.nullcontext()


def _cache_file(user: str, mem: Memory) -> Path:
    if mem.path is not None:
        return mem.path / "graph.json"
    # Hosted: one cache per account key (the key is the account; `user` does not apply).
    key = hashlib.sha256(mem.client.api_key.encode()).hexdigest()[:12]
    d = config.DATA / DEMO / f"hosted-{key}"
    d.mkdir(parents=True, exist_ok=True)
    return d / "graph.json"


_CITE = re.compile(r"\s*\[\[([^\]]+)\]\]")


def _clean(text: str) -> str:
    return _CITE.sub("", text).strip()


# ---- gathering passages ---------------------------------------------------------------------


class Passages:
    """Every passage memory gave back, each once, numbered in the order found."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._seen: dict[str, int] = {}

    def add(self, text: str, via: str, date: str = "", memory_id: str = "") -> bool:
        text = _clean(text)
        key = re.sub(r"\s+", " ", text.lower())[:400]
        if not text:
            return False
        if key in self._seen:
            row = self.rows[self._seen[key] - 1]
            if via not in row["via"]:
                row["via"].append(via)
            return False
        self.rows.append(
            {
                "id": len(self.rows) + 1,
                "text": text,
                "via": [via],
                "date": date,
                "memory_id": memory_id,
            }
        )
        self._seen[key] = len(self.rows)
        return True

    def numbered(self) -> str:
        return "\n\n".join(f"[{r['id']}] {r['text']}" for r in self.rows)


def _date(value: str, text: str) -> str:
    """The day a memory is about: the local engine's session date, else the date the passage
    opens with ("On 2026-07-14, ..."), else nothing."""
    m = re.match(r"\d{4}-\d{2}-\d{2}", value or "")
    if m:
        return m.group(0)
    m = re.match(r"On (\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else ""


def _search(mem: Memory, query: str, limit: int) -> list[dict]:
    """Passages for `query`, each with the day it is about. The local engine's search carries
    each episode's session date, which `Memory.recall` leaves out, so local calls it directly.
    A hosted search that found nothing can answer with prose about it: that is dropped."""
    if mem.mode == "hosted":
        hits = [h.content for h in mem.recall(query, limit=limit, wait=60).hits]
        return [{"content": _clean(t), "date": _date("", t)} for t in hits if not is_narration(t)]
    try:
        rows = mem.client.search(query, limit=limit)["results"]
    except MembaseError as e:
        if e.status == 403:  # nothing written yet
            return []
        raise
    return [
        {
            "content": _clean(r.get("content") or ""),
            "date": _date(r.get("session_date"), ""),
            "memory_id": str(r.get("source") or "").removeprefix("episode:"),
        }
        for r in rows
    ]


def _with_own(mem: Memory, rows: list[dict]) -> list[dict]:
    """Each passage with the note it came from, as the app wrote it (`note`), when it is one of
    this app's notes. The passage itself stays: it is what memory returned."""
    notes = own_notes(mem)
    return [{**r, "note": notes.get(r.get("memory_id") or "")} for r in rows]


def _recall_all(
    mem: Memory, user: str, queries: list[str], limit: int
) -> list[tuple[str, list[dict]]]:
    if mem.mode == "hosted":
        with ThreadPoolExecutor(max_workers=4) as pool:
            found = list(pool.map(lambda q: _search(mem, q, limit), queries))
    else:
        with _lock(user, mem):
            found = [_search(mem, q, limit) for q in queries]
    return list(zip(queries, found, strict=True))


NAMES = (
    "List every named person, place, project, product, event and organisation in these memory "
    "passages. "
    'Reply with JSON: {"names": ["..."]}, full names where the passages give them.'
)

GRAPH = (
    "You turn memory passages into a knowledge graph of the memory owner's life. The owner is the "
    'entity named "You" (the passages call them "the user" or "I"). Entity types: person, '
    "place, project, event, org (companies, clubs, conferences' organisers), and self for You. "
    "An event is something that happened or will happen on a date (a kickoff, an offsite, a "
    "talk, a trip, a wedding, a race); give its date as the passages state it. Use one canonical "
    'name per entity: the full name when any passage gives it ("Tomás Reyes", not "Tomás"), '
    'and merge mentions of the same thing ("Project Atlas", "Atlas project" and "Atlas" are '
    'one entity, named "Atlas"). Relations are short verb phrases read from source to '
    'target ("manages", "works at", "sponsor of", "held in", "attended", "sister of", '
    '"climbs with", "part of"). Be thorough: every named person, place, project, event and '
    "organisation becomes an entity, and every stated link between two of them a relation. "
    "Every entity and every relation lists the numbers of the "
    "passages that state it; leave out anything no passage states. Reply with JSON: "
    '{"entities": [{"name": "...", "type": "...", "note": "who or what it is, in at most '
    'eight words", "date": "", "passages": [<numbers>]}], "relations": [{"source": '
    '"<entity name>", "target": "<entity name>", "label": "...", "passages": '
    "[<numbers>]}]}"
)


def _slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-") or "x"


_FILLER = {"the", "project", "a", "an"}


def _key(name: str) -> str:
    """One key for names that differ only by filler words or order ("Project Atlas", "Atlas")."""
    words = [w for w in _slug(name).split("-") if w not in _FILLER]
    return "-".join(sorted(words)) or _slug(name)


def _ids(raw, valid: set[int]) -> list[int]:
    out = []
    for v in raw or []:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n in valid and n not in out:
            out.append(n)
    return out


def build(mem: Memory, user: str):
    """Progress events, then the finished graph (also written to the cache)."""
    started = time.monotonic()
    passages = Passages()

    yield {"type": "step", "text": "Reading the profile"}
    with _lock(user, mem):
        profile = mem.profile()
    for fact in profile.get("static") or []:
        passages.add(str(fact), "profile: standing fact")
    for item in profile.get("dynamic") or []:
        text = str(item.get("content") or "")
        passages.add(
            text,
            "profile: recent memory",
            _date(item.get("session_date") or "", text),
            str(item.get("id") or ""),
        )
    yield {
        "type": "step",
        "text": f"Profile: {len(profile.get('static') or [])} standing facts, "
        f"{len(profile.get('dynamic') or [])} recent memories",
    }

    yield {"type": "step", "text": f"{len(BROAD)} broad searches"}
    for query, hits in _recall_all(mem, user, BROAD, limit=20):
        new = sum(
            passages.add(h["content"], f"search: {query}", h["date"], h.get("memory_id", ""))
            for h in hits
        )
        yield {"type": "step", "text": f"  “{query}”: {len(hits)} passages, {new} new"}
    if not passages.rows:
        raise RuntimeError("memory gave back nothing: seed it first (07-memory-graph/seed.py)")

    names = (
        llm.json_reply(
            [
                {"role": "system", "content": NAMES},
                {"role": "user", "content": passages.numbered()},
            ]
        ).get("names")
        or []
    )
    found = [str(n) for n in dict.fromkeys(names) if str(n).strip()]
    names = found[:MAX_EXPAND]
    yield {"type": "step", "text": f"One hop out: a search for each of {len(names)} names found"}
    for query, hits in _recall_all(mem, user, names, limit=8):
        new = sum(
            passages.add(h["content"], f"search: {query}", h["date"], h.get("memory_id", ""))
            for h in hits
        )
        if new:
            yield {"type": "step", "text": f"  “{query}”: {new} new"}

    yield {"type": "step", "text": f"Naming entities and links in {len(passages.rows)} passages"}
    raw = llm.json_reply(
        [
            {"role": "system", "content": GRAPH},
            {
                "role": "user",
                "content": (
                    "Names a first read found (a checklist: include each one the passages "
                    "support, and "
                    "any others you find): "
                    + "; ".join(found)
                    + "\n\nPassages:\n"
                    + passages.numbered()
                ),
            },
        ]
    )
    valid = {r["id"] for r in passages.rows}
    nodes: dict[str, dict] = {}
    for e in raw.get("entities") or []:
        name = str(e.get("name") or "").strip()
        kind = str(e.get("type") or "").strip().lower()
        ids = _ids(e.get("passages"), valid)
        if not name or not ids:
            continue  # an entity no passage states is not from memory
        if name.lower() in ("you", "the user", "user", "me"):
            name, kind = "You", "self"
        node = nodes.setdefault(
            _key(name),
            {
                "id": _slug(name),
                "name": name,
                "type": kind if kind in TYPES else "org",
                "note": str(e.get("note") or ""),
                "date": str(e.get("date") or ""),
                "passages": [],
            },
        )
        node["passages"] += [i for i in ids if i not in node["passages"]]
    # A bare first name ("Sam") is the same person as the one full name it starts ("Sam Okoro").
    for key, node in list(nodes.items()):
        if node["type"] != "person" or " " in node["name"]:
            continue
        fuller = [
            n
            for n in nodes.values()
            if n is not node and n["type"] == "person" and n["name"].startswith(node["name"] + " ")
        ]
        if len(fuller) == 1:
            fuller[0]["passages"] += [i for i in node["passages"] if i not in fuller[0]["passages"]]
            nodes[key] = fuller[0]
            continue
        # No node has the full name, but the passages may ("Felix" -> "Felix Brandt").
        said = re.compile(re.escape(node["name"]) + r" ([^\W\d_][\w'-]+)")
        surnames = {
            m.group(1)
            for r in passages.rows
            for m in said.finditer(r["text"])
            if m.group(1)[0].isupper()
        }
        if len(surnames) == 1:
            node["name"] = f"{node['name']} {surnames.pop()}"
            node["id"] = _slug(node["name"])
            nodes[_key(node["name"])] = node
    links: dict[tuple, dict] = {}
    for r in raw.get("relations") or []:
        ends = []
        for end in (str(r.get("source") or ""), str(r.get("target") or "")):
            end = "You" if end.strip().lower() in ("the user", "user", "me", "you") else end
            ends.append(nodes.get(_key(end)))
        ids = _ids(r.get("passages"), valid)
        label = str(r.get("label") or "").strip()
        if None in ends or ends[0] is ends[1] or not ids or not label:
            continue
        src, dst = ends[0]["id"], ends[1]["id"]
        link = links.setdefault(
            (src, dst, label.lower()),
            {"source": src, "target": dst, "label": label, "passages": []},
        )
        link["passages"] += [i for i in ids if i not in link["passages"]]
    graph = {
        "nodes": list({id(n): n for n in nodes.values()}.values()),
        "links": list(links.values()),
        "passages": _with_own(mem, passages.rows),
        "queries": BROAD,
        "expanded": names,
        "profile": {
            "static": len(profile.get("static") or []),
            "dynamic": len(profile.get("dynamic") or []),
        },
        "mode": mem.mode,
        "user": user,
        "built_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "seconds": round(time.monotonic() - started, 1),
    }
    _cache_file(user, mem).write_text(
        json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    yield {"type": "graph", "graph": graph}


# ---- routes -----------------------------------------------------------------------------------


def _user(value: str | None) -> str:
    return (value or "default").strip() or "default"


@app.get("/api/graph")
def get_graph(user: str = "default") -> dict:
    user = _user(user)
    mem = memory(user)
    path = _cache_file(user, mem)
    owner = OWNERS.get(user, user.title())
    if not path.is_file():
        return {"graph": None, "owner": owner}
    return {"graph": json.loads(path.read_text(encoding="utf-8")), "owner": owner}


class Rebuild(BaseModel):
    user: str = "default"


@app.post("/api/graph/rebuild")
def rebuild(body: Rebuild):
    user = _user(body.user)
    return sse(build(memory(user), user))


class Node(BaseModel):
    name: str
    user: str = "default"


@app.post("/api/recall")
def recall(body: Node) -> dict:
    """What memory says about one entity, searched live."""
    user = _user(body.user)
    mem = memory(user)
    query = "me, the user" if body.name == "You" else body.name
    started = time.monotonic()
    with _lock(user, mem):
        hits = _with_own(mem, _search(mem, query, 6))
    seen: set[str] = set()
    hits = [h for h in hits if not (h["content"] in seen or seen.add(h["content"]))]
    return {"query": query, "hits": hits, "seconds": round(time.monotonic() - started, 2)}


class Note(BaseModel):
    text: str
    user: str = "default"


@app.post("/api/remember")
def remember(body: Note) -> dict:
    text = body.text.strip()
    if not text:
        raise ValueError("write something to remember")
    user = _user(body.user)
    mem = memory(user)
    started = time.monotonic()
    with _lock(user, mem):
        out = mem.remember(text, container=CONTAINER, title=text[:60])
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        keep_notes(
            mem, {m: {"title": "", "day": day, "text": text} for m in out.get("memory_ids") or []}
        )
    return {
        "status": out.get("status"),
        "seconds": round(time.monotonic() - started, 1),
        "learning": mem.mode == "hosted",
    }


@app.exception_handler(ValueError)
def bad_request(_, e: ValueError):
    from fastapi.responses import JSONResponse

    return JSONResponse({"error": str(e)}, status_code=400)


if __name__ == "__main__":
    run(app, port=8707)
