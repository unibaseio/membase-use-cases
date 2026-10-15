"""Study buddy: quizzes written only from the course passages memory recalls, graded against
those passages. Each finished quiz leaves one memory of what you got wrong (and of the old
weak spots you have now fixed); "Review my weak spots" recalls those memories and builds the
next quiz around them. How you like to learn is kept as standing facts in your profile."""

from __future__ import annotations

import contextlib
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from membase.errors import MembaseError  # noqa: E402

from demokit import ConfigError, Hit, Memory, llm  # noqa: E402
from demokit.web import create_app, run, sse  # noqa: E402

CONTAINER = "Study"
mem = Memory("03-study-buddy", default_mode="hosted")
app = create_app("Study buddy", HERE, mode=mem.mode)

# The local engine is one in-process store; one call at a time keeps a search from reading it
# while a write is half done. Hosted calls go over HTTP and can run side by side.
_local = threading.RLock() if mem.mode == "local" else None


def _mem():
    return _local if _local is not None else contextlib.nullcontext()


# ---- what a recalled passage is ----------------------------------------------------------

_CITE = re.compile(r"\s*\[\[([^\]]+)\]\]")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _cites(hit: Hit) -> list[str]:
    return _CITE.findall(hit.content)


def is_memory(hit: Hit) -> bool:
    """A quiz memory, not course material. Local: conversation memory comes back as
    `episode:` hits and documents as `document:` hits. Hosted: every hit is a fact the
    account's agent learned, and it cites the file it came from in `[[...]]`; a memory written
    with `memories.add` is a `memory-...` file."""
    if hit.source.startswith("document:"):
        return False
    if hit.source.startswith("episode:"):
        return True
    cites = _cites(hit)
    return bool(cites) and all(c.startswith("memory-") for c in cites)


def _is_quiz_doc(d: dict) -> bool:
    """A quiz memory the page wrote (`memories.add`, titled "Quiz on …"), not a lecture."""
    return (d.get("metadata") or {}).get("kind") == "memory" or str(
        d.get("title") or ""
    ).startswith("Quiz on ")


def course_docs() -> list[dict]:
    """The lectures in the Study container (not the quiz memories), oldest first, each with
    whether it has been learned yet."""
    with _mem():
        docs = mem.documents(CONTAINER)
    out = []
    for d in docs:
        if _is_quiz_doc(d):
            continue
        learned, run = d.get("learned"), None
        if mem.mode == "hosted":
            # The hosted list does not carry learning state; each document's own record does.
            got = mem.client.documents.get(d["id"])
            learned, run = bool(got.get("learned")), (got.get("learning_run") or {}).get("status")
        elif learned is None:
            learned = d.get("status") == "learned"
        out.append(
            {
                "id": d["id"],
                "title": d.get("title") or "",
                "custom_id": d.get("custom_id") or "",
                "learned": bool(learned),
                # A run can end `failed` with the document unlearned for good, though search can
                # still read the stored file; the page says so instead of waiting forever.
                "learning": run,
                "ready": bool(learned) or run not in ("queued", "running"),
            }
        )
    out.sort(key=lambda d: d["title"])
    return out


def _source_label(hit: Hit, docs: list[dict]) -> str:
    if hit.source.startswith("document:"):
        return hit.title or "Course"
    by_slug = {_slug(d["custom_id"] or d["title"]): d["title"] for d in docs}
    names = [by_slug.get(c, c) for c in _cites(hit) if not c.startswith("memory-")]
    return ", ".join(dict.fromkeys(names)) or "Course"


def _belongs(hit: Hit, doc: dict) -> bool:
    """Whether a course passage comes from this lecture."""
    if hit.source.startswith("document:"):
        return (hit.title or "").startswith(doc["title"]) or doc["id"] in hit.source
    return _slug(doc["custom_id"] or doc["title"]) in _cites(hit)


def _clean(text: str) -> str:
    return _CITE.sub("", text).strip()


