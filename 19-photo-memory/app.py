"""Photo memory: photos become memory one sentence each, and a photo is found by describing it.

A photo goes in once. Membase's media memory looks at it and writes down what is in it, in one
sentence. Later you describe the photo the way you remember it ("rows of orange gates",
"something sweet we ate"), and memory finds it by meaning, not by file name or tags. Nothing was
tagged by hand.

The photos are from Wikimedia Commons (CC0, CC BY and CC BY-SA); photos.py lists their authors."""

from __future__ import annotations

import shutil
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from photos import ALBUMS, PHOTOS, PHOTOS_DIR  # noqa: E402

from demokit import Memory  # noqa: E402
from demokit.web import create_app, run  # noqa: E402

DEMO = "19-photo-memory"
CONTAINER = "Photos"
PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp"}

mem = Memory(DEMO, user="me", default_mode="local")
app = create_app("Photo memory", HERE, mode=mem.mode)
UPLOADS = mem.path / "uploads"
UPLOADS.mkdir(exist_ok=True)
work = ThreadPoolExecutor(max_workers=2, thread_name_prefix="adding")
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


def media_url(path: str | None) -> str | None:
    """A file media memory keeps, as a URL under /files."""
    if not path:
        return None
    return "/files/" + Path(path).resolve().relative_to(mem.path.resolve()).as_posix()


def description(summary: str) -> str:
    """A caption as a line about the photo: "A tram climbs...", not "The image shows a tram..."."""
    words = summary.strip().split(" ", 3)
    if len(words) == 4 and words[0].lower() in {"the", "this"} and words[1] in {"image", "photo"}:
        summary = words[3]
    return summary[:1].upper() + summary[1:]


def photo_json(row: dict) -> dict:
    key = row.get("custom_id") or ""
    return {
        "id": row["id"],
        "key": key,
        "album": PHOTOS[key]["album"] if key in PHOTOS else "yours",
        "title": row["filename"],
        "url": media_url(row["path"]),
        "description": description(row["summary"]),
    }


def in_memory() -> list[dict]:
    """The photos in memory, oldest first."""
    if not any(c["name"] == CONTAINER for c in mem.containers()):
        return []
    rows = mem.client.media.list(container=CONTAINER)["media"]
    return [photo_json(r) for r in reversed(rows)]


def add(job_id: str, items: list[tuple[Path, str, str]]) -> None:
    """Add photos one by one; the job counts them as they land."""
    started = time.monotonic()
    try:
        for path, title, key in items:
            mem.client.media.add(path, container=CONTAINER, title=title, custom_id=key)
            with jobs_lock:
                jobs[job_id]["done"] += 1
        with jobs_lock:
            jobs[job_id].update(status="done", seconds=round(time.monotonic() - started))
    except Exception as e:
        with jobs_lock:
            jobs[job_id].update(status="error", error=f"{type(e).__name__}: {e}")
        raise


def _reported(future) -> None:
    if future.exception():
        print(f"adding: {future.exception()}", file=sys.stderr)


def start(title: str, album: str, items: list[tuple[Path, str, str]]) -> dict:
    job = {
        "id": uuid.uuid4().hex[:10],
        "album": album,
        "title": title,
        "status": "adding",
        "done": 0,
        "total": len(items),
        "started": time.time(),
    }
    with jobs_lock:
        jobs[job["id"]] = job
    work.submit(add, job["id"], items).add_done_callback(_reported)
    return job


@app.get("/api/memory")
def memory() -> dict:
    """The photos in memory, the albums not added yet, and what is being added."""
    photos = in_memory()
    have = {p["key"] for p in photos}
    with jobs_lock:
        running = [dict(j) for j in jobs.values() if j["status"] != "done"]
    busy = {j["album"] for j in running if j["status"] == "adding"}
    waiting = []
    for album, name in ALBUMS.items():
        keys = [k for k, p in PHOTOS.items() if p["album"] == album and k not in have]
        if (
            keys
            and album not in busy
            and all((PHOTOS_DIR / PHOTOS[k]["file"]).is_file() for k in keys)
        ):
            waiting.append({"album": album, "title": name, "count": len(keys)})
    return {
        "photos": photos,
        "albums": ALBUMS,
        "waiting": waiting,
        "jobs": running,
    }


@app.post("/api/albums/{album}")
def add_album(album: str) -> dict:
    """Add the album's sample photos that are not in memory yet, in the background."""
    if album not in ALBUMS:
        raise HTTPException(404, f"no album {album!r}")
    have = {p["key"] for p in in_memory()}
    items = [
        (PHOTOS_DIR / p["file"], p["title"], k)
        for k, p in PHOTOS.items()
        if p["album"] == album and k not in have
    ]
    missing = [str(path.name) for path, _, _ in items if not path.is_file()]
    if missing:
        raise HTTPException(404, f"{', '.join(missing)} not fetched: run seed.py --fetch first")
    if not items:
        raise HTTPException(400, f"{ALBUMS[album]} is in memory already")
    return start(ALBUMS[album], album, items)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in PHOTO_TYPES:
        raise HTTPException(
            400, f"{suffix or 'that'} is not a photo ({', '.join(sorted(PHOTO_TYPES))})"
        )
    key = uuid.uuid4().hex[:8]
    dest = UPLOADS / f"{key}{suffix}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    if not dest.stat().st_size:
        dest.unlink()
        raise HTTPException(400, "the file is empty")
    title = Path(file.filename).stem
    return start(title, "yours", [(dest, title, key)])


@app.delete("/api/jobs/{job_id}")
def dismiss(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.pop(job_id, None)
    if not job:
        raise HTTPException(404, "no such job")
    return {"dismissed": job_id}


@app.delete("/api/photos/{media_id}")
def remove(media_id: str) -> dict:
    """Forget a photo: its description and its file leave media memory."""
    return mem.client.media.delete(media_id, confirm=True)


class Find(BaseModel):
    q: str


@app.post("/api/find")
def find(body: Find) -> dict:
    """The photos that match, best first."""
    q = body.q.strip()
    if not q:
        raise HTTPException(400, "describe the photo")
    started = time.monotonic()
    out = mem.client.media.search(q, container=CONTAINER, kind="image", limit=6)
    return {
        "q": q,
        "seconds": round(time.monotonic() - started, 1),
        "results": [{**photo_json(r), "found_by": r["channels"]} for r in out["results"]],
    }


@app.get("/files/{path:path}")
def files(path: str) -> FileResponse:
    target = (mem.path / path).resolve()
    if not target.is_relative_to(mem.path.resolve()) or not target.is_file():
        raise HTTPException(404, "no such file")
    return FileResponse(target)


if __name__ == "__main__":
    run(app, port=8719)
