"""Put the course into memory: five synthetic lecture notes on introductory cell biology.

    uv run 03-study-buddy/seed.py               # all five lectures
    uv run 03-study-buddy/seed.py --lectures 2  # the first two (faster to try)

Each lecture in `course/` becomes one document in the `Study` container. Re-running skips
lectures already there (each carries a stable custom_id).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from demokit import Memory  # noqa: E402

CONTAINER = "Study"
COURSE = HERE / "course"


def lectures() -> list[tuple[str, str, str]]:
    """(custom_id, title, text) for each lecture note, in course order."""
    out = []
    for path in sorted(COURSE.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip()
        out.append((f"bio110:{path.stem}", title, text))
    return out


def _latest_run(mem: Memory) -> dict:
    """The Study memory's latest learning run (every document reports the container's latest)."""
    docs = mem.documents(CONTAINER)
    if not docs:
        return {}
    newest = max(docs, key=lambda d: str(d.get("created_at") or ""))
    return mem.client.documents.get(newest["id"]).get("learning_run") or {}


def _wait_learning(mem: Memory) -> dict:
    """Until the latest learning run is no longer queued or running. Waits on the container,
    not on the returned document: a write can come back with `document_id: null` when the
    folder sync is slow, and writing the next lecture then would start a
    second run that fails."""
    time.sleep(3)
    while (run := _latest_run(mem)).get("status") in ("queued", "running"):
        time.sleep(10)
    return run


def verify(mem: Memory, docs: list[tuple[str, str, str]]) -> None:
    """Every lecture is there under its own title, and learned. Exits non-zero otherwise, so a
    recording never starts on a half-learned course."""
    have = {d.get("title"): d for d in mem.documents(CONTAINER)}
    problems = []
    for _, title, _ in docs:
        d = have.get(title)
        if d is None:
            problems.append(f"{title!r} is missing (or lost its title)")
        elif mem.mode == "hosted" and not mem.client.documents.get(d["id"]).get("learned"):
            run = _latest_run(mem)
            problems.append(
                f"{title!r} is not learned (latest run {run.get('id')} {run.get('status')})"
            )
    if problems:
        raise SystemExit("the course is not ready:\n  " + "\n  ".join(problems))
    print(
        "All lectures are in memory under their titles"
        + (" and learned." if mem.mode == "hosted" else ".")
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--lectures", type=int, default=5, help="how many lectures to load")
    a = p.parse_args()

    mem = Memory("03-study-buddy", default_mode="hosted")
    docs = lectures()[: a.lectures]
    print(f"{len(docs)} lecture(s) into {CONTAINER!r} on the {mem.mode} base")
    for custom_id, title, text in docs:
        started = time.monotonic()
        out = mem.add_document(text, container=CONTAINER, title=title, custom_id=custom_id)
        run = {}
        if mem.mode == "hosted" and out.get("status") != "exists":
            # A write while the Memory is still learning starts a second run, which fails
            # ("Another learning run is active") and leaves the document unlearned. So hosted
            # writes go one learning run at a time.
            run = _wait_learning(mem)
        note = f"run {run.get('status')}" if run else ""
        print(f"  {title:<55} {out.get('status'):<8} {time.monotonic() - started:5.1f}s {note}")
    verify(mem, docs)


if __name__ == "__main__":
    main()
