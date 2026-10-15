"""The web shell every demo with a UI uses: FastAPI, the demo's own `static/`, the shared
`/kit` assets, server-sent events, and errors the page can show."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from membase.errors import MembaseError

from .config import ConfigError

logger = logging.getLogger("demokit")
KIT_STATIC = Path(__file__).parent / "static"


def create_app(title: str, demo_dir: Path, *, mode: str) -> FastAPI:
    """An app serving `demo_dir/static/index.html` at `/`, its files at `/static`, the shared
    kit at `/kit`, and `/api/info` (which base the memory runs on, for the header badge)."""
    app = FastAPI(title=title)

    @app.get("/api/info")
    def info() -> dict:
        return {"demo": demo_dir.name, "title": title, "mode": mode}

    static = demo_dir / "static"
    app.mount("/kit", StaticFiles(directory=KIT_STATIC), name="kit")
    if static.is_dir():
        app.mount("/static", StaticFiles(directory=static), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(static / "index.html")

    @app.exception_handler(MembaseError)
    def membase_error(_: Request, e: MembaseError) -> JSONResponse:
        # The SDK's own message is already actionable ("container is required ...").
        return JSONResponse({"error": str(e), "code": e.code}, status_code=e.status or 502)

    @app.exception_handler(ConfigError)
    def config_error(_: Request, e: ConfigError) -> JSONResponse:
        return JSONResponse({"error": str(e)}, status_code=500)

    return app


def sse(events: Iterable[dict]) -> StreamingResponse:
    """Each dict as one `data:` event. An exception mid-stream becomes an `error` event, so
    the page can say what went wrong instead of hanging."""

    def body() -> Iterator[bytes]:
        try:
            for event in events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()
        except Exception as e:  # noqa: BLE001 - reported to the page, logged here
            logger.exception("stream failed")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n".encode()

    return StreamingResponse(body(), media_type="text/event-stream")


def run(app: FastAPI, *, port: int) -> None:
    """`uv run <demo>/app.py` starts the server; PORT overrides the demo's own port."""
    import uvicorn

    port = int(os.environ.get("PORT") or port)
    print(f"\n  open http://127.0.0.1:{port}\n")
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=port, log_level="warning")


def timed(fn: Callable, *args, **kwargs) -> tuple[object, float]:
    import time

    started = time.monotonic()
    out = fn(*args, **kwargs)
    return out, time.monotonic() - started
