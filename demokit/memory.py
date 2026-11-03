"""One memory API for every demo, on either base.

* **hosted** — the Membase service, with developer keys. One account, its Memories made in
  the app (or by `scripts/bootstrap_hosted.py`). This is the product itself.
* **local** — the same API answered in process by the local engine
  (`unibaseio-membase[local]`), one directory per end user. This is how an app that serves
  many people keeps each person's memory apart.

The memory API never names a Memory in a request: a read covers every Memory the credential
reaches, and a write lands in its write target — the one Memory it reaches. A demo that keeps
several Memories (one per NPC, conversations apart from follow-ups) therefore holds one
credential per Memory: hosted, a developer key that reaches only that Memory
(`MEMBASE_KEY_FOR_<NAME>`, which `scripts/bootstrap_hosted.py` mints); local, the engine's write
target set for the write, and the engine's own search over that one Memory for a read.

Everything else goes through the public SDK (`membase.Membase`). The agent-trace verbs (cases
and skills) exist only on the local engine today, so they reach its `LocalBackend` — the same
object the `membase agent` command uses — and say so plainly on hosted.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from membase import Membase

from . import config
from .config import ConfigError

_SAFE = re.compile(r"[^a-zA-Z0-9_.-]+")


@dataclass
class Hit:
    content: str
    container: str
    container_name: str
    #: The `mem_` id of a learned fact (what `forget` takes); empty for a document's passage.
    source: str = ""
    score: float = 0.0
    title: str = ""
    #: `memory` (a learned fact) or `document` (a passage of material handed in).
    type: str = ""

    def as_dict(self) -> dict:
        return {
            "content": self.content,
            "container": self.container,
            "container_name": self.container_name,
            "source": self.source,
            "score": self.score,
            "title": self.title,
            "type": self.type,
        }


@dataclass
class Recall:
    query: str
    hits: list[Hit] = field(default_factory=list)
    seconds: float = 0.0
    #: Memories that could not answer, with why ({name, error}: one still waking, or learning).
    unheard: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "query": self.query,
            "hits": [h.as_dict() for h in self.hits],
            "seconds": round(self.seconds, 2),
            "unheard": self.unheard,
        }

    def context(self, heading: str = "Relevant memories") -> str:
        """The hits as a block to put in a prompt; empty when nothing was found."""
        if not self.hits:
            return ""
        lines = "\n".join(f"- {h.content}" for h in self.hits)
        return f"{heading}:\n{lines}"


# Hosted search answers "nothing found" with prose instead of an empty list:
# "No stored memory found about …", "I searched the fact store …". Such a hit is not memory.
_NARRATION = re.compile(
    r"^\W*(no (stored |relevant |matching )?(memory|memories|facts?|record)|i (found|could not|"
    r"couldn't|checked|searched|did not|didn't)|there (is|are) no|nothing (in|about)|"
    r"conclusion:|evidence:|findings|no (stored|saved)\b)|no (stored|relevant|matching) (memory|facts?) "
    r"(found|about)|\b(is|are) (not )?present in (the )?memory|not (stored|found|present) in (the )?memory|"
    r"memory (set )?contains no\b",
    re.I,
)


def is_narration(text: str) -> bool:
    """A hosted search's account of what it did not find, rather than a remembered passage."""
    return bool(_NARRATION.search(text.strip()))


