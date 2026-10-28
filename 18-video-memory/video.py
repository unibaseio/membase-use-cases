"""The video memory video. After the explainer: two films are in memory,
each drawn as its shots and its lines; the Sintel trailer is added, and the Watch and Listen
steps work on it until its card appears. "a little dragon flying toward a hand" finds the
trailer's shot at 0:33: it plays from there, and the trailer's shot track lights the shot up.
"the old man says it's not safe here" finds the line at 0:57 of Elephants Dream, said by the old
man on screen: it plays, and the line lights up on the line track.

A take is kept only if each search finds the right video, moment and speaker.

    .venv/bin/python scripts/video/make.py 18-video-memory
"""

import re

META = {
    "title": "Video memory",
    "title_html": "Video memory",
    "pitch": "Ask for a scene or a line. It plays from that second.",
    "base": "local",
    "base_label": "",
    "port": 8718,
    "banner_from_recording": True,
    "line": "Remembers every scene and every line.",
    "explain": {
        "title": "How a video is remembered",
        "actors": [
            {"id": "you", "icon": "user", "label": "You", "kind": "user", "at": [170, 380]},
            {
                "id": "vision",
                "icon": "scan-eye",
                "label": "Watch + listen",
                "kind": "model",
                "at": [170, 740],
                "tint": "#0f172b",
                "ink": "#fff",
            },
            {
                "id": "app",
                "icon": "layers",
                "label": "Video memory",
                "kind": "app",
                "box": [360, 205, 1470, 725],
                "tint": "#f6f6f3",
                "ink": "#1c1c1a",
            },
            {
                "id": "lib",
                "icon": "layers",
                "label": "Videos",
                "kind": "view",
                "at": [650, 540],
                "size": 170,
                "tint": "#5b5bd6",
                "ink": "#fff",
            },
            {
                "id": "mb",
                "kind": "membase",
                "base": "local",
                "tab": "Media memory",
                "folder": "Your videos",
                "box": [970, 250, 820, 640],
                "slots": [{"id": "media", "label": "Videos", "icon": "image"}],
            },
        ],
        "beats": [
            {
                "say": "Each scene and each line goes into memory",
                "membase": "learn",
                "facts": [
                    "0:33 · a dragon flies to a hand",
                    '0:57 · "It\'s not safe here"',
                    "3:42 · a robot on a bridge",
                ],
                "flows": [
                    {
                        "from": "lib",
                        "to": "vision",
                        "token": {"label": "a video", "icon": "layers"},
                    },
                    {"from": "vision", "to": "lib", "token": "scenes, lines, speakers"},
                    {
                        "from": "lib",
                        "to": "mb",
                        "token": {"label": "every moment", "icon": "captions"},
                    },
                ],
            },
            {
                "say": "Recall a scene",
                "membase": "recall",
                "hit": 0,
                "flows": [
                    {
                        "from": "you",
                        "to": "lib",
                        "token": {"label": "a dragon, a hand", "icon": "search"},
                    },
                    {"from": "lib", "to": "mb", "token": {"label": "the words", "icon": "search"}},
                    {"from": "mb", "to": "lib", "token": "Sintel", "result": "0:33"},
                ],
            },
            {
                "say": "Recall a line",
                "membase": "recall",
                "hit": 1,
                "flows": [
                    {
                        "from": "you",
                        "to": "lib",
                        "token": {"label": '"not safe here"', "icon": "search"},
                    },
                    {"from": "lib", "to": "mb", "token": {"label": "the words", "icon": "search"}},
                    {"from": "mb", "to": "lib", "token": "the old man", "result": "0:57"},
                ],
            },
        ],
    },
}
SEED = ["18-video-memory/seed.py"]


async def find(page, rec, n: int, q: str) -> dict:
    await rec.focus(".bar", pad=60)
    await rec.type("#q", q, delay=45)
    await rec.click("#go")
    await rec.focus("#findpane", pad=0)
    await rec.wait(
        "Searching every shot and line",
        page.wait_for_selector(f"body[data-found='{n}']", timeout=120_000),
    )
    return await page.evaluate(
        """() => ({
          where: document.querySelector('#moment .where')?.textContent || '',
          kind: document.querySelector('#moment .tag')?.textContent || '',
          text: document.querySelector('#moment .text')?.textContent || '',
          who: document.querySelector('#moment .who')?.textContent || '',
          hit: !!document.querySelector('#tracks .seg.hit'),
        })"""
    )


async def act(page, rec) -> None:
    await page.wait_for_selector(".vid", timeout=60_000)

    rec.step(1, "2 films in memory")
    await rec.focus(None)
    await rec.pause(1.6)
    await rec.focus("#memory", pad=0)
    await rec.pause(2.4)
    rec.step(1, "Add a video")
    await rec.click('.add[data-key="sintel-trailer"]')
    await rec.focus("#steps", pad=6)
    await rec.pause(1.2)
    rec.step(1, "Remembering")
    await rec.wait(
        "Remembering the trailer",
        page.wait_for_selector('.vid[data-key="sintel-trailer"]', timeout=300_000),
    )
    counts = await page.locator('.vid[data-key="sintel-trailer"] .m').inner_text()
    shots, lines = re.findall(r"\d+", counts)[:2]
    rec.step(1, "Remembered", f"{shots} scenes · {lines} lines")
    await rec.focus('.vid[data-key="sintel-trailer"]', pad=14)
    await rec.pause(2.6)

    rec.step(2, "Recall a scene")
    s = await find(page, rec, 1, "a little dragon flying toward a hand")
    if (
        "Sintel" not in s["where"]
        or s["kind"] != "seen"
        or not re.search(r"dragon", s["text"], re.I)
        or not s["hit"]
    ):
        raise SystemExit(f"the dragon search is not the payoff: {s}")
    rec.step(2, "Recall a scene", "Sintel · 0:33")
    await rec.focus(".hero", pad=10)
    await page.wait_for_selector("body[data-played='1']", timeout=30_000)
    await rec.pause(0.8)
    rec.step(2, "Found at 0:33")
    await rec.focus("#tracks", pad=10)
    await rec.pause(3.0)

    rec.step(3, "Recall a line")
    s = await find(page, rec, 2, "the old man says it's not safe here")
    if (
        "Elephants Dream" not in s["where"]
        or s["kind"] != "said"
        or "not safe" not in s["text"].lower()
        or not re.search(r"\b(old|older|elderly|bald)\b", s["who"])
    ):
        raise SystemExit(f"the line search is not the payoff: {s}")
    rec.step(3, "Recall a line", "Elephants Dream · 0:57")
    await rec.focus(".hero", pad=10)
    await page.wait_for_selector("body[data-played='2']", timeout=30_000)
    await rec.pause(1.0)
    rec.step(3, "Found at 0:57")
    await rec.focus("#tracks", pad=10)
    await rec.pause(3.2)
    await rec.focus(None)
    await rec.pause(1.8)
