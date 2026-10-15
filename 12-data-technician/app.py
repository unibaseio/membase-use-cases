"""Data technician: an agent classifies sensor windows with real tool calls, a scientist corrects
its mistakes, and each corrected run becomes agent memory (cases, then skills).

Before every classification the agent searches its memory for cases and skills and reads them as
the lab's notes; the page shows which were used. A held-out batch measures accuracy before and
after teaching, so the learning curve is measured, not drawn.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fastapi import HTTPException
from membase.local.backend import LocalError
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import agent  # noqa: E402
import windows  # noqa: E402

from demokit import Memory, config  # noqa: E402
from demokit.web import create_app, run, sse  # noqa: E402

DEMO = "12-data-technician"
AGENT = "technician"
CONTAINER = "Lab"
app = create_app("Data technician", HERE, mode=config.mode("local"))
_LAB = re.compile(r"^[a-z0-9-]{3,40}$")


class Lab:
    """One lab's memory directory, its runs in flight and its record (lab.json)."""

    def __init__(self, lab: str) -> None:
        self.id = lab
        self.mem = Memory(DEMO, user=lab, default_mode="local")
        self.path = self.mem.path / "lab.json"
        self.engine_lock = threading.Lock()  # one search or ingest at a time on the local engine
        self.lock = threading.Lock()
        self.runs: dict[str, dict] = {}
        if self.path.is_file():
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.state = {"lab": lab, "taught": {}, "ingested": [], "curve": []}
            self.save()

    def save(self) -> None:
        with self.lock:
            self.path.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    def notes(self, query: str) -> dict:
        """Cases and skills from memory for `query`; empty before the first corrected run."""
        if not self.state["ingested"]:
            return {"query": query, "cases": [], "skills": [], "seconds": 0.0}
        started = time.monotonic()
        with self.engine_lock:
            out = self.mem.agent_search(query, agent_id=AGENT, container=CONTAINER, limit=5)
        return {
            "query": query,
            "cases": out.get("cases", []),
            "skills": out.get("skills", [])[:3],
            "seconds": round(time.monotonic() - started, 2),
        }

    def skills(self) -> list[dict]:
        if not self.state["ingested"]:
            return []
        try:
            with self.engine_lock:
                return self.mem.agent_skills(agent_id=AGENT, container=CONTAINER)
        except LocalError as e:
            if e.status == 403:  # nothing ingested into the container yet
                return []
            raise


_labs: dict[str, Lab] = {}
_labs_lock = threading.Lock()


def lab_of(lab: str) -> Lab:
    if not _LAB.match(lab or ""):
        raise HTTPException(400, "lab must be 3-40 characters of a-z, 0-9 and '-'")
    with _labs_lock:
        if lab not in _labs:
            _labs[lab] = Lab(lab)
        return _labs[lab]


def window_or_404(wid: str) -> dict:
    if wid not in windows.BY_ID:
        raise HTTPException(404, f"no window {wid!r}")
    return windows.BY_ID[wid]


def digest(values: list) -> str:
    """A one-line shape of the window, so memory search can find cases about similar windows."""
    stats = agent.call_tool(values, "compute_stats", {})
    spikes = agent.call_tool(values, "find_spikes", {"z": 4})
    fit = agent.call_tool(values, "slope", {})
    run_ = agent.call_tool(values, "longest_run", {})
    top = max((abs(s["robust_z"]) for s in spikes["spikes"]), default=0)
    return (
        f"std {stats.get('std')}, nan {stats.get('nan')}, min {stats.get('min')}, "
        f"{spikes['count']} readings past robust z 4 (max {top}), slope "
        f"{fit.get('slope_per_100')} per 100 "
        f"(r2 {fit.get('r2')}), longest identical run {run_['length']}"
    )


