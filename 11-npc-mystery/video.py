"""The NPC mystery video, on the local engine. After the explainer: the investigator
tells Mara about a green glass button; the evening passes and Mara tells her niece Elsie at the
inn, which is one write into Elsie's memory; Elsie, asked at the ferry landing, recalls it and
says Mara told her; Tobias, asked the same at the lighthouse, recalls nothing; then Tobias is
accused.

The player's lines are fixed, and gossip goes to the teller's confidant (Mara tells Elsie), so
the route is the story's, not the model's. The take checks the payoff on the page and stops if
the gossip lost the button, Elsie does not credit Mara, or Tobias knows: record it again.
"""

ART = "11-npc-mystery/static/art.js"  # the game's own portraits, drawn into the explainer

META = {
    "title": "NPC mystery",
    "title_html": "Characters who remember<br>what you told them",
    "pitch": "Tell Mara a clue. That evening she tells Elsie, who says who told her. Tobias heard nothing.",
    "base": "local",
    "port": 8711,
    "banner_from_recording": True,
    "line": "A harbour mystery game. Each character keeps a memory of their own.",
    "intro_at": ["Ask Elsie at the landing", 14.0],  # Elsie has just recalled Mara's gossip
    "explain": {
        "title": "One memory per character",
        "actors": [
            {"id": "you", "icon": "user", "label": "You", "kind": "user", "at": [170, "mb.elsie"]},
            {
                "id": "game",
                "icon": "gamepad-2",
                "label": "The game",
                "kind": "app",
                "box": [360, 205, 1470, 725],
                "tint": "#1d1813",
                "ink": "#f3e8cf",
            },
            *(
                {
                    "id": who,
                    "art": [ART, "portrait", who, {"face": True}],
                    "label": who.title(),
                    "labelAt": "plate",
                    "kind": "character",
                    "at": [610, f"mb.{who}"],
                    "size": 120,
                    "ring": ring,
                }
                for who, ring in (("mara", "#a8482a"), ("elsie", "#56693a"), ("tobias", "#2c5a6b"))
            ),
            {
                "id": "mb",
                "kind": "membase",
                "base": "local",
                "tab": "Local engine, inside the game",
                "folder": "This player's folder",
                "stack": True,
                "box": [840, 240, 950, 665],
                "slots": [
                    {"id": "mara", "label": "Mara's memory"},
                    {"id": "elsie", "label": "Elsie's memory"},
                    {"id": "tobias", "label": "Tobias's memory"},
                ],
            },
        ],
        "beats": [
            {
                "say": "Tell Mara a clue: it goes in her memory",
                "membase": "learn",
                "facts": ["the clue"],
                "flows": [
                    {"from": "you", "to": "mara", "token": {"label": "a clue", "icon": "search"}},
                    {"from": "mara", "to": "mb.mara", "token": "the clue"},
                ],
            },
            {
                "say": "That evening, Mara's gossip is written to Elsie's",
                "membase": "learn",
                "facts": ["Mara's gossip"],
                "flows": [
                    {
                        "from": "mara",
                        "to": "mb.elsie",
                        "toAt": [-330, 0],  # land on the slot's near side, not its top
                        "token": {"label": "gossip", "icon": "message-circle"},
                    }
                ],
            },
            {
                "say": "Ask both: only Elsie recalls it",
                "membase": "recall",
                "flows": [
                    {
                        "from": "you",
                        "to": "elsie",
                        "token": {"label": "a question", "icon": "circle-help"},
                    },
                    {
                        "from": "you",
                        "to": "tobias",
                        "token": {"label": "a question", "icon": "circle-help"},
                        "par": True,
                    },
                    {"from": "mb.elsie", "to": "elsie", "token": "Mara's gossip"},
                    {"from": "mb.tobias", "to": "tobias", "token": "nothing", "par": True},
                ],
            },
        ],
    },
}
SEED: list[str] = []

CLUE = (
    "I found a green glass button stamped with an anchor under the harbour office window. "
    "Keep that between us, Mara."
)
ASK = "Have you heard anything about what I found under the harbour office window?"
SAVED = "() => !!document.querySelector('#status #saved')"
LINE = "() => document.querySelector('#talk #line')?.textContent || ''"


