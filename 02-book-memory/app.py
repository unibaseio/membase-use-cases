"""Book memory: a reading app for a book the model has not read.

Doorways in Drumorty (Lorna Moon, 1925) is in the `Book` memory. The page is an e-reader: the
book open, its contents, and a reading companion. A question first recalls notes from memory;
the reader turns to the lines they come from and marks them. One answer reads those notes and
cites them, the other has only the model's training.
"""

from __future__ import annotations

import queue
import re
import sys
import threading
from pathlib import Path

from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from load import BOOK, CONTAINER, QUESTIONS, STORIES, custom_id, drumorty, slug  # noqa: E402

from demokit import ConfigError, Hit, Memory, llm  # noqa: E402
from demokit.memory import is_narration  # noqa: E402
from demokit.web import create_app, run, sse  # noqa: E402

mem = Memory("02-book-memory", default_mode="hosted")
app = create_app("Book memory", HERE, mode=mem.mode)

ABOUT = f"{BOOK['title']} by {BOOK['author']} ({BOOK['year']}), {BOOK['about']}"
WITH_MEMORY = f"""You are the reading companion in an e-reader, and you have read the book
{ABOUT}. You are given numbered notes recalled from it. Answer only from them, like a well-read
librarian jotting a reply: one sentence, at most 20 words. Lead with the answer itself, not with
the question's subject (Q: How old was the miller? A: Sixty-two, by his own count [1].). Put the
note you used right after the claim it supports, as [1] or [2]. Keep the book's own words where
they are vivid. No preamble, do not name the book. If the notes do not answer it, say only: "The
stories I have read don't say." """
WITHOUT_MEMORY = f"""You answer questions about the book {ABOUT} from your own knowledge. You
have no access to the text. One sentence, at most 20 words. Lead with the answer itself, not with
the question's subject. No preamble."""

#: The page numbers of the 1925 edition's contents list, for the reader's contents.
PRINTED = {
    "The Corp’": 11,
    "Silk Both Sides": 27,
    "The Sinning of Jessie MacLean": 41,
    "Wantin’ a Hand": 65,
    "The Tattie-Doolie": 79,
    "The Courtin’ of Sally Ann": 115,
}

_CITE = re.compile(r"\s*\[\[([^\]]+)\]\]")
_TITLES = {slug(t): t for _, t in STORIES}
_TITLES.update({slug(custom_id(t)): t for _, t in STORIES})


# ---- the book on the page -------------------------------------------------------------------
# The reader shows the same Gutenberg text load.py wrote into memory (cached on disk). The
# model never sees it: the answer with memory gets only what recall returns.

_BOOK: dict[str, list[str]] = {}


def text() -> dict[str, list[str]]:
    """{story title: its paragraphs}, in book order."""
    if not _BOOK:
        for title, body in drumorty():
            _BOOK[title] = [p.strip() for p in body.split("\n\n") if p.strip()]
    return _BOOK


_STOP = set(
    "about after again also been before being could does from have into made more much only "
    "other over said some such than that their them then there these they this those very were "
    "what when where which while with would your described book story page".split()
)


