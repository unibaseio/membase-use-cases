"""End-to-end check on the local engine: three videos in memory, a shot and a line found.

    uv run 18-video-memory/smoke.py

Adds Elephants Dream and Tears of Steel with seed.py, then the Sintel trailer through the page's
own endpoint, and waits for it. Finds "a little dragon flying toward a hand" (a shot in the
trailer), "the old man says it's not safe here" (a line in Elephants Dream, said by the old man
on screen) and "a giant robot on a bridge" (a shot in Tears of Steel), and checks each video,
moment and speaker. Fetches a video by range as the player does, then removes Tears of Steel and
checks that it is no longer found. Exits non-zero with the reason on any failure.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# A fresh local store, so the check never passes on yesterday's data.
os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-18-"))
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402


def find(client: TestClient, q: str) -> list[dict]:
    r = client.post("/api/find", json={"q": q})
    assert r.status_code == 200, r.text
    out = r.json()
    print(f"  {q!r} ({out['seconds']}s)")
    for res in out["results"]:
        for m in res["moments"]:
            who = f" [{m['speaker']}]" if m["speaker"] else ""
            print(f"     {res['title']:<18} {m['kind']:<4} {m['t']:7.1f}s{who} {m['text'][:80]}")
    return out["results"]


def main() -> None:
    subprocess.run([sys.executable, str(HERE / "seed.py")], check=True, env=os.environ)
    import app as demo  # noqa: PLC0415 - after the store is chosen

    client = TestClient(demo.app)
    assert client.get("/").status_code == 200, "page did not load"
    print("base:", client.get("/api/info").json()["mode"])
    m = client.get("/api/memory").json()
    assert sorted(v["key"] for v in m["videos"]) == ["elephants-dream", "tears-of-steel"], m
    assert [w["key"] for w in m["waiting"]] == ["sintel-trailer"], m["waiting"]

    started = time.monotonic()
    r = client.post("/api/samples/sintel-trailer")
    assert r.status_code == 200, r.text
    while True:
        m = client.get("/api/memory").json()
        assert not [j for j in m["jobs"] if j["status"] == "error"], m["jobs"]
        if any(v["key"] == "sintel-trailer" for v in m["videos"]):
            break
        assert time.monotonic() - started < 300, "the trailer was not added in 5 minutes"
        time.sleep(2)
    for v in m["videos"]:
        print(
            f"  {v['title']:<18} {v['duration']:6.0f}s  {len(v['shots']):3d} shots  "
            f"{len(v['lines']):2d} lines  {v['speakers']}"
        )
        assert len(v["shots"]) >= 10 and v["url"] and v["poster"], v["title"]
        assert all(s["end"] and s["end"] > s["t"] for s in v["shots"]), v["title"]
    print(f"  the trailer was added in {time.monotonic() - started:.0f}s; totals {m['totals']}")
    assert not m["waiting"], m["waiting"]

    dragon = find(client, "a little dragon flying toward a hand")
    assert dragon and dragon[0]["title"] == "Sintel (trailer)", dragon
    shot = dragon[0]["moments"][0]
    assert shot["kind"] == "seen" and re.search(r"dragon", shot["text"], re.I), shot
    assert 30 <= shot["t"] <= 37, f"the dragon and the hand are at 0:32-0:36, not {shot['t']}"
    assert not shot["text"].lower().startswith("the image"), shot["text"]

    line = find(client, "the old man says it's not safe here")
    assert line and line[0]["title"] == "Elephants Dream", line
    said = line[0]["moments"][0]
    assert said["kind"] == "said" and "not safe" in said["text"].lower(), said
    assert 45 <= said["t"] <= 65, f"the line is at about 0:57, not {said['t']}"
    assert said["speaker"] and re.search(r"\b(old|older|elderly|bald)\b", said["speaker"]), said

    robot = find(client, "a giant robot on a bridge")
    assert robot and robot[0]["title"] == "Tears of Steel", robot
    assert re.search(r"robot", robot[0]["moments"][0]["text"], re.I), robot

    ed = next(v for v in m["videos"] if v["id"] == line[0]["id"])
    r = client.get(ed["url"], headers={"Range": "bytes=0-1023"})
    assert r.status_code == 206 and len(r.content) == 1024, (r.status_code, len(r.content))
    assert client.get(said["thumb"]).status_code == 200, said["thumb"]
    assert client.get("/files/../../../etc/passwd").status_code == 404

    tears = robot[0]["id"]
    assert client.delete(f"/api/videos/{tears}").status_code == 200
    assert not [r for r in find(client, "a giant robot on a bridge") if r["id"] == tears], (
        "a removed video was found"
    )
    m = client.get("/api/memory").json()
    assert [w["key"] for w in m["waiting"]] == ["tears-of-steel"], m["waiting"]
    print("  removed Tears of Steel: no longer found, and back among the videos to add")
    print("OK")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
