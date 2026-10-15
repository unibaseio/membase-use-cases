"""A synthetic runner's last four weeks: ten runs as post-run summaries, and their goals.

    uv run 17-run-coach-hud/seed.py           # ten runs ending two days ago, and two goals
    uv run 17-run-coach-hud/seed.py --reset   # start over (deletes this demo's local memory)

Jamie is made up. The pattern to find: every run of 8 km or more started faster than goal pace
and faded after km 7, with heart rate drifting past 175 just before; the easy runs were fine.
Each summary is written to memory dated the day it was run.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def m(s: str) -> int:
    a, b = s.split(":")
    return int(a) * 60 + int(b)


#: (days ago, time, kind, splits m:ss per km, avg HR, max HR, how it felt)
RUNS = [
    (
        27,
        "07:10",
        "easy run",
        "5:58 5:55 5:54 5:56 5:52 5:50",
        141,
        149,
        "Easy and relaxed. Calf fine.",
    ),
    (
        24,
        "18:30",
        "tempo run",
        "5:10 5:08 5:05 5:07 5:06 5:09 5:31 5:42",
        162,
        179,
        "Went out hard. Legs went heavy after km 6 and the left calf got tight.",
    ),
    (
        21,
        "07:45",
        "long run",
        "5:12 5:10 5:15 5:17 5:19 5:20 5:22 5:48 5:55 6:02 6:05 6:10",
        158,
        181,
        "Fine until km 7, then faded badly; walked twice in the last 3 km. Heart rate past 175 at km 7.",
    ),
    (19, "07:05", "easy run", "6:02 5:58 5:57 5:55 5:56", 139, 146, "Recovery jog, felt good."),
    (
        16,
        "18:15",
        "intervals",
        "5:40 4:45 5:50 4:42 5:52 4:44 5:55",
        156,
        177,
        "6x400 m, strong, even reps.",
    ),
    (
        14,
        "08:00",
        "long run",
        "5:05 5:07 5:10 5:12 5:14 5:16 5:19 5:52 6:01 6:08 6:12 6:15 6:20 6:22",
        165,
        183,
        "Started too fast again. Heart rate drifted to 178 by km 7, then the pace fell apart. Calf tight from km 8.",
    ),
    (
        11,
        "07:00",
        "easy run",
        "5:57 5:53 5:50 5:51 5:49 5:48",
        142,
        150,
        "Felt great, kept heart rate under 150.",
    ),
    (
        8,
        "07:20",
        "steady run",
        "5:12 5:10 5:11 5:13 5:12 5:14 5:16 5:44 5:52 5:58",
        160,
        180,
        "Good for 7 km, then faded: heart rate 176 at km 7 and legs gone for the last three.",
    ),
    (5, "18:40", "easy run", "6:00 5:58 5:56 5:57 5:55", 140, 147, "Recovery, easy."),
    (
        2,
        "07:15",
        "steady run",
        "5:08 5:06 5:05 5:09 5:11 5:13 5:15 5:41 5:49 5:53",
        163,
        181,
        "Went out too fast again and faded after km 7 to about 5:50. Heart rate 177 at km 7.",
    ),
]

GOALS = [
    "Jamie's goal: run the Riverside Half Marathon in about five weeks in under 1:52, which is "
    "5:18 per km, and finish strong instead of fading.",
    "Jamie keeps easy runs under heart rate 150; the left calf tightens when runs start too fast.",
]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--reset", action="store_true", help="delete this demo's local memory first")
    a = p.parse_args()
    if a.reset:
        sys.path.insert(0, str(HERE.parent))
        from demokit.config import DATA  # noqa: PLC0415

        shutil.rmtree(DATA / "17-run-coach-hud" / "jamie", ignore_errors=True)
    import app as demo  # noqa: PLC0415 - after any reset

    if demo.runs.all():
        sys.exit(f"{demo.runs.path} already has runs: run with --reset to start over")
    started = time.monotonic()
    for goal in GOALS:
        demo.mem.remember_fact(goal)
    today = datetime.now()
    made = []
    for days, hhmm, kind, splits, hr_avg, hr_max, felt in RUNS:
        h, mi = map(int, hhmm.split(":"))
        at = (today - timedelta(days=days)).replace(hour=h, minute=mi, second=0, microsecond=0)
        secs = [m(s) for s in splits.split()]
        made.append(
            {
                "id": f"seed-{days:02d}",
                "when": at.isoformat(timespec="minutes"),
                "kind": kind,
                "distance_km": float(len(secs)),
                "seconds": sum(secs),
                "splits": secs,
                "hr_avg": hr_avg,
                "hr_max": hr_max,
                "felt": felt,
            }
        )
    # One batch: the engine reads the ten summaries in parallel.
    ids = demo.remember_sessions(
        demo.mem,
        [
            {
                "session_id": f"run-{r['id']}",
                "session_date": datetime.fromisoformat(r["when"]).isoformat(timespec="seconds"),
                "turns": [{"role": demo.RUNNER, "content": demo.summary_text(r)}],
            }
            for r in made
        ],
        container=demo.CONTAINER,
    )
    for r in made:
        r["memory_ids"] = ids[f"run-{r['id']}"]
        demo.runs.add(r)
    missing = [r["id"] for r in made if not r["memory_ids"]]
    print(
        f"{len(made) - len(missing)}/{len(made)} runs and {len(GOALS)} goals in memory "
        f"in {time.monotonic() - started:.0f}s"
    )
    if missing:
        sys.exit(f"no memory was kept for {missing}")


if __name__ == "__main__":
    main()
