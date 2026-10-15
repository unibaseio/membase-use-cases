"""End-to-end check against the real engine and model: Maya tells Wren about an interview, ends
the session, and the next session opens by following up on it; Theo's Wren knows none of it.

    uv run 08-companion/smoke.py

Uses a fresh local data directory. Exits non-zero with the reason on any failure.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if os.environ.get("MEMBASE_DEMO_MODE", "") != "hosted":
    os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-08-"))
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402


def events(client: TestClient, path: str, body: dict) -> tuple[list[dict], str]:
    out = []
    with client.stream("POST", path, json=body) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    errors = [e for e in out if e["type"] == "error"]
    assert not errors, errors
    return out, "".join(e["text"] for e in out if e["type"] == "delta")


def say(client: TestClient, user: str, history: list[dict], message: str) -> str:
    _, reply = events(client, "/api/chat", {"user": user, "message": message, "history": history})
    history += [{"role": "user", "content": message}, {"role": "assistant", "content": reply}]
    print(f"  {user}: {message}\n  Wren: {reply[:160]}")
    return reply


def main() -> None:
    import app as demo  # noqa: PLC0415 - after the store is chosen

    client = TestClient(demo.app)
    print("base:", client.get("/api/info").json()["mode"])
    assert client.get("/").status_code == 200, "page did not load"

    started = time.monotonic()
    _, first = events(client, "/api/open", {"user": "maya"})
    print("first opener (no memory yet):", first[:160])

    history = [{"role": "assistant", "content": first}]
    say(
        client,
        "maya",
        history,
        "Hi Wren, I'm Maya. I'm a product designer and I live with my cat, Miso.",
    )
    say(
        client,
        "maya",
        history,
        (
            "Big news: I have a job interview at Brightwater Studio on Thursday. I'm nervous about "
            "the portfolio review."
        ),
    )
    end = client.post("/api/end", json={"user": "maya", "history": history}).json()
    print("open loops:", end["loops"])
    assert any("brightwater" in loop.lower() for loop in end["loops"]), f"no interview loop: {end}"

    out, opener = events(client, "/api/open", {"user": "maya"})
    recalled = next(e for e in out if e["type"] == "memories")
    print(
        f"maya's new session (recalled {len(recalled['hits'])} memories, "
        f"{len(recalled['facts'])} facts):"
    )
    print("  Wren:", opener)
    assert any("Brightwater" in h["content"] for h in recalled["hits"]), (
        f"follow-up not recalled: {recalled}"
    )
    jotted = [h["jot"]["text"] for h in recalled["hits"] if h.get("jot")]
    assert any(j in end["loops"] for j in jotted), (
        f"the recalled follow-up does not map back to the line Wren wrote: {recalled}"
    )
    print("recalled, as Wren wrote it:", jotted)
    assert "brightwater" in opener.lower() or "interview" in opener.lower(), (
        "opener missed the interview"
    )
    maya = client.get("/api/memory", params={"user": "maya"}).json()
    print("maya's profile:", maya["facts"])
    assert any("miso" in f.lower() for f in maya["facts"]), f"profile missed the cat: {maya}"

    out, theo_opener = events(client, "/api/open", {"user": "theo"})
    theo_recalled = next(e for e in out if e["type"] == "memories")
    print("theo's first session:\n  Wren:", theo_opener)
    assert not theo_recalled["hits"] and not theo_recalled["facts"], (
        f"theo saw memory: {theo_recalled}"
    )
    history = [{"role": "assistant", "content": theo_opener}]
    reply = say(
        client, "theo", history, "Do you remember anything about my job interview or my cat?"
    )
    theo = client.get("/api/memory", params={"user": "theo"}).json()
    for word in ("brightwater", "miso"):
        assert word not in reply.lower(), f"theo's Wren knows {word!r}: {reply}"
    assert theo["directory"] != maya["directory"], "both people share one directory"
    assert "Follow-ups" not in theo["containers"], f"theo has maya's follow-ups: {theo}"
    print(f"directories: {maya['directory']}  vs  {theo['directory']}")
    print(f"done in {time.monotonic() - started:.0f}s")
    print("OK")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