def _recall_many(queries: list[str], limit: int = 8) -> list[Hit]:
    """Several searches of the Study container, merged, each passage once."""
    if mem.mode == "hosted":
        with ThreadPoolExecutor(max_workers=4) as pool:
            recalls = list(
                pool.map(
                    lambda q: mem.recall(q, container=CONTAINER, limit=limit, wait=60), queries
                )
            )
    else:
        with _mem():
            recalls = [mem.recall(q, container=CONTAINER, limit=limit) for q in queries]
    seen, hits = set(), []
    for r in recalls:
        for h in r.hits:
            key = _clean(h.content)[:300]
            if key and key not in seen:
                seen.add(key)
                hits.append(h)
    return hits


def preferences() -> list[str]:
    with _mem():
        return [str(s) for s in mem.profile().get("static", [])]


def _prefs_block(prefs: list[str]) -> str:
    if not prefs:
        return "The student has not said how they like to learn."
    return "How the student likes to learn (follow this):\n" + "\n".join(f"- {p}" for p in prefs)


# ---- the quiz -----------------------------------------------------------------------------

QUIZ = (
    "You write short-answer quiz questions for a student of an introductory cell biology "
    "course. Use ONLY the numbered course passages below: every question and every answer must "
    "be stated in one passage, and you cite that passage's number. Never use outside knowledge. "
    "Ask about one specific fact or distinction per question, answerable in a few words. "
    'Reply with JSON: {"questions": [{"passage": <number>, "question": "...", '
    '"answer": "the correct answer in a few words, as the passage states it", '
    '"concept": "what is tested, 2-5 words", "trap": "a plausible wrong answer a confused '
    'student would give, such as the idea it is most often mixed up with"}]}'
)

REVIEW = (
    "You write a review quiz for a student, aimed at their weak spots. For each numbered weak "
    "spot, write exactly one short-answer question that tests that exact confusion, using ONLY "
    "the course passages listed under it; cite the passage number you used. Never use outside "
    'knowledge. Reply with JSON: {"questions": [{"spot": <weak spot number>, "passage": '
    '<passage number>, "question": "...", "answer": "the correct answer in a few words", '
    '"concept": "what is tested, 2-5 words", "trap": "the wrong answer the student gave '
    'before, or the idea they confused it with"}]}'
)

GRADE = (
    "You grade a student's short answers. For each item you get the question, the course "
    "passage it came from, the expected answer and the student's answer. Judge only against the "
    "passage. Accept answers that mean the same thing in other words or with small spelling "
    "slips. Feedback is one short line of at most 14 words, like a tutor's note in a margin: "
    "grounded in the passage, shaped by how the student likes to learn, no praise words, and "
    "it does not restate the question. For a wrong or blank answer, write `mistake` as one concise line in "
    'the form "Confused X with Y when asked about Z." (X is what they said or implied, Y is the '
    'right idea, Z is what the question asked), or "Did not know Z." for a blank answer. For a '
    'correct answer `mistake` is empty. Reply with JSON: {"results": [{"correct": true|false, '
    '"feedback": "...", "mistake": "..."}]} in the order given.'
)

WEAK = (
    "You keep a student's list of weak spots from memories of their past quizzes.\n"
    "Step 1: in `mistakes`, copy out every individual mistake the memories mention, one per "
    "entry, with the number of the memory it is in. A memory may hold several.\n"
    "Step 2: in `weak_spots`, group those mistakes into one entry per specific confusion. "
    "`misses` is how many different quizzes it went wrong in: memory often restates one mistake "
    "in other words, so mistakes from the same quiz (the same date, topic or score line) count "
    "once. `fixed` is true only when a later memory says the student now answers it correctly "
    "(the words 'now answers'), and no memory after that repeats the mistake. Course facts, "
    "explanations of the right answer and notes that a mistake was 'addressed' never count. "
    "Fixed weak spots stay in the list. Use only what the memories say, and ignore anything that "
    "is course material rather than the student's own results.\n"
    'Reply with JSON: {"mistakes": [{"memory": <number>, "text": "..."}], "weak_spots": '
    '[{"concept": "short name, e.g. Mitosis vs meiosis", "confusion": "Confused X with Y when '
    'asked about Z.", "said": "X alone: the wrong answer the student gave, at most three words, e.g. mitochondria", '
    '"misses": <number>, "fixed": true|false, "query": "a short search for '
    'the course material that explains it", "memories": [<memory numbers>]}]}, open weak spots '
    "first."
)