class Memory:
    """A demo's memory. `user` picks the local directory; hosted ignores it (the key is the
    account)."""

    def __init__(self, demo: str, *, user: str = "default", default_mode: str = "local") -> None:
        self.demo = demo
        self.user = user
        self.mode = config.mode(default_mode)
        if self.mode == "local":
            config.require("OPENAI_API_KEY", "the local memory engine extracts and embeds with it")
            self.path = config.DATA / _SAFE.sub("_", demo) / _SAFE.sub("_", user)
            self.path.mkdir(parents=True, exist_ok=True)
            self.client = Membase(local=str(self.path))
        else:
            key = config.require(
                "MEMBASE_API_KEY", "this demo runs on hosted Membase (Connect > Developer keys)"
            )
            self.path = None
            self.client = self._hosted(key)
        self._names: set[str] | None = None
        self._clients: dict[str, Membase] = {}
        # The local engine has one write target at a time; a write sets it, under this lock.
        self._target = threading.Lock()

    @staticmethod
    def _hosted(key: str) -> Membase:
        return Membase(
            api_key=key, base_url=os.environ.get("MEMBASE_BASE_URL") or None, timeout=300
        )

    # ---- Memories ----------------------------------------------------------------------

    def containers(self) -> list[dict]:
        """The Memories this demo reaches, `{name, kind}`."""
        return list(self.client.capabilities().get("memories") or [])

    def container(self, name: str) -> str:
        """`name`, once it is known to be a Memory this demo can use.

        Local: any name; the engine creates the Memory on its first write. Hosted: Memories
        are made in the app, so a missing one is an error that names it."""
        if self.mode == "local":
            return name
        if self._names is None or name not in self._names:
            self._names = {m["name"] for m in self.containers()}
        if name not in self._names:
            raise ConfigError(
                f"no Memory named {name!r} on this Membase account: create one with that name in "
                f"the app, or run scripts/bootstrap_hosted.py --containers {name!r}"
            )
        return name

    def _only(self, name: str) -> Membase:
        """Hosted: a client whose key reaches `name` and nothing else — what a write needs, and
        what keeps a read to that one Memory."""
        self.container(name)
        if name not in self._clients:
            env = key_env(name)
            key = os.environ.get(env, "").strip()
            if key:
                self._clients[name] = self._hosted(key)
            elif [m["name"] for m in self.containers() if m.get("kind", "text") == "text"] == [
                name
            ]:
                self._clients[name] = self.client  # the main key reaches this Memory alone
            else:
                raise ConfigError(
                    f"{env} is not set: writing to {name!r}, or reading it alone, needs a key that "
                    f"reaches only that Memory (Connect > Developer keys), or run "
                    f"scripts/bootstrap_hosted.py, which mints one per Memory"
                )
        return self._clients[name]

    def _backend(self):
        if self.mode != "local":
            raise ConfigError(
                "agent memory (cases and skills) runs on the local engine: "
                "set MEMBASE_DEMO_MODE=local for this demo"
            )
        return self.client._http._transport.backend  # noqa: SLF001 - see the module docstring

    @contextmanager
    def _writing_to(self, name: str) -> Iterator[Membase]:
        """The client whose write lands in `name`."""
        if self.mode == "hosted":
            yield self._only(name)
            return
        backend = self._backend()
        with self._target:
            # What MEMBASE_WRITE_TARGET sets for `membase serve`, for this one write.
            backend._write_target = name  # noqa: SLF001
            try:
                yield self.client
            finally:
                backend._write_target = None  # noqa: SLF001

    # ---- writes ------------------------------------------------------------------------

    def remember(self, text: str, *, container: str, title: str = "") -> dict:
        """One thing worth keeping. Hosted, every write starts a learning run in the account's
        box, so write once per finished exchange, not per message. The receipt is the note it
        was written as: `{id: "doc_…", kind: "note", status, learning}`."""
        with self._writing_to(container) as c:
            return c.memories.add(text, title=title)

    def remember_conversation(self, turns: list[dict], *, container: str, title: str = "") -> dict:
        """A finished conversation, turn by turn (`role` user/assistant, `content`)."""
        transcript = "\n".join(
            f"{'User' if t['role'] == 'user' else 'Assistant'}: {t['content'].strip()}"
            for t in turns
            if (t.get("content") or "").strip()
        )
        return self.remember(transcript, container=container, title=title)

    def remember_fact(self, text: str) -> dict:
        """A standing statement about the user (their profile, the account's rather than a
        Memory's). The same one again keeps the one there (`created: false`)."""
        return self.client.profile_facts.add(text)

    def add_document(
        self, content: str, *, container: str, title: str = "", custom_id: str = ""
    ) -> dict:
        """Raw material into `container`; the same `custom_id` again is the same document."""
        with self._writing_to(container) as c:
            return c.documents.add(content, title=title, custom_id=custom_id)

    def forget(self, memory_id: str) -> dict:
        """Forget one `mem_` fact (the key needs Full access; the material it came from stays)."""
        return self.client.memories.forget(memory_id, confirm=True)

    # ---- reads -------------------------------------------------------------------------

    def recall(
        self, query: str, *, container: str | None = None, limit: int = 8, wait: float = 0.0
    ) -> Recall:
        """Passages on `query`, from every Memory or from `container` alone. A hosted Memory that
        is still waking (or learning) answers in `partial` instead of with hits; with `wait` > 0
        the search is retried until it answers or the time is up, and whoever stayed silent is
        reported in `unheard`."""
        started = time.monotonic()
        while True:
            if container and self.mode == "local":
                hits, unheard = self._local_search(query, container, limit)
            else:
                client = self._only(container) if container else self.client
                out = client.search(query, limit=limit)
                hits = [_hit(r) for r in out.get("items", [])]
                unheard = [
                    {"name": p.get("memory_name") or "", "error": p.get("reason") or "error"}
                    for p in out.get("partial", [])
                    if p.get("reason") != "truncated"
                ]
            if not unheard or time.monotonic() - started >= wait:
                break
            time.sleep(min(10.0, max(1.0, wait - (time.monotonic() - started))))
        return Recall(query, hits=hits, seconds=time.monotonic() - started, unheard=unheard)

    def _local_search(self, query: str, container: str, limit: int) -> tuple[list[Hit], list]:
        """The local engine's search over one Memory: what a key that reaches only that Memory
        reads on hosted."""
        from membase.local.backend import LocalError

        try:
            out = self._backend().search(query, container, limit)
        except LocalError as e:
            if e.status == 403:
                # A local Memory that has never been written to does not exist yet.
                return [], []
            raise
        hits = []
        for r in out.get("results", []):
            source = str(r.get("source") or "")
            kind, _, rest = source.partition(":")
            hits.append(
                Hit(
                    content=str(r.get("content") or ""),
                    container=container,
                    container_name=str(r.get("container_name") or container),
                    source=local_memory_id(rest) if kind == "episode" else "",
                    score=float(r.get("score") or 0.0),
                    title=str(r.get("title") or ""),
                    type="memory" if kind == "episode" else "document",
                )
            )
        unheard = [
            {"name": c["name"], "error": c["error"]} for c in out["containers"] if c.get("error")
        ]
        return hits, unheard

    def profile_facts(self) -> list[str]:
        """Who the user is: the standing statements, newest first."""
        return [str(f.get("content") or "") for f in self.client.profile_facts.list()["items"]]

    def documents(self, container: str | None = None) -> list[dict]:
        """The material handed in, newest first (`{id, kind, title, memory_name, learning, …}`)."""
        if container and self.mode == "hosted":
            return self._only(container).documents.list()["items"]
        items = self.client.documents.list()["items"]
        return [d for d in items if not container or d.get("memory_name") == container]

    def document(self, document_id: str) -> dict:
        """One document, with `learning` (each Memory's status) and two readings of it:
        `learned` (every Memory has read it) and `learning_status` (the one that matters now:
        failed, then processing, then pending, then succeeded)."""
        return with_learning(self.client.documents.get(document_id))

    # ---- agent memory: traces become cases, cases become skills (local engine) ----------

    def agent_ingest(
        self, messages: list[dict], *, agent_id: str, session_id: str, container: str
    ) -> dict:
        """An agent's run (OpenAI-style messages with tool calls) into its cases and skills."""
        return self._backend().agent_ingest(
            messages, agent_id=agent_id, session_id=session_id, container=container
        )

    def agent_search(self, query: str, *, agent_id: str, container: str, limit: int = 5) -> dict:
        return self._backend().agent_search(
            query, agent_id=agent_id, limit=limit, container=container
        )

    def agent_skills(self, *, agent_id: str, container: str) -> list[dict]:
        return self._backend().agent_skills(agent_id, container=container)["skills"]

    def close(self) -> None:
        for c in {id(c): c for c in [self.client, *self._clients.values()]}.values():
            c.close()


def key_env(name: str) -> str:
    """The variable holding the key that reaches only the Memory `name`: MEMBASE_KEY_FOR_<NAME>."""
    return "MEMBASE_KEY_FOR_" + re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")


def local_memory_id(internal: str) -> str:
    """The `mem_` id the API gives the local engine's fact `<container>:<n>`."""
    from membase.local import ids

    return ids.encode("memory", internal)


_ORDER = ("failed", "processing", "pending", "succeeded")


def with_learning(doc: dict) -> dict:
    """`doc` (a document or a write's receipt) with `learned` and `learning_status` read from
    its `learning` list."""
    states = [str(x.get("status") or "") for x in doc.get("learning") or []]
    status = next((s for s in _ORDER if s in states), doc.get("status") or "")
    return {
        **doc,
        "learned": bool(states) and all(s == "succeeded" for s in states),
        "learning_status": status,
    }


def _hit(r: dict) -> Hit:
    name = str(r.get("memory_name") or "")
    return Hit(
        content=str(r.get("content") or ""),
        container=name,
        container_name=name,
        source=str(r.get("id") or ""),
        score=float(r.get("score") or 0.0),
        title=str(r.get("title") or ""),
        type=str(r.get("type") or ""),
    )
