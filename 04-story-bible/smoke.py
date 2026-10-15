"""End-to-end check against the real API: the bible in, a planted contradiction caught, a
continuation that uses a bible-only detail, and an accepted scene that becomes canon.

    DEMO_ENV_FILE=.secrets/04-story-bible.env uv run 04-story-bible/smoke.py

Writes to the configured hosted account. Exits non-zero with the reason on any failure.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402

# Ilse never drinks wine, and her compass never points north: both are in the bible only.
PLANTED = (
    "Ilse pours herself a glass of red wine and sits at the map table.\n\n"
    "She takes out Corin's compass. The needle swings and settles, as it always does, on north."
)
OPENING = (
    "The second tide-bell rings while Ilse is still on the Lantern Stair.\n\n"
    'Pell is ten steps ahead of her, then eleven. "Now means now," Pell says.'
)
# Details a continuation can only have from the bible, none of them in OPENING.
BIBLE_ONLY = [
    "low hour",
    "third bell",
    "spine chapel",
    "compass",
    "corin",
    "kelp",
    "oilskin",
    "leviathan",
    "rib bridge",
    "odile",
    "abbess",
    "backwards",
    "four hundred",
    "tobiah",
    "gullet",
]


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


def wait_learned(client: TestClient, minutes: int = 20) -> list[dict]:
    deadline = time.monotonic() + minutes * 60
    while True:
        docs = client.get("/api/canon").json()["documents"]
        if docs and all(
            d["learned"] or d["learning"] not in ("queued", "running", "waiting") for d in docs
        ):
            stuck = [d for d in docs if not d["learned"]]
            if stuck:
                print("WARNING: learning ended without these counting as learned:", stuck)
            return docs
        assert time.monotonic() < deadline, f"not learned after {minutes} minutes: {docs}"
        time.sleep(20)


def main() -> None:
    subprocess.run([sys.executable, str(HERE / "seed.py")], check=True, env=os.environ)
    import app as demo  # noqa: PLC0415

    client = TestClient(demo.app)
    info = client.get("/api/info").json()
    print("base:", info["mode"])
    assert client.get("/").status_code == 200, "page did not load"
    started = time.monotonic()
    docs = wait_learned(client)
    print(f"bible learned: {len(docs)} documents ({time.monotonic() - started:.0f}s)")

    # 1. The planted contradiction is caught, and the catch cites a recalled passage.
    out = events(client, "/api/check", {"text": PLANTED})
    memories = next(e for e in out if e["type"] == "memories")
    issues = next(e for e in out if e["type"] == "issues")["issues"]
    print(
        f"check: {len(memories['hits'])} passages in {memories['seconds']}s, {len(issues)} issues"
    )
    for i in issues:
        print(f"  - {i['quote']!r}: {i['problem']} {i['passages']}")
    compass = [i for i in issues if "north" in (i["quote"] + i["problem"]).lower()]
    assert compass, f"the compass contradiction was not flagged: {issues}"
    assert all(1 <= n <= len(memories["hits"]) for i in issues for n in i["passages"])

    # 2. A continuation uses a detail only the bible has.
    out = events(client, "/api/continue", {"text": OPENING})
    text = "".join(e["text"] for e in out if e["type"] == "delta")
    used = [w for w in BIBLE_ONLY if w in text.lower()]
    print("continuation:", text[:400].replace("\n", " "))
    print("bible-only details used:", used)
    assert used, f"continuation used no bible-only detail: {text!r}"

    # 3. An accepted scene becomes canon: written once, learned, then recalled.
    token = uuid.uuid4().hex[:6]
    scene = (
        "At the Gullet, Pell trades nine copper bits for a gold vertebra with a hole bored "
        f"through it, stamped with the mark {token.upper()}. She hangs it on a string around "
        "her neck and will not say who sold it to her."
    )
    first = client.post("/api/accept", json={"text": scene}).json()
    again = client.post("/api/accept", json={"text": scene}).json()
    assert not first.get("already"), first
    assert first.get("id") or first.get("status") == "waiting", first
    assert again.get("already"), f"accepting the same scene twice wrote it twice: {again}"
    print(f"accepted: {first['title']} ({first.get('status')}; second accept: already canon)")
    wait_learned(client)
    recall = demo.mem.recall(
        "What does Pell wear around her neck?", container=demo.CONTAINER, limit=6, wait=60
    )
    joined = " ".join(h.content for h in recall.hits).lower()
    print("recalled:", [h.content[:120] for h in recall.hits])
    assert "vertebra" in joined, f"the accepted scene did not become canon: {joined!r}"
    print("OK")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