def _numbered(hits: list[Hit], docs: list[dict]) -> str:
    return "\n\n".join(
        f"[{i}] ({_source_label(h, docs)}) {_clean(h.content)}" for i, h in enumerate(hits, 1)
    )


def _question_rows(
    raw: list[dict], hits: list[Hit], docs: list[dict], spots: list[dict] | None = None
) -> list[dict]:
    rows = []
    for q in raw:
        try:
            p = hits[int(q.get("passage")) - 1]
        except (TypeError, ValueError, IndexError):
            continue  # a question that cites no passage we gave it is not grounded: drop it
        target = None
        if spots is not None:
            try:
                target = spots[int(q.get("spot")) - 1]
            except (TypeError, ValueError, IndexError):
                continue
        if not (q.get("question") and q.get("answer")):
            continue
        rows.append(
            {
                "id": len(rows) + 1,
                "question": str(q["question"]),
                "answer": str(q["answer"]),
                "concept": str(q.get("concept") or ""),
                "trap": str(q.get("trap") or ""),
                "passage": _clean(p.content),
                "source": _source_label(p, docs),
                "target": target,
            }
        )
    return rows


class QuizRequest(BaseModel):
    topic: str
    count: int = 4


@app.post("/api/quiz")
def quiz(body: QuizRequest):
    """A quiz on one lecture, written only from the passages memory recalls for it."""
    count = max(3, min(5, body.count))

    def events():
        docs = course_docs()
        doc = next((d for d in docs if d["title"] == body.topic), None)
        if doc is None:
            raise ValueError(f"no lecture called {body.topic!r} in the Study memory")
        name = re.sub(r"^Lecture \d+:\s*", "", doc["title"])
        parts = [p.strip() for p in re.split(r"\s+[—-]\s+", name) if p.strip()]
        queries = list(
            dict.fromkeys([name, *parts, f"{parts[0]} key terms", f"{parts[0]} common exam traps"])
        )
        yield {"type": "status", "text": f"Recalling course passages on {name}"}
        started = time.monotonic()
        hits = [h for h in _recall_many(queries) if not is_memory(h)]
        mine = [h for h in hits if _belongs(h, doc)]
        hits = (mine if len(mine) >= 2 else hits)[:10]
        yield {
            "type": "passages",
            "seconds": round(time.monotonic() - started, 1),
            "hits": [
                {"content": _clean(h.content), "source": _source_label(h, docs)} for h in hits
            ],
        }
        if not hits:
            raise RuntimeError(
                "memory returned no course passages on this lecture yet"
                + (" (the hosted Memory may still be learning it)" if mem.mode == "hosted" else "")
            )
        yield {"type": "status", "text": "Writing questions from those passages"}
        reply = llm.json_reply(
            [
                {"role": "system", "content": QUIZ},
                {
                    "role": "user",
                    "content": f"{_prefs_block(preferences())}\n\nWrite {count} questions.\n\n"
                    f"Course passages:\n{_numbered(hits, docs)}",
                },
            ]
        )
        rows = _question_rows(reply.get("questions") or [], hits, docs)[:count]
        if not rows:
            raise RuntimeError(f"the model wrote no question grounded in the passages: {reply}")
        yield {"type": "quiz", "topic": name, "questions": rows}

    return sse(events())


# ---- weak spots -----------------------------------------------------------------------------

# How a review's "now answers X correctly" line reads once hosted learning has restated it.
_FIX_EVIDENCE = re.compile(
    r"now answers|now correctly|fixed weak spot|weak spots? (?:were |was )?(?:corrected|fixed)"
    r"|quiz on weak spots|weak spots quiz|quiz review|labell?ed .weak spots.",
    re.I,
)

