"""Dated memories on the local engine.

`memories.add` stamps each memory with the time of the call. A care log, a recorded
conversation or a past run needs the time it happened (pills at 08:15 logged at 08:40; a week
of history seeded at once), so writes go to the local engine's sessions with their own `session_date` — the same call `memories.add`
makes, with the date given instead of now — and come back with the memory ids that `forget`
takes. Recall keeps each hit's date and memory id, which `demokit.Recall` drops.
"""

from __future__ import annotations

import threading

from membase.errors import MembaseError

from .config import ConfigError
from .memory import Memory

# The local engine writes a new container's metadata file in place while every write reads
# all of them, so two first writes at once can read a half-written file. One at a time here.
_CREATE = threading.Lock()


def _backend(mem: Memory):
    if mem.mode != "local":
        raise ConfigError(
            "this demo dates each memory by when it happened, which needs the local engine: "
            "unset MEMBASE_DEMO_MODE or set it to local"
        )
    return mem.client._http._transport.backend  # noqa: SLF001 - see the module docstring


def remember_sessions(
    mem: Memory, sessions: list[dict], *, container: str, owner: str | None = None
) -> dict[str, list[str]]:
    """Sessions ({session_id, session_date ISO, turns: [{role, content}]}) into `container`,
    each dated by its own `session_date`. Returns each session's memory ids (empty when the
    engine kept nothing from it)."""
    b = _backend(mem)
    with _CREATE:
        cid = b._resolve(container, create=True)  # noqa: SLF001
    engine, lock = b.engine(cid)
    wanted = {s["session_id"] for s in sessions}
    with lock:
        engine.ingest_sessions_parallel(sessions, episode_owner=owner)
        engine.save()
        ids: dict[str, list[str]] = {sid: [] for sid in wanted}
        for e in engine.episodes(limit=1_000_000):
            if e["session_id"] in wanted:
                ids[e["session_id"]].append(f"{cid}:{e['id']}")
    return ids


def recall(mem: Memory, query: str, *, container: str, limit: int = 10) -> list[dict]:
    """Hits as {memory_id, content, title, date, score}; nothing when the container is empty."""
    try:
        out = mem.client.search(query, container=mem.container(container), limit=limit)
    except MembaseError as e:
        if e.status == 403:  # a local container that has never been written to
            return []
        raise
    hits = []
    for r in out.get("results", []):
        source = str(r.get("source") or "")
        if not source.startswith("episode:"):
            continue
        hits.append(
            {
                "memory_id": source.removeprefix("episode:"),
                "content": r.get("content") or "",
                "title": r.get("title") or "",
                "date": r.get("session_date") or "",
                "score": float(r.get("score") or 0.0),
            }
        )
    return hits
