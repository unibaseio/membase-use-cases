"""Reunite: match two people's memories of the same childhood, for a person to review.

Families describe a child they lost touch with; adults describe what they remember from early
childhood. Each submission is a document in memory, in `Families` or `Seekers`. For a seeker,
memory recalls family records on the whole account and on each kind of detail (objects, people,
places, marks); the model then compares the seeker with each recalled family, detail by detail,
and says which details plausibly describe the same thing ("a red tin toy fire truck" and "a
little metal fire engine") and which contradict. A reviewer reads both records side by side and
decides. The system only suggests.

Synthetic records only. This is a demo, not a tracing or reunification service.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from demokit import Memory, llm  # noqa: E402
from demokit.config import DATA  # noqa: E402
from demokit.memory import is_narration  # noqa: E402
from demokit.web import create_app, run  # noqa: E402

DEMO = "15-reunite"
CONTAINERS = {"family": "Families", "seeker": "Seekers"}
PREFIX = {"family": "F", "seeker": "S"}
FIELDS = {
    "family": [
        ("contact", "Who is searching"),
        ("child", "The child's name then"),
        ("born", "Born (year, roughly)"),
        ("lost", "When and where you lost touch"),
        ("looks", "Looks and marks"),
        ("loved", "Things they loved or carried"),
        ("people", "People in their life"),
        ("places", "Places they knew"),
        ("story", "Anything else"),
    ],
    "seeker": [
        ("contact", "Your name now"),
        ("born", "Born (year, roughly)"),
        ("placed", "How you came into care, where you grew up"),
        ("earliest", "Earliest memories"),
        ("objects", "Objects you remember"),
        ("people", "People you remember"),
        ("places", "Places you remember"),
        ("marks", "Marks or features"),
        ("story", "Anything else"),
    ],
}
# A seeker's details that go to recall one by one, besides the whole account.
PROBES = ("earliest", "objects", "people", "places", "marks")
CANDIDATES = 5

mem = Memory(DEMO, user="operator", default_mode="local")
app = create_app("Reunite", HERE, mode=mem.mode)


class Store:
    """Records, suggested matches and review decisions, in one JSON file beside the memory.
    Memory holds the records as documents; this keeps their form fields for the review screen."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()

    def read(self) -> dict:
        with self.lock:
            if not self.path.is_file():
                return {"records": {}, "matches": {}, "reviews": {}}
            return json.loads(self.path.read_text())

    def change(self, fn) -> dict:
        with self.lock:
            data = self.read()
            out = fn(data)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1))
            tmp.replace(self.path)
            return out


store = Store((mem.path or DATA / DEMO) / "reunite.json")
work = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reunite")


def record_text(rec: dict) -> str:
    lines = [f"{'Family' if rec['kind'] == 'family' else 'Seeker'} record {rec['id']}"]
    for key, label in FIELDS[rec["kind"]]:
        if value := (rec["fields"].get(key) or "").strip():
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def record_title(rec: dict) -> str:
    f = rec["fields"]
    if rec["kind"] == "family":
        return (
            f"Family {rec['id']}: {f.get('child') or 'a child'} ({f.get('contact') or 'unnamed'})"
        )
    return f"Seeker {rec['id']}: {f.get('contact') or 'unnamed'}"


