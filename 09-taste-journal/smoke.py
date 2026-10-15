"""End-to-end check against the real engine and model: seed a fresh journal, log tonight's wine,
then ask for a red for Friday dinner and for the palate. Every citation must be a tasting memory
recalled for that question, the new wine must be in memory with its date, and the answer must
cite a tasting Sam loved and one Sam disliked.

    uv run 09-taste-journal/smoke.py

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
os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-09-"))
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402


def ask(client: TestClient, body: dict) -> tuple[list[dict], str, list[int]]:
    out = []
    with client.stream("POST", "/api/ask", json=body) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    errors = [e for e in out if e["type"] == "error"]
    assert not errors, errors
    hits = next(e for e in out if e["type"] == "memories")["hits"]
    text = "".join(e["text"] for e in out if e["type"] == "delta")
    cited = next(e for e in out if e["type"] == "done")["cited"]
    return hits, text, cited


def main() -> None:
    started = time.monotonic()
    subprocess.run([sys.executable, str(HERE / "seed.py")], check=True, env=os.environ)
    print(f"seeded in {time.monotonic() - started:.0f}s")
    import app as demo  # noqa: PLC0415 - after the store is chosen
    import seed  # noqa: PLC0415

    client = TestClient(demo.app)
    print("base:", client.get("/api/info").json()["mode"])
    assert client.get("/").status_code == 200, "page did not load"

    logged = client.post(
        "/api/tastings",
        json={
            "kind": "wine",
            "name": "Etna Rosso",
            "origin": "Mount Etna, Sicily, 2022",
            "notes": "Sour cherry, rose petals, a hint of volcanic smoke. Light and fresh with "
            "fine tannins. Lovely slightly chilled.",
            "rating": 5,
        },
    )
    assert logged.status_code == 200, logged.text
    new = logged.json()["tasting"]
    print("scored the new wine:", new["flavor"])
    assert new["flavor"]["fruit"] >= 4 and new["flavor"]["body"] <= 6, new["flavor"]
    demo.writer.flush()
    journal = client.get("/api/tastings").json()["tastings"]
    assert len(journal) == len(seed.TASTINGS) + 1, f"journal has {len(journal)} tastings"
    mine = next(t for t in journal if t["id"] == new["id"])
    assert mine["in_memory"] and mine["memory_ids"], mine

    hits, text, cited = ask(client, {"kind": "next", "hint": "a red for Friday dinner"})
    print(f"\na red for Friday dinner (recalled {len(hits)} tastings):\n{text}")
    by_n = {h["n"]: h for h in hits}
    assert all(h["tasting"] for h in hits), "a recalled memory is no tasting in the journal"
    assert set(cited) <= set(by_n), f"cites {cited}, recalled {sorted(by_n)}"
    used = [by_n[n] for n in cited]
    print("cites:", [(h["name"], h["rating"]) for h in used])
    new_hit = next((h for h in hits if h["tasting"] == new["id"]), None)
    assert new_hit and new_hit["date"] == new["date"], (
        f"tonight's wine not recalled with its date: {new_hit}"
    )
    assert any(h["rating"] >= 4 for h in used), "cites nothing Sam loved"
    assert any(h["rating"] <= 2 for h in used), "cites nothing Sam disliked"

    hits, text, cited = ask(client, {"kind": "palate"})
    print(f"\nmy palate (recalled {len(hits)} tastings):\n{text}")
    assert len(cited) >= 3, f"the palate cites {cited}"
    print(f"done in {time.monotonic() - started:.0f}s")
    print("OK")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
