"""The browser memory video, on hosted Membase. After the architecture card: in Chromium with
the real extension loaded, two pages read on one day are remembered from the side panel and
learned; later, on a third page, a question is answered from that page and the two remembered
ones, each citation pointing back to the page it came from.

Recorded in the extension's demo window (extension/demo.html): the real page on the left, the
real side panel on the right, the panel reading the page from a real tab with the same URL.

    scripts/video/record_hosted.sh 06-browser-memory --containers Browsing
"""

import functools
import http.server
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXT_ID = "lhojclgfedbhfpkjklfgjgnikckelabe"
PAGES = "http://127.0.0.1:18706"
P = "#panel >> internal:control=enter-frame >> "  # inside the side panel
QUESTION = (
    "I want to hike the loop I saved this weekend, carrying the pack I read about. "
    "Which day should I go, and what do I need to plan for water and gear?"
)

META = {
    "title": "Browser memory",
    "title_html": "Ask your memory about<br>the page you are on",
    "pitch": "Remember pages from a side panel. Later, on any page, the answer draws on them and says which page each fact came from.",
    "base": "hosted",
    "port": 8706,
    "extension": "06-browser-memory/extension",
    "start_url": f"chrome-extension://{EXT_ID}/demo.html?pages={PAGES}",
    "url_label": "Chrome · Browser Memory extension",
    "banner_from_recording": True,
    "arch": {
        "kick": "How it works",
        "title": "The extension holds no key; your memory stays in Membase",
        "nodes": [
            {
                "t": "Side panel",
                "d": "reads the page in the tab you are on; stores nothing, holds no key",
            },
            {
                "t": "Companion on 127.0.0.1",
                "d": "holds the Membase key; answers only the extension, only on loopback",
            },
            {
                "t": "Membase · Browsing memory",
                "d": "every page you remembered, learned into facts that cite the page",
                "mb": True,
            },
            {"t": "Model", "d": "answers from the page and the recalled memories, citing each one"},
        ],
        "foot": "A bearer token never sits in browser storage: revoke the companion's key and the panel stops at once.",
    },
}
SEED: list[str] = []


def setup() -> None:
    """Serve the three fictional pages on a fixed port: a page's URL is its identity in memory."""
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(HERE / "pages"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 18706), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


def panel(page):
    return next(f for f in page.frames if "panel.html" in f.url)


async def strays(page) -> None:
    """The recorder draws its cursor in every document, so each iframe (the page, the panel)
    gets a second one parked mid-frame. The real cursor is the window's own: hide the others."""
    for f in page.frames:
        if f is not page.main_frame:
            try:
                await f.evaluate("() => document.getElementById('__mbcursor')?.remove()")
            except Exception:  # noqa: BLE001 - a frame mid-navigation; the next call gets it
                pass


async def remember(page, rec, tab: str, title_part: str) -> None:
    await rec.click(f"#tab-{tab}")
    await page.wait_for_timeout(600)
    await strays(page)
    await panel(page).wait_for_function(
        f"() => document.querySelector('#page-title').textContent.includes({title_part!r})",
        timeout=60_000,
    )
    await strays(page)
    await rec.focus("#page", pad=0)
    await rec.pause(2.5)
    await rec.click(P + "#remember")
    await rec.wait(
        "Saving the page to memory",
        panel(page).wait_for_selector("#remember-out .ok, #remember-out.bad", timeout=120_000),
    )
    if await panel(page).locator("#remember-out.bad").count():
        raise SystemExit(
            f"remembering failed: {await panel(page).locator('#remember-out').inner_text()}"
        )
    await rec.focus(P + "#page", pad=14)
    await rec.pause(2.2)


async def answered(frame) -> None:
    """The take shows what the captions say: the day from the page, the water stop from the
    trail notes, the rain cover from the review, and cited memories from both saved pages."""
    answer = (await frame.locator("#answer").inner_text()).lower()
    for want, why in (("sunday", "the forecast"), ("tamsin", "the trail notes")):
        if want not in answer:
            raise SystemExit(f"the answer does not use {why}: {answer!r}")
    if "rain cover" not in answer and "corvid" not in answer:
        raise SystemExit(f"the answer does not use the pack review: {answer!r}")
    sources = set(await frame.locator(".mem.used .from a").all_inner_texts())
    if not any("Larchmere Ridge" in s for s in sources) or not any("Corvid" in s for s in sources):
        raise SystemExit(f"the cited memories do not come from both saved pages: {sources}")


async def act(page, rec) -> None:
    await page.wait_for_function(
        "() => [...document.querySelectorAll('iframe')].length === 2", timeout=60_000
    )
    await page.wait_for_timeout(1500)
    await strays(page)
    await panel(page).wait_for_function(
        "() => /hosted|local/.test(document.querySelector('#badge').textContent)", timeout=60_000
    )

    rec.step(
        1,
        "Remember pages you read",
        "A trail guide and a pack review: one click each in the side panel",
    )
    await remember(page, rec, "larchmere-ridge-loop", "Larchmere")
    await remember(page, rec, "corvid-38-review", "Corvid")

    rec.step(2, "Membase learns them", "A saved page can be recalled once it shows Learned")
    await rec.focus(P + "#pages", pad=30)
    await rec.wait(
        "Membase learns both pages",
        panel(page).wait_for_function(
            "() => document.querySelectorAll('#pages .state[data-state=learned]').length >= 2",
            timeout=900_000,
        ),
    )
    await rec.pause(2.0)

    rec.step(
        3,
        "Days later, on the forecast: ask",
        "Which day to go, and what to plan for water and gear",
    )
    await rec.click("#tab-larchmere-forecast")
    await page.wait_for_timeout(600)
    await strays(page)
    await panel(page).wait_for_function(
        "() => document.querySelector('#page-title').textContent.includes('forecast')",
        timeout=60_000,
    )
    await strays(page)
    await rec.focus("#page", pad=0)
    await rec.pause(2.5)
    await rec.type(P + "#question", QUESTION, delay=14)
    await rec.click(P + "#ask")
    await rec.hide_cursor()  # nothing more is clicked
    await strays(page)
    await rec.wait(
        "Searching your memory, answering",
        panel(page).wait_for_function(
            "() => !document.querySelector('#ask').disabled && document.querySelector('#answer').textContent.length > 40",
            timeout=300_000,
        ),
    )
    await answered(panel(page))
    await rec.focus(P + "#answer-card", pad=14)
    await rec.pause(5.0)

    rec.step(
        4,
        "Every fact says where it came from",
        "Recalled memories, each linked to the page you saved",
    )
    await rec.focus(P + "#mems-card", pad=16)
    await rec.pause(4.5)
    await rec.focus(None)
    await rec.pause(1.0)
