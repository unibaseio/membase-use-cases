"""The taste journal video, on the local engine. After the explainer: Pour, Sam's tasting
journal app. Sam adds tonight's wine, an Etna Rosso he loved; it lands at the top of the journal
and as a dot on the palate map, among five months of tastings. Sam asks the sommelier for a red
for Friday dinner; memory recalls the entries the answer may use (the rest of the map and the
journal fade); the note cites them by number, and each cited entry is numbered on the map and in
the journal: tonight's Etna, the Fleurie Sam loved, and the heavy reds he rated 2 of 5.

The take stops unless the note cites tonight's wine, an older tasting Sam loved and one he
disliked.
"""

META = {
    "title": "Taste journal",
    "title_html": "A tasting journal that<br>knows your palate",
    "pitch": "Every coffee, tea and wine Sam logs is a dated memory. Ask for a red for Friday: the sommelier's note cites Sam's own entries, and they light up.",
    "base": "local",
    "port": 8709,
    "banner_from_recording": True,
    "line": "Sam logs every tasting in Pour. Ask for a red: it cites his entries.",
    "explain": {
        "title": "Every tasting is a dated memory",
        "actors": [
            {"id": "sam", "icon": "user", "label": "Sam", "kind": "user", "at": [170, 360]},
            {
                "id": "model",
                "icon": "sparkles",
                "label": "Sommelier",
                "kind": "model",
                "at": [170, 760],
                "tint": "#0f172b",
                "ink": "#fff",
            },
            {
                "id": "pour",
                "icon": "wine",
                "label": "Pour",
                "kind": "app",
                "box": [360, 205, 1470, 725],
                "tint": "#f6efe4",
                "ink": "#3b1f22",
            },
            {
                "id": "journal",
                "icon": "notebook-pen",
                "label": "Journal",
                "kind": "view",
                "at": [650, 540],
                "size": 170,
                "tint": "#7a2335",
                "ink": "#fff",
                "labelColor": "#3b1f22",
            },
            {
                "id": "mb",
                "kind": "membase",
                "base": "local",
                "tab": "Local engine, inside Pour",
                "folder": "Sam's folder",
                "box": [970, 250, 820, 640],
                "slots": [{"id": "tastings", "label": "Tastings", "icon": "wine", "facts": 3}],
            },
        ],
        "beats": [
            {
                "say": "Tonight's wine is remembered, dated tonight",
                "membase": "learn",
                "facts": ["Etna Rosso · 5 of 5 · tonight"],
                "flows": [
                    {
                        "from": "sam",
                        "to": "journal",
                        "token": {"label": "Etna Rosso", "icon": "wine"},
                    },
                    {
                        "from": "journal",
                        "to": "mb",
                        "token": {"label": "a tasting", "icon": "file-text"},
                    },
                ],
            },
            {
                "say": "A red for Friday? Memory returns his tastings",
                "membase": "recall",
                "hit": 3,
                "flows": [
                    {
                        "from": "sam",
                        "to": "journal",
                        "token": {"label": "a red, Friday?", "icon": "circle-help"},
                    },
                    {
                        "from": "journal",
                        "to": "mb",
                        "token": {"label": "the question", "icon": "search"},
                    },
                    {"from": "mb", "to": "journal", "token": "13 tastings"},
                ],
            },
            {
                "say": "The sommelier may cite only those",
                "flows": [
                    {
                        "from": "journal",
                        "to": "model",
                        "token": {"label": "13 tastings", "icon": "wine"},
                    },
                    {
                        "from": "model",
                        "to": "journal",
                        "token": "3 picks",
                        "result": "cites his entries",
                    },
                ],
            },
        ],
    },
}
SEED = ["09-taste-journal/seed.py"]
WINE = {
    "name": "Etna Rosso",
    "origin": "Mount Etna, Sicily, 2022",
    "notes": "Sour cherry, rose petals, a hint of volcanic smoke. Light and fresh with fine tannins. Lovely slightly chilled.",
}
ASK = "a red for Friday dinner"
KEPT = "() => /remembered/.test(document.querySelector('.entry.fresh .state')?.textContent || '')"


