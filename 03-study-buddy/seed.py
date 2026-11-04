"""Put the course into memory: five synthetic lecture notes on introductory cell biology.

    uv run 03-study-buddy/seed.py               # all five lectures
    uv run 03-study-buddy/seed.py --lectures 2  # the first two (faster to try)

Each lecture in `course/` becomes one document in the `Study` Memory. Re-running skips
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


def _wait_learning(mem: Memory, document_id: str) -> dict:
    """Until the account has learned `document_id` (or failed to): a write answers at once and the
    learning runs after it. A write during a run is `pending`; that run starts the next one."""
    while (doc := mem.document(document_id))["learning_status"] in ("processing", "pending"):
        time.sleep(10)
    return doc


def verify(mem: Memory, docs: list[tuple[str, str, str]]) -> None:
    """Every lecture is there under its own title, and learned. Exits non-zero otherwise, so a
    recording never starts on a half-learned course."""
    have = {d.get("title"): d for d in mem.documents(CONTAINER)}
    problems = []
    for _, title, _ in docs:
        d = have.get(title)
        if d is None:
            problems.append(f"{title!r} is missing (or lost its title)")
        elif mem.mode == "hosted" and not (doc := mem.document(d["id"]))["learned"]:
            problems.append(f"{title!r} is not learned ({doc['learning_status']})")
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
    started = time.monotonic()
    written = []
    for custom_id, title, text in docs:
        out = mem.add_document(text, container=CONTAINER, title=title, custom_id=custom_id)
        print(f"  {title:<55} {out.get('status') or '':<10} {time.monotonic() - started:5.1f}s")
        written.append((title, out))
    if mem.mode == "hosted":
        # Every write answers at once; one written while a run is going is `pending`, and that
        # run starts the next. So write them all, then wait for each to be learned.
        for title, out in written:
            if out.get("id"):
                doc = _wait_learning(mem, out["id"])
                print(
                    f"  {title:<55} {doc['learning_status']:<10} {time.monotonic() - started:5.1f}s"
                )
    verify(mem, docs)


if __name__ == "__main__":
    main()
