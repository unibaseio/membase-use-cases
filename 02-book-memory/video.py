"""The book memory video, on hosted Membase. After the architecture card: a reading app with
Doorways in Drumorty open, a 1925 book of village stories the model has never read; its reading
companion has read three of the stories (they are in memory). A question recalls the line that
answers it; the reader turns to that line and marks it; the answer that read it is right and
cites it, the one that did not guesses.

The questions are the app's own samples, checked beforehand: without the book, gpt-4.1-mini gets
each one wrong every time. A take is kept only if the answer with memory has the book's answer
(a cold potato; 36 and fifteen years), cites a line that is marked on the page and holds it, and
the answer without does not have it.

Record on a fresh account (SEED loads and verifies the book first):
scripts/video/record_hosted.sh 02-book-memory --containers Book
"""

import re

META = {
    "title": "Book memory",
    "title_html": "A book no<br>model has read",
    "pitch": "A little-read 1925 book is in memory. Ask the reading companion: it marks the line that answers you. Without memory, the model guesses.",
    "base": "hosted",
    "port": 8702,
    "banner_from_recording": True,
    "arch": {
        "kick": "How it works",
        "title": "The book is in memory; the model sees only what recall returns",
        "nodes": [
            {
                "t": "Reading app",
                "d": "Membase SDK with a developer key for the Book memory; one model, asked twice",
            },
            {
                "t": "Membase API",
                "d": "add puts each story in; search returns notes for a question",
                "mb": True,
            },
            {
                "t": "Your account's agent VM",
                "d": "each story lands as a file; a learning run turns it into facts. Search is a recall turn over them",
                "mb": True,
            },
            {
                "t": "Book memory",
                "d": "Doorways in Drumorty (Lorna Moon, 1925): three stories, from Project Gutenberg",
                "mb": True,
            },
        ],
        "foot": "Same model, same question. Only one of the two answers gets the recalled lines.",
    },
}
SEED = ["02-book-memory/load.py"]

DONT_KNOW = re.compile(
    r"\b(do not|don't|cannot|can't|not (sure|certain|familiar|aware)|no (information|record|details?))\b",
    re.I,
)
RECALLED = """() => document.querySelector('#text mark.hl.on')
  || /Nothing in/.test(document.querySelector('#with')?.textContent || '')"""
ANSWERED = "() => !document.querySelector('#another').disabled"


async def answered(page, q: dict) -> str:
    """The answer without memory, after checking the take shows what the captions say: the
    answer with memory is right and cites a line that is marked on the page and holds the
    answer; the answer without does not have it."""
    with_text = await page.locator("#with").inner_text()
    without_text = await page.locator("#without").inner_text()
    cited = " ".join(await page.locator("#text mark.hl.cited").all_inner_texts())
    if not re.search(q["expect"], with_text, re.I):
        raise SystemExit(f"the answer with memory missed the passage: {with_text!r}")
    if not await page.locator("#cited .ref").count() or not re.search(q["expect"], cited, re.I):
        raise SystemExit(f"the answer cites no marked line that holds the answer: {cited!r}")
    if re.search(q["expect"], without_text, re.I):
        raise SystemExit(f"the model alone knew the answer this time: {without_text!r}")
    return without_text


async def recalled(page, rec, what: str) -> None:
    await rec.wait("Searching the Book memory", page.wait_for_function(RECALLED, timeout=240_000))
    if not await page.locator("#text mark.hl").count():
        raise SystemExit(f"memory returned no line for {what}")


async def lines(page) -> str:
    n = await page.locator("#text mark.hl").count()
    return {1: "The line", 2: "Two lines"}.get(n, f"{n} lines")


async def act(page, rec) -> None:
    await page.wait_for_selector(".sample", timeout=120_000)
    book = await page.evaluate("() => fetch('/api/book').then((r) => r.json())")
    if sum(s["learned"] for s in book["stories"]) < 3:
        raise SystemExit(f"the book is not learned: {book['stories']}")
    q, q2 = book["questions"][0], book["questions"][2]

    rec.step(1, "The book is in memory", "Doorways in Drumorty, 1925, open in a reading app")
    await rec.focus(None)
    await rec.pause(2.2)
    rec.step(
        1,
        "The book is in memory",
        "The companion has read three of its six stories: the hosted Memory learned them",
    )
    await rec.focus("#library", pad=12)
    await rec.pause(3.2)

    rec.step(2, "Ask", f"“{q['q']}” The model alone gets this wrong")
    await rec.focus("#companion", pad=10)
    await rec.hover(".sample >> nth=0", pause=1.2)
    await rec.click(".sample >> nth=0")

    rec.step(3, "Recall", "Membase searches the Book memory for this question")
    await rec.hover("#shelf .cover", pause=0.1)  # the cursor on the cover, off the text
    await rec.focus("#page", pad=6)
    await recalled(page, rec, "the first question")
    rec.step(3, "Recall", f"{await lines(page)} memory returned, marked in {q['story']}")
    await rec.pause(3.4)

    await rec.wait("Both answers", page.wait_for_function(ANSWERED, timeout=180_000))
    without_text = await answered(page, q)
    alone = "says it does not know" if DONT_KNOW.search(without_text) else "guesses, and is wrong"
    rec.step(
        4, "Two answers", f"Has read it: a cold potato, cited to {q['story']}. Hasn't: it {alone}"
    )
    await rec.focus("#answers", pad=12)
    await rec.pause(4.2)
    await rec.focus(None)
    await rec.pause(2.4)

    # one more question, from another story: the same contrast, with numbers
    rec.step(2, "Ask another", f"“{q2['q']}”")
    await rec.focus("#companion", pad=10)
    await rec.click("#another")
    await rec.hover(".sample >> nth=2", pause=1.0)
    await rec.click(".sample >> nth=2")
    rec.step(3, "Recall", "Membase searches the Book memory again")
    await rec.hover("#shelf .cover", pause=0.1)
    await rec.focus("#page", pad=6)
    await recalled(page, rec, "the second question")
    rec.step(3, "Recall", f"{await lines(page)} from {q2['story']}, marked in the book")
    await rec.pause(3.2)
    await rec.wait("Both answers", page.wait_for_function(ANSWERED, timeout=180_000))
    without_text = await answered(page, q2)
    alone = "says it does not know" if DONT_KNOW.search(without_text) else "guesses wrong"
    rec.step(4, "Two answers", f"Has read it: 36, and fifteen years. Hasn't: it {alone}")
    await rec.focus("#answers", pad=12)
    await rec.pause(3.6)
    await rec.focus(None)
    await rec.pause(2.6)
