"""The companion video, on the local engine. After the explainer: Night Line, the
listener line of a late-night radio show. Maya calls in and tells Wren about Thursday's
interview at Brightwater Studio; Wren signs off and jots it in her notebook (Maya's memory
directory); on the next call Wren speaks first and asks about the interview, from the note she
recalled; Theo, on his own line with an empty notebook, is a stranger to Wren.

The callers' lines are fixed. The take is kept only if the follow-up for the interview is
written, Maya's next call opens on the interview, and Theo's Wren knows nothing of it.
Record with .venv/bin/python scripts/video/make.py 08-companion
"""

import re
from pathlib import Path

# Wren's portrait, as the page draws it, for the explainer
WREN = re.search(
    r"const WREN = `(<svg.*?</svg>)`",
    (Path(__file__).parent / "static/index.html").read_text(),
    re.S,
)[1]

META = {
    "title": "Companion",
    "title_html": "A companion<br>that follows up",
    "pitch": "Tell Wren about Thursday's interview. On the next call, Wren asks about it first. Each caller's memory is a directory of its own.",
    "base": "local",
    "port": 8708,
    "banner_from_recording": True,
    "line": "Night Line's host follows up on your call. Each caller has their own memory.",
    "intro_at": ["Next call: Wren asks first", 6.0],
    "explain": {
        "title": "One memory per caller",
        "actors": [
            {"id": "maya", "icon": "user", "label": "Maya", "kind": "user", "at": [170, "mb.maya"]},
            {"id": "theo", "icon": "user", "label": "Theo", "kind": "user", "at": [170, "mb.theo"]},
            {
                "id": "show",
                "icon": "radio",
                "label": "Night Line",
                "kind": "app",
                "box": [360, 205, 1470, 725],
                "tint": "#1c2840",
                "ink": "#f3e8cf",
            },
            {
                "id": "wren",
                "icon": WREN,
                "fill": True,
                "label": "Wren",
                "labelAt": "plate",
                "kind": "character",
                "at": [600, 620],
                "size": 190,
                "ring": "#c9563c",
            },
            {
                "id": "mb",
                "kind": "membase",
                "base": "local",
                "tab": "Local engine, inside Night Line",
                "stack": True,
                "box": [900, 250, 880, 650],
                "slots": [
                    {"id": "maya", "label": "Maya's memory", "icon": "folder"},
                    {"id": "theo", "label": "Theo's memory", "icon": "folder"},
                ],
            },
        ],
        "beats": [
            {
                "say": "Maya tells Wren about Thursday's interview",
                "membase": "learn",
                "facts": ["Ask: the interview"],
                "flows": [
                    {
                        "from": "maya",
                        "to": "wren",
                        "token": {"label": "the interview", "icon": "message-circle"},
                    },
                    {"from": "wren", "to": "mb.maya", "token": "a follow-up"},
                ],
            },
            {
                "say": "Next call, Wren asks about it first",
                "membase": "recall",
                "flows": [
                    {
                        "from": "maya",
                        "to": "wren",
                        "token": {"label": "a new call", "icon": "phone"},
                    },
                    {"from": "mb.maya", "to": "wren", "token": "the interview"},
                ],
            },
            {
                "say": "Theo's memory is his own: it's empty",
                "membase": "recall",
                "flows": [
                    {
                        "from": "theo",
                        "to": "wren",
                        "token": {"label": "my interview?", "icon": "circle-help"},
                    },
                    {"from": "mb.theo", "to": "wren", "token": "nothing"},
                ],
            },
        ],
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