WEAK_QUERIES = [
    "quiz mistakes: what I confused or did not know",
    "weak spots I have fixed: now answers correctly",
]


def weak_spots() -> dict:
    """Recall the quiz memories, then name the weak spots in them."""
    started = time.monotonic()
    hits = [h for h in _recall_many(WEAK_QUERIES, limit=12) if is_memory(h)]
    seconds = round(time.monotonic() - started, 1)
    memories = [_clean(h.content) for h in hits]
    if not memories:
        return {"weak_spots": [], "memories": [], "seconds": seconds}
    reply = llm.json_reply(
        [
            {"role": "system", "content": WEAK},
            {
                "role": "user",
                "content": "Memories:\n"
                + "\n".join(f"[{i}] {m}" for i, m in enumerate(memories, 1)),
            },
        ]
    )
    # "fixed" needs evidence: a quiz memory saying the student now answers it correctly. Hosted
    # learning has written "…weak spots and that they were addressed" after a single quiz, and a
    # recalled course fact is not a fix either, whatever the model made of them.
    any_fix = any(_FIX_EVIDENCE.search(m) for m in memories)
    # A mistake counts once per session; hosted recall restates one mistake in several facts, and
    # the model has counted those twice. No count can be higher than the sessions on record.
    try:
        with _mem():
            sessions = sum(1 for d in mem.documents(CONTAINER) if _is_quiz_doc(d))
    except Exception:  # noqa: BLE001 - the clamp is a correction, never a reason to fail
        sessions = 0
    spots = []
    for s in reply.get("weak_spots") or []:
        if not s.get("concept"):
            continue
        spots.append(
            {
                "concept": str(s["concept"]),
                "confusion": str(s.get("confusion") or ""),
                "said": str(s.get("said") or ""),
                "misses": min(int(s.get("misses") or 1), sessions)
                if sessions
                else int(s.get("misses") or 1),
                "fixed": bool(s.get("fixed")) and any_fix,
                "query": str(s.get("query") or s["concept"]),
                "memories": [m for m in s.get("memories") or [] if isinstance(m, int)],
            }
        )
    return {"weak_spots": spots, "memories": memories, "seconds": seconds}


@app.get("/api/weak-spots")
def get_weak_spots() -> dict:
    return weak_spots()


class ReviewRequest(BaseModel):
    count: int = 4


@app.post("/api/review")
def review(body: ReviewRequest):
    """Recall the weak spots, then a quiz with one question on each open one, written from the
    course passages memory recalls for it."""

    def events():
        yield {"type": "status", "text": "Recalling what you got wrong before"}
        found = weak_spots()
        yield {"type": "weak", **found}
        spots = [s for s in found["weak_spots"] if not s["fixed"]][: max(1, min(5, body.count))]
        if not spots:
            yield {"type": "quiz", "topic": "Weak spots", "questions": [], "empty": True}
            return
        yield {"type": "status", "text": f"Recalling course passages for {len(spots)} weak spot(s)"}
        docs = course_docs()
        hits = [h for h in _recall_many([s["query"] for s in spots], limit=4) if not is_memory(h)]
        if not hits:
            raise RuntimeError("memory returned no course passages for these weak spots")
        hits = hits[:12]
        listing = "\n".join(
            f"Weak spot {i}: {s['concept']}. {s['confusion']}" for i, s in enumerate(spots, 1)
        )
        yield {"type": "status", "text": "Writing questions around them"}
        reply = llm.json_reply(
            [
                {"role": "system", "content": REVIEW},
                {
                    "role": "user",
                    "content": f"{_prefs_block(preferences())}\n\n{listing}\n\n"
                    f"Course passages:\n{_numbered(hits, docs)}",
                },
            ]
        )
        rows, aimed = [], set()
        for row in _question_rows(reply.get("questions") or [], hits, docs, spots):
            # one card per weak spot: the model sometimes writes several for one
            if row["target"]["concept"] not in aimed:
                aimed.add(row["target"]["concept"])
                rows.append({**row, "id": len(rows) + 1})
        if not rows:
            raise RuntimeError(f"the model wrote no question grounded in the passages: {reply}")
        yield {"type": "quiz", "topic": "Weak spots", "questions": rows}

    return sse(events())


