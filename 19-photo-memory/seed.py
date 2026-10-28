"""The sample photos, and the albums already in memory.

    uv run 19-photo-memory/seed.py --fetch    # only download the photos
    uv run 19-photo-memory/seed.py            # download, then add the Lisbon and Home albums
    uv run 19-photo-memory/seed.py --reset    # start over (deletes this demo's local memory)

The Kyoto album is left for the page to add.
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
from photos import PHOTOS, fetch  # noqa: E402

from demokit import Memory  # noqa: E402

DEMO = "19-photo-memory"
CONTAINER = "Photos"
ADDED = ["lisbon", "home"]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--fetch", action="store_true", help="only download the photos")
    p.add_argument("--reset", action="store_true", help="delete this demo's local memory first")
    a = p.parse_args()

    for key in PHOTOS:
        fetch(key)
    if a.fetch:
        return

    mem = Memory(DEMO, user="me", default_mode="local")
    if a.reset:
        mem.close()
        shutil.rmtree(mem.path)
        mem = Memory(DEMO, user="me", default_mode="local")
    started = time.monotonic()
    for key, r in PHOTOS.items():
        if r["album"] not in ADDED:
            continue
        out = mem.client.media.add(fetch(key), container=CONTAINER, title=r["title"], custom_id=key)
        print(f"  {r['title']:<20} {out.get('summary', 'in memory already')}")
    print(f"  added in {time.monotonic() - started:.0f}s")
    mem.close()


if __name__ == "__main__":
    main()
