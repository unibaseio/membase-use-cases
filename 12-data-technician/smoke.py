"""End-to-end check on the local engine: held-out accuracy before teaching, a round of the
scientist's corrections ingested as agent memory, held-out accuracy again.

    uv run 12-data-technician/smoke.py              # teach up to 6 corrections
    uv run 12-data-technician/smoke.py --teach 3

Uses a fresh DEMO_DATA_DIR. Asserts that corrected runs produced cases and skills and that the
second evaluation actually retrieved them; prints both accuracies (the change is reported, not
asserted: it is whatever the run measured).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-12-"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from fastapi.testclient import TestClient  # noqa: E402


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


def evaluate(client: TestClient, lab: str) -> dict:
    started = time.monotonic()
    point = next(e for e in events(client, "/api/evaluate", {"lab": lab}) if e["type"] == "point")
    wrong = [f"{r['id']}:{r['truth']}->{r['label']}" for r in point["results"] if not r["ok"]]
    print(
        f"  held-out after {point['corrections']} corrections: {point['correct']}/{point['total']} "
        f"({time.monotonic() - started:.0f}s)  wrong: {', '.join(wrong) or 'none'}"
    )
    return point


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--teach", type=int, default=6, help="stop after this many corrected runs")
    a = p.parse_args()
    import app as demo  # noqa: PLC0415 - after the store is chosen

    client = TestClient(demo.app)
    print("base:", client.get("/api/info").json()["mode"], "| data:", os.environ["DEMO_DATA_DIR"])
    assert client.get("/").status_code == 200, "page did not load"
    lab = client.post("/api/labs/new").json()["lab"]
    train = client.get("/api/windows").json()["train"]

    print("1. baseline")
    before = evaluate(client, lab)

    print("2. teaching")
    taught = 0
    for w in train:
        if taught >= a.teach:
            break
        ev = events(client, "/api/classify", {"lab": lab, "window": w["id"]})
        notes = next(e for e in ev if e["type"] == "notes")
        v = next(e for e in ev if e["type"] == "verdict")
        line = (
            f"  {w['id']} {w['variant']:<16} agent {v['label']!s:<8} truth {v['truth']:<8} "
            f"rounds {v['rounds']} notes {len(notes['skills'])}s/{len(notes['cases'])}c"
        )
        if v["correct"]:
            client.post("/api/accept", json={"lab": lab, "run_id": v["run_id"]}).raise_for_status()
            print(line, " right")
            continue
        reason = w["rule"] or f"It is {w['truth']}."
        ev = events(
            client,
            "/api/correct",
            {"lab": lab, "run_id": v["run_id"], "label": w["truth"], "reason": reason},
        )
        done = next(e for e in ev if e["type"] == "ingested")
        print(
            line,
            f" corrected -> {done['status']}, cases {done['cases']}, skills +{done['skills_added']}"
            f"/~{done['skills_updated']} ({done['seconds']}s)"
            + (f" skipped {done['skipped']}" if done["skipped"] else "")
            + (f" failed {done['failed']}" if done["failed"] else ""),
        )
        taught += 1 if done["cases"] else 0

    state = client.get(f"/api/lab?lab={lab}").json()
    cases = sum(r["cases"] or 0 for r in state["ingested"])
    print(f"  ingested runs {len(state['ingested'])}, cases {cases}, skills {len(state['skills'])}")
    for s in state["skills"]:
        print(f"   skill {s['name']}: {s['description'][:120]}")
    assert cases > 0, "no corrected run became a case"
    assert state["skills"], "no skills were produced"

    print("3. after teaching")
    after = evaluate(client, lab)
    retrieved = [r for r in after["results"] if r["skills_used"] or r["cases_used"]]
    assert len(retrieved) == after["total"], (
        "the second evaluation did not retrieve the lab's notes"
    )
    print(
        f"held-out accuracy: {before['correct']}/{before['total']} before, "
        f"{after['correct']}/{after['total']} after {after['corrections']} corrections"
    )
    print("OK")


if __name__ == "__main__":
    main()
