"""Put the Saltmarrow story bible into memory: characters, world rules, style guide, two scenes.

    uv run 04-story-bible/seed.py

The files in `bible/` go in together as one document in the `Story Bible` container: one
hosted write, so one learning run reads all of it. All of it is original fiction written for
this demo. Re-running does nothing once the bible is there (it carries a stable custom_id).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from demokit import Memory  # noqa: E402

CONTAINER = "Story Bible"
TITLE = "Saltmarrow story bible"
CUSTOM_ID = "bible:saltmarrow"


def bible() -> str:
    """Every file in bible/, in order, as one text."""
    parts = [p.read_text(encoding="utf-8").strip() for p in sorted((HERE / "bible").glob("*.md"))]
    return "\n\n".join(parts) + "\n"


def main() -> None:
    mem = Memory("04-story-bible", default_mode="hosted")
    if any(d.get("custom_id") == CUSTOM_ID for d in mem.documents(CONTAINER)):
        print(f"{TITLE!r} is already in {CONTAINER!r}")
        return
    text = bible()
    started = time.monotonic()
    out = mem.add_document(text, container=CONTAINER, title=TITLE, custom_id=CUSTOM_ID)
    print(
        f"{TITLE!r} ({len(text):,} characters) into {CONTAINER!r} on the {mem.mode} base: "
        f"{out.get('status')} in {time.monotonic() - started:.1f}s"
    )
    if mem.mode == "hosted":
        # Wait for the learning run, then check: a recording must not start on an unlearned
        # bible, and a slow sync can drop the title.
        while True:
            time.sleep(10)
            docs = mem.documents(CONTAINER)
            doc = next((d for d in docs if d.get("title") == TITLE), None)
            newest = max(docs, key=lambda d: str(d.get("created_at") or "")) if docs else None
            run = (
                (mem.client.documents.get(newest["id"]).get("learning_run") or {}) if newest else {}
            )
            if run.get("status") not in ("queued", "running"):
                break
        if doc is None or not mem.client.documents.get(doc["id"]).get("learned"):
            raise SystemExit(
                f"the bible is not ready: title {'kept' if doc else 'lost'}, run {run}"
            )
        print(f"Learned in {time.monotonic() - started:.0f}s (run {run.get('id')}).")


if __name__ == "__main__":
    main()
