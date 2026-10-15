"""The companion video, on the local engine. After the architecture card: Night Line, the
listener line of a late-night radio show. Maya calls in and tells Wren about Thursday's
interview at Brightwater Studio; Wren signs off and jots it in her notebook (Maya's memory
directory); on the next call Wren speaks first and asks about the interview, from the note she
recalled; Theo, on his own line with an empty notebook, is a stranger to Wren.

The callers' lines are fixed. The take is kept only if the follow-up for the interview is
written, Maya's next call opens on the interview, and Theo's Wren knows nothing of it.
Record with .venv/bin/python scripts/video/make.py 08-companion
"""

import re

META = {
    "title": "Companion",
    "title_html": "A companion<br>that follows up",
    "pitch": "Tell Wren about Thursday's interview. On the next call, Wren asks about it first. Each caller's memory is a directory of its own.",
    "base": "local",
    "port": 8708,
    "banner_from_recording": True,
    "arch": {
        "kick": "How it works",
        "title": "One memory directory per caller, on the local engine",
        "nodes": [
            {
                "t": "Night Line app",
                "d": "Wren's persona; recall before every reply, a write when she signs off",
            },
            {
                "t": "Membase local engine",
                "d": "membase-core in the app's process: search, add, profile. A write is searchable in seconds",
                "mb": True,
            },
            {
                "t": "Maya's directory",
                "d": "data/08-companion/maya/: the call as episodes, follow-ups, profile facts",
                "mb": True,
            },
            {
                "t": "Theo's directory",
                "d": "data/08-companion/theo/: a separate store. Nothing of Maya's is in it",
                "mb": True,
            },
        ],
        "foot": "Wren's notebook is the caller's memory: one directory, one memory, per person.",
    },
}
SEED: list[str] = []

READY = "() => !document.querySelector('#send').disabled"
MAYA = (
    "Hi Wren, I'm Maya. Long day: I have a job interview at Brightwater Studio on Thursday "
    "and I'm nervous about the portfolio review. Miso, my cat, kept me company while I prepped."
)
THEO = "Hi, I'm Theo. Do you remember my job interview?"


async def ready(page) -> None:
    await page.wait_for_timeout(400)
    await page.wait_for_function(READY, timeout=180_000)


async def act(page, rec) -> None:
    await page.wait_for_function(READY, timeout=180_000)

    rec.step(1, "Maya calls in", "She tells Wren about Thursday's interview at Brightwater Studio")
    await rec.focus(None)
    await rec.pause(1.6)
    await rec.focus("#stage", pad=10)
    await rec.type("#msg", MAYA, delay=16)
    await rec.click("#send")
    await rec.wait("Wren searches Maya's memory and replies", ready(page))
    await rec.focus(".msg.assistant >> nth=-1", pad=18)
    await rec.pause(2.8)

    rec.step(2, "Wren signs off", "She jots down what to ask next time, in Maya's memory")
    await rec.focus("#stage", pad=10)
    await rec.click("#end")
    await rec.wait(
        "Picking out what to follow up",
        page.wait_for_selector("#ended:not([hidden])", timeout=180_000),
    )
    await rec.focus("#rail", pad=10)
    await rec.wait(
        "Writing to Maya's directory", page.wait_for_selector("#written", timeout=180_000)
    )
    if not await page.locator(".write.loop", has_text=re.compile("Brightwater", re.I)).count():
        raise SystemExit("no follow-up for the interview was written: record again")
    await rec.pause(3.2)

    rec.step(3, "Next call: Wren asks first", "From the note she recalled: the interview")
    await rec.click("#again")
    await rec.focus("#stage", pad=10)
    await rec.wait("Wren searches her notebook", ready(page))
    opener = await page.locator(".msg.assistant >> nth=0").inner_text()
    if not re.search(r"interview|Brightwater", opener, re.I):
        raise SystemExit(f"the opener missed the interview: {opener!r}")
    if not await page.locator("#opener-from").count():
        raise SystemExit("the opener recalled no follow-up")
    await rec.pause(1.0)
    await rec.focus("#opener", pad=14)
    await rec.pause(4.2)

    rec.step(
        4, "Theo's line: his own notebook", "His memory is a directory of its own, still empty"
    )
    await rec.focus(None)
    await rec.click(".person[data-user=theo]")
    await rec.wait("Wren picks up Theo's line", ready(page))
    await rec.pause(1.6)
    await rec.focus("#stage", pad=10)
    await rec.type("#msg", THEO, delay=22)
    await rec.click("#send")
    await rec.wait("Wren searches Theo's memory and replies", ready(page))
    reply = await page.locator(".msg.assistant >> nth=-1").inner_text()
    if re.search(r"Brightwater|Miso|Maya", reply, re.I):
        raise SystemExit(f"Theo's Wren knows Maya's memory: {reply!r}")
    if await page.locator("#page .write").count():
        raise SystemExit("Theo's notebook has entries")
    rec.step(4, "Theo's line: his own notebook", "Wren has no memory of his interview, or of Maya")
    await rec.hover("#colophon", pause=0.1)
    await rec.focus(".msg.assistant >> nth=-1", pad=18)
    await rec.pause(3.0)
    await rec.focus(None)
    await rec.pause(2.2)
