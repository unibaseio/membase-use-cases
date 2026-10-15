"""End-to-end check on the local engine: a synthetic day of audio in, two questions answered.

    uv run 16-wearable-diary/smoke.py

Makes (or copies from data/16-wearable-diary/seed-audio) the seeded day's audio, uploads each
clip through the page's own endpoint with its time, waits until each is transcribed, split into
turns and remembered, reads the day's diary, then asks "What did I promise Sam?" and "What time
is the design review?" (moved later in the day) and checks each answer, the clip it cites and
the line of that clip it plays from. Exits non-zero with the reason on any failure.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
KNOWN_AUDIO = HERE.parent / "data" / "16-wearable-diary" / "seed-audio"
# A fresh local store, so the check never passes on yesterday's data.
os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-16-"))
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402


def ask(client: TestClient, question: str) -> dict:
    r = client.post("/api/ask", json={"question": question})
    assert r.status_code == 200, r.text
    out = r.json()
    print(
        f"  Q: {question}\n  A: {out['answer']} {out['change']}  ({out['seconds']}s, {len(out['recalled'])} recalled)"
    )
    for c in out["cited"]:
        m = c["moment"] or {}
        print(
            f"     cites {c['when'][11:]} {c['title']}{' (changed it)' if c['changed_it'] else ''}"
            f", plays from {m.get('start')}s: {m.get('text')!r}"
        )
    return out


def main() -> None:
    subprocess.run(
        [sys.executable, str(HERE / "seed.py"), "--audio-only", "--reuse", str(KNOWN_AUDIO)],
        check=True,
        env=os.environ,
    )
    import app as demo  # noqa: PLC0415 - after the store is chosen
    from seed import AUDIO  # noqa: PLC0415

    manifest = json.loads((AUDIO / "manifest.json").read_text())
    client = TestClient(demo.app)
    assert client.get("/").status_code == 200, "page did not load"
    print("base:", client.get("/api/info").json()["mode"])
    today = datetime.now().date().isoformat()
    started = time.monotonic()
    for m in manifest:
        path = Path(m["file"])
        r = client.post(
            "/api/clips",
            files={"audio": (path.name, path.read_bytes(), "audio/wav")},
            data={"when": f"{today}T{m['time']}"},
        )
        assert r.status_code == 200, r.text
    while True:
        day = client.get("/api/clips").json()
        statuses = [c["status"] for c in day["clips"]]
        assert "error" not in statuses, [c.get("error") for c in day["clips"]]
        if statuses and all(s == "saved" for s in statuses):
            break
        assert time.monotonic() - started < 300, f"clips not processed in 5 minutes: {statuses}"
        time.sleep(2)
    print(
        f"{len(day['clips'])} clips transcribed, split and remembered in {time.monotonic() - started:.0f}s"
    )
    by_time = {c["when"][11:]: c for c in day["clips"]}
    for c in day["clips"]:
        print(
            f"  {c['when'][11:]}  {c['title']:<34} {', '.join(c['speakers']):<28} {c['summary'][:70]}"
        )
    assert len(day["clips"]) == len(manifest), day
    assert any("Sam" in s for s in by_time["17:15"]["speakers"]), by_time["17:15"]["speakers"]
    for c in day["clips"]:
        assert "Me" in c["speakers"] and "Alex" not in c["speakers"], (
            f"the wearer is not 'Me': {c['speakers']}"
        )

    diary = client.get(f"/api/diary?date={today}").json()
    print(f"  diary: {diary['entry']}")
    assert diary["ready"] and diary["entry"], diary

    out = ask(client, "What did I promise Sam?")
    sam = next((c for c in out["cited"] if c["id"] == by_time["17:15"]["id"]), None)
    assert sam, "did not cite the call with Sam"
    assert "Saturday" in out["answer"], out["answer"]
    assert re.search(r"\b(9|nine)\b", out["answer"], re.I), out["answer"]
    assert re.search(r"promise", sam["moment"]["text"], re.I), (
        f"the Sam clip does not play from the promise: {sam['moment']}"
    )
    assert sam["moment"]["start"] and sam["moment"]["start"] > 5, sam["moment"]

    out = ask(client, "What time is the design review?")
    cited = {c["id"]: c for c in out["cited"]}
    moved = cited.get(by_time["15:10"]["id"])
    assert moved, "did not cite the clip that moved it"
    assert moved["changed_it"], "the 15:10 clip is not marked as the one that changed it"
    assert re.search(r"(3|three)[ .:]?(30|thirty)", moved["moment"]["text"], re.I), moved["moment"]
    assert re.search(r"3[:.]30|three[- ]thirty|half past three", out["answer"], re.I), out["answer"]
    assert by_time["09:30"]["id"] in cited, "did not cite the earlier time"
    assert re.search(r"\b3(:00)?\b|three", out["was"], re.I), (
        f"does not say what it was before the later clip: {out['was']!r}"
    )
    assert out["change"].startswith("Priya changed it at 15:10"), out["change"]
    assert all(c["passages"] for c in out["cited"]), "a cited clip has no recalled passage"
    assert "Thursday" in out["answer"], out["answer"]

    lunch = by_time["12:40"]
    r = client.post(f"/api/clips/{lunch['id']}/forget")
    assert r.status_code == 200 and r.json()["memories"] >= 1, r.text
    assert lunch["id"] not in [c["id"] for c in client.get("/api/clips").json()["clips"]]
    gone = demo.recall(demo.mem, "ramen place on Fifth Street", container=demo.CONTAINER)
    assert not set(lunch["memory_ids"]) & {h["memory_id"] for h in gone}, (
        "a forgotten clip was recalled"
    )
    print(f"  forgot the lunch clip: {r.json()['memories']} memories and its audio")
    print("OK")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
