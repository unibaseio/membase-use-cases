"""Put a book into memory: Doorways in Drumorty by Lorna Moon (1925, public domain), a little-read
book of stories about a Scottish village. The model has not read it, so with memory and without
give different answers.

    uv run 02-book-memory/load.py               # the first three stories
    uv run 02-book-memory/load.py --stories 6   # all six
    uv run 02-book-memory/load.py --verify      # check only: every story in memory and learned
    uv run 02-book-memory/load.py --file my-book.txt --title "My Book"

The text comes from Project Gutenberg (#79252) and is cached under data/02-book-memory/. Each
story becomes one document in the `Book` container. Re-running skips stories already there
(each carries a stable custom_id). Exits non-zero when a story is missing or not learned, so a
recording never starts on a half-learned book.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from demokit import Memory  # noqa: E402
from demokit.config import DATA  # noqa: E402
from demokit.memory import is_narration  # noqa: E402

CONTAINER = "Book"
BOOK = {
    "title": "Doorways in Drumorty",
    "author": "Lorna Moon",
    "year": 1925,
    "gutenberg": 79252,
    "about": "stories of a Scottish village",
}
GUTENBERG = f"https://www.gutenberg.org/cache/epub/{BOOK['gutenberg']}/pg{BOOK['gutenberg']}.txt"
# The stories in book order, as the contents list names them, with how this demo titles them.
STORIES = [
    ("THE CORP’", "The Corp’"),
    ("SILK BOTH SIDES", "Silk Both Sides"),
    ("THE SINNING OF JESSIE MACLEAN", "The Sinning of Jessie MacLean"),
    ("WANTIN’ A HAND", "Wantin’ a Hand"),
    ("THE TATTIE-DOOLIE", "The Tattie-Doolie"),
    ("THE COURTIN’ OF SALLY ANN", "The Courtin’ of Sally Ann"),
]

#: Questions the model gets wrong without the book (gpt-4.1-mini, asked three times each with
#: the book's title and author: every answer was a confident guess, and wrong). `expect` is
#: what a right answer contains; `story` is where the book says it.
QUESTIONS = [
    {
        "q": "How did Sandy MacNab die?",
        "expect": r"potato",
        "answer": "He choked on a cold potato and hiccoughed himself to death.",
        "story": "The Corp’",
    },
    {
        "q": "What prize had Kirsty Fraser won that made Mistress MacNab angry with her?",
        "expect": r"butter",
        "answer": "First prize for her butter, at the show.",
        "story": "The Corp’",
    },
    {
        "q": "How old was Jessie MacLean, and how long had Jock Sclessor been keeping company with her?",
        "expect": r"(36|thirty-six|six and thirty)[\s\S]*(15|fifteen)|(15|fifteen)[\s\S]*(36|thirty-six|six and thirty)",
        "answer": "She was thirty-six, and Jock had kept company with her for fifteen years.",
        "story": "Silk Both Sides",
    },
    {
        "q": "What does a man wear in his buttonhole in Drumorty when he means to propose?",
        "expect": r"gowan|daisy",
        "answer": "A white gowan (a field daisy).",
        "story": "Silk Both Sides",
    },
]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().replace("’", "")).strip("-")


def custom_id(title: str) -> str:
    return f"drumorty:{slug(title)}"


def drumorty() -> list[tuple[str, str]]:
    """(title, text) for each story, in book order. The download is cached."""
    cache = DATA / "02-book-memory" / f"pg{BOOK['gutenberg']}.txt"
    if not cache.is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        r = httpx.get(GUTENBERG, follow_redirects=True, timeout=60)
        r.raise_for_status()
        cache.write_text(r.text, encoding="utf-8")
    text = cache.read_text(encoding="utf-8").replace("\r\n", "\n")
    body = text.split("*** START OF", 1)[1].split("*** END OF", 1)[0]
    body, _, notes = body.partition("\nFOOTNOTES\n")
    body = body.split("\nTHE END\n", 1)[0]
    # The book glosses its Scots words in footnotes ("mutch[1]" ... "[1] A close-frilled cap.").
    # Put each gloss in place, so a passage carries its own meaning.
    gloss = {
        n: " ".join(t.split()).rstrip(".")
        for n, t in re.findall(r"^\[(\d+)\] (.+?)(?=\n\n|\Z)", notes, re.M | re.S)
    }
    body = re.sub(
        r"\[(\d+)\]", lambda m: f" ({gloss[m[1]].lower()})" if m[1] in gloss else "", body
    )
    # A story starts at its title on a line of its own; the contents list indents the same
    # titles, so only the unindented ones count.
    starts = []
    for heading, title in STORIES:
        m = re.search(rf"^{re.escape(heading)}$", body, re.M)
        if not m:
            raise SystemExit(f"the Gutenberg text has no heading {heading!r}: has it changed?")
        starts.append((m.start(), m.end(), title))
    stories = []
    for i, (_, end, title) in enumerate(starts):
        stop = starts[i + 1][0] if i + 1 < len(starts) else len(body)
        part = body[end:stop].strip()
        part = re.sub(r"^\([^)\n]*\)\s*", "", part)  # a footnote on the heading
        part = re.sub(r"^_[^_\n]+_\s*", "", part)  # the title again, in italics
        # Gutenberg wraps lines at ~70 columns; a single newline is not a paragraph break.
        part = re.sub(r"[ \t]*(?<!\n)\n(?!\n)[ \t]*", " ", part)
        part = re.sub(r"_([^_]+)_", r"\1", part)  # italics
        stories.append((title, re.sub(r"\n{3,}", "\n\n", part)))
    return stories


# ---- hosted: one learning run at a time ------------------------------------------------


def _latest_run(mem: Memory) -> dict:
    """The Book memory's latest learning run (every document reports the container's latest)."""
    docs = mem.documents(CONTAINER)
    if not docs:
        return {}
    newest = max(docs, key=lambda d: str(d.get("created_at") or ""))
    return mem.client.documents.get(newest["id"]).get("learning_run") or {}


def _wait_learning(mem: Memory) -> dict:
    """Until the latest learning run is no longer queued or running. Waits on the container,
    not on the returned document: a write can come back with `document_id: null` when the
    folder sync is slow, and writing the next story then would start a second run that fails."""
    time.sleep(3)
    while (run := _latest_run(mem)).get("status") in ("queued", "running"):
        time.sleep(10)
    return run


def verify(mem: Memory, titles: list[str], *, recall: bool = True) -> None:
    """Every story is there under its own title and learned, and the video's question recalls
    the passage that answers it. Exits non-zero otherwise."""
    have = {d.get("title"): d for d in mem.documents(CONTAINER)}
    problems = []
    for title in titles:
        d = have.get(title)
        if d is None:
            problems.append(f"{title!r} is missing (or lost its title)")
        elif mem.mode == "hosted" and not mem.client.documents.get(d["id"]).get("learned"):
            run = _latest_run(mem)
            problems.append(
                f"{title!r} is not learned (latest run {run.get('id')} {run.get('status')})"
            )
    if not problems and recall and QUESTIONS[0]["story"] in titles:
        # A run can end `succeeded` with nothing recallable: ask for real.
        q = QUESTIONS[0]
        hits = mem.recall(q["q"], container=CONTAINER, limit=6, wait=90).hits
        real = [h.content for h in hits if not is_narration(h.content)]
        if not any(re.search(q["expect"], h, re.I) for h in real):
            problems.append(
                f"recall of {q['q']!r} did not return the passage that answers it: {real!r}"
            )
    if problems:
        raise SystemExit("the book is not ready:\n  " + "\n  ".join(problems))
    print(
        f"All {len(titles)} stories are in memory under their titles"
        + (" and learned" if mem.mode == "hosted" else "")
        + (", and the first question recalls its passage." if recall else ".")
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--stories", type=int, default=3, help="how many stories to load (1-6)")
    p.add_argument("--verify", action="store_true", help="only check that the book is ready")
    p.add_argument("--file", help="load this text file instead, as one document")
    p.add_argument("--title", default="", help="the document title for --file")
    a = p.parse_args()

    mem = Memory("02-book-memory", default_mode="hosted")
    if a.file:
        docs = [(a.title or Path(a.file).stem, Path(a.file).read_text(encoding="utf-8"))]
    else:
        docs = drumorty()[: max(1, a.stories)]
    if a.verify:
        return verify(mem, [t for t, _ in docs], recall=not a.file)
    size = sum(len(t) for _, t in docs) // 1000
    print(f"{len(docs)} stories ({size} KB) into {CONTAINER!r} on the {mem.mode} base")
    for title, text in docs:
        started = time.monotonic()
        out = mem.add_document(text, container=CONTAINER, title=title, custom_id=custom_id(title))
        run = {}
        if mem.mode == "hosted" and out.get("status") != "exists":
            # A write while the Memory is still learning starts a second run, which fails
            # ("Another learning run is active") and leaves the document unlearned. So hosted
            # writes go one learning run at a time.
            run = _wait_learning(mem)
        note = f"run {run.get('id')} {run.get('status')}" if run else ""
        print(f"  {title:<32} {out.get('status'):<8} {time.monotonic() - started:5.1f}s {note}")
    verify(mem, [t for t, _ in docs], recall=not a.file)


if __name__ == "__main__":
    main()
