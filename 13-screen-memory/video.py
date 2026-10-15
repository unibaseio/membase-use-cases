"""The screen memory video, on the local engine. The page is Lookback, a screenshot library on a
desktop. After the architecture card: Jordan's six screenshots are imported and each one is read
by the vision model and remembered, dated when it was taken, while the library fills; in the
search panel, "What was my flight number?" is answered from the flight booking (S1), which opens
with SL 482 marked; "How did I fix the VPN error last time?" is answered from the VPN settings
screenshot (S3), with WireGuard marked. The questions are the page's own; a take whose answer
lacks the value, the citation or the mark is not kept.

    .venv/bin/python scripts/video/make.py 13-screen-memory
"""

META = {
    "title": "Screen memory",
    "title_html": "Ask your screenshots<br>what they showed",
    "pitch": "A vision model reads each screenshot, and memory keeps what was on it with the time it was taken. Ask later: the answer opens the screenshot, with the place marked.",
    "base": "local",
    "port": 8713,
    "banner_from_recording": True,
    "arch": {
        "kick": "How it works",
        "title": "Every screenshot becomes one dated memory",
        "nodes": [
            {
                "t": "Vision model",
                "d": "reads each screenshot: the app, the values and the text on screen",
            },
            {
                "t": "Screens memory",
                "d": "one memory per screenshot on the local engine, dated when it was taken",
                "mb": True,
            },
            {
                "t": "Recall",
                "d": "a search finds the memories that answer the question",
                "mb": True,
            },
            {
                "t": "Answer",
                "d": "a model answers from them and names the screenshot; the page shows its image",
            },
        ],
        "foot": "Each memory id the write returns is linked to its image, so a recalled memory leads back to the screenshot.",
    },
}
SEED: list[str] = []
SHOTS = "() => document.querySelectorAll('#gallery .shot[id^=shot-S]').length"


async def ask(page, rec, n: int, question: str, must: str, source: str) -> None:
    await rec.type("#q", question, delay=30)
    await rec.press("Enter")
    await rec.focus("#spot", pad=8)
    await rec.wait(
        "Recalling, then answering",
        page.wait_for_selector(f"body[data-answered='{n}']", timeout=120_000),
    )
    answer = await page.locator("#answer").inner_text()
    cited = await page.evaluate(
        "() => [...document.querySelectorAll('#list .row.cited')].map((r) => r.id)"
    )
    opened = await page.locator("#list .row.on").get_attribute("id")
    marks = await page.locator("#shotview .hl").count()
    if must.lower() not in answer.lower() or f"row-{source}" not in cited:
        raise SystemExit(f"take not kept: {question!r} -> {answer!r}, cited {cited}")
    if opened != f"row-{source}" or not marks:
        raise SystemExit(f"take not kept: opened {opened}, {marks} marks on it")
    await rec.hover("#scope", pause=0.3)  # the cursor off the answer and the screenshot


async def act(page, rec) -> None:
    await page.wait_for_selector("#add-samples:not([disabled])", timeout=60_000)
    await page.evaluate("document.fonts.ready")

    rec.step(
        1,
        "Jordan's six screenshots go in",
        "A vision model reads each one; memory keeps it, dated when it was taken",
    )
    await rec.focus(None)
    await rec.pause(2.0)
    await rec.click("#add-samples")
    await rec.focus("#content", pad=4)
    for n in range(1, 7):
        await rec.wait(
            "Reading the screenshot, writing it to memory",
            page.wait_for_function(f"() => ({SHOTS})() >= {n}", timeout=180_000),
        )
        await rec.pause(1.2 if n <= 2 else 0.4)
    await page.wait_for_selector("#busy", state="hidden", timeout=30_000)
    rec.step(1, "Jordan's six screenshots go in", "18 September to 11 October, each one remembered")
    await rec.focus(None)
    await rec.pause(2.0)

    rec.step(
        2,
        "Weeks later: what was my flight number?",
        "Memory is searched; the answer opens its screenshot",
    )
    await rec.click("#search")
    await rec.pause(0.5)
    await ask(page, rec, 1, "What was my flight number?", "SL 482", "S1")
    rec.step(
        2, "Weeks later: what was my flight number?", "SL 482, marked on the booking of 2 October"
    )
    await rec.pause(1.0)
    await rec.focus("#shotview", pad=10)
    await rec.pause(3.4)

    rec.step(
        3, "How did I fix the VPN error?", "Asked the same way, answered from another screenshot"
    )
    await ask(page, rec, 2, "How did I fix the VPN error last time?", "WireGuard", "S3")
    rec.step(
        3, "How did I fix the VPN error?", "Switched to WireGuard: the VPN settings of 18 September"
    )
    await rec.pause(1.0)
    await rec.focus("#shotview", pad=10)
    await rec.pause(3.4)
    await rec.focus(None)
    await rec.pause(2.0)
