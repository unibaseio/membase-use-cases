"""End-to-end check on the local engine: synthetic records in, suggested matches out, scored.

    uv run 15-reunite/smoke.py

Seeds a fresh data directory (ten families, ten seekers, three true pairs whose details are
paraphrased, never copied), then reports where each true family ranks among the suggestions
for its seeker: after recall alone, and after the side-by-side comparison. Fails unless every
true pair ranks in the top three, or the fire engine and the fire truck are not paired for S-01
and F-01. Records one review decision through the API.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# A fresh local store, so the check never passes on yesterday's data.
os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-15-"))
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402


def main() -> None:
    subprocess.run([sys.executable, str(HERE / "seed.py")], check=True, env=os.environ)
    import app as demo  # noqa: PLC0415 - after the store is chosen
    from seed import TRUE_PAIRS  # noqa: PLC0415

    client = TestClient(demo.app)
    assert client.get("/").status_code == 200, "page did not load"
    queue = client.get("/api/queue").json()
    print(
        f"base: {client.get('/api/info').json()['mode']}; {queue['families']} families, "
        f"{len(queue['seekers'])} seekers"
    )
    assert all(s["match_status"] == "ready" for s in queue["seekers"]), queue["seekers"]

    hits = {"recall": [0, 0], "compared": [0, 0]}
    for seeker_id, family_id in TRUE_PAIRS.items():
        detail = client.get(f"/api/seekers/{seeker_id}").json()
        ranked = [c["family_id"] for c in detail["candidates"]]
        recall_rank = next(
            (c["recall_rank"] for c in detail["candidates"] if c["family_id"] == family_id), None
        )
        rank = ranked.index(family_id) + 1 if family_id in ranked else None
        true = next((c for c in detail["candidates"] if c["family_id"] == family_id), None)
        for key, r in (("recall", recall_rank), ("compared", rank)):
            hits[key][0] += r == 1
            hits[key][1] += r is not None and r <= 3
        print(
            f"  {seeker_id} -> {family_id}: recall rank {recall_rank}, compared rank {rank}, "
            f"score {true and true['score']}; ranking {[(c['family_id'], c['score']) for c in detail['candidates']]}"
        )
        if true:
            for o in true["overlaps"][:3]:
                print(f"      overlap: {o.get('seeker')!r} ~ {o.get('family')!r}")
            for o in true["conflicts"][:2]:
                print(f"      conflict: {o.get('seeker')!r} vs {o.get('family')!r}")
    n = len(TRUE_PAIRS)
    for key, (top1, top3) in hits.items():
        print(f"{key:>9}: top-1 {top1}/{n} ({top1 / n:.0%}), top-3 {top3}/{n} ({top3 / n:.0%})")

    others = [s for s in queue["seekers"] if s["id"] not in TRUE_PAIRS]
    best = sorted(
        ((s["top"] or {}).get("score", 0), s["id"], (s["top"] or {}).get("family_id"))
        for s in others
    )
    print(
        "seekers with no true family, best suggestion:",
        ", ".join(f"{sid}->{fid} {sc}" for sc, sid, fid in best),
    )
    true_scores = [
        c["score"]
        for sid, fid in TRUE_PAIRS.items()
        for c in client.get(f"/api/seekers/{sid}").json()["candidates"]
        if c["family_id"] == fid
    ]
    print(
        f"true-pair scores {true_scores}; highest score for a seeker with no true family {best[-1][0]}"
    )

    assert hits["compared"][1] == n, "a true pair is not in the top three after comparison"

    s01 = client.get("/api/seekers/S-01").json()
    f01 = next(c for c in s01["candidates"] if c["family_id"] == "F-01")
    assert any(
        "fire engine" in o.get("seeker", "") and "fire truck" in o.get("family", "")
        for o in f01["overlaps"]
    ), f"the fire engine and the fire truck are not paired: {f01['overlaps']}"
    assert f01["passages"] and all(x["text"] for x in f01["passages"]), "no recalled passage kept"
    print(
        f"  S-01/F-01: fire engine ~ fire truck paired; {len(f01['passages'])} recalled passages kept"
    )

    r = client.post(
        "/api/reviews",
        json={
            "seeker_id": "S-01",
            "family_id": "F-01",
            "decision": "match",
            "note": "scar, toy and song all agree",
        },
    )
    assert r.status_code == 200, r.text
    decided = next(s for s in client.get("/api/queue").json()["seekers"] if s["id"] == "S-01")[
        "decided"
    ]
    assert decided == {"F-01": "match"}, decided
    print("OK")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