def _norm(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return re.sub(r"\s+", " ", s).lower()


def _words(s: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z']{4,}", _norm(s)) if w not in _STOP}


def _sentences(para: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence; a closing quote stays with its sentence."""
    out, start = [], 0
    for m in re.finditer(r"[.!?]+[”’\"]?(?=\s+[“‘\"A-Z(]|\s*$)", para):
        out.append((start, m.end()))
        start = m.end()
        while start < len(para) and para[start] == " ":
            start += 1
    if start < len(para):
        out.append((start, len(para)))
    return out


def _stretch(hit: str) -> list[tuple[str, int]] | None:
    """Where a long hit (a stretch of a story, from the local engine) sits in the book: the
    paragraphs it covers, or None when it cannot be found."""
    head = _norm(hit)[:50]
    for title, paras in text().items():
        for i, para in enumerate(paras):
            if head in _norm(para):
                covered, n = [], 0
                while i < len(paras) and n < len(hit):
                    covered.append((title, i))
                    n += len(paras[i]) + 2
                    i += 1
                return covered
    return None


def locate(hit: str, story_hint: str, question: str) -> dict | None:
    """The sentence in the book a recalled note comes from: {story, para, start, end}.

    A hosted note restates the book ("Jessie MacLean is described as “six and thirty”"), often
    quoting it: quotes found in a sentence count most, then the words they share. A local hit
    is a stretch of the story itself: the sentence in it that fits the question best. No good
    match: None, and the page marks nothing."""
    long = len(hit) > 400
    want = _words(question) if long else _words(hit)
    quotes = (
        [] if long else [_norm(q).strip(" ,.") for q in re.findall(r"[“\"]([^”\"]{6,})[”\"]", hit)]
    )
    where = _stretch(hit) if long else None
    candidates = where or [(t, i) for t, ps in text().items() for i in range(len(ps))]
    best, best_score = None, 0.0
    for title, i in candidates:
        para = text()[title][i]
        for a, b in _sentences(para):
            sent = _norm(para[a:b])
            score = len(want & _words(sent)) + sum(4 + len(q.split()) for q in quotes if q in sent)
            if title == story_hint:
                score += 0.5
            if score > best_score:
                best, best_score = {"story": title, "para": i, "start": a, "end": b}, score
    need = 2 if long else max(3, 0.45 * len(want))
    return best if best and best_score >= need else None


def story_of(hit: Hit) -> str:
    """Which story a note came from. Local: the document's title. Hosted: the learned fact
    cites the wiki page it came from (`[[drumorty-the-corp]]`), named by the learning run."""
    if hit.source.startswith("document:") and hit.title:
        return hit.title.split(" > ")[0].split(" / ")[0]
    for c in _CITE.findall(hit.content):
        for key, title in _TITLES.items():
            if key in slug(c):
                return title
    return ""


def passages(hits: list[Hit], question: str = "") -> list[dict]:
    """The hits worth showing and citing: real notes, each once, without wiki links, each with
    the line of the book it points at. Hosted search answers a miss with prose ("No stored
    memory found…"), which is not memory."""
    out, seen = [], set()
    for h in hits:
        body = _CITE.sub("", h.content).strip()
        if not body or is_narration(body) or body in seen:
            continue
        seen.add(body)
        story = story_of(h)
        spot = locate(body, story, question)
        out.append(
            {
                "n": len(out) + 1,
                "text": body,
                "story": story or (spot or {}).get("story", ""),
                "spot": spot,
                "score": h.score,
            }
        )
    return out


class Ask(BaseModel):
    question: str


@app.get("/api/book")
def book() -> dict:
    """The book: every story with its text and whether memory holds it (and has learned it),
    and the sample questions."""
    paras = text()
    order = {t: i for i, (_, t) in enumerate(STORIES)}
    contents = [
        {
            "title": t,
            "printed": PRINTED.get(t),
            "paras": paras[t],
            "in_memory": False,
            "learned": False,
            "learning": None,
        }
        for _, t in STORIES
    ]
    by_title = {c["title"]: c for c in contents}
    error = None
    try:
        docs = mem.documents(CONTAINER)
    except ConfigError as e:  # hosted, and the container does not exist yet
        docs, error = [], str(e)
    for d in docs:
        learned, run_state = True, None  # the local engine reads a document in as it is added
        if mem.mode == "hosted":
            # The hosted list does not carry learning state; each document's own record does.
            got = mem.client.documents.get(d["id"])
            learned = bool(got.get("learned"))
            run_state = (got.get("learning_run") or {}).get("status")
        c = by_title.get(d.get("title") or "")
        if c is None:  # something else in the memory (load.py --file): listed after the book
            c = {"title": d.get("title") or "", "printed": None, "paras": [], "in_memory": True}
            contents.append(c)
        c.update(in_memory=True, learned=learned, learning=run_state)
    contents.sort(key=lambda c: order.get(c["title"], 99))
    out = {"book": BOOK, "stories": contents, "questions": QUESTIONS, "mode": mem.mode}
    if error:
        out["error"] = error
    return out


@app.post("/api/ask")
def ask(body: Ask):
    question = body.question.strip()
    if not question:
        raise ValueError("the question is empty")

    def events():
        recall = mem.recall(question, container=CONTAINER, limit=6, wait=60)
        found = passages(recall.hits, question)
        yield {
            "type": "passages",
            "passages": found,
            "seconds": round(recall.seconds, 2),
            "unheard": recall.unheard,
        }
        numbered = "\n\n".join(
            f"[{p['n']}] ({p['story'] or 'the book'}) {p['text']}" for p in found
        )
        prompts = {
            "with": [
                {"role": "system", "content": WITH_MEMORY},
                {
                    "role": "user",
                    "content": f"Notes from the book:\n\n{numbered or '(none were found)'}"
                    f"\n\nQuestion: {question}",
                },
            ],
            "without": [
                {"role": "system", "content": WITHOUT_MEMORY},
                {"role": "user", "content": question},
            ],
        }
        # Both answers stream at once; a queue interleaves their tokens in arrival order.
        out: queue.Queue = queue.Queue()

        def answer(side: str) -> None:
            try:
                for delta in llm.stream(prompts[side], temperature=0.3):
                    out.put({"type": "delta", "side": side, "text": delta})
            except Exception as e:  # noqa: BLE001 - surfaced to the page as an error event
                out.put({"type": "error", "error": f"{side}: {e}"})
            finally:
                out.put({"type": "end", "side": side})

        for side in prompts:
            threading.Thread(target=answer, args=(side,), daemon=True).start()
        open_sides = len(prompts)
        while open_sides:
            event = out.get()
            if event["type"] == "error":
                raise RuntimeError(event["error"])
            if event["type"] == "end":
                open_sides -= 1
            yield event
        yield {"type": "done"}

    return sse(events())


@app.exception_handler(ValueError)
def bad_request(_, e: ValueError):
    from fastapi.responses import JSONResponse

    return JSONResponse({"error": str(e)}, status_code=400)


if __name__ == "__main__":
    run(app, port=8702)
