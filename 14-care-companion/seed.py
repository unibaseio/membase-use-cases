"""A synthetic week of care notes for a synthetic person, Margaret.

    uv run 14-care-companion/seed.py           # the week up to Tuesday; the demo clock at 12:30
    uv run 14-care-companion/seed.py --reset   # start over (deletes this demo's local memory)

Margaret, her daughter Anna, her grandson Leo, her neighbour Mr. Okafor, her caregiver Sofia
and Dr. Reyes are all made up. Each note is written to memory dated when it happened, and the
demo clock is set to the most recent Tuesday (today, if it is a Tuesday) at 12:30. So "this
morning" and "yesterday" mean the same thing whenever the demo is opened, and the follow-up
with Dr. Reyes is always on Thursday.
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


def week(today: datetime) -> list[tuple[int, str, str, str]]:
    """(day offset from today, HH:MM, kind, what the caregiver wrote)."""
    appt = today + timedelta(days=2)
    dentist = today + timedelta(days=8)
    return [
        (
            -6,
            "08:10",
            "meds",
            "Morning pills taken with breakfast (donepezil and the blood pressure tablet).",
        ),
        (-6, "12:30", "meal", "Lunch: tomato soup and a cheese sandwich. Ate all of it."),
        (
            -6,
            "15:00",
            "appointment",
            "Saw Dr. Reyes at the Elm Street surgery for a blood pressure check. All fine.",
        ),
        (-6, "20:00", "meds", "Evening pills taken."),
        (-5, "08:20", "meds", "Morning pills taken."),
        (-5, "11:00", "note", "Short walk to the duck pond with Sofia. Margaret fed the ducks."),
        (
            -5,
            "16:00",
            "visitor",
            "Grandson Leo visited for an hour and brought photos from his school trip.",
        ),
        (-5, "20:05", "meds", "Evening pills taken."),
        (
            -4,
            "08:30",
            "meds",
            "Refused morning pills at first; took them at 09:15 after a cup of tea.",
        ),
        (-4, "13:00", "meal", "Lunch: fish pie. Ate about half."),
        (-4, "14:00", "visitor", "Hairdresser Paula came to the house for a cut and set."),
        (-4, "20:00", "meds", "Evening pills taken."),
        (-3, "08:05", "meds", "Morning pills taken."),
        (
            -3,
            "10:30",
            "visitor",
            "Neighbour Mr. Okafor dropped in with tomatoes from his garden and stayed for coffee.",
        ),
        (
            -3,
            "19:00",
            "note",
            "Phone call with her sister Jean in Dundee, about 20 minutes. Margaret was cheerful.",
        ),
        (-3, "20:10", "meds", "Evening pills taken."),
        (-2, "08:15", "meds", "Morning pills taken."),
        (-2, "12:45", "meal", "Lunch: shepherd's pie, ate all of it, and rice pudding."),
        (-2, "20:00", "meds", "Evening pills taken."),
        (
            (appt - today).days,
            "10:30",
            "appointment",
            f"Follow-up with Dr. Reyes at the Elm Street surgery on {appt:%A} {appt.day} {appt:%B}. "
            "Anna will drive.",
        ),
        (
            (dentist - today).days,
            "09:00",
            "appointment",
            f"Dentist check-up with Dr. Lin on {dentist:%A} {dentist.day} {dentist:%B}.",
        ),
        (-1, "08:10", "meds", "Morning pills taken."),
        (-1, "12:45", "meal", "Lunch: chicken and rice. Ate about half."),
        (
            -1,
            "15:00",
            "visitor",
            "Daughter Anna visited, stayed for tea and brought yellow tulips.",
        ),
        (-1, "20:00", "meds", "Evening pills taken."),
        (0, "07:55", "meal", "Breakfast: porridge with honey and a cup of tea."),
        (
            0,
            "08:15",
            "meds",
            "Morning pills taken with breakfast (donepezil and the blood pressure tablet).",
        ),
        (
            0,
            "10:00",
            "note",
            "Did the crossword together with Sofia; Margaret got the long answer.",
        ),
        (0, "11:30", "visitor", "Physiotherapist Tom came for leg exercises, 30 minutes."),
    ]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--reset", action="store_true", help="delete this demo's local memory first")
    a = p.parse_args()

    if a.reset:
        sys.path.insert(0, str(HERE.parent))
        from demokit.config import DATA  # noqa: PLC0415

        shutil.rmtree(DATA / "14-care-companion" / "margaret", ignore_errors=True)
    import app as demo  # noqa: PLC0415 - after any reset

    if demo.log.entries():
        sys.exit(f"{demo.log.path} already has entries: run with --reset to start over")

    today = datetime.now().replace(hour=12, minute=30, second=0, microsecond=0)
    today -= timedelta(days=(today.weekday() - 1) % 7)  # the most recent Tuesday
    entries = []
    for offset, hhmm, kind, text in week(today):
        h, m = map(int, hhmm.split(":"))
        at = (today + timedelta(days=offset)).replace(hour=h, minute=m)
        entries.append(demo.new_entry(kind, text, at.isoformat(timespec="minutes")))
    demo.log.put(*entries)
    started = time.monotonic()
    demo.write_entries(entries)
    demo.set_clock(today)
    saved = sum(1 for e in demo.log.entries() if e["status"] == "saved")
    print(
        f"{saved}/{len(entries)} notes in memory in {time.monotonic() - started:.0f}s; "
        f"demo clock {today:%A %d %B %H:%M}"
    )
    if saved != len(entries):
        sys.exit("some notes did not reach memory: see log.json for why")


if __name__ == "__main__":
    main()
