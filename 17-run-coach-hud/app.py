"""Run coach HUD: Pacenote, a coach for smart glasses that remembers your past runs.

Before a run the coach recalls recent runs and reads the runner's goals; code counts the runs
that faded after km 7 from their splits, and the model writes a one-line headline, two short
cues and a few moments in the run to speak up, each tied to the runs it came from. The phone
companion shows the brief. "Start run" streams a simulated run (pace, heart rate, distance)
into the HUD seen through the glasses, and the cues fire in the lens at their moments; the km
6.5 cue shows the runs it counted. At the finish the run's summary is written to memory, dated
now, and the next brief reads it.

The runner, the runs and the goals are synthetic, and the run is a simulation. This is a demo,
not training or medical advice.
"""

from __future__ import annotations

import json
import random
import re
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from demokit import Memory, llm  # noqa: E402
from demokit.dated import recall, remember_sessions  # noqa: E402
from demokit.web import create_app, run, sse  # noqa: E402

DEMO = "17-run-coach-hud"
CONTAINER = "Runs"
RUNNER = "Jamie"

mem = Memory(DEMO, user="jamie", default_mode="local")
app = create_app("Run coach HUD", HERE, mode=mem.mode)


class Runs:
    """Each run's numbers and memory ids (`runs.json`), for the history list; the coach itself
    reads memory."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()

    def all(self) -> list[dict]:
        with self.lock:
            return json.loads(self.path.read_text()) if self.path.is_file() else []

    def add(self, run_: dict) -> None:
        with self.lock:
            data = json.loads(self.path.read_text()) if self.path.is_file() else []
            data.append(run_)
            self.path.write_text(json.dumps(data, indent=1))


runs = Runs(mem.path / "runs.json")
BRIEFS: dict[str, dict] = {}


def pace(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def clock(seconds: float) -> str:
    s = int(round(seconds))
    return (
        f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
    )


def summary_text(r: dict) -> str:
    """A finished run as the post-run summary memory reads."""
    at = datetime.fromisoformat(r["when"])
    splits = ", ".join(f"km {i}: {pace(s)}" for i, s in enumerate(r["splits"], 1))
    return (
        f"{RUNNER}'s run on {at:%A} {at.day} {at:%B %Y} at {at:%H:%M}: {r['kind']}, "
        f"{r['distance_km']:g} km in {clock(r['seconds'])} (average {pace(r['seconds'] / r['distance_km'])}/km). "
        f"Splits per km: {splits}. Average heart rate {r['hr_avg']}, max {r['hr_max']}. "
        f"How it felt: {r['felt']}"
    )


def save_run(r: dict) -> dict:
    """The run's summary into memory, dated when it was run; its numbers into runs.json."""
    r = {**r, "id": r.get("id") or uuid.uuid4().hex[:10]}
    ids = remember_sessions(
        mem,
        [
            {
                "session_id": f"run-{r['id']}",
                "session_date": datetime.fromisoformat(r["when"]).isoformat(timespec="seconds"),
                "turns": [{"role": RUNNER, "content": summary_text(r)}],
            }
        ],
        container=CONTAINER,
    )[f"run-{r['id']}"]
    if not ids:
        raise RuntimeError("the engine kept no memory from this run summary")
    r["memory_ids"] = ids
    runs.add(r)
    return r


# ---- the brief ----------------------------------------------------------------------------

#: A run "faded after km 7" when its splits after km 7 average this many seconds per km slower
#: than its km 3-7 splits. Counted in code from the run log, never by the model.
FADE_KM = 7
FADE_SECONDS = 15


def fade(r: dict) -> dict | None:
    """How a run longer than FADE_KM went after km 7: the slowdown in s/km, and whether it
    counts as a fade. None for a run that never got past km 7."""
    s = r["splits"]
    if r["distance_km"] <= FADE_KM or len(s) <= FADE_KM:
        return None
    before = s[2:FADE_KM]
    after = s[FADE_KM:]
    slower = round(sum(after) / len(after) - sum(before) / len(before))
    return {"slower": slower, "faded": slower >= FADE_SECONDS}


