"""Video memory: videos become memory shot by shot and line by line, and a moment is found by
what was seen or what was said in it.

A video goes in once. Membase's media memory watches it (finds where each shot starts and ends
and captions it) and listens to it (transcribes the dialogue and works out which person on
screen says each line). Every shot and every line is its own memory, with its time. Later you
describe what you saw ("a dragon flying at sunset") or quote what you heard ("the old man says
it's not safe here"), and the video plays from that second. Under the player is the video as
memory holds it, a track of shots and a track of lines, with the moment that matched lit up.

The videos are the Blender Foundation's open movies (CC BY)."""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from membase.errors import MembaseError
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from videos import VIDEOS, VIDEOS_DIR  # noqa: E402

from demokit import Memory  # noqa: E402
from demokit.web import create_app, run  # noqa: E402

DEMO = "18-video-memory"
CONTAINER = "Videos"
VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
# No request names a Memory: a media write lands in the local engine's write target.
os.environ.setdefault("MEMBASE_WRITE_TARGET", CONTAINER)

mem = Memory(DEMO, user="me", default_mode="local")
app = create_app("Video memory", HERE, mode=mem.mode)
UPLOADS = mem.path / "uploads"
UPLOADS.mkdir(exist_ok=True)
work = ThreadPoolExecutor(max_workers=2, thread_name_prefix="adding")
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()

_FRAMING = re.compile(
    r"^(the|this) (image|scene|frame|shot|picture) (depicts|features|shows|captures|displays|"
    r"presents|portrays)\s+",
    re.I,
)


def media_url(url: str | None) -> str | None:
    """A file media memory serves (`file_url`, a moment's `thumb_url`), as a URL under /files."""
    if not url:
        return None
    return "/files/" + url.removeprefix("/v1/media/")


def shot_text(caption: str) -> str:
    """A caption as a line about the shot: "A dragon soars...", not "The image depicts..."."""
    text = _FRAMING.sub("", caption.strip())
    return text[:1].upper() + text[1:]


def moment_json(m: dict) -> dict:
    said = m["kind"] == "speech"
    return {
        "t": round(m["t"], 2),
        "end": round(m["end"], 2) if m.get("end") is not None else None,
        "kind": "said" if said else "seen",
        "text": m["text"] if said else shot_text(m["text"]),
        "speaker": m.get("speaker"),
        "sure": m.get("speaker_confidence"),
        "thumb": media_url(m.get("thumb_url")),
    }