def notes_prompt(notes: dict) -> str:
    """The retrieved cases and skills as the lab's notes in the system prompt."""
    # The cases come first: each carries the scientist's correction and its key insight word for
    # word, while a skill is the engine's summary and can be worded more loosely.
    parts = []
    for c in notes["cases"]:
        # The approach keeps the steps, the scientist's correction and the outcome.
        parts.append(
            f"Past case: {c['task_intent']}\nInsight: {c.get('key_insight') or ''}\n"
            f"What happened:\n{c.get('approach', '')[:1500]}".strip()
        )
    for s in notes["skills"]:
        parts.append(f"Skill '{s['name']}': {s['description']}\n{s['content'][:2500]}")
    if not parts:
        return ""
    return (
        "\n\nLab notes from memory (learned from the scientist's corrections):\n\n"
        + "\n\n".join(parts)
    )


def first_messages(lab: Lab, w: dict) -> tuple[list[dict], dict]:
    query = (
        f"Classify a temperature-probe sensor window as clean, spike, drift, flatline or dropout. "
        f"Window shape: {digest(w['values'])}"
    )
    notes = lab.notes(query)
    messages = [
        {"role": "system", "content": agent.SYSTEM + notes_prompt(notes)},
        {"role": "user", "content": f"Classify sensor window {w['id']} (120 readings)."},
    ]
    return messages, notes


def used(notes: dict) -> dict:
    return {
        "query": notes["query"],
        "seconds": notes["seconds"],
        "skills": [
            {
                "id": s.get("id"),
                "name": s["name"],
                "description": s["description"],
                "content": s["content"],
                "score": s.get("score"),
            }
            for s in notes["skills"]
        ],
        "cases": [
            {
                # the session id is "<window>-<run id>": which corrected window the case came from
                "window": (c.get("session_id") or "").split("-")[0] or None,
                "task_intent": c["task_intent"],
                "key_insight": c.get("key_insight"),
                "score": c.get("score"),
            }
            for c in notes["cases"]
        ],
    }


# ---- endpoints -------------------------------------------------------------------------


@app.get("/api/windows")
def get_windows() -> dict:
    return {
        "labels": windows.LABELS,
        "train": windows.TRAIN_WINDOWS,
        "held_out": [
            {k: w[k] for k in ("id", "values", "truth")} for w in windows.HELD_OUT_WINDOWS
        ],
    }


@app.post("/api/labs/new")
def new_lab() -> dict:
    lab = "lab-" + uuid.uuid4().hex[:8]
    lab_of(lab)
    return {"lab": lab}


@app.get("/api/lab")
def get_lab(lab: str) -> dict:
    lb = lab_of(lab)
    return {**lb.state, "skills": lb.skills(), "directory": str(lb.mem.path)}


class Classify(BaseModel):
    lab: str
    window: str


@app.post("/api/classify")
def classify(body: Classify):
    lb = lab_of(body.lab)
    w = window_or_404(body.window)

    def events():
        messages, notes = first_messages(lb, w)
        yield {"type": "notes", **used(notes)}
        answer = None
        for ev in agent.run(messages, w["values"]):
            if ev["type"] == "answer":
                answer = ev
            yield ev
        run_id = uuid.uuid4().hex[:10]
        lb.runs[run_id] = {"window": w["id"], "messages": messages, "label": answer["label"]}
        yield {
            "type": "verdict",
            "run_id": run_id,
            "label": answer["label"],
            "truth": w["truth"],
            "correct": answer["label"] == w["truth"],
            "rule": w.get("rule", ""),
            "rounds": agent.tool_rounds(messages),
        }

    return sse(events())


class Correct(BaseModel):
    lab: str
    run_id: str
    label: str
    reason: str


