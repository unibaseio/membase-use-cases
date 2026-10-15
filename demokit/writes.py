"""Two ways demos write memory without making the person wait or losing a write.

**BackgroundWriter** (local engine). A local write takes 5-8 s. Writes for one person run one
at a time, in order, off the request path; the page can show how many are pending and the last
one that failed, and `flush()` waits for them (before a read that must see them).

**HostedQueue** (hosted). Every hosted write starts a learning run in the container. A second
write while a run is still going starts a second run, and that run fails ("Another learning
run is active for this memory"); nothing retries it, and every document in the container then
reads as not learned. So hosted writes go through one queue per container: each waits until
the container's latest learning run has finished, then writes. A write that cannot go at once
is reported as `waiting`, never as done.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor


class BackgroundWriter:
    """Writes for one person run one at a time, in order, off the request path. A local write
    takes 5-8 s; the page shows how many are still running and the last one that failed."""

    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._lock = threading.Lock()
        self._futures: list[Future] = []
        self.error = ""

    def submit(self, label: str, fn: Callable[[], object]) -> None:
        def job() -> None:
            try:
                fn()
            except Exception as e:  # noqa: BLE001 - kept for the page, which shows it
                self.error = f"{label}: {e}"
                raise

        with self._lock:
            self._futures = [f for f in self._futures if not f.done()]
            self._futures.append(self._pool.submit(job))

    @property
    def pending(self) -> int:
        with self._lock:
            return sum(1 for f in self._futures if not f.done())

    def flush(self, timeout: float = 180) -> None:
        """Wait for every write in flight; a failed one is raised once, then dropped."""
        with self._lock:
            futures = list(self._futures)
        for f in futures:
            f.exception(timeout=timeout)
        with self._lock:
            self._futures = [f for f in self._futures if not f.done()]
        for f in futures:
            if f.exception() is not None:
                raise RuntimeError(f"a memory write failed: {self.error}") from f.exception()


logger = logging.getLogger(__name__)
BUSY = ("queued", "running")


class HostedQueue:
    """Hosted writes to one container, one learning run at a time (see the module docstring)."""

    def __init__(self, mem, container: str, *, max_wait: float = 900) -> None:
        self.mem, self.container, self.max_wait = mem, container, max_wait
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self.waiting: dict[str, dict] = {}  # custom_id -> row for a write not made yet
        self.failed: dict[str, dict] = {}  # custom_id -> row with the error
        self._last_doc: str | None = None
        threading.Thread(target=self._loop, daemon=True, name=f"writer:{container}").start()

    def rows(self) -> list[dict]:
        """Writes still waiting behind a learning run, then writes that failed."""
        with self._lock:
            return [*self.waiting.values(), *self.failed.values()]

    def submit(
        self, custom_id: str, row: dict, write: Callable[[], dict], *, wait: float = 15
    ) -> dict:
        """Queue `write` (returns the API's answer). Waits up to `wait` seconds for it to go
        through, so an idle container answers with the written document; otherwise the answer
        says it is waiting behind the current learning run."""
        done = threading.Event()
        result: dict = {}
        with self._lock:
            if custom_id in self.waiting:
                return {**self.waiting[custom_id], "already": True}
            self.failed.pop(custom_id, None)
            self.waiting[custom_id] = {**row, "learned": False, "learning": "waiting"}
        self._q.put((custom_id, write, done, result))
        if done.wait(wait) and result:
            if "error" in result:
                raise RuntimeError(result["error"])
            return result
        return {**row, "learned": False, "learning": "waiting", "status": "waiting"}

    def _idle(self) -> None:
        """Until the container's latest learning run is no longer queued or running."""
        if self._last_doc is None:
            docs = self.mem.documents(self.container)
            self._last_doc = docs[0]["id"] if docs else None
        if self._last_doc is None or self.mem.mode != "hosted":
            return
        deadline = time.monotonic() + self.max_wait
        while time.monotonic() < deadline:
            run = self.mem.client.documents.get(self._last_doc).get("learning_run") or {}
            if run.get("status") not in BUSY:
                return
            time.sleep(5)
        logger.warning("learning run still busy after %ss; writing anyway", self.max_wait)

    def _loop(self) -> None:
        while True:
            custom_id, write, done, result = self._q.get()
            try:
                self._idle()
                out = write()
                self._last_doc = out.get("document_id") or self._last_doc
                with self._lock:
                    row = self.waiting.pop(custom_id, {})
                result.update(
                    {
                        **row,
                        "id": out.get("document_id"),
                        "learned": False,
                        "learning": (out.get("learning_run") or {}).get("status"),
                        "status": out.get("status"),
                    }
                )
            except Exception as e:  # noqa: BLE001 - kept for the page to show, and logged
                logger.exception("write failed")
                with self._lock:
                    row = self.waiting.pop(custom_id, {})
                    self.failed[custom_id] = {**row, "learning": "write failed", "error": str(e)}
                result["error"] = str(e)
            finally:
                done.set()
