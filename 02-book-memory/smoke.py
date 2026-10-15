"""End-to-end check against the real API: two stories of Doorways in Drumorty in, two questions
the model alone gets wrong, and answers with memory that are right and cite the passage.

    uv run 02-book-memory/smoke.py            # on the demo's base (MEMBASE_DEMO_MODE to switch)

Writes to its own data directory (local) or the configured account (hosted). Exits non-zero
with the reason on any failure.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if os.environ.get("MEMBASE_DEMO_MODE", "") != "hosted":
    # A fresh local store, so the check never passes on yesterday's data.
    os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-02-"))
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402


def ask(client: TestClient, question: str) -> tuple[dict, str, str]:
    events = []
    with client.stream("POST", "/api/ask", json={"question": question}) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    errors = [e for e in events if e["type"] == "error"]
    assert not errors, errors
    found = next(e for e in events if e["type"] == "passages")
    side = lambda s: "".join(e["text"] for e in events if e["type"] == "delta" and e["side"] == s)  # noqa: E731
    return found, side("with"), side("without")


def main() -> None:
    # load.py waits for each hosted learning run and exits non-zero unless both stories are
    # learned under their titles and the first question recalls its passage
    subprocess.run(
        [sys.executable, str(HERE / "load.py"), "--stories", "2"], check=True, env=os.environ
    )
    import app as demo  # noqa: PLC0415 - after the store is chosen

    client = TestClient(demo.app)
    info = client.get("/api/info").json()
    print("base:", info["mode"])
    assert client.get("/").status_code == 200, "page did not load"
    book = client.get("/api/book").json()
    held = [s for s in book["stories"] if s["in_memory"]]
    titles = [s["title"] for s in held]
    assert {"The Corp’", "Silk Both Sides"} <= set(titles), f"stories missing: {titles}"
    assert all(s["learned"] for s in held), held
    # the reader's pages: every story of the book, with its text
    text = {s["title"]: s["paras"] for s in book["stories"]}
    assert len(text) == 6 and all(text.values()), "the book's text is missing"

    for q in (book["questions"][0], book["questions"][3]):
        found, with_memory, without = ask(client, q["q"])
        passages = found["passages"]
        print(f"\n{q['q']}\n  recalled {len(passages)} passages in {found['seconds']}s")
        print("  with memory:", with_memory)
        print("  without:    ", without)
        assert passages, f"memory returned nothing: {found}"
        assert any(re.search(q["expect"], p["text"], re.I) for p in passages), (
            f"no recalled passage holds the answer: {passages}"
        )
        assert any(p["story"] == q["story"] for p in passages), (
            f"no passage is labelled {q['story']!r}: {[p['story'] for p in passages]}"
        )
        # the page marks the line of the book that a recalled passage points at
        lines = [
            text[p["spot"]["story"]][p["spot"]["para"]][p["spot"]["start"] : p["spot"]["end"]]
            for p in passages
            if p["spot"]
        ]
        print("  marked:", lines)
        assert any(re.search(q["expect"], line, re.I) for line in lines), (
            f"no marked line holds the answer: {lines}"
        )
        assert re.search(q["expect"], with_memory, re.I), (
            f"answer missed the passage: {with_memory!r}"
        )
        cited = {int(n) for n in re.findall(r"\[(\d+)\]", with_memory)}
        assert cited & {p["n"] for p in passages}, f"the answer cites no passage: {with_memory!r}"
        # the demo's premise: the model has not read this book
        assert not re.search(q["expect"], without, re.I), f"the model alone knew it: {without!r}"
    print("OK")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
