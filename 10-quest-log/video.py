"""The quest log video, on the local engine. After the architecture card: Rin's Quest Log, a cozy
RPG quest log. Rin tells the scribe the plan for next Monday, with the 7:00 gym on it again; the
scribe turns to the past days in the chronicle (memory gives them back, each with its date); the
app counts them (the 7:00 gym was skipped on each of the last three Mondays, the 18:30 sessions
were all done); the gym quest is rewritten to 18:30 with a scribe's note that carries those
dates. Rin marks it done: a Complete stamp, the XP, and the day goes into the chronicle, dated.

The take checks the counts against what seed.py wrote, and stops if they differ.
"""

from datetime import date, timedelta

META = {
    "title": "Quest log",
    "title_html": "A quest log that<br>remembers how days went",
    "pitch": "Every closed quest is remembered with its date. The next plan is counted against past days like it, and the quest that keeps failing is rewritten.",
    "base": "local",
    "port": 8710,
    "banner_from_recording": True,
    "arch": {
        "kick": "How it works",
        "title": "Rin's outcomes are dated memories; the app counts what recall returns",
        "nodes": [
            {
                "t": "Quest log memory",
                "d": "data/10-quest-log/rin/: one memory per day, dated by the day it was for",
                "mb": True,
            },
            {
                "t": "Recall",
                "d": "the planned weekday, and each item at any time; every hit keeps its date",
                "mb": True,
            },
            {
                "t": "Model",
                "d": "says which recalled days mention each item, with a quote; the app checks the quote and counts",
            },
            {
                "t": "Quest board",
                "d": "only a quest that keeps failing is rewritten, and its note shows the dates behind it",
            },
        ],
        "foot": "Membase keeps the history; the app does the arithmetic, so the numbers on screen are true.",
    },
}
SEED = ["10-quest-log/seed.py"]
PLAN = (
    "Gym at 7:00 before work, finish the Atlas slide deck, 15-minute inbox sweep at lunch, "
    "call Jun about Saturday, read 20 pages before bed"
)


def expected() -> tuple[list[str], list[str]]:
    """The days seed.py wrote: the three Mondays before the planned one (gym skipped), and the
    Wednesdays and Fridays since the first of them, up to yesterday (18:30 gym done)."""
    today = date.today()
    plan_day = today + timedelta(days=-today.weekday() % 7)
    first, last = plan_day - timedelta(weeks=3), today - timedelta(days=1)
    mondays = [(first + timedelta(weeks=k)).isoformat() for k in range(3)]
    evenings, d = [], first
    while d <= last:
        if d.weekday() in (2, 4):
            evenings.append(d.isoformat())
        d += timedelta(days=1)
    return mondays, evenings


def short(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d.day} {d.strftime('%b')}"


async def act(page, rec) -> None:
    mondays, evenings = expected()
    first = date.fromisoformat(mondays[0])
    days = (date.today() - first).days  # seeded: the first Monday up to yesterday
    await page.wait_for_function(
        "() => /days remembered/.test(document.querySelector('#chronstat').textContent)",
        timeout=60_000,
    )
    await page.wait_for_timeout(600)

    rec.step(1, "Rin plans next Monday", f"The chronicle already holds {days} days, each dated")
    await rec.focus(None)
    await rec.pause(1.6)
    await rec.focus("#rail", pad=6)
    await rec.pause(2.2)
    rec.step(1, "Rin plans next Monday", "The 7:00 gym is on the list again")
    await rec.focus("#stage", pad=6)
    await rec.type("#plan", PLAN, delay=16)
    await rec.pause(1.0)
    await rec.click("#go")

    rec.step(2, "The scribe turns to past days", "Memory gives them back, each with its date")
    await rec.focus("#rail", pad=6)
    await rec.wait("Recalling past days", page.wait_for_selector("#rail.reading", timeout=180_000))
    await rec.pause(2.6)
    await rec.wait(
        "Reading each day for the plan's items",
        page.wait_for_selector("#evidence .ev.flag", timeout=180_000),
    )
    flagged = await page.evaluate(
        "() => [...document.querySelectorAll('#evidence .ev.flag')].map((r) => r.textContent)"
    )
    if len(flagged) != 1 or "Gym" not in flagged[0]:
        raise SystemExit(f"expected exactly the gym to be flagged, got {flagged}")
    await rec.pause(0.6)  # the tally paints before the camera moves onto it

    rec.step(
        3,
        "The app counts: skipped on each of the last 3 Mondays",
        f"7:00 gym: {', '.join(short(d) for d in mondays)}. At 18:30: done {len(evenings)} of {len(evenings)}",
    )
    await rec.focus("#evidence .ev.flag", pad=14)
    await rec.pause(2.6)
    # a date is a day memory gave back: hovering it lights that day in the chronicle, with its words
    await rec.focus(None)
    await rec.hover("#evidence .ev.flag .chip-d.skipped >> nth=1", pause=3.0)
    await rec.wait(
        "Drawing up the quests", page.wait_for_function("() => window.__plan", timeout=120_000)
    )
    plan = await page.evaluate("() => window.__plan")
    item = next((e for e in plan["evidence"] if e["adapt"]), None)
    habit = item and item["habit"]
    works = item and item["works"]
    got = (
        [r["day"] for r in habit["days"]] if habit else [],
        [r["status"] for r in habit["days"]] if habit else [],
        [r["day"] for r in works["days"]] if works else [],
    )
    if got != (mondays, ["skipped"] * 3, evenings) or not habit["consecutive"]:
        raise SystemExit(
            f"the counted evidence {got} is not what seed.py wrote ({mondays}, {evenings})"
        )
    quest = next((q for q in plan["quests"] if q["change"]), None)
    if not quest or quest["slot"] != "evening" or "18:30" not in quest["title"]:
        raise SystemExit(f"the gym quest did not move to 18:30: {quest}")
    await rec.hover("#plansum", pause=0.6)

    rec.step(
        4,
        "Monday's gym quest is rewritten",
        "Moved to 18:30; the scribe's note carries the three dates",
    )
    await rec.focus(".quest.adapted", pad=12)
    await rec.pause(5.5)

    # the loop closes: the outcome goes back into memory, dated by its day
    rec.step(
        5,
        "Monday evening: Rin goes",
        f"Quest complete: +{quest['xp']} XP, and the day is remembered, dated {short(plan['date'])}",
    )
    await rec.click(".quest.adapted button.done", pause=1.4)
    await rec.focus("#rail", pad=6)
    await rec.wait(
        "Writing the outcome to memory",
        page.wait_for_function(
            "(want) => document.querySelector('#chronstat').textContent === want",
            arg=f"{days + 1} days remembered · Mon {short(mondays[0])} – Mon {short(plan['date'])}",
            timeout=120_000,
        ),
    )
    await rec.pause(2.4)
    await rec.focus(None)
    await rec.pause(2.4)
