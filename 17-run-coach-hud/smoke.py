"""End-to-end check on the local engine: past runs in, a brief, a coached run, the next brief.

    uv run 17-run-coach-hud/smoke.py

Seeds a fresh data directory with ten runs where every long run faded after km 7, then checks
that the brief puts a cue just before km 7 that names that pattern, that the simulated run
streams metrics and fires cues, that the finished run is written to memory, and that the next
brief recalls today's run. Exits non-zero with the reason on any failure.
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
# A fresh local store, so the check never passes on yesterday's data.
os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-17-"))
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402


def show(b: dict) -> None:
    print(
        f"  headline: {b['headline']}  (target {b['target_pace']}/km, {len(b['recalled'])} runs recalled, {b['seconds']}s)"
    )
    for c in b["cues"]:
        print(f"  cue: {c['text']}  <- {c['because']}")
    for m in b["moments"]:
        at = f"km {m['km']}" if "km" in m else f"HR > {m['hr_above']}"
        print(f"  moment {at}: {m['text']}")


def expected() -> tuple[int, int]:
    """Faded runs over 7 km in seed.py: km 8 on at least 15 s/km slower than km 3-7."""
    from seed import RUNS, m  # noqa: PLC0415

    faded = total = 0
    for _days, _hhmm, _kind, splits, *_ in RUNS:
        s = [m(x) for x in splits.split()]
        if len(s) > 7:
            total += 1
            faded += sum(s[7:]) / len(s[7:]) - sum(s[2:7]) / 5 >= 15
    return faded, total


def stated_counts(b: dict) -> list[tuple[int, int]]:
    """Every "N of (your last) M" the brief's text states, model-written parts included."""
    words = " ".join(
        [b["headline"]]
        + [c["text"] + " " + c["because"] for c in b["cues"]]
        + [m["text"] for m in b["moments"]]
    )
    return [
        (int(a), int(c))
        for a, c in re.findall(r"\b(\d+) of (?:your |the )?(?:last )?(\d+)\b", words)
    ]


def main() -> None:
    subprocess.run([sys.executable, str(HERE / "seed.py")], check=True, env=os.environ)
    import app as demo  # noqa: PLC0415 - after the store is chosen

    client = TestClient(demo.app)
    assert client.get("/").status_code == 200, "page did not load"
    print("base:", client.get("/api/info").json()["mode"])

    r = client.post("/api/brief", json={"distance_km": 10, "kind": "steady run"})
    assert r.status_code == 200, r.text
    first = r.json()
    show(first)
    words = " ".join(
        [first["headline"]]
        + [c["text"] + " " + c["because"] for c in first["cues"]]
        + [m["text"] for m in first["moments"]]
    )
    assert re.search(r"\b(km ?7|7 ?km|kilometre 7|seventh)\b", words, re.I), (
        "the brief missed the fade after km 7"
    )
    assert re.search(r"fade|faded|slow", words, re.I), "the brief missed the fade"
    faded, total = expected()
    print(f"seeded: {faded} of {total} runs over 7 km faded after km 7")
    p = first["pattern"]
    assert (p["faded"], p["of"]) == (faded, total), f"the brief counted {p['faded']} of {p['of']}"
    counted = next((m for m in first["moments"] if m.get("counted")), None)
    assert counted and counted["km"] == 6.5, f"no counted cue at km 6.5: {first['moments']}"
    assert counted["text"].startswith(f"{faded} of your last {total} runs over 7 km faded"), counted
    assert len({u["memory_id"] for u in counted["uses"]}) == total, (
        "the cue does not cite every run"
    )
    wrong = [c for c in stated_counts(first) if c != (faded, total)]
    assert not wrong, f"the brief states counts that are not true: {wrong}"

    events = []
    with client.stream("POST", "/api/run", json={"brief_id": first["id"]}) as resp:
        assert resp.status_code == 200, resp.read()
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    errors = [e for e in events if e["type"] == "error"]
    assert not errors, errors
    ticks = [e for e in events if e["type"] == "tick"]
    cues = [e for e in events if e["type"] == "cue"]
    splits = [e for e in events if e["type"] == "split"]
    saved = next(e for e in events if e["type"] == "saved")["run"]
    print(f"run: {len(ticks)} metric updates, {len(splits)} splits, {len(cues)} cues")
    for c in cues:
        print(f"  at km {c['km']}: {c['text']}")
    print(f"saved: {demo.summary_text(saved)}")
    assert len(ticks) > 50 and len(splits) == 10, (len(ticks), len(splits))
    assert len(cues) >= 2, cues
    fired = [c for c in cues if c.get("counted")]
    assert fired and 6.5 <= fired[0]["km"] < 7, f"the km 6.5 cue did not fire before km 7: {cues}"
    assert saved["memory_ids"], saved

    second = client.post("/api/brief", json={"distance_km": 10, "kind": "steady run"}).json()
    show(second)
    recalled = {h["memory_id"] for h in second["recalled"]}
    assert set(saved["memory_ids"]) & recalled, "the next brief did not recall today's run"
    used = {u["memory_id"] for item in second["cues"] + second["moments"] for u in item["uses"]}
    mentions_today = re.search(
        r"\b(today|this morning|latest|last run|most recent|just now)\b",
        second["headline"] + " ".join(c["because"] for c in second["cues"]),
        re.I,
    )
    assert set(saved["memory_ids"]) & used or mentions_today, (
        "the next brief does not use today's run"
    )
    assert "No fade after km 7" in saved["felt"], saved["felt"]
    p = second["pattern"]
    assert (p["faded"], p["of"], p["latest_faded"]) == (faded, total + 1, False), p
    wrong = [c for c in stated_counts(second) if c not in ((faded, total + 1),)]
    assert not wrong, f"the next brief states counts that are not true: {wrong}"
    for b in (first, second):
        for c in b["cues"]:
            assert not re.search(
                r"\b\d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", c["because"]
            ), f"the model wrote a date into a cue (the app adds them from the cited runs): {c}"
    print("OK")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
