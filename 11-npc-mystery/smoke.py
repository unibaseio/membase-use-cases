"""End-to-end check on the local engine: tell one character something distinctive, let it gossip
to a second, and check the second knows it (and who told it) while the third does not.

    uv run 11-npc-mystery/smoke.py

Uses a fresh DEMO_DATA_DIR. Exits non-zero with the reason on any failure.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-11-"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from fastapi.testclient import TestClient  # noqa: E402

FACT = "I found a green glass button stamped with an anchor under the harbour office window."


def talk(client: TestClient, player: str, npc: str, message: str) -> tuple[str, list[dict]]:
    events = []
    with client.stream(
        "POST", "/api/talk", json={"player": player, "npc": npc, "message": message}
    ) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    errors = [e for e in events if e["type"] == "error"]
    assert not errors, errors
    reply = "".join(e["text"] for e in events if e["type"] == "delta")
    return reply, events


def main() -> None:
    import app as demo  # noqa: PLC0415 - after the store is chosen

    client = TestClient(demo.app)
    info = client.get("/api/info").json()
    print("base:", info["mode"], "| data:", os.environ["DEMO_DATA_DIR"])
    assert client.get("/").status_code == 200, "page did not load"

    player = client.post("/api/new").json()["player"]
    # Gossip only when time passes (the default), so the third character provably hears nothing.
    state = client.get(f"/api/game?player={player}").json()
    assert state["auto_gossip"] is False, "gossip after every exchange should be off by default"

    started = time.monotonic()
    reply, events = talk(client, player, "mara", FACT + " Keep that between us, Mara.")
    saved = next(e for e in events if e["type"] == "saved")
    print(
        f"Mara: {reply[:160]!r}  (saved in {saved['seconds']}s, "
        f"turn {time.monotonic() - started:.0f}s)"
    )

    # Time passes, as the page's button does: Mara (the only one who heard) tells her confidant.
    g = client.post("/api/gossip", json={"player": player}).json()
    assert g.get("type") == "gossip", f"no gossip happened: {g}"
    assert (g["from"], g["to"]) == ("mara", "elsie"), f"gossip went {g['from']} -> {g['to']}"
    print(f"gossip Mara -> Elsie: {g['what']!r}")
    assert "button" in g["what"].lower(), f"gossip lost the fact: {g['what']!r}"
    counts = client.get(f"/api/game?player={player}").json()["memories"]
    assert counts["elsie"] == {"talks": 0, "gossip": 1}, counts
    assert counts["tobias"] == {"talks": 0, "gossip": 0}, counts

    question = "Have you heard anything about what I found under the harbour office window?"
    elsie, events = talk(client, player, "elsie", question)
    hits = next(e for e in events if e["type"] == "memories")["hits"]
    print(f"Elsie recalled {len(hits)}: {[h['content'][:90] for h in hits]}")
    print(f"Elsie: {elsie!r}")
    assert any("button" in h["content"].lower() and "mara" in h["content"].lower() for h in hits), (
        "Elsie's memory has no gossip from Mara about the button"
    )
    assert "button" in elsie.lower(), "Elsie did not mention the button"
    assert "mara" in elsie.lower(), "Elsie did not say Mara told her"

    tobias, events = talk(client, player, "tobias", question)
    hits = next(e for e in events if e["type"] == "memories")["hits"]
    print(f"Tobias recalled {len(hits)}: {[h['content'][:90] for h in hits]}")
    print(f"Tobias: {tobias!r}")
    assert not any("button" in h["content"].lower() for h in hits), "Tobias's memory has the button"
    assert "anchor" not in tobias.lower() and "button" not in tobias.lower(), (
        "Tobias knows about the button"
    )

    # The culprit stays consistent: what he claimed is in his own memory for next time.
    claim, _ = talk(client, player, "tobias", "Where were you when the lamp went dark?")
    again, events = talk(
        client, player, "tobias", "Remind me: what did you tell me about where you were?"
    )
    hits = next(e for e in events if e["type"] == "memories")["hits"]
    print(f"Tobias first: {claim!r}\nTobias again: {again!r}")
    assert any(
        "lamp" in h["content"].lower() or "lighthouse" in h["content"].lower() for h in hits
    ), "Tobias did not recall his own earlier statement"

    out = client.post("/api/accuse", json={"player": player, "suspect": "tobias"}).json()
    assert out["correct"] and "Tobias" in out["truth"], out
    print("accuse Tobias: correct")
    print("OK")


if __name__ == "__main__":
    main()
