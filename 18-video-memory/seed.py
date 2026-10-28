"""The sample videos, and the two already in memory.

    uv run 18-video-memory/seed.py --fetch    # only download the three videos
    uv run 18-video-memory/seed.py            # download, then add Elephants Dream and Tears of Steel
    uv run 18-video-memory/seed.py --reset    # start over (deletes this demo's local memory)
    uv run 18-video-memory/seed.py --reuse DIR   # copy videos fetched before from DIR

The Sintel trailer is left for the page to add.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from videos import VIDEOS, VIDEOS_DIR, fetch  # noqa: E402

from demokit import Memory  # noqa: E402

DEMO = "18-video-memory"
CONTAINER = "Videos"
ADDED = ["elephants-dream", "tears-of-steel"]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--fetch", action="store_true", help="only download the videos")
    p.add_argument("--reset", action="store_true", help="delete this demo's local memory first")
    p.add_argument("--reuse", type=Path, help="a folder holding the videos' MP4 files already")
    a = p.parse_args()

    if a.reuse:
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        for r in VIDEOS.values():
            src = a.reuse / r["file"]
            if src.is_file() and not (VIDEOS_DIR / r["file"]).is_file():
                shutil.copy2(src, VIDEOS_DIR / r["file"])
    for key in VIDEOS:
        fetch(key)
    if a.fetch:
        return

    mem = Memory(DEMO, user="me", default_mode="local")
    if a.reset:
        mem.close()
        shutil.rmtree(mem.path)
        mem = Memory(DEMO, user="me", default_mode="local")
    for key in ADDED:
        r = VIDEOS[key]
        started = time.monotonic()
        out = mem.client.media.add(
            VIDEOS_DIR / r["file"], container=CONTAINER, title=r["title"], custom_id=key
        )
        if out["status"] == "exists":
            print(f"  {r['title']}: in memory already")
            continue
        print(
            f"  {r['title']}: {out['moments']} shots and lines in {time.monotonic() - started:.0f}s"
        )
    mem.close()


if __name__ == "__main__":
    main()