def pattern(recalled: list[dict]) -> dict:
    """The fade pattern across the runs the coach recalled, counted from their numbers in the
    run log (each recalled memory maps to its run by memory id). Newest first."""
    by_memory = {m: r for r in runs.all() for m in r.get("memory_ids", [])}
    seen, long_runs = set(), []
    for h in recalled:
        r = by_memory.get(h["memory_id"])
        if not r or r["id"] in seen or not (f := fade(r)):
            continue
        seen.add(r["id"])
        long_runs.append(
            {
                "run_id": r["id"],
                "memory_id": h["memory_id"],
                "date": r["when"],
                "distance_km": r["distance_km"],
                "kind": r["kind"],
                "splits": r["splits"],
                **f,
            }
        )
    long_runs.sort(key=lambda x: x["date"], reverse=True)
    faded = [x for x in long_runs if x["faded"]]
    return {
        "long": long_runs,
        "faded": len(faded),
        "of": len(long_runs),
        "latest_faded": long_runs[0]["faded"] if long_runs else None,
    }


def fade_moment(p: dict, target: str, distance_km: float) -> dict | None:
    """The cue just before km 7, with the count from `pattern` and the runs it rests on."""
    if not p["faded"] or distance_km <= FADE_KM:
        return None
    head = f"{p['faded']} of your last {p['of']} runs over {FADE_KM} km faded after km {FADE_KM}."
    text = (
        f"{head} Not the latest: hold {target} again."
        if p["latest_faded"] is False
        else f"{head} Hold {target} now."
    )
    return {
        "km": FADE_KM - 0.5,
        "text": text,
        "uses": [{"memory_id": x["memory_id"], "date": x["date"]} for x in p["long"]],
        "counted": True,
    }


BRIEF = """You are Pacenote, a running coach that speaks through smart glasses to {runner}.
Today's planned run: {plan}. It is now {now}.

You are given {runner}'s goals and past runs recalled from memory, each numbered and dated, and
a line counted in code from those runs' splits. Use that count exactly as given; never count
runs yourself. Look for patterns across the runs: how fast they started, what heart rate did,
how it felt, and what changed in the most recent run.

Talk like a coach at the start line: short, direct, second person, no pleasantries, no
"Remember to", no "Great job". Write:
- "headline": how the most recent run went, against the ones before it (at most 12 words), saying
  only what its entry shows (a fast or a controlled start, a fade or none);
- "cues": two cues to read before setting off, each at most 7 words, imperative; each with
  "because": the pattern behind it, without dates (at most 10 words; the app adds the date of
  every run you list in "uses"), and "uses": entry numbers;
- "target_pace": today's target pace in m:ss per km, from the goals and recent runs;
- "moments": one or two moments in today's run to speak up, each {{"km": number within the
  planned distance}} or {{"hr_above": number}}, with "text" (at most 10 words) and "uses": entry
  numbers. The fade after km {fade_km} already has its own cue at km {fade_cue}: do not write
  another moment about it or between km {fade_cue} and km {fade_km}. Put each moment just before
  where past runs went wrong, with the real numbers from the entries, then what to do now.

Write no dates in "because" or "text": the app shows each cited run's own date. If the
most recent run broke a pattern, say so. Apply each goal only to the kind of run it is about (an
easy-run limit is not a steady-run limit). Use only what the entries show; never invent a run.
Reply with JSON:
{{"headline": "...", "target_pace": "m:ss", "cues": [{{"text": "...", "because": "...", "uses": [1]}}],
 "moments": [{{"hr_above": 172, "text": "...", "uses": [2]}}]}}"""


class BriefIn(BaseModel):
    distance_km: float = 10
    kind: str = "steady run"


def _secs(text: str, default: float) -> float:
    try:
        m, s = str(text).strip().split(":")
        return int(m) * 60 + int(s)
    except ValueError:
        return default


#: Entry numbers the model sometimes writes into its text ("..., uses 2 6 9", "(entries 2, 4)").
ENTRY_REFS = re.compile(
    r"[,;]?\s*\(?\b(?:uses?|entr(?:y|ies)|runs?)\s*:?\s*((?:\d+(?:\s*,\s*|\s+and\s+|\s+)?)+)\)?\.?\s*$",
    re.I,
)


def tidy(text) -> tuple[str, list[int]]:
    """A cue's text without entry numbers written into it, and those numbers, which become
    citations like the ones the model put in "uses"."""
    text = str(text or "").strip()
    m = ENTRY_REFS.search(text)
    if not m:
        return text, []
    return text[: m.start()].rstrip(" ,;"), [int(n) for n in re.findall(r"\d+", m.group(1))]