async def say(page, rec, text: str, label: str) -> str:
    await rec.type("#msg", text, delay=18)
    await rec.click("#send")
    await rec.focus("#talk", pad=12)
    await rec.wait(label, page.wait_for_function(SAVED, timeout=180_000))
    return (await page.evaluate(LINE)).lower()


async def act(page, rec) -> None:
    # the opening card is the game's own; take the case before the first step
    await page.wait_for_selector("#begin", state="visible", timeout=60_000)
    await rec.click("#begin")
    await page.wait_for_selector("#opening", state="hidden")
    await rec.pause(1.6)

    rec.step(1, "Tell Mara a clue", "Only Mara hears it, and she will remember it")
    await rec.focus(None)
    await rec.pause(1.2)
    mara = await say(page, rec, CLUE, "Mara answers; the exchange is written to her memory")
    if not mara.strip():
        raise SystemExit("Mara did not answer")
    await rec.pause(2.5)
    await rec.focus("#status", pad=12)
    await rec.pause(1.6)
    await rec.focus("#knows", pad=10)
    await rec.pause(2.2)

    rec.step(
        2, "Later that evening, Mara tells Elsie", "Her words go into Elsie's memory, nobody else's"
    )
    await rec.click("#pass")
    await rec.focus(None)
    await rec.wait(
        "Mara retells it; written to Elsie's memory",
        page.wait_for_selector("#gossip-card", timeout=180_000),
    )
    written = (await page.locator("#knows-elsie #gossip-written").inner_text()).lower()
    if "mara" not in written or "button" not in written:
        raise SystemExit(f"the gossip did not carry the button to Elsie: {written!r}")
    if await page.locator("#knows-tobias .entry.none").count() != 1:
        raise SystemExit("Tobias heard something during the evening")
    await rec.pause(1.0)
    await rec.focus("#gossip-card", pad=14)
    await rec.pause(3.2)
    await rec.focus("#knows-elsie", pad=12)
    await rec.pause(2.5)

    rec.step(3, "Ask Elsie at the landing", "She remembers it, and says Mara told her")
    await rec.click("#ask-elsie")
    await rec.focus(None)
    await rec.pause(1.6)
    elsie = await say(page, rec, ASK, "Elsie searches her memory and answers")
    recalled = (await page.locator("#recalled").inner_text()).lower()
    if not ("button" in recalled and "mara" in recalled):
        raise SystemExit(f"Elsie's recall has no gossip from Mara: {recalled!r}")
    if not ("button" in elsie and "mara" in elsie):
        raise SystemExit(f"Elsie did not credit Mara with the button: {elsie!r}")
    await rec.pause(2.6)
    await rec.focus("#status", pad=12)
    await rec.pause(1.5)
    await rec.focus("#memory-clip", pad=12)
    await rec.pause(3.0)

    rec.step(3, "Ask Tobias the same", "Nobody told him: he remembers nothing")
    await rec.focus(None)  # the clipping goes away when you leave Elsie
    await rec.click("#npc-tobias")
    await rec.pause(1.6)
    tobias = await say(page, rec, ASK, "Tobias searches his memory and answers")
    recalled = (await page.locator("#recalled").inner_text()).lower()
    if any(w in tobias or w in recalled for w in ("button", "anchor", "green glass")):
        raise SystemExit(f"Tobias knows about the button: {tobias!r} / {recalled!r}")
    await rec.pause(2.6)
    await rec.focus("#memory-clip", pad=12)
    await rec.pause(2.5)

    rec.step(4, "Accuse Tobias", "The case closes and the truth comes out")
    await rec.click("#accuse-open")
    await rec.focus(None)
    await rec.pause(1.2)
    await rec.click("#accuse-tobias")
    await page.wait_for_selector("#reveal.win", timeout=30_000)
    await rec.pause(0.8)
    await rec.focus("#reveal", pad=24)
    await rec.pause(4.0)
    await rec.focus(None)
    await rec.pause(1.2)
