"""One memory API for every demo, on either base.

* **hosted** — the Membase service, with a developer key. One account, its containers made in
  the app (or by `scripts/bootstrap_hosted.py`). This is the product itself.
* **local** — the same API answered in process by the local engine
  (`unibaseio-membase[local]`), one directory per end user. This is how an app that serves
  many people keeps each person's memory apart.

Every call below goes through the public SDK (`membase.Membase`). The agent-trace verbs
(cases and skills) exist only on the local engine today, so they reach its `LocalBackend` — the
same object the `membase agent` command uses — and say so plainly on hosted.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

from membase import Membase
from membase.errors import MembaseError

from . import config
from .config import ConfigError

_SAFE = re.compile(r"[^a-zA-Z0-9_.-]+")


@dataclass
class Hit:
    content: str
    container: str
    container_name: str
    source: str = ""
    score: float = 0.0
    title: str = ""

    def as_dict(self) -> dict:
        return {
            "content": self.content,
            "container": self.container,
            "container_name": self.container_name,
            "source": self.source,
            "score": self.score,
            "title": self.title,
        }


@dataclass
class Recall:
    query: str
    hits: list[Hit] = field(default_factory=list)
    seconds: float = 0.0
    #: Containers that could not answer, with why (a hosted container still waking, ...).
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
            self.client = Membase(
                api_key=key, base_url=os.environ.get("MEMBASE_BASE_URL") or None, timeout=300
            )
        self._ids: dict[str, str] = {}

    # ---- containers --------------------------------------------------------------------

    def container(self, name: str) -> str:
        """The id to pass for a container called `name`.

        Local: the name itself; the engine creates it on first write. Hosted: containers are
        made in the app, so a missing one is an error that names it."""
        if self.mode == "local":
            return name
        if name not in self._ids:
            for c in self.client.containers.list()["containers"]:
                self._ids[c["name"]] = c["id"]
                self._ids[c["id"]] = c["id"]
        if name not in self._ids:
            raise ConfigError(
                f"no container named {name!r} on this Membase account: create a Memory with that "
                f"name in the app, or run scripts/bootstrap_hosted.py --containers {name!r}"
            )
        return self._ids[name]

    def containers(self) -> list[dict]:
        return self.client.containers.list()["containers"]

    # ---- writes ------------------------------------------------------------------------

    def remember(self, text: str, *, container: str, title: str = "") -> dict:
        """One thing worth keeping. Hosted, every write starts a learning run in the account's
        agent, so write once per finished exchange, not per message."""
        return self.client.memories.add(text, container=self.container(container), title=title)

    def remember_conversation(self, turns: list[dict], *, container: str, title: str = "") -> dict:
        """A finished conversation, turn by turn (`role` user/assistant, `content`)."""
        transcript = "\n".join(
            f"{'User' if t['role'] == 'user' else 'Assistant'}: {t['content'].strip()}"
            for t in turns
            if (t.get("content") or "").strip()
        )
        return self.remember(transcript, container=container, title=title)

    def remember_fact(self, text: str) -> dict:
        """A standing fact about the user (their profile)."""
        return self.client.memories.add(text, static=True)

    def add_document(
        self, content: str, *, container: str, title: str = "", custom_id: str = ""
    ) -> dict:
        return self.client.add(
            content, container=self.container(container), title=title, custom_id=custom_id
        )

    def forget(self, memory_id: str, *, container: str | None = None) -> dict:
        return self.client.memories.forget(
            memory_id, container=self.container(container) if container else None, confirm=True
        )

    # ---- reads -------------------------------------------------------------------------

    def recall(
        self, query: str, *, container: str | None = None, limit: int = 8, wait: float = 0.0
    ) -> Recall:
        """Passages on `query`. Hosted containers that are still waking answer with an error
        instead of hits; with `wait` > 0 the search is retried until they answer or the time
        is up, and whoever stayed silent is reported in `unheard`."""
        started = time.monotonic()
        cid = self.container(container) if container else None
        while True:
            try:
                out = self.client.search(query, container=cid, limit=limit)
            except MembaseError as e:
                if self.mode == "local" and e.status == 403:
                    # A local container that has never been written to does not exist yet.
                    return Recall(query, seconds=time.monotonic() - started)
                raise
            unheard = [c for c in out.get("containers", []) if c.get("error")]
            if not unheard or time.monotonic() - started >= wait:
                break
            time.sleep(min(10.0, max(1.0, wait - (time.monotonic() - started))))
        hits = [
            Hit(
                content=str(r.get("content") or ""),
                container=str(r.get("container") or ""),
                container_name=str(r.get("container_name") or r.get("container") or ""),
                source=str(r.get("source") or ""),
                score=float(r.get("score") or 0.0),
                title=str(r.get("title") or ""),
            )
            for r in out.get("results", [])
        ]
        return Recall(query, hits=hits, seconds=time.monotonic() - started, unheard=unheard)

    def profile(self, topic: str | None = None) -> dict:
        return self.client.profile(topic)

    def documents(self, container: str | None = None) -> list[dict]:
        try:
            return self.client.documents.list(
                container=self.container(container) if container else None
            )["documents"]
        except MembaseError as e:
            if self.mode == "local" and e.status == 403:
                # A local container that has never been written to does not exist yet.
                return []
            raise

    # ---- agent memory: traces become cases, cases become skills (local engine) ----------

    def _backend(self):
        if self.mode != "local":
            raise ConfigError(
                "agent memory (cases and skills) runs on the local engine: "
                "set MEMBASE_DEMO_MODE=local for this demo"
            )
        return self.client._http._transport.backend  # noqa: SLF001 - see the module docstring

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
        self.client.close()
