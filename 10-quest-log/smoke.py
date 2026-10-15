"""End-to-end check against the real engine and model: seed three weeks of history, plan the
next Monday with a 7:00 gym session, and check what the app counted against what was seeded
(the gym skipped on each of the last three Mondays, done at 18:30 on every Wednesday and
Friday). The gym quest must move to the evening; nothing else may change. Then close a quest
and check that memory gives it back with its date.

    uv run 10-quest-log/smoke.py

Uses a fresh local data directory. Exits non-zero with the reason on any failure.
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
os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-10-"))
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402

PLAN = (
    "Gym at 7:00 before work, finish the Atlas slide deck, 15-minute inbox sweep at lunch, "
    "call Jun about Saturday, read 20 pages before bed"
)


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


def main() -> None:
    started = time.monotonic()
    subprocess.run([sys.executable, str(HERE / "seed.py")], check=True, env=os.environ)
    print(f"seeded in {time.monotonic() - started:.0f}s")
    import app as demo  # noqa: PLC0415 - after the store is chosen
    import seed  # noqa: PLC0415

    client = TestClient(demo.app)
    assert client.get("/").status_code == 200, "page did not load"
    state = client.get("/api/state").json()
    print("base:", client.get("/api/info").json()["mode"], "· in memory:", state["stats"])
    monday = state["plan_day"]
    want = seed.expected()

    t = time.monotonic()
    out = events(client, "/api/plan", {"date": monday, "plan": PLAN})
    memories = next(e for e in out if e["type"] == "memories")
    ev = next(e for e in out if e["type"] == "evidence")["items"]
    day = next(e for e in out if e["type"] == "quests")
    print(
        f"\nplan for Monday {monday}: {len(memories['hits'])} days recalled, {time.monotonic() - t:.0f}s"
    )
    for e in ev:
        h, w = e["habit"], e["works"]
        print(
            f"  {e['item']!r}: {'ADAPT ' if e['adapt'] else ''}"
            + (
                f"{h['where']} skipped {h['skipped']}/{h['total']} {[r['day'] for r in h['days']]}"
                if h
                else "-"
            )
            + (f"; {w['where']} done {w['done']}/{w['total']}" if w else "")
            + (f" ({e['unverified']} quotes not in their passage)" if e["unverified"] else "")
        )
    for q in day["quests"]:
        print(f"  [{q['slot']:<9}] {q['title']}" + (f"  <- {q['change']}" if q["change"] else ""))

    # every recalled passage is a real, dated memory from before the planned day
    assert all(h["day"] < monday and h["memory_id"] for h in memories["hits"]), memories["hits"]
    flagged = [e for e in ev if e["adapt"]]
    assert len(flagged) == 1 and "gym" in flagged[0]["item"].lower(), f"flagged {flagged}"
    h, w = flagged[0]["habit"], flagged[0]["works"]
    mondays = [(r["day"], r["status"]) for r in h["days"]]
    assert mondays == want["mondays"], f"Monday evidence {mondays}, seeded {want['mondays']}"
    assert h["consecutive"] and h["skipped"] == h["total"] == 3, h
    evenings = [(r["day"], r["status"]) for r in w["days"]] if w else []
    assert evenings == want["evenings"], f"18:30 evidence {evenings}, seeded {want['evenings']}"
    changed = [q for q in day["quests"] if q["change"]]
    assert len(changed) == 1 and changed[0]["slot"] == "evening", f"changed {changed}"
    assert len(day["quests"]) == len(ev), "a plan item became no quest"

    before = client.get("/api/state").json()["stats"]["xp"]
    gym = changed[0]
    after = client.post(
        "/api/quest", json={"date": monday, "id": gym["id"], "status": "done"}
    ).json()
    assert after["stats"]["xp"] == before + gym["xp"], after["stats"]
    demo.writer.flush()
    hits = demo.recall(
        demo.mem, f"gym on {demo.weekday(monday)} {monday}", container=demo.CONTAINER
    )
    dated = [x for x in hits if x["date"].startswith(monday)]
    assert dated, f"the closed quest is not recalled with its date {monday}: {hits[:3]}"
    print(
        f"\nclosed {gym['title']!r}; memory gives it back dated {dated[0]['date']}:"
        f"\n  {dated[0]['content'][:160]}"
    )
    print(f"done in {time.monotonic() - started:.0f}s")
    print("OK")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
