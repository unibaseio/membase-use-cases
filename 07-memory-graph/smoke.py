"""End-to-end check against the real API: a life seeded into memory, read back into a graph,
with the seeded people, places and links present and traced to the passages they came from.

    uv run 07-memory-graph/smoke.py            # on the demo's base (MEMBASE_DEMO_MODE to switch)

Writes to its own data directory (local) or the configured account (hosted). Exits non-zero
with the reason on any failure.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
if os.environ.get("MEMBASE_DEMO_MODE", "") != "hosted":
    # A fresh local store, so the check never passes on yesterday's data.
    os.environ.setdefault("DEMO_DATA_DIR", tempfile.mkdtemp(prefix="smoke-07-"))
sys.path.insert(0, str(HERE.parent))

from fastapi.testclient import TestClient  # noqa: E402

# (name as seeded, type it should get)
ENTITIES = [
    ("Tomás Reyes", "person"),
    ("Aiko Mori", "person"),
    ("Clara Jensen", "person"),
    ("Sam Okoro", "person"),
    ("Felix Brandt", "person"),
    ("Harbor Bank", "org"),
    ("Northwind Labs", "org"),
    ("Lisbon Climbing Club", "org"),
    ("Atlas", "project"),
    ("Beacon", "project"),
    ("Berlin", "place"),
    ("Sintra", "place"),
]
# Links the notes state outright; the graph must find at least two (either direction).
RELATIONS = [
    ("Clara Jensen", "Harbor Bank"),
    ("Aiko Mori", "Atlas"),
    ("Felix Brandt", "Lisbon Climbing Club"),
    ("Sam Okoro", "Beacon"),
    ("Nora", "Berlin"),
    ("Tomás Reyes", "You"),
    ("Nora", "Malik Haddad"),
]


def fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def main() -> None:
    subprocess.run([sys.executable, str(HERE / "seed.py")], check=True, env=os.environ)
    import app as demo  # noqa: PLC0415 - after the store is chosen

    client = TestClient(demo.app)
    info = client.get("/api/info").json()
    print("base:", info["mode"])
    assert client.get("/").status_code == 200, "page did not load"
    assert client.get("/api/graph").json()["graph"] is None, "a fresh store already has a graph"

    events = []
    with client.stream("POST", "/api/graph/rebuild", json={}) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    errors = [e for e in events if e["type"] == "error"]
    assert not errors, errors
    for e in events:
        if e["type"] == "step":
            print("  " + e["text"])
    graph = next(e for e in events if e["type"] == "graph")["graph"]
    passages = {p["id"]: p["text"] for p in graph["passages"]}
    nodes = graph["nodes"]
    print(
        f"graph: {len(nodes)} entities, {len(graph['links'])} links, "
        f"{len(passages)} passages, {graph['seconds']}s"
    )

    def find(name: str) -> dict | None:
        want = fold(name)
        return next((n for n in nodes if fold(n["name"]) == want), None) or next(
            (n for n in nodes if want in fold(n["name"])), None
        )

    missing = []
    for name, kind in ENTITIES:
        node = find(name)
        if node is None:
            missing.append(name)
            continue
        assert node["type"] == kind, f"{name} is a {node['type']}, not a {kind}"
        texts = [passages[i] for i in node["passages"]]
        key = fold(name.split()[0])
        assert texts and any(key in fold(t) for t in texts), (
            f"{name}: no source passage names it: {texts}"
        )
    assert not missing, f"seeded entities missing from the graph: {missing}"
    print(f"found all {len(ENTITIES)} seeded entities, each with a passage that names it")

    by_id = {n["id"]: n for n in nodes}
    found = []
    for a, b in RELATIONS:
        na, nb = find(a), find(b)
        if not (na and nb):
            continue
        for link in graph["links"]:
            if {link["source"], link["target"]} == {na["id"], nb["id"]}:
                texts = [passages[i] for i in link["passages"]]
                assert texts, f"link {a}-{b} has no passage"
                found.append(link)
                src, dst = by_id[link["source"]]["name"], by_id[link["target"]]["name"]
                print(f"  link: {src} —{link['label']}→ {dst}  (passages {link['passages']})")
    assert len(found) >= 2, f"seeded relations missing: {graph['links']}"

    if graph["mode"] == "local":
        # Each note is dated by the day it happened, not the day it was seeded.
        from seed import NOTES  # noqa: PLC0415

        days = {day for _title, day, _text in NOTES}
        dated = {p["date"] for p in graph["passages"] if p["date"]}
        assert len(dated & days) >= 5, f"the notes do not carry their own days: {sorted(dated)}"
        print(f"notes dated by the day they happened: {len(dated & days)} distinct days")
        # Each passage from a note maps back to the note as Lena wrote it.
        texts = {text for _title, _day, text in NOTES}
        mapped = [p for p in graph["passages"] if p.get("note")]
        assert mapped and all(p["note"]["text"] in texts for p in mapped), (
            "a note maps to the wrong text"
        )
        assert len(mapped) >= len([p for p in graph["passages"] if p["date"]]) - 1, (
            f"passages without their note: {[p['text'][:60] for p in graph['passages'] if not p.get('note')]}"
        )
        print(f"{len(mapped)} passages map back to Lena's own notes")

    cached = client.get("/api/graph").json()["graph"]
    assert cached and len(cached["nodes"]) == len(nodes), "graph was not cached"
    live = client.post("/api/recall", json={"name": "Felix Brandt"}).json()
    assert any("felix" in fold(h["content"]) for h in live["hits"]), (
        f"live recall missed Felix: {live}"
    )
    if graph["mode"] == "local":
        assert all(h["date"] for h in live["hits"]), f"a live hit has no date: {live}"
    print(f"live recall for Felix Brandt: {len(live['hits'])} passages in {live['seconds']}s")
    print("OK")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
