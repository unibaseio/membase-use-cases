"""End-to-end check against the real API: the whole team run, through the app.

    uv run scripts/bootstrap_hosted.py --name 05-agent-team --containers Team --read-key
    DEMO_ENV_FILE=.secrets/05-agent-team.env uv run 05-agent-team/smoke.py

Asserts: the Investigator's finding was written; the Fixer's memory search returned it; the
Reviewer gave a verdict; the Auditor's search worked and its write was refused with a 403.
Exits non-zero with the reason on any failure.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import app as demo  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def states_cause(text: str) -> bool:
    """Whether a passage states the root cause: the refill measures elapsed time from the
    bucket's creation instead of from the last refill."""
    t = text.lower()
    return ("refill" in t or "elapsed" in t) and any(
        w in t for w in ("created", "creation", "updated_at", "last refill")
    )


def main() -> None:
    client = TestClient(demo.app)
    assert client.get("/").status_code == 200, "page did not load"
    print("base:", client.get("/api/info").json()["mode"])
    started = time.monotonic()
    events: list[dict] = []
    with client.stream("POST", "/api/run", json={}) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            events.append(ev)
            show(ev)
    errors = [e for e in events if e["type"] == "error"]
    assert not errors, errors
    done = next((e for e in events if e["type"] == "done"), None)
    assert done, "the run did not finish"

    tools = [e for e in events if e["type"] == "tool"]
    by = lambda role, name: [e for e in tools if e["role"] == role and e["name"] == name]  # noqa: E731

    finding = [e for e in by("Investigator", "add_memory") if e["ok"]]
    assert finding, "the Investigator wrote no finding"
    print(
        f"\nfinding written: {finding[0]['result']['document_id']}: {finding[0]['args']['content'][:400]!r}"
    )
    for e in by("Fixer", "add_memory"):
        print(
            f"fixer's decision: {'written' if e['ok'] else e['error']}: {e['args']['content'][:300]!r}"
        )
    patches = [e for e in by("Fixer", "propose_patch") if e["ok"]]
    print("fixer's patch:\n" + (patches[-1]["result"]["diff"] if patches else "(none)"))
    tests = [e["result"]["summary"] for e in tools if e["name"] == "run_tests" and e["ok"]]
    print(f"test runs: {tests}")
    print(
        f"the finding states the root cause: {states_cause(finding[0]['args']['content'])}; "
        f"the fix makes the tests pass: {bool(patches) and tests[-1:] == ['OK']}"
    )

    searches = [e for e in by("Fixer", "search_memories") if e["ok"]]
    assert searches, "the Fixer never searched memory"
    hits = [h["content"] for e in searches for h in e["result"]["hits"]]
    print("fixer's search returned:\n  - " + "\n  - ".join(h[:220] for h in hits))
    # The finding comes back rephrased by learning: it counts when a passage is attributed to
    # this run's Investigator, or states the root cause.
    run_id = next(e["run"] for e in events if e["type"] == "run")
    found = [h for h in hits if run_id in h or states_cause(h)]
    assert found, f"the Fixer's search did not return this run's finding (run {run_id}): {hits}"
    print(f"fixer's search returned the finding: {found[0][:160]!r}")

    assert done["verdict"], "the Reviewer gave no verdict"
    print(
        f"verdict: {'approved' if done['verdict']['approve'] else 'rejected'}: {done['verdict']['reasons'][:200]}"
    )

    audit_search = [e for e in by("Auditor", "search_memories") if e["ok"]]
    assert audit_search, "the Auditor's search did not work"
    refused = by("Auditor", "add_memory")
    assert refused and refused[0].get("refused") and refused[0]["status"] == 403, (
        f"the Auditor's write was not refused with 403: {refused}"
    )
    print(
        f"auditor search: {len(audit_search[0]['result']['hits'])} hits; "
        f"auditor write refused: HTTP {refused[0]['status']} {json.dumps(refused[0]['body'])}"
    )
    waits = [e for e in events if e["type"] == "wait" and e["learned"]]
    print("learning waits: " + ", ".join(f"{e['role']} {e['seconds']}s" for e in waits))
    print(f"run took {time.monotonic() - started:.0f}s")
    print("OK")


def show(ev: dict) -> None:
    t = ev["type"]
    if t == "tool":
        status = (
            "ok"
            if ev["ok"]
            else f"REFUSED {ev.get('status')}"
            if ev.get("refused")
            else f"error {ev.get('error')}"
        )
        print(f"  {ev['role']:<12} {ev['name']:<16} {ev['seconds']:>6}s  {status}")
    elif t == "wait" and (ev["learned"] or ev["seconds"] % 30 < 5):
        print(
            f"  {'Membase':<12} waiting for {ev['role']}'s memory: {ev['seconds']}s learned={ev['learned']} run={ev['run_status']}"
        )
    elif t == "note":
        print(f"  note: {ev['text']}")
    elif t == "agent" and ev["status"] == "start":
        print(f"{ev['role']}: {ev['task']}")


if __name__ == "__main__":
    main()