# ---- grading, and the one memory each quiz leaves ---------------------------------------------


class Answered(BaseModel):
    question: str
    answer: str
    passage: str
    concept: str = ""
    target: dict | None = None
    given: str = ""


class GradeRequest(BaseModel):
    topic: str
    questions: list[Answered]


def quiz_memory(topic: str, items: list[Answered], results: list[dict]) -> str:
    """The one memory a finished quiz leaves: its score, each mistake, each fixed weak spot."""
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    right = sum(1 for r in results if r["correct"])
    lines = [f"Study quiz on {topic} ({stamp}): {right} of {len(results)} correct."]
    lines += [f"Mistake: {r['mistake']}" for r in results if not r["correct"] and r["mistake"]]
    lines += [f"Fixed weak spot: {r['fixed']}" for r in results if r["correct"] and r["fixed"]]
    return "\n".join(lines)


def grade_items(items: list[Answered]) -> list[dict]:
    """Grade answers against the passages they came from (no write)."""
    prompt = "\n\n".join(
        f"Item {i}.\nQuestion: {q.question}\nPassage: {q.passage}\n"
        f"Expected answer: {q.answer}\n"
        + (
            f"Weak spot it targets: {q.target.get('concept')} ({q.target.get('confusion')})\n"
            if q.target
            else ""
        )
        + f"Student's answer: {q.given.strip() or '(blank)'}"
        for i, q in enumerate(items, 1)
    )
    reply = llm.json_reply(
        [
            {"role": "system", "content": GRADE},
            {"role": "user", "content": f"{_prefs_block(preferences())}\n\n{prompt}"},
        ]
    )
    raw = reply.get("results") or []
    if len(raw) != len(items):
        raise RuntimeError(f"the grader returned {len(raw)} results for {len(items)} answers")
    return [
        {
            "correct": bool(r.get("correct")),
            "feedback": str(r.get("feedback") or ""),
            "mistake": str(r.get("mistake") or "").strip(),
            # A weak spot answered right is fixed. One plain sentence: long nested
            # "X: … when asked: …? Previously: …" lines made hosted learning fail more often
            # with "invalid JSON".
            "fixed": (
                f"now answers {q.target.get('concept')} correctly ({q.answer}), "
                "after an earlier mistake on it"
                if q.target and r.get("correct")
                else ""
            ),
        }
        for r, q in zip(raw, items, strict=True)
    ]


@app.post("/api/grade")
def grade(body: GradeRequest):
    """Grade a whole quiz and write its one memory (the smoke uses this; the page checks one
    answer at a time with /api/check and writes with /api/finish)."""
    if not body.questions:
        raise ValueError("no questions to grade")

    def events():
        results = grade_items(body.questions)
        yield {"type": "graded", "results": results}
        yield from write_quiz_memory(quiz_memory(body.topic, body.questions, results), body.topic)

    return sse(events())


@app.post("/api/check")
def check(item: Answered) -> dict:
    """One answer, graded against its passage. Nothing is written yet."""
    return grade_items([item])[0]


class Finished(BaseModel):
    topic: str
    questions: list[Answered]
    results: list[dict]


@app.post("/api/finish")
def finish(body: Finished):
    """The quiz is done: write its one memory (each mistake and each fixed weak spot a line)."""
    if len(body.questions) != len(body.results) or not body.questions:
        raise ValueError("one result per question")
    return sse(write_quiz_memory(quiz_memory(body.topic, body.questions, body.results), body.topic))