def brief(distance_km: float = 10, kind: str = "steady run") -> dict:
    if not 1 <= distance_km <= 42.2:
        raise HTTPException(400, "distance must be 1-42.2 km")
    started = time.monotonic()
    now = datetime.now()
    hits: dict[str, dict] = {}
    for q in (
        "recent runs: pace per km, where the pace faded, heart rate, how it felt",
        "long runs that started too fast and faded late; heart rate drift",
        f"most recent run, {now:%A} {now.day} {now:%B %Y}",
    ):
        for h in recall(mem, q, container=CONTAINER, limit=10):
            hits.setdefault(h["memory_id"], h)
    ordered = sorted(hits.values(), key=lambda h: h["date"], reverse=True)
    goals = mem.profile().get("static", [])
    found = pattern(ordered)
    lines = [f"Goal: {g}" for g in goals]
    for i, h in enumerate(ordered, 1):
        at = datetime.fromisoformat(h["date"])
        days = (now.date() - at.date()).days
        ago = "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"
        latest = " — the most recent run" if i == 1 else ""
        lines.append(f"[{i}] {at:%a %d %b} ({ago}{latest}): {h['content']}")
    if found["of"]:
        latest = (
            "the most recent of them did not fade"
            if found["latest_faded"] is False
            else ("the most recent of them faded too")
        )
        lines.append(
            f"Counted in code from the splits: {found['faded']} of the last {found['of']} runs over "
            f"{FADE_KM} km faded after km {FADE_KM} (km 8 onward at least {FADE_SECONDS} s/km slower "
            f"than km 3-7); {latest}."
        )
    plan = f"{distance_km:g} km {kind}"
    out = llm.json_reply(
        [
            {
                "role": "system",
                "content": BRIEF.format(
                    runner=RUNNER,
                    plan=plan,
                    now=f"{now:%A %d %B %Y, %H:%M}",
                    fade_km=FADE_KM,
                    fade_cue=FADE_KM - 0.5,
                ),
            },
            {
                "role": "user",
                "content": "\n".join(lines) or "(no goals and no past runs in memory)",
            },
        ]
    )

    def cited(nums) -> list[dict]:
        out_ = []
        for n in nums or []:
            if isinstance(n, int) and 1 <= n <= len(ordered):
                h = ordered[n - 1]
                out_.append({"memory_id": h["memory_id"], "date": h["date"]})
        return out_

    cues = [
        {
            "text": tidy(c.get("text"))[0],
            "because": tidy(c.get("because"))[0],
            "uses": cited((c.get("uses") or []) + tidy(c.get("because"))[1]),
        }
        for c in out.get("cues") or []
        if isinstance(c, dict) and c.get("text")
    ][:2]
    target_pace = pace(_secs(out.get("target_pace"), 330))
    moments = []
    counted = fade_moment(found, target_pace, distance_km)
    if counted:
        moments.append(counted)
    for m in out.get("moments") or []:
        if not isinstance(m, dict) or not m.get("text"):
            continue
        text, nums = tidy(m["text"])
        item = {"text": text, "uses": cited((m.get("uses") or []) + nums)}
        if isinstance(m.get("km"), (int, float)) and 0 < m["km"] < distance_km:
            # the counted fade cue owns the stretch just before km 7
            if counted and counted["km"] - 1 <= m["km"] <= FADE_KM:
                continue
            item["km"] = float(m["km"])
        elif isinstance(m.get("hr_above"), (int, float)):
            item["hr_above"] = int(m["hr_above"])
        else:
            continue
        moments.append(item)
    b = {
        "id": uuid.uuid4().hex[:10],
        "plan": {"distance_km": distance_km, "kind": kind},
        "headline": str(out.get("headline") or ""),
        "target_pace": target_pace,
        "cues": cues,
        "moments": moments,
        "pattern": found,
        "goals": goals,
        "recalled": ordered,
        "seconds": round(time.monotonic() - started, 2),
    }
    BRIEFS[b["id"]] = b
    return b


# ---- the simulated run --------------------------------------------------------------------

TICK = 15.0  # simulated seconds per update
SLEEP = 0.12  # real seconds per update
CUE_HOLD = 3.0  # real seconds the run waits after a cue at a km, so it is read near that km