def video_json(row: dict) -> dict:
    """A video as memory holds it: its shots and its lines, each a moment with its time."""
    moments = [moment_json(m) for m in row["moments"]]
    shots = [m for m in moments if m["kind"] == "seen"]
    lines = [m for m in moments if m["kind"] == "said"]
    return {
        "id": row["id"],
        "key": row.get("custom_id") or "",
        "title": row["filename"],
        "duration": row["duration"],
        "summary": row["summary"],
        "url": media_url(row["file_url"]),
        "poster": shots[len(shots) // 2]["thumb"] if shots else None,
        "shots": shots,
        "lines": lines,
        "speakers": list(dict.fromkeys(m["speaker"] for m in lines if m["speaker"])),
    }


def in_memory() -> list[dict]:
    rows = [r for r in mem.client.media.list(limit=1000)["items"] if r["kind"] == "video"]
    return [video_json(mem.client.media.get(r["id"])) for r in reversed(rows)]


def add(job_id: str, path: Path, title: str, key: str) -> None:
    started = time.monotonic()
    try:
        out = mem.client.media.add(path, title=title, custom_id=key)
        with jobs_lock:
            jobs[job_id].update(
                status="done", media_id=out["id"], seconds=round(time.monotonic() - started)
            )
    except Exception as e:
        with jobs_lock:
            jobs[job_id].update(status="error", error=f"{type(e).__name__}: {e}")
        raise


def _reported(future) -> None:
    if future.exception():
        print(f"adding: {future.exception()}", file=sys.stderr)


def start(path: Path, title: str, key: str) -> dict:
    job = {
        "id": uuid.uuid4().hex[:10],
        "key": key,
        "title": title,
        "status": "adding",
        "started": time.time(),
    }
    with jobs_lock:
        jobs[job["id"]] = job
    work.submit(add, job["id"], path, title, key).add_done_callback(_reported)
    return job


@app.get("/api/memory")
def memory() -> dict:
    """The videos in memory, the sample videos not added yet, and videos being added."""
    videos = in_memory()
    have = {v["key"] for v in videos}
    with jobs_lock:
        running = [dict(j) for j in jobs.values() if j["status"] != "done"]
    busy = {j["key"] for j in running if j["status"] == "adding"}
    waiting = [
        {"key": key, "title": v["title"], "file": v["file"], "year": v["year"]}
        for key, v in VIDEOS.items()
        if (VIDEOS_DIR / v["file"]).is_file() and key not in have and key not in busy
    ]
    return {
        "videos": videos,
        "waiting": waiting,
        "jobs": running,
        "totals": {
            "videos": len(videos),
            "shots": sum(len(v["shots"]) for v in videos),
            "lines": sum(len(v["lines"]) for v in videos),
            "voices": sum(len(v["speakers"]) for v in videos),
        },
    }


@app.post("/api/samples/{key}")
def add_sample(key: str) -> dict:
    v = VIDEOS.get(key)
    if not v or not (VIDEOS_DIR / v["file"]).is_file():
        raise HTTPException(404, f"no sample video {key!r}: run seed.py --fetch first")
    return start(VIDEOS_DIR / v["file"], v["title"], key)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_TYPES:
        raise HTTPException(
            400, f"{suffix or 'that'} is not a video file ({', '.join(sorted(VIDEO_TYPES))})"
        )
    key = uuid.uuid4().hex[:8]
    dest = UPLOADS / f"{key}{suffix}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    if not dest.stat().st_size:
        dest.unlink()
        raise HTTPException(400, "the file is empty")
    return start(dest, Path(file.filename).stem, key)


@app.delete("/api/jobs/{job_id}")
def dismiss(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.pop(job_id, None)
    if not job:
        raise HTTPException(404, "no such job")
    return {"dismissed": job_id}


@app.delete("/api/videos/{media_id}")
def remove(media_id: str) -> dict:
    """Forget a video: its shots, its lines and its file leave media memory."""
    return mem.client.media.delete(media_id, confirm=True)


class Find(BaseModel):
    q: str


@app.post("/api/find")
def find(body: Find) -> dict:
    """The moments that match, best first, grouped by video."""
    q = body.q.strip()
    if not q:
        raise HTTPException(400, "describe what you saw or quote what was said")
    started = time.monotonic()
    out = mem.client.media.search(q, kind="video", limit=6)
    return {
        "q": q,
        "seconds": round(time.monotonic() - started, 1),
        "results": [
            {
                "id": r["id"],
                "title": r["filename"],
                "moments": [moment_json(m) for m in r["moments"]],
            }
            for r in out["items"]
        ],
    }


_SERVED = re.compile(r"(med_[A-Za-z0-9_-]+)/(?:file|thumbs/([^?#]+))")


@app.get("/files/{path:path}")
def files(path: str, request: Request) -> Response:
    """A video or a thumbnail, from media memory's own file routes; a range for the player."""
    found = _SERVED.fullmatch(path)
    if not found:
        raise HTTPException(404, "no such file")
    try:
        f = mem.client.media.file(
            found[1], thumb=found[2], range=request.headers.get("range") or None
        )
    except MembaseError as e:
        raise HTTPException(404 if (e.status or 500) < 500 else 502, "no such file") from e
    headers = {"content-range": f.content_range} if f.content_range else {}
    return Response(f.content, f.status, media_type=f.content_type, headers=headers)


if __name__ == "__main__":
    run(app, port=8718)
