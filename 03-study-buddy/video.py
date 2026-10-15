"""The study buddy video, on hosted Membase. After the explainer: Cue, a flashcard app
for BIO 110. A deck for the Cellular respiration lecture is written from passages Membase
recalls from the lecture notes, one card at a time. Two cards are missed: each flips to the
lecture line it came from, with the student's answer struck through in the margin, and goes to
the review pile. The session is one note to memory. Next session, the pile comes back from
memory with what the student said, and the review deck is dealt from it; right this time, the
cards are marked learned.

The student is simulated: for the cards it misses it types the deck writer's typical wrong
answer (`trap`), and otherwise the answer as the notes give it. A take is kept only if both
misses are graded wrong, the pile comes back from memory, both session notes are learned and
the pile then shows cards learned.

Record on a fresh account (record_hosted.sh runs seed.py first and retries on a new account):
scripts/video/record_hosted.sh 03-study-buddy --containers Study
"""

META = {
    "title": "Study buddy",
    "title_html": "Flashcards that<br>remember your mistakes",
    "pitch": "Cards come from the lecture notes in memory. The ones you miss are remembered with what you said, and the next review deals exactly those.",
    "base": "hosted",
    "port": 8703,
    "banner_from_recording": True,
    "line": "Cue deals cards from the lecture notes, then the ones you missed.",
    "intro_at": ["A review deck from the pile", 80.0],  # a review card: "last time you said"
    "explain": {
        "title": "Cue keeps your mistakes in Membase",
        "actors": [
            {"id": "you", "icon": "user", "label": "You", "kind": "user", "at": [250, 560]},
            {
                "id": "cue",
                "icon": "layers",
                "label": "Cue",
                "kind": "app",
                "at": [660, 560],
                "size": 200,
                "labelAt": "inside",
                "tint": "#24584a",
                "ink": "#fff",
            },
            {
                "id": "mb",
                "kind": "membase",
                "base": "hosted",
                "key": "Developer key",
                "box": [1080, 300, 700, 470],
                "slots": [
                    {
                        "id": "study",
                        "label": "Study memory",
                        "icon": "graduation-cap",
                        "facts": 2,
                    }
                ],
            },
        ],
        "beats": [
            {
                "say": "Cards are written from the lecture notes",
                "membase": "recall",
                "hit": 0,
                "flows": [
                    {
                        "from": "cue",
                        "to": "mb",
                        "token": {"label": "Lecture 3", "icon": "search"},
                    },
                    {"from": "mb", "to": "cue", "token": "passages"},
                    {"from": "cue", "to": "you", "token": {"label": "3 cards", "icon": "layers"}},
                ],
            },
            {
                "say": "Your misses go in as one note",
                "membase": "learn",
                "facts": ["Missed: “matrix”", "Missed: “NADH”"],
                "flows": [
                    {"from": "you", "to": "cue", "token": {"label": "2 misses", "icon": "x"}},
                    {
                        "from": "cue",
                        "to": "mb",
                        "token": {"label": "session note", "icon": "file-text"},
                    },
                ],
            },
            {
                "say": "Next session, the review deals those misses",
                "membase": "recall",
                "hit": 2,
                "flows": [
                    {
                        "from": "cue",
                        "to": "mb",
                        "token": {"label": "my misses", "icon": "search"},
                    },
                    {"from": "mb", "to": "cue", "token": "2 misses"},
                    {
                        "from": "cue",
                        "to": "you",
                        "token": {"label": "review deck", "icon": "layers"},
                        "result": "right this time",
                    },
                ],
            },
        ],
    },
}
SEED: list[str] = []
TOPIC = "Cellular respiration"
WRONG_AT = {0, 2}  # the cards the student misses in the first session

LEARNED = (
    "() => /Learned|not learned/.test(document.querySelector('#savestate')?.textContent || '')"
)
PILE = "() => /to review/.test(document.querySelector('#pilecount')?.textContent || '')"


