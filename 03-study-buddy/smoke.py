"""End-to-end check against the real API: course in, a quiz from recalled passages, wrong
answers, the mistakes recalled as weak spots, a review quiz aimed at them, then right answers
that fix them.

    uv run 03-study-buddy/smoke.py            # on the demo's base (MEMBASE_DEMO_MODE to switch)

Writes to its own data directory (local) or the configured account (hosted; use a fresh one
from scripts/bootstrap_hosted.py, since the check counts weak spots). Exits non-zero with the
reason on any failure.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if os.environ.get("MEMBASE_DEMO_MODE", "") != "hosted":
    # A fresh local store, so the check never passes on yesterday's data.
    os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-03-"))
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402

LECTURE = "Lecture 4: Cell division — mitosis and meiosis"
_GENERIC = {
    "confused",
    "asked",
    "about",
    "which",
    "where",
    "there",
    "their",
    "these",
    "those",
    "answer",
    "answers",
    "correctly",
    "question",
    "longer",
    "what",
    "when",
    "with",
    "know",
}


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{5,}", text.lower()) if w not in _GENERIC}


def events(client: TestClient, path: str, body: dict) -> list[dict]:
    out = []
    with client.stream("POST", path, json=body) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    errors = [e for e in out if e["type"] == "error"]
    assert not errors, errors
    return out


def one(evs: list[dict], kind: str) -> dict:
    return next(e for e in evs if e["type"] == kind)


def wait_learned(client: TestClient, saved: dict, info: dict) -> dict:
    """Hosted: wait for the quiz memory's learning run. A failed run commits nothing and is not
    retried by the service, so the page offers "Write it again"; this does the same, once."""
    if info["mode"] != "hosted":
        return {"learned": True}
    for attempt in (1, 2):
        deadline = time.monotonic() + 900
        while True:
            state = client.get(f"/api/learning/{saved['document_id']}").json()
            if state["done"]:
                break
            assert time.monotonic() < deadline, f"quiz memory not learned after 15 minutes: {state}"
            time.sleep(15)
        if state["learned"]:
            return state
        print(f"WARNING: learning run {state['run_id']} ended {state['run']} (attempt {attempt})")
        if attempt == 1:
            evs = events(client, "/api/rewrite", {"text": saved["text"], "topic": saved["topic"]})
            saved = one(evs, "saved")
            print("  wrote the quiz memory again")
    return state


def main() -> None:
    subprocess.run([sys.executable, str(HERE / "seed.py")], check=True, env=os.environ)
    import app as demo  # noqa: PLC0415 - after the store is chosen

    client = TestClient(demo.app)
    info = client.get("/api/info").json()
    print("base:", info["mode"])
    assert client.get("/").status_code == 200, "page did not load"
    if info["mode"] == "hosted":
        deadline = time.monotonic() + 1200
        while True:
            docs = client.get("/api/course").json()["documents"]
            if len(docs) >= 5 and all(d["ready"] for d in docs):
                unlearned = [d for d in docs if not d["learned"]]
                if unlearned:
                    print("WARNING: learning did not finish for:", unlearned)
                break
            assert time.monotonic() < deadline, f"course not learned after 20 minutes: {docs}"
            time.sleep(20)

    before = client.get("/api/weak-spots").json()
    open_before = [s for s in before["weak_spots"] if not s["fixed"]]
    print(f"weak spots before: {len(open_before)} open")

    # 1. A quiz on one lecture, every question tied to a passage memory recalled.
    started = time.monotonic()
    evs = events(client, "/api/quiz", {"topic": LECTURE, "count": 4})
    passages = one(evs, "passages")
    questions = one(evs, "quiz")["questions"]
    recalled = {h["content"] for h in passages["hits"]}
    assert len(questions) >= 3, questions
    assert all(q["passage"] in recalled for q in questions), (
        "a question is not from a recalled passage"
    )
    print(
        f"quiz: {len(questions)} questions from {len(recalled)} recalled passages "
        f"in {time.monotonic() - started:.1f}s"
    )
    for q in questions:
        print(f"  Q: {q['question']}  [{q['source'][:50]}]")

    # 2. Deliberately wrong answers: the misconception each question was written to catch.
    graded = events(
        client,
        "/api/grade",
        {
            "topic": "Cell division",
            "questions": [{**q, "given": q["trap"]} for q in questions],
        },
    )
    results = one(graded, "graded")["results"]
    mistakes = [r["mistake"] for r in results if not r["correct"] and r["mistake"]]
    assert len(mistakes) >= 2, f"wrong answers were not caught: {results}"
    saved = one(graded, "saved")
    print(f"graded: {len(mistakes)} mistakes; one memory written in {saved['seconds']}s:")
    print("  " + saved["text"].replace("\n", "\n  "))
    wait_learned(client, saved, info)

    # 3. "Review my weak spots" recalls those mistakes.
    expected = set().union(*(words(m) for m in mistakes))
    deadline = time.monotonic() + 600
    while True:
        found = client.get("/api/weak-spots").json()
        recalled_text = " ".join(found["memories"]).lower()
        if expected & words(recalled_text):
            break
        assert time.monotonic() < deadline, f"mistakes not recalled: {found}"
        time.sleep(20)
    open_now = [s for s in found["weak_spots"] if not s["fixed"]]
    assert len(open_now) > len(open_before), f"weak spots did not grow: {found['weak_spots']}"
    print(f"weak spots after: {len(open_now)} open, recalled in {found['seconds']}s")
    for s in open_now:
        print(f"  - {s['concept']}: {s['confusion']}")

    # 4. The next quiz is built around them.
    evs = events(client, "/api/review", {"count": 4})
    review = one(evs, "quiz")["questions"]
    assert review, "the review quiz is empty"
    targets = {q["target"]["concept"] for q in review}
    open_names = {s["concept"] for s in one(evs, "weak")["weak_spots"] if not s["fixed"]}
    assert targets <= open_names, f"review targets {targets} are not open weak spots {open_names}"
    aimed = [
        q
        for q in review
        if expected & words(q["question"] + " " + q["answer"] + " " + q["target"]["confusion"])
    ]
    assert aimed, f"no review question is about the mistakes {mistakes}: {review}"
    print(f"review quiz: {len(review)} questions, each aimed at a weak spot")
    for q in review:
        print(f"  Q: {q['question']}  -> weak spot: {q['target']['concept']}")

    # 5. Right answers fix them: the list shrinks.
    graded = events(
        client,
        "/api/grade",
        {
            "topic": "Weak spots review",
            "questions": [{**q, "given": q["answer"]} for q in review],
        },
    )
    results = one(graded, "graded")["results"]
    fixed = [r["fixed"] for r in results if r["correct"] and r["fixed"]]
    assert fixed, f"right answers fixed nothing: {results}"
    saved = one(graded, "saved")
    state = wait_learned(client, saved, info)
    deadline = time.monotonic() + 600
    while True:
        after = client.get("/api/weak-spots").json()
        still_open = [s for s in after["weak_spots"] if not s["fixed"]]
        if len(still_open) < len(open_now) and len(still_open) < len(after["weak_spots"]):
            break
        assert time.monotonic() < deadline, (
            f"weak spots were not marked fixed: {after['weak_spots']}"
            + (
                ""
                if state["learned"]
                else f" (the review memory's learning run {state['run_id']} ended {state['run']})"
            )
        )
        time.sleep(20)
    print(
        f"after the review: {len(still_open)} open, "
        f"{len(after['weak_spots']) - len(still_open)} fixed"
    )
    print("OK")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
