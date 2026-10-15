"""The wearable diary video, on the local engine. After the architecture card: Earshot, the
companion app of a clip-on recording pendant, with nothing from today yet. Syncing brings in
Alex's Wednesday (four synthetic-speech clips): each is transcribed with its timings, the model
says who spoke each line, and the conversation is remembered at the time it was recorded; the
day gets its diary. "What did I promise Sam?" is answered from the 17:15 call, and the clip
plays from the line where Alex promised. "What time is the design review?" comes out as 3:30:
the 15:10 clip changed it from 3:00, and both clips are shown.

A take is kept only if the answers say so, the Sam clip plays from the promise, and the 15:10
clip is the one marked as having changed it."""

import re

META = {
    "title": "Wearable diary",
    "title_html": "A day of audio,<br>remembered",
    "pitch": "Clips from a recording pendant become dated conversation memory. Ask what you promised, and the answer plays the moment you said it.",
    "base": "local",
    "port": 8716,
    "banner_from_recording": True,
    "arch": {
        "kick": "How it works",
        "title": "Audio in, dated conversation memory out",
        "nodes": [
            {
                "t": "Pendant clip",
                "d": "a recording with the time it was made: 09:30, 12:40, 15:10, 17:15",
            },
            {
                "t": "Transcribe",
                "d": "speech to text with timings; the model says who spoke each line",
            },
            {
                "t": "Conversation memory",
                "d": "one conversation per clip, remembered at the time it was recorded",
                "mb": True,
            },
            {
                "t": "Recall",
                "d": "a question finds the conversations; the answer plays the clip, and the later one wins",
                "mb": True,
            },
        ],
        "foot": "Each memory keeps when it was said, so a later conversation can overrule an earlier one.",
    },
}
SEED = ["16-wearable-diary/seed.py --audio-only --reuse data/16-wearable-diary/seed-audio"]
ALL_SAVED = "() => document.querySelectorAll('.conv.saved').length === 4"


async def ask(page, rec, question: str) -> None:
    await rec.type("#q", question, delay=45)
    await rec.click("#go")
    await rec.wait(
        "Recalling conversations, answering", page.wait_for_selector("#answer", timeout=120_000)
    )


async def shown(page) -> dict:
    """What the page shows: the answer, the change line, each cited clip and its line."""
    return await page.evaluate(
        """() => ({
          answer: document.querySelector('#answer-text').firstChild.textContent,
          change: document.querySelector('#answer-text .chg')?.textContent || '',
          cites: [...document.querySelectorAll('.cite')].map((c) => ({
            time: c.dataset.time,
            tag: c.querySelector('.tag')?.textContent || '',
            quote: c.querySelector('.quote')?.textContent || '',
          })),
        })"""
    )


async def act(page, rec) -> None:
    await page.wait_for_selector("#sample", timeout=60_000)

    rec.step(1, "A day on the pendant", "Alex's Wednesday: four conversations, not synced yet")
    await rec.focus(None)
    await rec.pause(2.2)
    await rec.click("#sample")
    rec.step(
        1,
        "Synced and remembered",
        "Each clip is transcribed, split by speaker and remembered at the time it was recorded",
    )
    await rec.focus("#day", pad=8)
    await rec.wait(
        "Transcribing, splitting and remembering 4 clips",
        page.wait_for_function(ALL_SAVED, timeout=300_000),
    )
    await rec.wait("Writing the diary", page.wait_for_selector("#diary.fresh", timeout=120_000))
    await rec.pause(2.0)
    rec.step(1, "The day, written up", "A diary for Wednesday, and what you said you would do")
    await rec.focus("#diary", pad=12)
    await rec.pause(3.4)

    rec.step(2, "What did I promise Sam?", "Memory finds the 17:15 call")
    await rec.focus("#askpane", pad=0)
    await ask(page, rec, "What did I promise Sam?")
    s = await shown(page)
    sam = next((c for c in s["cites"] if c["time"] == "17:15"), None)
    if (
        not sam
        or "Saturday" not in s["answer"]
        or not re.search(r"\b(9|nine)\b", s["answer"], re.I)
        or "promise" not in sam["quote"].lower()
    ):
        raise SystemExit(f"the Sam answer is not the payoff: {s}")
    rec.step(
        2, "What did I promise Sam?", "Saturday at 9, with the car. The 17:15 call is the source"
    )
    await rec.focus("#answer", pad=10)
    await rec.pause(3.2)
    rec.step(2, "Play the moment", "The clip starts at the line where you promised")
    play = '.cite[data-time="17:15"] .play'
    await rec.click(play)
    await rec.focus('.cite[data-time="17:15"]', pad=12)
    await rec.pause(4.2)
    played = await page.evaluate("() => document.querySelector('#player').currentTime")
    if played < 11:
        raise SystemExit(f"the Sam clip did not play from the promise: {played}")
    await rec.click(play)  # pause it again

    rec.step(3, "What time is the design review?", "Two conversations mention it")
    await rec.focus("#askpane", pad=0)
    await ask(page, rec, "What time is the design review?")
    s = await shown(page)
    tags = {c["time"]: c for c in s["cites"]}
    if (
        not re.search(r"3[:.]30|three[- ]thirty|half past three", s["answer"], re.I)
        or not s["change"].startswith("Priya changed it at 15:10")
        or not re.search(r"\b3\b|three", s["change"], re.I)
        or tags.get("15:10", {}).get("tag") != "Changed it"
        or "09:30" not in tags
    ):
        raise SystemExit(f"the design review answer is not the payoff: {s}")
    rec.step(3, "A later clip changed it", "3:30, not 3:00: Priya moved it at 15:10")
    await rec.focus("#answer-text", pad=12)
    await rec.pause(3.4)
    rec.step(3, "A later clip changed it", "The 09:30 stand-up said 3; the 15:10 chat moved it")
    await rec.focus("#cites", pad=10)
    await rec.pause(4.0)
    await rec.focus("#timeline", pad=10)
    await rec.pause(2.4)
    await rec.focus(None)
    await rec.pause(1.6)
