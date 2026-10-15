"""End-to-end check on the local engine: a seeded week, three time questions, one correction.

    uv run 14-care-companion/smoke.py

Seeds a fresh data directory, asks "this morning", "yesterday" and "next" questions and checks
each answer cites the right note, then corrects the doctor's appointment (wrong day) and checks
the same question now gets the corrected day. Exits non-zero with the reason on any failure.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
# A fresh local store, so the check never passes on yesterday's data.
os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-14-"))
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402


def ask(client: TestClient, question: str) -> dict:
    r = client.post("/api/ask", json={"question": question})
    assert r.status_code == 200, r.text
    out = r.json()
    print(
        f"  Q: {question}\n  A: {out['answer']}  ({out['seconds']}s, {len(out['recalled'])} recalled)"
    )
    for c in out["cited"]:
        print(f"     cites {c['when']}  {c['text']}")
    return out


def main() -> None:
    subprocess.run([sys.executable, str(HERE / "seed.py")], check=True, env=os.environ)
    import app as demo  # noqa: PLC0415 - after the store is chosen

    client = TestClient(demo.app)
    assert client.get("/").status_code == 200, "page did not load"
    state = client.get("/api/state").json()
    now = datetime.fromisoformat(state["now"])
    assert f"{now:%A}" == "Tuesday", f"the demo clock should be a Tuesday, not {state['now']}"
    entries = state["entries"]
    print(
        f"base: {client.get('/api/info').json()['mode']}; clock {state['now_label']}; {len(entries)} notes"
    )

    def find(day: int, text: str) -> dict:
        date = (now + timedelta(days=day)).date().isoformat()
        return next(e for e in entries if e["when"].startswith(date) and text in e["text"])

    pills_today = find(0, "Morning pills")
    anna = find(-1, "Anna")
    appt = find(2, "Dr. Reyes")

    out = ask(client, "Did I take my pills this morning?")
    assert pills_today["id"] in [c["id"] for c in out["cited"]], "did not cite this morning's pills"
    assert re.search(r"\b(yes|you did|you took)\b", out["answer"], re.I), out["answer"]

    out = ask(client, "Who came to see me yesterday?")
    assert anna["id"] in [c["id"] for c in out["cited"]], "did not cite yesterday's visit"
    assert "Anna" in out["answer"], out["answer"]
    for other in ("Leo", "Okafor", "Tom"):
        assert other not in out["answer"], f"named {other}, who did not come yesterday"

    question = "When is my next doctor visit?"
    before = ask(client, question)
    old_day, new_day = now + timedelta(days=2), now + timedelta(days=3)
    assert appt["id"] in [c["id"] for c in before["cited"]], "did not cite the booked follow-up"
    assert f"{old_day:%A}" in before["answer"], before["answer"]

    # The caregiver finds the appointment was booked for the wrong day.
    fixed_text = (
        f"Follow-up with Dr. Reyes at the Elm Street surgery on {new_day:%A} {new_day.day} "
        f"{new_day:%B}, at 14:00 (the surgery moved it). Anna will drive."
    )
    fixed_when = new_day.replace(hour=14, minute=0).isoformat(timespec="minutes")
    r = client.post(
        f"/api/entries/{appt['id']}/correct",
        json={"kind": "appointment", "text": fixed_text, "when": fixed_when},
    )
    assert r.status_code == 200, r.text
    fixed = r.json()
    started = time.monotonic()
    while True:
        by_id = {e["id"]: e for e in client.get("/api/state").json()["entries"]}
        if by_id[appt["id"]]["status"] == "replaced" and by_id[fixed["id"]]["status"] == "saved":
            break
        assert "error" not in (by_id[appt["id"]]["status"], by_id[fixed["id"]]["status"]), by_id
        assert time.monotonic() - started < 120, "correction did not finish in 2 minutes"
        time.sleep(1)
    print(
        f"  corrected in {time.monotonic() - started:.1f}s: old memory forgotten, new one written"
    )

    after = ask(client, question)
    gone = {e["id"]: e for e in client.get("/api/state").json()["entries"]}[appt["id"]]
    assert gone["forgotten"] == appt["memory_ids"], gone
    returned = {h["memory_id"] for h in after["recalled"]}
    assert not returned & set(gone["forgotten"]), "recall still returns the forgotten memory"
    cited = [c["id"] for c in after["cited"]]
    assert fixed["id"] in cited and appt["id"] not in cited, (
        f"answer still cites the old note: {cited}"
    )
    assert f"{new_day:%A}" in after["answer"], after["answer"]
    assert f"{old_day:%A}" not in after["answer"], f"still says {old_day:%A}: {after['answer']}"
    print(f"before: {before['answer']}\nafter:  {after['answer']}")
    print("OK")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
