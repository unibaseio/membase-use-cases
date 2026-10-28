"""The photo memory video. After the explainer: two albums are in memory;
the Kyoto album is added, and the Look step describes each photo as it lands, one sentence each.
"rows of orange gates" finds Fushimi Inari, just added. "something sweet we ate" finds the
pastries and the birthday cake, and nothing else: by meaning, not by words.

A take is kept only if each search finds the right photos.

    .venv/bin/python scripts/video/make.py 19-photo-memory
"""

META = {
    "title": "Photo memory",
    "title_html": "Photo memory",
    "pitch": "Describe a photo. It comes back.",
    "base": "local",
    "base_label": "",
    "port": 8719,
    "banner_from_recording": True,
    "line": "Remembers what is in every photo.",
    "explain": {
        "title": "How a photo is remembered",
        "actors": [
            {"id": "you", "icon": "user", "label": "You", "kind": "user", "at": [170, 380]},
            {
                "id": "vision",
                "icon": "scan-eye",
                "label": "Look",
                "kind": "model",
                "at": [170, 740],
                "tint": "#0f172b",
                "ink": "#fff",
            },
            {
                "id": "app",
                "icon": "layers",
                "label": "Photo memory",
                "kind": "app",
                "box": [360, 205, 1470, 725],
                "tint": "#f6f6f3",
                "ink": "#1c1c1a",
            },
            {
                "id": "lib",
                "icon": "image",
                "label": "Photos",
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
                "folder": "Your photos",
                "box": [970, 250, 820, 640],
                "slots": [{"id": "media", "label": "Photos", "icon": "image"}],
            },
        ],
        "beats": [
            {
                "say": "What is in each photo goes into memory",
                "membase": "learn",
                "facts": [
                    "orange torii gates on a forest path",
                    "a custard tart held in a hand",
                    "a birthday cake with lit candles",
                ],
                "flows": [
                    {"from": "lib", "to": "vision", "token": {"label": "a photo", "icon": "image"}},
                    {"from": "vision", "to": "lib", "token": "one sentence"},
                    {"from": "lib", "to": "mb", "token": {"label": "every photo", "icon": "image"}},
                ],
            },
            {
                "say": "Recall a photo",
                "membase": "recall",
                "hit": 0,
                "flows": [
                    {
                        "from": "you",
                        "to": "lib",
                        "token": {"label": "orange gates", "icon": "search"},
                    },
                    {"from": "lib", "to": "mb", "token": {"label": "the words", "icon": "search"}},
                    {"from": "mb", "to": "lib", "token": "Fushimi Inari", "result": "1 photo"},
                ],
            },
            {
                "say": "Vague works too",
                "membase": "recall",
                "hit": 1,
                "flows": [
                    {
                        "from": "you",
                        "to": "lib",
                        "token": {"label": "something sweet", "icon": "search"},
                    },
                    {"from": "lib", "to": "mb", "token": {"label": "the words", "icon": "search"}},
                    {"from": "mb", "to": "lib", "token": "tart, cake", "result": "2 photos"},
                ],
            },
        ],
    },
}
SEED = ["19-photo-memory/seed.py"]


async def find(page, rec, n: int, q: str) -> list[str]:
    await rec.focus(".bar", pad=60)
    await rec.type("#q", q, delay=45)
    await rec.click("#go")
    await rec.focus("#findpane", pad=0)
    await rec.wait(
        "Searching every photo",
        page.wait_for_selector(f"body[data-found='{n}']", timeout=120_000),
    )
    return await page.evaluate(
        """() => [...document.querySelectorAll('#library .tile.hit')]
          .sort((a, b) => +a.querySelector('.rank').textContent - +b.querySelector('.rank').textContent)
          .map((t) => t.dataset.key)"""
    )


async def act(page, rec) -> None:
    await page.wait_for_selector(".tile", timeout=60_000)

    n = await page.locator("#library .tile").count()
    rec.step(1, f"{n} photos in memory")
    await rec.focus(None)
    await rec.pause(1.6)
    await rec.focus("#side", pad=0)
    await rec.pause(2.0)
    rec.step(1, "Add an album", "Kyoto")
    await rec.click('.add[data-album="kyoto"]')
    await rec.focus("#steps", pad=6)
    await rec.pause(1.0)
    rec.step(1, "Remembering")
    await rec.focus("#library", pad=10)
    await rec.wait(
        "Remembering four photos",
        page.wait_for_function(
            "!document.querySelector('.album[data-album=kyoto] .slot')", timeout=180_000
        ),
    )
    n = await page.locator("#library .tile").count()
    rec.step(1, "Remembered", f"{n} photos")
    await rec.focus("#side", pad=0)
    await rec.pause(2.6)

    rec.step(2, "Recall a photo")
    keys = await find(page, rec, 1, "rows of orange gates")
    if keys[:1] != ["kyoto-gates"]:
        raise SystemExit(f"the gates search is not the payoff: {keys}")
    rec.step(2, "Recall a photo", "Found: Fushimi Inari")
    await rec.focus("#side", pad=0)
    await rec.pause(2.4)
    await rec.focus("#library", pad=10)
    await rec.pause(1.6)

    rec.step(3, "Vague works too")
    keys = await find(page, rec, 2, "something sweet we ate")
    if set(keys) != {"lisbon-pastries", "home-cake"}:
        raise SystemExit(f"the sweet search is not the payoff: {keys}")
    rec.step(3, "Vague works too", "Found: a tart, a cake")
    await rec.focus("#library", pad=10)
    await rec.pause(2.4)
    await rec.focus("#side", pad=0)
    await rec.pause(2.2)
    await rec.focus(None)
    await rec.pause(1.8)
