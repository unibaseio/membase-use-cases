"""End-to-end check on the local engine: photos in memory, each found by describing it.

    uv run 19-photo-memory/smoke.py

Adds the Lisbon and Home albums with seed.py, then the Kyoto album through the page's own
endpoint, and waits for it. Finds "rows of orange gates" (Fushimi Inari, just added), "something
sweet we ate" (the pastries and the cake, and nothing else) and "an animal having a nap" (the cat,
not the dog). Fetches a photo as the page does, then removes the cat and checks that it is no
longer found. Exits non-zero with the reason on any failure.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# A fresh local store, so the check never passes on yesterday's data.
os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-19-"))
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402


def find(client: TestClient, q: str) -> list[dict]:
    r = client.post("/api/find", json={"q": q})
    assert r.status_code == 200, r.text
    out = r.json()
    print(f"  {q!r} ({out['seconds']}s)")
    for p in out["results"]:
        print(f"     {p['key']:<16} {p['description'][:90]}")
    return out["results"]


def main() -> None:
    subprocess.run([sys.executable, str(HERE / "seed.py")], check=True, env=os.environ)
    import app as demo  # noqa: PLC0415 - after the store is chosen

    client = TestClient(demo.app)
    assert client.get("/").status_code == 200, "page did not load"
    print("base:", client.get("/api/info").json()["mode"])
    m = client.get("/api/memory").json()
    assert len(m["photos"]) == 10, [p["key"] for p in m["photos"]]
    assert [w["album"] for w in m["waiting"]] == ["kyoto"], m["waiting"]

    started = time.monotonic()
    r = client.post("/api/albums/kyoto")
    assert r.status_code == 200, r.text
    while True:
        m = client.get("/api/memory").json()
        assert not [j for j in m["jobs"] if j["status"] == "error"], m["jobs"]
        if not m["jobs"]:
            break
        assert time.monotonic() - started < 180, "Kyoto was not added in 3 minutes"
        time.sleep(1)
    print(f"  Kyoto added in {time.monotonic() - started:.0f}s")
    assert len(m["photos"]) == 14 and not m["waiting"], m
    for p in m["photos"]:
        assert (
            p["url"] and p["description"] and not p["description"].lower().startswith("the image")
        )

    gates = find(client, "rows of orange gates")
    assert gates and gates[0]["key"] == "kyoto-gates", gates

    sweet = find(client, "something sweet we ate")
    keys = [p["key"] for p in sweet]
    assert set(keys[:2]) == {"lisbon-pastries", "home-cake"}, keys
    assert not set(keys) - {"lisbon-pastries", "home-cake", "kyoto-ramen"}, keys

    nap = find(client, "an animal having a nap")
    assert nap and nap[0]["key"] == "lisbon-cat", nap
    assert "home-dog" not in [p["key"] for p in nap], nap

    assert client.get(nap[0]["url"]).status_code == 200, nap[0]["url"]
    assert client.get("/files/../../../etc/passwd").status_code == 404

    cat = nap[0]["id"]
    assert client.delete(f"/api/photos/{cat}").status_code == 200
    assert cat not in [p["id"] for p in find(client, "an animal having a nap")], (
        "a removed photo was found"
    )
    print("  removed the cat: no longer found")
    print("OK")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
