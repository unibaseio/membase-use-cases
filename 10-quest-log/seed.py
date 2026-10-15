"""Three weeks of synthetic quest history for one player, into memory and the chronicle.

    uv run 10-quest-log/seed.py

Writes every day from the Monday three weeks before the next planned Monday up to yesterday,
one memory per day in the `Quest log` container, dated by that day (the days are written in
parallel, about 20 s on the local engine). Re-running skips days already in memory.

The history has habits to find. The 7:00 gym session is skipped on every Monday (late Sundays),
while the 18:30 gym session on Wednesdays and Fridays is always done. "Clear the whole inbox" is
skipped, while a 15-minute sweep gets done. Morning deep work gets done and afternoon deep work
does not. `expected()` says what the Monday evidence must be, so the smoke and the video can
check the app's counts against it.
"""

from __future__ import annotations

import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as demo  # noqa: E402

# Per weekday (Monday = 0): (title, category, difficulty, slot, done?, notes by occurrence)
WEEK: dict[int, list[tuple]] = {
    0: [
        (
            "Morning gym session at 7:00",
            "body",
            "hard",
            "morning",
            False,
            [
                "Sunday night ran late; snoozed the alarm three times.",
                "Standup moved to 8:30 and there was no time before it.",
                "Too tired after a late Sunday. Felt guilty all morning.",
            ],
        ),
        ("Deep work: Atlas onboarding flows", "work", "hard", "morning", True, [""]),
        (
            "Clear the whole inbox",
            "work",
            "normal",
            "afternoon",
            False,
            [
                "Meetings all afternoon.",
                "Got through 20 of 140 emails and gave up.",
                "Back-to-back calls.",
            ],
        ),
        ("Read 20 pages before bed", "mind", "easy", "evening", True, [""]),
    ],
    1: [
        ("Deep work block 9:00-11:00", "work", "hard", "morning", True, [""]),
        ("Prep for the 1:1 with Priya", "work", "easy", "midday", True, [""]),
        ("Cook dinner at home", "home", "normal", "evening", True, [""]),
        ("Read 20 pages before bed", "mind", "easy", "evening", True, [""]),
    ],
    2: [
        (
            "Evening gym session at 18:30",
            "body",
            "hard",
            "evening",
            True,
            ["Went straight from work, felt great.", "Short but done."],
        ),
        ("Deep work: Atlas research synthesis", "work", "hard", "morning", True, [""]),
        (
            "Afternoon deep work: write the usability report",
            "work",
            "hard",
            "afternoon",
            False,
            ["Meetings ate the afternoon.", "Kept getting pulled into Slack threads."],
        ),
        ("Read 20 pages before bed", "mind", "easy", "evening", True, [""]),
    ],
    3: [
        ("Deep work: prototype review", "work", "hard", "morning", True, [""]),
        (
            "Clear the whole inbox",
            "work",
            "normal",
            "afternoon",
            False,
            ["Too big, didn't start.", ""],
        ),
        ("Call Mum", "social", "easy", "evening", True, [""]),
        ("Read 20 pages before bed", "mind", "easy", "evening", False, ["Fell asleep."]),
    ],
    4: [
        (
            "Evening gym session at 18:30",
            "body",
            "hard",
            "evening",
            True,
            ["", "Added a 10-minute stretch."],
        ),
        ("Weekly review", "mind", "normal", "afternoon", True, [""]),
        (
            "15-minute inbox sweep",
            "work",
            "easy",
            "midday",
            True,
            ["Archived 60 emails, felt lighter."],
        ),
    ],
    5: [
        ("Long run, 8 km", "body", "hard", "morning", True, ["Slow and easy."]),
        ("Laundry and tidy the flat", "home", "normal", "midday", True, [""]),
        ("Dinner with Jun and Ade", "social", "normal", "evening", True, [""]),
    ],
    6: [
        ("Meal prep for the week", "home", "normal", "afternoon", True, [""]),
        (
            "Plan the week",
            "mind",
            "easy",
            "evening",
            False,
            ["Stayed up past 1 am watching a series.", "Stayed up late again, skipped it."],
        ),
        ("Read 20 pages before bed", "mind", "easy", "evening", True, [""]),
    ],
}


def first_day(plan_day: date) -> date:
    """The Monday three weeks before the planned Monday: the history holds exactly three Mondays."""
    return plan_day - timedelta(weeks=3)


def history(plan_day: date, end: date) -> list[tuple[str, list[dict]]]:
    seen: dict[str, int] = {}
    days = []
    day = first_day(plan_day)
    while day <= end:
        quests = []
        for title, category, difficulty, slot, done, notes in WEEK[day.weekday()]:
            n = seen.get(title, 0)
            seen[title] = n + 1
            quests.append(
                {
                    "id": uuid.uuid5(uuid.NAMESPACE_URL, f"{day}:{title}").hex[:8],
                    "title": title,
                    "category": category,
                    "difficulty": difficulty,
                    "xp": demo.XP[difficulty],
                    "slot": slot,
                    "status": "done" if done else "skipped",
                    "note": notes[n % len(notes)],
                }
            )
        days.append((day.isoformat(), quests))
        day += timedelta(days=1)
    return days


def expected(plan_day: date | None = None) -> dict:
    """What the seeded history says about the 7:00 gym on the planned Monday: skipped on each
    of the three Mondays before it, and the 18:30 sessions that were done (up to yesterday, as
    seeded)."""
    plan_day = plan_day or demo.next_monday()
    days = history(plan_day, date.today() - timedelta(days=1))
    gym = lambda title: [  # noqa: E731
        (d, q["status"]) for d, qs in days for q in qs if q["title"] == title
    ]
    return {
        "mondays": gym("Morning gym session at 7:00"),
        "evenings": gym("Evening gym session at 18:30"),
    }


def main() -> None:
    plan_day = demo.next_monday()
    end = date.today() - timedelta(days=1)
    plan = history(plan_day, end)
    have = demo.log.days()
    todo = [(d, qs) for d, qs in plan if not have.get(d, {}).get("memory_ids")]
    print(
        f"{len(plan)} days ({plan[0][0]} to {plan[-1][0]}) into {demo.CONTAINER!r} on the "
        f"{demo.mem.mode} base; {len(plan) - len(todo)} already in memory"
    )
    started = time.monotonic()
    ids = demo.remember_days(todo) if todo else {}
    with demo.log.lock:
        days = demo.log.days()
        for day, quests in todo:
            days[day] = {
                "plan": "; ".join(q["title"] for q in quests),
                "quests": quests,
                "memory_ids": ids[day],
            }
        demo.log.save(days)
    for day, quests in todo:
        marks = " ".join("+" if q["status"] == "done" else "x" for q in quests)
        print(f"  {demo.weekday(day):<9} {day}  {marks:<10} {len(ids[day])} memory")
    empty = [d for d, _ in todo if not ids[d]]
    if empty:
        raise SystemExit(f"the engine kept nothing for {empty}")
    print(f"written in {time.monotonic() - started:.0f}s; the next planned Monday is {plan_day}")


if __name__ == "__main__":
    main()
