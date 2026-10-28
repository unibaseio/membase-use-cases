"""The sample videos: Blender Foundation open movies (CC BY), fetched once and kept in
data/18-video-memory/videos/. The long films come as .mov and are made into 480p MP4 so a
browser can stream and seek them."""

from __future__ import annotations

import shutil
import subprocess
import urllib.request
from pathlib import Path

from demokit.config import ROOT

VIDEOS_DIR = ROOT / "data" / "18-video-memory" / "videos"

VIDEOS = {
    "elephants-dream": {
        "title": "Elephants Dream",
        "year": 2006,
        "file": "elephants_dream.mp4",
        "url": "https://download.blender.org/ED/elephantsdream-480-h264-st-aac.mov",
        "transcode": True,
    },
    "tears-of-steel": {
        "title": "Tears of Steel",
        "year": 2012,
        "file": "tears_of_steel.mp4",
        "url": "https://download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov",
        "transcode": True,
    },
    "sintel-trailer": {
        "title": "Sintel (trailer)",
        "year": 2010,
        "file": "sintel_trailer.mp4",
        "url": "https://download.blender.org/durian/trailer/sintel_trailer-480p.mp4",
        "transcode": False,
    },
}


def ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "membase-use-cases/0.1"})
    tmp = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(req, timeout=120) as r, tmp.open("wb") as out:
        shutil.copyfileobj(r, out)
    tmp.replace(dest)


def fetch(key: str) -> Path:
    """The video's MP4, downloaded (and made 480p) the first time."""
    r = VIDEOS[key]
    dest = VIDEOS_DIR / r["file"]
    if dest.is_file():
        return dest
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {r['title']}")
    if not r["transcode"]:
        download(r["url"], dest)
        return dest
    src = dest.with_name(dest.stem + "_src" + Path(r["url"]).suffix)
    if not src.is_file():
        download(r["url"], src)
    print(f"  making {dest.name} (480p)")
    tmp = dest.with_name(dest.stem + ".part.mp4")
    subprocess.run(
        [
            ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-vf",
            "scale=-2:480",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            str(tmp),
        ],
        check=True,
    )
    tmp.replace(dest)
    src.unlink()
    return dest