def new_record(kind: str, fields: dict) -> dict:
    if kind not in FIELDS:
        raise HTTPException(400, "kind must be family or seeker")
    allowed = {k for k, _ in FIELDS[kind]}
    fields = {k: str(v).strip() for k, v in fields.items() if k in allowed and str(v).strip()}
    if len(fields) < 3:
        raise HTTPException(400, "fill in at least three fields: matching needs details to compare")

    def add(data: dict) -> dict:
        n = 1 + sum(1 for r in data["records"].values() if r["kind"] == kind)
        rec = {
            "id": f"{PREFIX[kind]}-{n:02d}",
            "kind": kind,
            "fields": fields,
            "status": "saving",
            "doc_id": "",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        data["records"][rec["id"]] = rec
        return rec

    return store.change(add)


def save_record(rec: dict) -> dict:
    """The record into memory as one document (custom_id = its id)."""
    try:
        out = mem.add_document(
            record_text(rec),
            container=CONTAINERS[rec["kind"]],
            title=record_title(rec),
            custom_id=f"reunite:{rec['id']}",
        )
    except Exception as e:
        _set_record(rec["id"], status="error", error=f"{type(e).__name__}: {e}")
        raise
    return _set_record(rec["id"], status="saved", doc_id=out["document_id"])


def _set_record(rid: str, **changes) -> dict:
    def upd(data: dict) -> dict:
        data["records"][rid].update(changes)
        return data["records"][rid]

    return store.change(upd)


# ---- matching ---------------------------------------------------------------------------

COMPARE = """You help a human reviewer compare two accounts that may describe the same child.

The FAMILY record is what a family remembers about a child they lost touch with. The SEEKER
record is what an adult remembers from their own early childhood. Early memories are
fragmentary and childish; names were often changed; objects get described differently ("a red
tin toy truck" and "a little metal fire engine" can be the same toy; "smell of bread through the
floor" fits "a flat above a bakery"). Years and ages can be off by one or two.

Find:
- overlaps: details in both that plausibly refer to the same thing;
- conflicts: details that contradict each other (a different decade, a mark on the other side,
  a different kind of place). A missing detail is not a conflict.

Weigh specific, unusual details heavily and generic ones (a dog, the sea, a grandmother)
lightly. Then score 0-100 how likely it is that both describe the same child, where 80+ means
several specific details agree and nothing important conflicts, and under 30 means only
generic overlap or a hard conflict. You suggest; a person decides.

List only real contradictions as conflicts, never agreements or mere uncertainty: a detail
described differently that could be the same thing ("a reddish mark" and "a strawberry
birthmark" on the same wrist) is an overlap. For each side, quote the exact words that name the
detail, copied from the field values (without the field label) so they can be marked in the
record: one continuous run of words that includes what the thing is ("a little metal fire
engine", not just "red"), at most 12 words, never an ellipsis. Write like a caseworker's margin note: the summary
at most 18 words, each "why" at most 7 words, no hedging phrases.

Reply with JSON:
{"score": 0-100, "verdict": "strong" | "possible" | "weak" | "unlikely",
 "summary": "one sentence for the reviewer",
 "overlaps": [{"seeker": "exact words", "family": "exact words", "why": "short"}],
 "conflicts": [{"seeker": "exact words", "family": "exact words", "why": "short",
                "real": true if these cannot both be true, false if they could}]}"""


def _doc_to_family(data: dict) -> dict[str, str]:
    return {
        r["doc_id"]: r["id"]
        for r in data["records"].values()
        if r["kind"] == "family" and r["doc_id"]
    }


def recall_families(seeker: dict) -> list[dict]:
    """Family records memory recalls for this seeker: the whole account and each detail,
    fused by rank (reciprocal rank fusion). Each comes with the passages that found it."""
    f = seeker["fields"]
    queries = [("whole account", " ".join(f.get(k, "") for k in PROBES + ("story",)).strip())]
    queries += [(k, f[k]) for k in PROBES if f.get(k)]
    families = _doc_to_family(store.read())
    fused: dict[str, dict] = {}
    for label, q in queries:
        recall = mem.recall(q, container=CONTAINERS["family"], limit=8)
        seen: set[str] = set()
        hits = [h for h in recall.hits if not is_narration(h.content)]
        for rank, hit in enumerate(hits):
            doc_id = hit.source.removeprefix("document:").split("#", 1)[0]
            fid = families.get(doc_id)
            if not fid or fid in seen:
                continue
            seen.add(fid)
            c = fused.setdefault(
                fid, {"family_id": fid, "rrf": 0.0, "found_by": [], "passages": []}
            )
            c["rrf"] += 1.0 / (60 + rank)
            c["found_by"].append(label)
            # the passage memory returned for this search, as it came back
            if hit.content and all(hit.content != x["text"] for x in c["passages"]):
                c["passages"].append({"by": label, "text": hit.content})
    ranked = sorted(fused.values(), key=lambda c: -c["rrf"])
    for i, c in enumerate(ranked, 1):
        c["recall_rank"] = i
        c["rrf"] = round(c["rrf"], 4)
    return ranked


def compare(seeker: dict, family: dict) -> dict:
    out = llm.json_reply(
        [
            {"role": "system", "content": COMPARE},
            {
                "role": "user",
                "content": f"SEEKER\n{record_text(seeker)}\n\nFAMILY\n{record_text(family)}",
            },
        ]
    )
    return {
        "score": max(0, min(100, int(out.get("score") or 0))),
        "verdict": str(out.get("verdict") or ""),
        "summary": str(out.get("summary") or ""),
        "overlaps": [o for o in out.get("overlaps") or [] if isinstance(o, dict)],
        # A "conflict" the model itself says could both be true is not one.
        "conflicts": [
            o
            for o in out.get("conflicts") or []
            if isinstance(o, dict) and o.get("real") is not False
        ],
    }


def match(seeker_id: str) -> dict:
    """Recall, then compare the top candidates in parallel; ranked by the comparison score."""
    started = time.monotonic()
    store.change(
        lambda d: d["matches"].update(
            {
                seeker_id: {
                    **d["matches"].get(seeker_id, {}),
                    "status": "matching",
                    "phase": "recall",
                }
            }
        )
    )
    try:
        data = store.read()
        seeker = data["records"][seeker_id]
        recalled = recall_families(seeker)
        top = recalled[:CANDIDATES]
        store.change(
            lambda d: d["matches"][seeker_id].update(
                {"phase": "compare", "recalled": len(recalled), "comparing": len(top)}
            )
        )
        with ThreadPoolExecutor(max_workers=CANDIDATES) as pool:
            verdicts = list(
                pool.map(lambda c: compare(seeker, data["records"][c["family_id"]]), top)
            )
        candidates = sorted(
            ({**c, **v} for c, v in zip(top, verdicts, strict=True)),
            key=lambda c: (-c["score"], c["recall_rank"]),
        )
        result = {
            "status": "ready",
            "candidates": candidates,
            "recalled": len(recalled),
            "families": sum(1 for r in data["records"].values() if r["kind"] == "family"),
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "seconds": round(time.monotonic() - started, 1),
        }
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        store.change(
            lambda d: d["matches"].update({seeker_id: {"status": "error", "error": error}})
        )
        raise
    store.change(lambda d: d["matches"].update({seeker_id: result}))
    return result


def submit(kind: str, fields: dict, *, then_match: bool = True) -> dict:
    """Synchronous: the record into memory, then (a seeker) its matches. A new family makes
    every seeker's suggestions stale: they were checked without it."""
    rec = new_record(kind, fields)
    save_record(rec)
    if kind == "family":
        store.change(lambda d: [m.update({"stale": True}) for m in d["matches"].values()])
    elif then_match:
        match(rec["id"])
    return store.read()["records"][rec["id"]]


def _logged(future) -> None:
    if future.exception():
        print(f"reunite: {future.exception()}", file=sys.stderr)


# ---- routes -----------------------------------------------------------------------------


class RecordIn(BaseModel):
    kind: str
    fields: dict[str, str]


class ReviewIn(BaseModel):
    seeker_id: str
    family_id: str
    decision: str
    note: str = ""


@app.get("/api/fields")
def fields() -> dict:
    return {k: [{"key": key, "label": label} for key, label in v] for k, v in FIELDS.items()}


@app.get("/api/queue")
def queue() -> dict:
    data = store.read()
    seekers = []
    for rec in sorted(data["records"].values(), key=lambda r: r["id"]):
        if rec["kind"] != "seeker":
            continue
        m = data["matches"].get(rec["id"], {})
        reviews = data["reviews"].get(rec["id"], {})
        top = (m.get("candidates") or [None])[0]
        seekers.append(
            {
                "id": rec["id"],
                "title": record_title(rec),
                "record_status": rec["status"],
                "match_status": m.get("status")
                or ("waiting" if rec["status"] != "error" else "error"),
                "stale": bool(m.get("stale")),
                "top": {
                    "family_id": top["family_id"],
                    "score": top["score"],
                    "verdict": top["verdict"],
                }
                if top
                else None,
                "decided": {fid: r["decision"] for fid, r in reviews.items()},
            }
        )
    families = sum(1 for r in data["records"].values() if r["kind"] == "family")
    return {"seekers": seekers, "families": families}


@app.get("/api/seekers/{seeker_id}")
def seeker(seeker_id: str) -> dict:
    data = store.read()
    rec = data["records"].get(seeker_id)
    if not rec or rec["kind"] != "seeker":
        raise HTTPException(404, "no such seeker")
    m = data["matches"].get(seeker_id, {})
    candidates = [
        {
            **c,
            "family": data["records"][c["family_id"]],
            "title": record_title(data["records"][c["family_id"]]),
        }
        for c in m.get("candidates") or []
    ]
    return {
        "seeker": rec,
        "title": record_title(rec),
        "match": {k: v for k, v in m.items() if k != "candidates"},
        "candidates": candidates,
        "reviews": data["reviews"].get(seeker_id, {}),
    }


@app.post("/api/records")
def add_record(body: RecordIn) -> dict:
    rec = new_record(body.kind, body.fields)

    def job() -> None:
        save_record(rec)
        if rec["kind"] == "family":
            store.change(lambda d: [m.update({"stale": True}) for m in d["matches"].values()])
        else:
            match(rec["id"])

    work.submit(job).add_done_callback(_logged)
    return rec


@app.post("/api/seekers/{seeker_id}/match")
def rematch(seeker_id: str) -> dict:
    rec = store.read()["records"].get(seeker_id)
    if not rec or rec["kind"] != "seeker":
        raise HTTPException(404, "no such seeker")
    if rec["status"] != "saved":
        raise HTTPException(409, f"this record is {rec['status']}, not yet in memory")
    store.change(
        lambda d: d["matches"].update(
            {
                seeker_id: {
                    **d["matches"].get(seeker_id, {}),
                    "status": "matching",
                    "phase": "recall",
                }
            }
        )
    )
    work.submit(match, seeker_id).add_done_callback(_logged)
    return {"status": "matching"}


@app.post("/api/reviews")
def review(body: ReviewIn) -> dict:
    if body.decision not in ("match", "no_match", "undecided"):
        raise HTTPException(400, "decision must be match, no_match or undecided")
    data = store.read()
    if body.seeker_id not in data["records"] or body.family_id not in data["records"]:
        raise HTTPException(404, "no such record")
    entry = {
        "decision": body.decision,
        "note": body.note.strip(),
        "at": datetime.now().isoformat(timespec="seconds"),
    }

    def put(d: dict) -> dict:
        reviews = d["reviews"].setdefault(body.seeker_id, {})
        if body.decision == "undecided":
            reviews.pop(body.family_id, None)
        else:
            reviews[body.family_id] = entry
        return reviews

    return {"reviews": store.change(put)}


if __name__ == "__main__":
    run(app, port=8715)