def simulate(b: dict, *, sleep: float = SLEEP, seed: int | None = None):
    """A runner who follows the brief: a controlled first two km, the target pace through the
    middle, a small kick in the last km. Yields HUD events; cues fire at the brief's moments."""
    rng = random.Random(seed)
    dist_km = b["plan"]["distance_km"]
    target = _secs(b["target_pace"], 330)
    km_moments = sorted((m for m in b["moments"] if "km" in m), key=lambda m: m["km"])
    hr_moments = [m for m in b["moments"] if "hr_above" in m]
    t = d = 0.0
    hr = 118.0
    splits, hrs, split_start = [], [], 0.0
    yield {"type": "start", "plan": b["plan"], "target_pace": b["target_pace"]}
    if b["cues"]:
        yield {
            "type": "cue",
            "text": b["cues"][0]["text"],
            "because": b["cues"][0]["because"],
            "uses": b["cues"][0]["uses"],
            "km": 0,
        }
    while dist_km - d > 1e-6:
        km = d
        if km < 2:
            p = target + 8
        elif km >= dist_km - 1:
            p = target - 6
        else:
            p = target
        p += rng.uniform(-4, 4)
        step = min(TICK / p, dist_km - d)  # km covered this tick
        dt = step * p
        d += step
        t += dt
        effort = 150 + 4 * max(0.0, km - 1) + (8 if km >= dist_km - 1 else 0) - (target - 300) / 6
        hr += (min(effort, 182) - hr) * 0.18 + rng.uniform(-1.2, 1.2)
        hrs.append(hr)
        yield {
            "type": "tick",
            "t": round(t),
            "km": round(d, 3),
            "pace": pace(p),
            "pace_s": round(p),
            "hr": round(hr),
        }
        for m in [m for m in km_moments if m["km"] <= d]:
            km_moments.remove(m)
            yield {
                "type": "cue",
                "text": m["text"],
                "km": round(d, 2),
                "at_km": m["km"],
                "uses": m["uses"],
                "counted": bool(m.get("counted")),
            }
            if sleep:
                time.sleep(CUE_HOLD)
        for m in [m for m in hr_moments if hr > m["hr_above"]]:
            hr_moments.remove(m)
            yield {
                "type": "cue",
                "text": m["text"],
                "km": round(d, 2),
                "hr": round(hr),
                "uses": m["uses"],
            }
        while len(splits) + 1 <= d + 1e-9:  # crossed a whole km: its split, timed at the line
            line_t = t - (d - (len(splits) + 1)) * p
            splits.append(round(line_t - split_start))
            split_start = line_t
            yield {
                "type": "split",
                "km": len(splits),
                "pace": pace(splits[-1]),
                "pace_s": splits[-1],
                "hr": round(hr),
            }
        if dist_km - d <= 1e-6 and d - len(splits) > 1e-6:  # the last part-km, as a pace
            splits.append(round((t - split_start) / (d - len(splits))))
            yield {
                "type": "split",
                "km": round(d, 2),
                "pace": pace(splits[-1]),
                "pace_s": splits[-1],
                "hr": round(hr),
            }
        if sleep:
            time.sleep(sleep)
    yield {
        "type": "finish",
        "run": {
            "when": datetime.now().isoformat(timespec="minutes"),
            "kind": b["plan"]["kind"],
            "distance_km": dist_km,
            "seconds": round(t),
            "splits": splits,
            "hr_avg": round(sum(hrs) / len(hrs)),
            "hr_max": round(max(hrs)),
        },
    }


def felt(r: dict, target: float) -> str:
    """The simulated runner's own note, from the numbers."""
    s = r["splits"]
    first = s[0]
    parts = [
        f"Started controlled ({pace(first)} first km)."
        if first >= target
        else f"Started fast ({pace(first)} first km)."
    ]
    if f := fade(r):
        parts.append(
            f"Faded after km {FADE_KM}, about {f['slower']}s/km slower."
            if f["faded"]
            else f"No fade after km {FADE_KM}: held pace to the end and finished with a kick."
        )
    parts.append("Simulated run, coached through the glasses.")
    return " ".join(parts)


class RunIn(BaseModel):
    brief_id: str


@app.post("/api/brief")
def make_brief(body: BriefIn) -> dict:
    return brief(body.distance_km, body.kind)


@app.post("/api/run")
def start_run(body: RunIn):
    b = BRIEFS.get(body.brief_id)
    if not b:
        raise HTTPException(404, "that brief has expired: get a new one")

    def events():
        finished = None
        for e in simulate(b):
            if e["type"] == "finish":
                finished = e["run"]
            yield e
        finished["felt"] = felt(finished, _secs(b["target_pace"], 330))
        yield {"type": "saving", "summary": summary_text(finished)}
        saved = save_run(finished)
        yield {"type": "saved", "run": saved}
        yield {"type": "done"}

    return sse(events())


@app.get("/api/runs")
def history() -> dict:
    return {
        "runs": sorted(runs.all(), key=lambda r: r["when"], reverse=True),
        "goals": mem.profile().get("static", []),
    }


if __name__ == "__main__":
    run(app, port=8717)