def names(rows: list[dict]) -> str:
    """'the Fleurie', 'the Fleurie and the Rioja', … as a caption says them."""
    short = [f"the {r['name'].replace('Beaujolais ', '').replace(' Sauvignon', '')}" for r in rows]
    return short[0] if len(short) == 1 else ", ".join(short[:-1]) + " and " + short[-1]


async def act(page, rec) -> None:
    await page.wait_for_function(
        "() => document.querySelectorAll('#entries .entry').length >= 20", timeout=60_000
    )
    await page.wait_for_timeout(600)

    rec.step(1, "Sam adds tonight's wine", "Etna Rosso: loved it, in his own words")
    await rec.focus(None)
    await rec.pause(1.6)
    await rec.focus("#card", pad=8)
    await rec.click("#kinds button[data-kind='wine']")
    await rec.type("#name", WINE["name"], delay=45)
    await rec.type("#origin", WINE["origin"], delay=22)
    await rec.type("#notes", WINE["notes"], delay=11)
    await rec.click("#stars button[data-n='5']", pause=0.8)
    await rec.click("#save")
    await rec.wait("Placing it on the map", page.wait_for_selector(".entry.fresh", timeout=120_000))

    n = await page.locator("#entries .entry").count()
    rec.step(
        2,
        "It joins five months of tastings",
        f"{n} since May: a Fleurie he loved, a Barossa Shiraz he rated 2 of 5",
    )
    await rec.focus(None)
    await rec.pause(1.4)
    await rec.hover("#map .dot[data-name='Beaujolais Fleurie']", pause=2.4)
    await rec.hover("#map .dot[data-name='Barossa Shiraz']", pause=2.4)
    await rec.hover(".entry.fresh .n", pause=0.3)
    await rec.wait("Writing it to memory", page.wait_for_function(KEPT, timeout=120_000))
    rec.step(2, "It joins five months of tastings", "Remembered in seconds, dated tonight")
    await rec.focus(".entry.fresh", pad=8)
    await rec.pause(2.0)

    rec.step(3, "Sam asks: a red for Friday dinner?", "The sommelier answers from his journal")
    await rec.focus("#card", pad=8)
    await rec.type("#hint", ASK, delay=40)
    await rec.click("#ask")
    await rec.wait("Recalling tastings", page.wait_for_selector("#map.asking", timeout=120_000))
    turned = await page.evaluate("() => document.querySelectorAll('#map .dot.recalled').length")
    rec.step(
        3,
        "Sam asks: a red for Friday dinner?",
        f"Memory returns {turned} tastings that bear on it; the rest fade",
    )
    await rec.focus(None)
    await rec.pause(2.6)

    await rec.wait(
        "Writing the note", page.wait_for_function("() => window.__answer", timeout=180_000)
    )
    cited = (await page.evaluate("() => window.__answer"))["cited"]
    tonight = [c for c in cited if c["today"]]
    loved = [c for c in cited if c["rating"] >= 4 and not c["today"]]
    disliked = [c for c in cited if c["rating"] <= 2]
    if not tonight:
        raise SystemExit(f"the note does not cite tonight's wine: {cited}")
    if not loved:
        raise SystemExit(f"the note cites no older tasting Sam loved: {cited}")
    if not disliked:
        raise SystemExit(f"the note cites no tasting Sam disliked: {cited}")

    rec.step(
        4,
        "The note cites his own entries",
        f"Tonight's Etna and {names(loved[:2])}, which he loved; {names(disliked[:2])}, which he didn't",
    )
    await rec.focus("#card", pad=6)
    await rec.pause(3.4)
    await rec.focus(None)
    await rec.pause(1.2)
    # each number lights its entry on the map and in the journal
    await rec.hover(f"#picks sup.c[data-cite='{tonight[0]['id']}']", pause=2.4)
    await rec.hover(f"#picks sup.c[data-cite='{disliked[0]['id']}']", pause=2.6)
    await rec.hover("#by", pause=0.6)
    await rec.pause(2.2)