def write_quiz_memory(text: str, topic: str):
    """The one write a finished quiz makes, as page events."""
    yield {"type": "saving", "text": text}
    started = time.monotonic()
    while (busy := learning_run_active()) is not None:
        # A hosted write while the Memory is still learning starts a second run that fails
        # ("Another learning run is active"), so the quiz memory waits its turn.
        yield {
            "type": "waiting",
            "text": f"Waiting for learning run {busy['id']} to finish before writing",
        }
        if time.monotonic() - started > 600:
            raise RuntimeError(f"learning run {busy['id']} still {busy['status']} after 10 minutes")
        time.sleep(10)
    with _mem():
        out = mem.remember(text, container=CONTAINER, title=f"Quiz on {topic}")
    yield {
        "type": "saved",
        "text": text,
        "topic": topic,
        "seconds": round(time.monotonic() - started, 1),
        "document_id": out.get("document_id"),
        "learning": mem.mode == "hosted",
    }


class Rewrite(BaseModel):
    text: str
    topic: str


@app.post("/api/rewrite")
def rewrite(body: Rewrite):
    """Write a quiz memory again after its hosted learning run failed (nothing was committed,
    and the service does not retry it)."""
    if not body.text.strip():
        raise ValueError("nothing to write")
    return sse(write_quiz_memory(body.text, body.topic))


def learning_run_active() -> dict | None:
    """Hosted: the Study Memory's learning run, while it is still queued or running. Every
    document in a container reports the container's latest run, so the newest one tells."""
    if mem.mode != "hosted":
        return None
    docs = mem.documents(CONTAINER)
    if not docs:
        return None
    newest = max(docs, key=lambda d: str(d.get("created_at") or ""))
    run = mem.client.documents.get(newest["id"]).get("learning_run") or {}
    return run if run.get("status") in ("queued", "running") else None


@app.get("/api/learning/{document_id}")
def learning(document_id: str) -> dict:
    """Hosted: whether the account's agent has learned a quiz memory yet."""
    if mem.mode != "hosted":
        return {"learned": True, "run": None, "run_id": None, "done": True}
    got = mem.client.documents.get(document_id)
    run = got.get("learning_run") or {}
    learned = bool(got.get("learned"))
    return {
        "learned": learned,
        "run": run.get("status"),
        "run_id": run.get("id"),
        "done": learned or run.get("status") not in ("queued", "running"),
    }


# ---- the course and how you like to learn -----------------------------------------------------


@app.get("/api/course")
def course() -> dict:
    try:
        docs = course_docs()
    except ConfigError as e:  # hosted, and the container does not exist yet
        return {"documents": [], "preferences": [], "error": str(e)}
    return {"documents": docs, "preferences": preferences()}


def record_fact(mem: Memory, text: str) -> str:
    """A standing fact into the profile. Hosted, the write can come back 422 ("the assistant
    reported the fact recorded but it is not in the profile") although the fact lands a few
    seconds later; so on that error the profile itself is read until it shows the fact."""
    try:
        mem.remember_fact(text)
        return "recorded"
    except MembaseError as e:
        if mem.mode != "hosted" or e.status != 422:
            raise
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            time.sleep(10)
            if text in (mem.profile().get("static") or []):
                return "recorded (the write reported 422, then the fact appeared in the profile)"
        raise


class Preference(BaseModel):
    text: str


@app.post("/api/preferences")
def add_preference(body: Preference) -> dict:
    text = body.text.strip()
    if not text:
        raise ValueError("say how you like to learn")
    started = time.monotonic()
    while (busy := learning_run_active()) is not None:
        # Same rule as quiz memories: no hosted write while the Memory is still learning.
        if time.monotonic() - started > 300:
            raise RuntimeError(
                f"learning run {busy['id']} is still {busy['status']}; try again in a minute"
            )
        time.sleep(10)
    with _mem():
        status = record_fact(mem, text)
    return {"preferences": preferences(), "status": status}


@app.exception_handler(ValueError)
def bad_request(_, e: ValueError):
    from fastapi.responses import JSONResponse

    return JSONResponse({"error": str(e)}, status_code=400)


if __name__ == "__main__":
    run(app, port=8703)
