"""The care companion video, on the local engine. After the architecture card: Hearth, a tablet
and a phone on a kitchen table. Sofia's phone holds the care log of Margaret's week (seed.py,
demo clock Tuesday 12:30). Margaret taps "Did I take my pills this morning?" on her tablet (yes,
8:15, today's note) and "When is my next doctor visit?" (Thursday). Sofia edits the note on her
phone: the visit moved to Friday 14:00, which forgets the old memory and writes the new one; the
old note stays in the log crossed out. Margaret asks again and hears Friday.

The questions are the tablet's own buttons and the edit is fixed text, so the take is
deterministic; a take whose answers do not say what the captions say is not kept.

    .venv/bin/python scripts/video/make.py 14-care-companion
"""

from datetime import datetime, timedelta

META = {
    "title": "Care companion",
    "title_html": "A memory aid that<br>knows what day it is",
    "pitch": "A caregiver logs the day. Margaret asks simple questions and gets warm answers with the time worked out. Fix a note, and the old one is forgotten.",
    "base": "local",
    "port": 8714,
    "banner_from_recording": True,
    "arch": {
        "kick": "How it works",
        "title": "Dated memories, recalled with the time worked out",
        "nodes": [
            {
                "t": "Caregiver's log",
                "d": "Sofia writes what happened: pills at 08:15, a visit, an appointment",
            },
            {
                "t": "Daily log memory",
                "d": "one memory per note on the local engine, dated when it happened",
                "mb": True,
            },
            {
                "t": "Recall + time",
                "d": "each recalled note is labelled today, yesterday or in 2 days; a model answers from those",
                "mb": True,
            },
            {
                "t": "Correct = forget",
                "d": "an edit deletes the old memory and writes the new one; the next answer changes",
                "mb": True,
            },
        ],
        "foot": "A demo with a made-up person and made-up notes. It is not a medical service.",
    },
}
SEED = ["14-care-companion/seed.py"]
ANSWERED = "() => !!document.querySelector('#answer-card') && !document.querySelector('#thinking')"


async def ask(page, rec, button: str) -> str:
    await rec.click(button)
    await rec.wait(
        "Recalling Sofia's notes, working out the time",
        page.wait_for_function(ANSWERED, timeout=120_000),
    )
    # the cursor comes to rest on the answer (a still page sends no new screencast frames)
    await rec.hover("#answer-text", pause=0.4)
    return await page.locator("#answer-text").inner_text()


async def act(page, rec) -> None:
    await page.wait_for_selector("#q-pills", timeout=60_000)
    await page.wait_for_selector("#log .entry", timeout=60_000)
    state = await page.evaluate("fetch('/api/state').then((r) => r.json())")
    now = datetime.fromisoformat(state["now"])
    friday = now + timedelta(days=3)
    assert f"{now:%A}" == "Tuesday", state["now"]

    rec.step(
        1,
        "Sofia keeps Margaret's care log",
        "Each note on her phone is one memory, dated when it happened",
    )
    await rec.focus(None)
    await rec.pause(2.2)
    await rec.focus("#phone", pad=8)
    await rec.pause(3.2)

    rec.step(2, "Did I take my pills this morning?", "Yes, at 8:15: today's note, not yesterday's")
    await rec.focus("#tablet", pad=8)
    answer = await ask(page, rec, "#q-pills")
    today_pills = f"#cites .cite[data-when='{now:%Y-%m-%d}T08:15']"
    if "8:15" not in answer or not await page.locator(today_pills).count():
        raise SystemExit(f"take not kept: pills -> {answer!r}")
    await rec.focus("#answer-card", pad=14)
    await rec.pause(3.0)
    rec.step(
        2, "Did I take my pills this morning?", "Sofia's phone marks the note the answer came from"
    )
    await rec.focus(None)
    await rec.pause(2.8)

    rec.step(3, "When is my next doctor visit?", "Thursday at 10:30, with Dr. Reyes")
    await rec.focus("#tablet", pad=8)
    answer = await ask(page, rec, "#q-doctor")
    if "Thursday" not in answer:
        raise SystemExit(f"take not kept: doctor -> {answer!r}")
    await rec.focus("#answer-card", pad=14)
    await rec.pause(2.8)

    rec.step(
        4,
        "The surgery moves it: Sofia edits the note",
        "Friday at 14:00. The Thursday memory is forgotten",
    )
    await rec.focus("#phone", pad=8)
    await rec.pause(0.6)
    await rec.click(".entry[data-text*='Follow-up with Dr. Reyes']")
    await page.wait_for_selector("#sheet.on #fix-text")
    await rec.pause(0.6)
    await rec.type(
        "#fix-text",
        f"Follow-up with Dr. Reyes moved to Friday {friday.day} {friday:%B} at 14:00. Anna will drive.",
        delay=16,
    )
    await rec.hover("#fix-when", pause=0.3)
    await page.fill("#fix-when", friday.replace(hour=14, minute=0).isoformat(timespec="minutes"))
    await rec.pause(0.8)
    await rec.click("#fix-save")
    await rec.wait(
        "Forgetting the old memory, writing the new one",
        page.wait_for_function(
            "() => document.querySelector('.entry.replaced') && !document.querySelector('.entry.saving, .entry.correcting') && !document.querySelector('#sheet.on')",
            timeout=120_000,
        ),
    )
    gone = await page.locator(".entry.replaced .st").inner_text()
    if "Forgotten" not in gone:
        raise SystemExit(f"the old note is not shown as forgotten: {gone!r}")
    await rec.focus("#log .p-day[data-day='Coming up']", pad=10)
    await rec.pause(3.4)

    rec.step(
        5, "Margaret asks again: Friday", "The Thursday note is forgotten, so the answer changes"
    )
    await rec.focus("#tablet", pad=8)
    answer = await ask(page, rec, "#q-doctor")
    gone_cite = page.locator("#gone-cite")
    if (
        "Friday" not in answer
        or "Thursday" in answer
        or not await gone_cite.count()
        or "forgot" not in (await gone_cite.inner_text())
    ):
        raise SystemExit(f"take not kept: doctor after the edit -> {answer!r}")
    await rec.focus("#answer-card", pad=14)
    await rec.pause(4.2)
    await rec.focus(None)
    await rec.pause(3.0)