async def answer_all(page, rec, wrong: set[int], review: bool) -> None:
    """One card at a time: write, flip, read the back, next. The student is simulated: for a
    card it misses it types the deck writer's typical wrong answer (`trap`), and otherwise the
    answer as the notes give it."""
    i = 0
    while True:
        await page.wait_for_selector("#question", timeout=240_000)
        await rec.focus("#card", pad=14)
        if review:
            rec.step(
                4,
                "A review deck from the pile",
                "Each card aims at a miss; what you said last time is in the margin",
            )
            await rec.pause(2.4 if i == 0 else 0.6)
        elif i:
            rec.step(
                1,
                "A deck from the lecture notes",
                f"Card {i + 1}: write the answer, then flip the card",
            )
        cur = await page.evaluate("() => window.__current")
        given = (cur.get("trap") or "I don't know") if i in wrong else cur["answer"]
        await rec.type("#answer", given, delay=16)
        await rec.press("Enter")  # the card's form flips it, like the Flip button
        await rec.wait(
            "Checking against the notes", page.wait_for_selector("#verdict", timeout=120_000)
        )
        await rec.pause(0.9)  # the card turns over
        if i in wrong:
            rec.step(
                1,
                "A miss goes to the review pile",
                "The back shows the lecture line; your answer is struck through in the margin",
            )
            if i == min(wrong):  # the first miss: show it landing in the pile
                await rec.pause(1.7)
                await rec.focus(None)
                await rec.pause(1.4)
            else:
                await rec.pause(1.9)
        elif review:
            rec.step(
                4, "Right this time", "The card flips to the lecture line, and comes off the pile"
            )
            await rec.pause(1.4 if i == 0 else 0.8)
        else:
            rec.step(
                1,
                "A deck from the lecture notes",
                "Right: the back shows the lecture line the card was written from",
            )
            await rec.pause(0.5)
        last = "Finish" in await page.locator("#next").inner_text()
        await rec.click("#next")
        if last:
            return
        i += 1


async def ready(page) -> None:
    """The decks are listed and the review pile is back from memory."""
    await page.wait_for_selector(".lecture", timeout=300_000)
    await page.wait_for_function(PILE, timeout=300_000)


async def wait_learned(page, rec, label: str) -> None:
    await rec.wait(label, page.wait_for_function(LEARNED, timeout=900_000))
    if "Learned" not in await page.locator("#savestate").inner_text():
        # a failed learning run, even after the page wrote it again: record again
        raise SystemExit("the session note was not learned: record again on a fresh account")


async def act(page, rec) -> None:
    await rec.wait("Opening the course and the review pile", ready(page))

    rec.step(
        1,
        "A deck from the lecture notes",
        "Cue, a flashcard app for BIO 110: the five lectures are in a Membase memory",
    )
    await rec.focus(None)
    await rec.pause(1.4)
    await rec.click(f".lecture:has-text('{TOPIC}')")
    rec.step(
        1,
        "A deck from the lecture notes",
        "Membase recalls the lecture's passages; each card is written from one of them",
    )
    await rec.focus("#stage", pad=0)
    await rec.wait(
        "Recalling the lecture, writing the cards",
        page.wait_for_selector("#question", timeout=300_000),
    )
    await answer_all(page, rec, WRONG_AT, review=False)

    rec.step(
        2, "The session goes into memory", "One note: the score and each miss. Membase learns it"
    )
    await page.wait_for_selector("#notetext:not(:empty)", timeout=120_000)
    missed = await page.locator("#done .mini .no").count()
    if missed != len(WRONG_AT):
        raise SystemExit(
            f"the grader marked {missed} cards wrong, not {len(WRONG_AT)}: record again"
        )
    await rec.focus("#saved", pad=18)
    await rec.pause(2.2)
    await wait_learned(page, rec, "Membase learns the session note")
    await rec.pause(1.0)

    rec.step(3, "Next session", "The review pile is recalled from memory")
    await rec.focus(None)  # the page reloads: nothing on it is where it was
    await page.reload()
    await rec.wait("Recalling the review pile", ready(page))
    spots = await page.locator("#weak .spot:not(.fixed)").count()
    if spots < 1 or not await page.locator("#review").count():
        raise SystemExit("the misses did not come back from memory: record again")
    cards = {1: "One card", 2: "Two cards", 3: "Three cards"}.get(spots, f"{spots} cards")
    rec.step(3, "Next session", f"{cards} back from memory, each with what you said")
    await rec.focus("#pile", pad=0)
    await rec.pause(2.8)

    rec.step(4, "A review deck from the pile", "Dealt from the misses in memory")
    await rec.click("#review")
    await rec.focus("#stage", pad=0)
    await rec.wait(
        "Recalling the pile, writing the review",
        page.wait_for_selector("#question", timeout=300_000),
    )
    await answer_all(page, rec, set(), review=True)
    await page.wait_for_selector("#notetext:not(:empty)", timeout=120_000)
    rec.step(4, "Right this time", "The review session is one more note to memory")
    await rec.focus("#saved", pad=18)
    await rec.pause(1.4)
    await wait_learned(page, rec, "Membase learns the review")
    # right after learning, recall may not surface the new note yet: check the pile again until it does
    learned = (
        "() => /[1-9]\\d* learned/.test(document.querySelector('#pilecount')?.textContent || '')"
    )
    for attempt in range(4):
        try:
            await rec.wait(
                "Recalling the review pile", page.wait_for_function(learned, timeout=90_000)
            )
            break
        except Exception:
            if attempt == 3:
                raise
            await rec.click("#refresh")
    rec.step(4, "Right this time", "Back from memory: the cards are marked learned")
    await rec.focus("#pile", pad=0)
    await rec.pause(3.0)
    await rec.focus(None)
    await rec.pause(0.8)
