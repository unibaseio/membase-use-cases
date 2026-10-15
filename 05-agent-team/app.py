"""Agent team: an Investigator, a Fixer and a Reviewer share one Membase memory, each with its
own key; an Auditor with a read-only key can search it, and its write is refused by Membase."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from fastapi.responses import JSONResponse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import team  # noqa: E402

from demokit import config  # noqa: E402
from demokit.web import create_app, run, sse  # noqa: E402

app = create_app("Agent team", HERE, mode=config.mode("hosted"))
_running = threading.Lock()


@app.post("/api/run")
def start():
    team.keys()  # a missing key is a clear error now, not mid-stream
    if not _running.acquire(blocking=False):
        return JSONResponse(
            {"error": "a run is already going; wait for it to finish"}, status_code=409
        )

    def events():
        try:
            for event in team.run():
                yield {k: v for k, v in event.items() if k != "result_for_model"}
        finally:
            _running.release()

    return sse(events())


@app.get("/api/feed")
def feed() -> dict:
    return {"documents": team.feed()}


@app.get("/api/fixture")
def fixture() -> dict:
    """The repository the agents work on, for the page's side panel."""
    files = {}
    for p in sorted(team.FIXTURE.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.name != "__init__.py":
            files[str(p.relative_to(team.FIXTURE))] = p.read_text(encoding="utf-8")
    return {"files": files}


if __name__ == "__main__":
    run(app, port=8705)