@app.post("/api/correct")
def correct(body: Correct):
    """The scientist's correction is the next user turn; the agent answers it (it may re-check
    with tools), and the whole run goes into agent memory."""
    lb = lab_of(body.lab)
    run_ = lb.runs.get(body.run_id)
    if not run_:
        raise HTTPException(
            404, "that run is gone (the server restarted?): classify the window again"
        )
    if body.label not in windows.LABELS:
        raise HTTPException(400, f"label must be one of {', '.join(windows.LABELS)}")
    w = windows.BY_ID[run_["window"]]
    reason = body.reason.strip()

    def events():
        messages = run_["messages"]
        messages.append(
            {
                "role": "user",
                "content": f"That's wrong: window {w['id']} is {body.label}. {reason}".strip(),
            }
        )
        yield from agent.run(messages, w["values"])
        yield {"type": "ingesting", "rounds": agent.tool_rounds(messages)}
        trace = [
            m for m in messages if m["role"] != "system"
        ]  # the engine maps user/assistant/tool turns
        started = time.monotonic()
        with lb.engine_lock:
            out = lb.mem.agent_ingest(
                trace, agent_id=AGENT, session_id=f"{w['id']}-{body.run_id}", container=CONTAINER
            )
        seconds = round(time.monotonic() - started, 1)
        record = {
            "window": w["id"],
            "run_id": body.run_id,
            "agent_label": run_["label"],
            "label": body.label,
            "reason": reason,
            "at": time.time(),
            "seconds": seconds,
            **{
                k: out.get(k)
                for k in (
                    "status",
                    "cases",
                    "skills_added",
                    "skills_updated",
                    "skill_ids",
                    "skipped",
                    "failed",
                )
            },
        }
        with lb.lock:
            lb.state["taught"][w["id"]] = {"result": "corrected", "label": body.label}
            if out.get("cases"):
                lb.state["ingested"].append(record)
        lb.save()
        lb.runs.pop(body.run_id, None)
        yield {
            "type": "ingested",
            **record,
            "skills": lb.skills(),
            "ingested_runs": len(lb.state["ingested"]),
        }

    return sse(events())


class Accept(BaseModel):
    lab: str
    run_id: str


@app.post("/api/accept")
def accept(body: Accept) -> dict:
    """The agent was right: nothing to teach, so nothing is written."""
    lb = lab_of(body.lab)
    run_ = lb.runs.pop(body.run_id, None)
    if not run_:
        raise HTTPException(404, "that run is gone: classify the window again")
    with lb.lock:
        lb.state["taught"][run_["window"]] = {"result": "right", "label": run_["label"]}
    lb.save()
    return {"ok": True}


class Evaluate(BaseModel):
    lab: str


@app.post("/api/evaluate")
def evaluate(body: Evaluate):
    """The held-out batch with whatever the agent has learned so far: one point on the curve."""
    lb = lab_of(body.lab)

    def one(w: dict) -> dict:
        messages, notes = first_messages(lb, w)
        label = None
        for ev in agent.run(messages, w["values"]):
            if ev["type"] == "answer":
                label = ev["label"]
        return {
            "id": w["id"],
            "truth": w["truth"],
            "label": label,
            "ok": label == w["truth"],
            "skills_used": [s["name"] for s in notes["skills"]],
            "cases_used": len(notes["cases"]),
        }

    def events():
        n = len(lb.state["ingested"])
        yield {"type": "start", "total": len(windows.HELD_OUT_WINDOWS), "corrections": n}
        results = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            for fut in as_completed([pool.submit(one, w) for w in windows.HELD_OUT_WINDOWS]):
                r = fut.result()
                results.append(r)
                yield {"type": "item", **r}
        results.sort(key=lambda r: r["id"])
        right = sum(r["ok"] for r in results)
        point = {
            "corrections": n,
            "correct": right,
            "total": len(results),
            "accuracy": round(right / len(results), 3),
            "at": time.time(),
            "results": results,
        }
        with lb.lock:
            lb.state["curve"].append(point)
        lb.save()
        yield {"type": "point", **point}

    return sse(events())


if __name__ == "__main__":
    run(app, port=8712)
