"""The technician: an LLM tool loop over one sensor window, with real tools that compute on the
readings. `run` yields every step as an event, so the page can show the whole trace."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from demokit import config, llm  # noqa: E402

MAX_STEPS = 10

SYSTEM = (
    "You are the data technician for a lab's sensor quality control. Each task is one window of "
    "120 readings from a temperature probe. Classify it as exactly one of: clean, spike, drift, "
    "flatline, dropout.\n"
    "Inspect the window with the tools before deciding: call at least three different tools, one "
    "at a time. Then answer in one short sentence (at most 20 words) with the evidence, and end "
    "with a final line 'Label: <label>'.\n"
    "If the scientist corrects you, re-check with a tool, then state the lab's rule you will "
    "follow from now on in one line starting 'Lab rule:', and end with the corrected label.\n"
    "If the lab's notes below apply, follow them: they are this lab's conventions and override "
    "your own habits."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "compute_stats",
            "description": "Summary statistics over readings [start, end) (default: the whole "
            "window). "
            "NaN readings are counted and ignored.",
            "parameters": {
                "type": "object",
                "properties": {"start": {"type": "integer"}, "end": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_spikes",
            "description": "Readings whose robust z-score (median/MAD) is at least `z` "
            "in magnitude.",
            "parameters": {
                "type": "object",
                "properties": {"z": {"type": "number", "description": "threshold, default 4"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "slope",
            "description": "Least-squares line over readings [start, end): slope per 100 "
            "samples, r2, "
            "and the fitted total change.",
            "parameters": {
                "type": "object",
                "properties": {"start": {"type": "integer"}, "end": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "longest_run",
            "description": "The longest run of identical consecutive readings: where, "
            "how long, value.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_segment",
            "description": "The raw readings [start, end), at most 40 of them (NaN shown as null).",
            "parameters": {
                "type": "object",
                "properties": {"start": {"type": "integer"}, "end": {"type": "integer"}},
                "required": ["start", "end"],
            },
        },
    },
]


def _span(x: np.ndarray, args: dict) -> tuple[int, int]:
    start = max(0, int(args.get("start") or 0))
    end = min(len(x), int(args.get("end") or len(x)))
    if end <= start:
        raise ValueError(f"empty range [{start}, {end})")
    return start, end


def call_tool(values: list, name: str, args: dict) -> dict:
    """Run one tool on the window's readings; errors come back as a result the agent can read."""
    x = np.array([np.nan if v is None else v for v in values], dtype=float)
    try:
        if name == "compute_stats":
            s, e = _span(x, args)
            seg = x[s:e]
            ok = seg[~np.isnan(seg)]
            if not ok.size:
                return {"range": [s, e], "n": int(seg.size), "nan": int(seg.size)}
            med = float(np.median(ok))
            return {
                "range": [s, e],
                "n": int(seg.size),
                "nan": int(np.isnan(seg).sum()),
                "mean": round(float(ok.mean()), 3),
                "std": round(float(ok.std()), 3),
                "min": float(ok.min()),
                "max": float(ok.max()),
                "median": round(med, 3),
                "mad": round(float(np.median(np.abs(ok - med))), 3),
            }
        if name == "find_spikes":
            z = float(args.get("z") or 4)
            ok = ~np.isnan(x)
            med = float(np.median(x[ok]))
            sigma = 1.4826 * float(np.median(np.abs(x[ok] - med))) or 1e-9
            rz = (x - med) / sigma
            idx = [i for i in range(len(x)) if ok[i] and abs(rz[i]) >= z]
            return {
                "threshold_z": z,
                "count": len(idx),
                "spikes": [
                    {"index": i, "value": float(x[i]), "robust_z": round(float(rz[i]), 1)}
                    for i in idx[:15]
                ],
            }
        if name == "slope":
            s, e = _span(x, args)
            t = np.arange(s, e, dtype=float)
            seg = x[s:e]
            ok = ~np.isnan(seg)
            if ok.sum() < 3:
                return {"range": [s, e], "error": "too few readings"}
            m, b = np.polyfit(t[ok], seg[ok], 1)
            fit = m * t[ok] + b
            ss_res = float(((seg[ok] - fit) ** 2).sum())
            ss_tot = float(((seg[ok] - seg[ok].mean()) ** 2).sum()) or 1e-9
            return {
                "range": [s, e],
                "slope_per_100": round(float(m * 100), 3),
                "r2": round(1 - ss_res / ss_tot, 3),
                "fitted_total_change": round(float(m * (e - s)), 3),
            }
        if name == "longest_run":
            best, start, cur = 1, 0, 1
            for i in range(1, len(x)):
                cur = cur + 1 if x[i] == x[i - 1] else 1
                if cur > best:
                    best, start = cur, i - cur + 1
            v = x[start]
            return {"start": start, "length": best, "value": None if np.isnan(v) else float(v)}
        if name == "view_segment":
            s, e = _span(x, args)
            e = min(e, s + 40)
            return {"range": [s, e], "values": [None if np.isnan(v) else float(v) for v in x[s:e]]}
        return {"error": f"no tool named {name}"}
    except (ValueError, TypeError) as err:
        return {"error": str(err)}


LABEL = re.compile(r"label:\s*\**\s*(clean|spike|drift|flatline|dropout)", re.I)


def parse_label(text: str) -> str | None:
    found = LABEL.findall(text or "")
    return found[-1].lower() if found else None


def run(messages: list[dict], values: list) -> Iterator[dict]:
    """Continue `messages` (system + user turns so far) until the agent answers in text. Appends
    every assistant turn and tool result to `messages` and yields each as an event."""
    client = llm.client()
    for _ in range(MAX_STEPS):
        out = client.chat.completions.create(
            model=config.model(),
            messages=messages,
            tools=TOOLS,
            parallel_tool_calls=False,
            temperature=0.2,
        )
        msg = out.choices[0].message
        if msg.tool_calls:
            turn = {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.function.name, "arguments": c.function.arguments},
                    }
                    for c in msg.tool_calls
                ],
            }
            messages.append(turn)
            if msg.content:
                yield {"type": "thought", "text": msg.content}
            for c in msg.tool_calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield {"type": "tool_call", "name": c.function.name, "args": args}
                result = call_tool(values, c.function.name, args)
                messages.append(
                    {"role": "tool", "tool_call_id": c.id, "content": json.dumps(result)}
                )
                yield {"type": "tool_result", "name": c.function.name, "result": result}
            continue
        text = msg.content or ""
        messages.append({"role": "assistant", "content": text})
        yield {"type": "answer", "text": text, "label": parse_label(text)}
        return
    raise RuntimeError(f"the agent did not answer within {MAX_STEPS} steps")


def tool_rounds(messages: list[dict]) -> int:
    return sum(1 for m in messages if m.get("role") == "assistant" and m.get("tool_calls"))
