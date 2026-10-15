"""End-to-end check on the local engine: the six sample screenshots are read and remembered
(dated when they were taken), two questions are answered from the right screenshots, which open
with the answer's place marked, and a corrected how-to run becomes a procedure that a later
similar task retrieves.

    uv run 13-screen-memory/smoke.py

Uses a fresh DEMO_DATA_DIR. If samples/ is missing it renders them first with seed.py, which
needs a Python that has Playwright (SEED_PYTHON, default ~/miniconda3/bin/python).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-13-"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from fastapi.testclient import TestClient  # noqa: E402

QUESTIONS = [
    # question, a phrase the answer must contain, the screenshot it must cite
    ("What was my flight number?", ["SL 482", "SL482"], "flight-confirmation.png"),
    ("How did I fix the VPN error last time?", ["WireGuard"], "vpn-settings.png"),
]


def sse(client: TestClient, path: str, body: dict) -> list[dict]:
    events = []
    with client.stream("POST", path, json=body) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    errors = [e for e in events if e["type"] == "error"]
    assert not errors, errors
    return events


def ask(client: TestClient, question: str) -> tuple[str, dict, list[str]]:
    events = sse(client, "/api/ask", {"question": question})
    errors = [e for e in events if e["type"] == "error"]
    assert not errors, errors
    answer = "".join(e["text"] for e in events if e["type"] == "delta")
    memories = next(e for e in events if e["type"] == "memories")
    return answer, memories, next(e for e in events if e["type"] == "done")


def main() -> None:
    if not (HERE / "samples" / "samples.json").is_file():
        seed_python = os.environ.get("SEED_PYTHON") or str(Path.home() / "miniconda3/bin/python")
        subprocess.run([seed_python, str(HERE / "seed.py")], check=True)
    import app as demo  # noqa: PLC0415 - after the store is chosen

    client = TestClient(demo.app)
    print("base:", client.get("/api/info").json()["mode"], "| data:", os.environ["DEMO_DATA_DIR"])
    assert client.get("/").status_code == 200, "page did not load"

    for s in client.get("/api/samples").json()["samples"]:
        started = time.monotonic()
        events = sse(client, "/api/samples/add", {"file": s["file"]})
        assert [e["type"] for e in events] == ["read", "remembered"], events
        rec = events[-1]["screen"]
        a = rec["analysis"]
        print(
            f"  {rec['id']} {s['file']:<26} {a.get('app', '')!s:<22} "
            f"{len(a.get('key_values') or {})} values, "
            f"{len(rec['memory_ids'])} memories ({time.monotonic() - started:.0f}s)"
        )
        assert rec["memory_ids"], f"{s['file']}: the write returned no memory id"
    ids = {s["file"]: s["id"] for s in client.get("/api/screens").json()["screens"]}
    dup = client.post("/api/samples/add", json={"file": "vpn-error.png"})
    assert dup.status_code == 409, f"a sample was accepted twice: {dup.status_code}"

    for question, phrases, source in QUESTIONS:
        answer, memories, done = ask(client, question)
        cited = done["cited"]
        shown = [f"{h['screen']}:{h['content'][:70]}" for h in memories["hits"][:3]]
        print(
            f"Q: {question}\n  recalled ({memories['seconds']}s): {shown}\n  A: {answer}\n  "
            f"cited: {cited}"
        )
        assert any(p.lower() in answer.lower() for p in phrases), f"answer lacks {phrases}"
        assert ids[source] in cited, f"answer did not cite {ids[source]} ({source})"
        # the page opens that screenshot and marks where the answer is on it (its text layer)
        assert done["open"] == ids[source], f"opened {done['open']}, not {ids[source]}"
        marks = (done["regions"].get(ids[source]) or {}).get("boxes")
        assert marks, f"nothing marked on {source} for {answer!r}"
        print(f"  opened {done['open']}, marked {len(marks)} place(s)")
        # the memory is dated when the screenshot was taken, not when it was added
        taken = next(x for x in demo.load() if x["id"] == ids[source])["captured_at"]
        hit = next(h for h in memories["hits"] if h["screen"] == ids[source])
        assert hit["date"].startswith(taken[:16]), f"{source} recalled with date {hit['date']}"

    # Redo a task: the agent works it out across screens, the user pushes back, the run is saved
    # as agent memory, and a later similar task starts from that procedure.
    first, ev = howto(
        client, "My VPN won't connect again. Walk me through what I did last time to fix it."
    )
    print(f"how-to run: {ev['done']['rounds']} tool rounds, opened {ev['opened']}")
    _, ev = howto(
        client,
        "That did not work: I'm on a cafe network and WireGuard still won't connect. What else "
        "did I set up?",
        session=first,
    )
    print(f"  after the follow-up: {ev['done']['rounds']} tool rounds\n  A: {ev['answer'][:240]}")
    saved = client.post("/api/howto/save", json={"session": first}).json()
    print(
        f"  saved: {saved['status']}, cases {saved['cases']}, skills +{saved['skills_added']}, "
        f"skipped {saved['skipped']}"
    )
    assert saved["cases"], f"the run did not become a case: {saved['skipped']}"
    _, ev = howto(
        client, "VPN says the handshake timed out at the airport lounge. How do I get it working?"
    )
    used = ev["procedures"]
    print(
        f"  later task retrieved {len(used['skills'])} procedure(s), {len(used['cases'])} past "
        f"run(s): "
        f"{[k['name'] for k in used['skills']]}"
    )
    assert used["cases"] or used["skills"], "the later task retrieved no procedure"
    print("OK")


def howto(client: TestClient, message: str, session: str | None = None) -> tuple[str, dict]:
    events = []
    body = {"message": message, **({"session": session} if session else {})}
    with client.stream("POST", "/api/howto", json=body) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    errors = [e for e in events if e["type"] == "error"]
    assert not errors, errors
    sid = next(e for e in events if e["type"] == "session")["session"]
    return sid, {
        "done": next(e for e in events if e["type"] == "done"),
        "answer": next(e for e in reversed(events) if e["type"] == "answer")["text"],
        "opened": [
            e["args"].get("id")
            for e in events
            if e["type"] == "tool_call" and e["name"] == "open_screen"
        ],
        "procedures": next((e for e in events if e["type"] == "procedures"), {}),
    }


if __name__ == "__main__":
    main()
