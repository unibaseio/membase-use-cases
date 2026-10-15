"""Coding memory: watch the hooks work. The page runs the real hook scripts (the ones the
Claude Code plugin, Codex and Gemini CLI run) on a sample Claude Code session: save it as a
session would end, then send a prompt from a new session and see what the hook injects.

The deliverable is the plugin and the installers (see README); this page is a window on them.
Its hooks keep their state under data/01-coding-memory/ (MEMBASE_HOME), not ~/.membase.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE / "claude-plugin" / "hooks"))
import membase_memory  # noqa: E402

from demokit import Memory  # noqa: E402
from demokit.config import DATA  # noqa: E402
from demokit.web import create_app, run  # noqa: E402

CONTAINER = "Coding"
RUN = HERE / "claude-plugin" / "hooks" / "run.sh"
FIXTURE = HERE / "fixtures" / "claude-session.jsonl"
WORK = DATA / "01-coding-memory"
HOOK_HOME = Path(os.environ.get("MEMBASE_HOME") or WORK / "membase")
PROJECT = WORK / "quillmate"  # the sample session's project folder
SESSION = str(uuid.uuid4())  # the "next session" the page's prompts belong to

mem = Memory("01-coding-memory", default_mode="hosted")
app = create_app("Coding memory", HERE, mode=mem.mode)


def hook(event: str, payload: dict) -> tuple[str, float]:
    PROJECT.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "MEMBASE_HOME": str(HOOK_HOME)}
    started = time.monotonic()
    out = subprocess.run(
        [str(RUN), "claude", event],
        input=json.dumps(payload),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if out.returncode:
        raise RuntimeError(f"{event} hook exited {out.returncode}: {out.stderr[-400:]}")
    return out.stdout, round(time.monotonic() - started, 2)


def log_tail(n: int = 14) -> list[str]:
    path = HOOK_HOME / "hooks.log"
    return path.read_text(encoding="utf-8").splitlines()[-n:] if path.is_file() else []


@app.get("/api/session")
def session() -> dict:
    """The sample transcript, line by line, marked with what the hook keeps."""
    rows = []
    for raw in FIXTURE.read_text(encoding="utf-8").splitlines():
        o = json.loads(raw)
        if o.get("type") not in ("user", "assistant"):
            rows.append({"kind": o.get("type"), "text": json.dumps(o)[:120], "kept": False})
            continue
        content = o["message"]["content"]
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        for b in blocks:
            kind = b.get("type")
            text = (
                b.get("text") or b.get("thinking") or json.dumps(b.get("input") or b.get("content"))
            )
            kept = (
                kind == "text"
                and not o.get("isMeta")
                and not text.startswith(membase_memory._NOISE)  # noqa: SLF001
                and "<system-reminder>" not in text
            )
            rows.append({"kind": f"{o['type']} {kind}", "text": text[:600], "kept": kept})
    turns = membase_memory.claude_turns(FIXTURE)
    saved = membase_memory.condense(
        turns, header="Claude Code session on project quillmate (…), <date>."
    )
    return {"rows": rows, "saved": saved}


@app.post("/api/save")
def save() -> dict:
    """End the sample session: the SessionEnd hook queues it and returns; a detached process
    saves it (one memories.add, which starts one learning run)."""
    sid = str(uuid.uuid4())
    transcript = WORK / f"{sid}.jsonl"
    PROJECT.mkdir(parents=True, exist_ok=True)
    with transcript.open("w", encoding="utf-8") as f:
        for raw in FIXTURE.read_text(encoding="utf-8").splitlines():
            o = json.loads(raw)
            o.update({k: v for k, v in (("cwd", str(PROJECT)), ("sessionId", sid)) if k in o})
            f.write(json.dumps(o) + "\n")
    _, seconds = hook(
        "session-end",
        {
            "session_id": sid,
            "transcript_path": str(transcript),
            "cwd": str(PROJECT),
            "hook_event_name": "SessionEnd",
            "reason": "prompt_input_exit",
        },
    )
    return {"seconds": seconds, "log": log_tail()}


class Prompt(BaseModel):
    prompt: str


@app.post("/api/prompt")
def prompt(body: Prompt) -> dict:
    out, seconds = hook(
        "prompt",
        {
            "session_id": SESSION,
            "cwd": str(PROJECT),
            "hook_event_name": "UserPromptSubmit",
            "prompt": body.prompt,
        },
    )
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"] if out.strip() else ""
    return {
        "context": context,
        "seconds": seconds,
        "budget": float(os.environ.get("MEMBASE_RECALL_BUDGET") or 10),
        "log": log_tail(),
    }


@app.get("/api/sessions")
def sessions() -> dict:
    """Saved sessions in the Coding Memory, newest first, with whether each is learned."""
    docs = mem.documents(CONTAINER)[:8]
    out = []
    for d in docs:
        full = mem.client.documents.get(d["id"])  # the list does not carry `learned`
        run_info = full.get("learning_run") or {}
        out.append(
            {
                "title": d.get("title"),
                "learned": bool(full.get("learned")),
                "run": run_info.get("status"),
                "created_at": d.get("created_at"),
            }
        )
    return {"documents": out, "log": log_tail()}


if __name__ == "__main__":
    run(app, port=8701)
