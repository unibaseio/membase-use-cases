"""Capture the real runs the coding-memory video replays: two separate Claude Code sessions on
one project, with Membase in between.

    DEMO_ENV_FILE=.secrets/<name>.env .venv/bin/python 01-coding-memory/video_capture.py

Session 1 states a decision. The session ends, the plugin saves it, the hosted Memory learns
it. Session 2 is a new `claude -p` process with no shared context; the project's code still
has the old numbering, so the decision can only come from memory. Every stream-json event is
kept with the second it arrived; video.py plays them back at that pace (waits sped up and
marked). Writes data/video/01-coding-memory/capture.json.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from demokit import Memory  # noqa: E402

OUT = ROOT / "data" / "video" / HERE.name
PLUGIN = HERE / "claude-plugin"

SESSIONS = [
    "Two tablets that sync offline keep producing the same invoice number. Look at "
    "billing/numbering.py. We've decided: new invoice numbers are ULIDs generated on the "
    "device, formatted INV-<ULID>, and existing invoices keep their old numbers forever. "
    "Confirm the cause in one sentence and restate the decision in one line. Just answer: "
    "don't edit files or save anything yourself.",
    "I'm writing api/export.py. How should new invoice numbers be generated, and may the "
    "export renumber old invoices? Two short sentences.",
]


def injected(project: Path, events: list[dict]) -> list[dict]:
    """What the Membase hooks added to the session, from Claude Code's own transcript."""
    sid = next(e["ev"]["session_id"] for e in events if e["ev"].get("subtype") == "init")
    path = Path.home() / ".claude" / "projects" / str(project).replace("/", "-") / f"{sid}.jsonl"
    out = []
    for line in path.read_text().splitlines():
        a = json.loads(line).get("attachment") or {}
        if a.get("type") == "hook_additional_context":
            out.append({"hook": a.get("hookEvent"), "content": "\n".join(a.get("content") or [])})
    return out


def run_session(prompt: str, project: Path, env: dict, t0: float) -> dict:
    cmd = [
        "claude",
        "-p",
        "--plugin-dir",
        str(PLUGIN),
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--allowedTools=Read",
        prompt,
    ]
    started = time.monotonic() - t0
    proc = subprocess.Popen(
        cmd, cwd=project, env=env, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True
    )
    events = []
    for line in proc.stdout:
        if line.startswith("{"):
            events.append({"t": round(time.monotonic() - t0, 3), "ev": json.loads(line)})
    proc.wait(600)
    if proc.returncode != 0:
        raise SystemExit(f"claude exited {proc.returncode}")
    result = next((e["ev"].get("result") for e in events if e["ev"].get("type") == "result"), "")
    print(f"session: {len(events)} events; answer: {result!r}")
    return {
        "prompt": prompt,
        "started": started,
        "ended": round(time.monotonic() - t0, 3),
        "events": events,
        "injected": injected(project, events),
    }


def wait_saved(log: Path, timeout: float = 120) -> str:
    """Until the plugin's detached save reports in the hook log."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lines = log.read_text().splitlines() if log.exists() else []
        if saved := [x for x in lines if " saved " in x]:
            return saved[-1]
        if errors := [x for x in lines if " flush " in x and "error" in x]:
            raise SystemExit(f"save failed: {errors[-1]}")
        time.sleep(1)
    raise SystemExit(f"the session was not saved within {timeout}s:\n" + log.read_text()[-800:])


def wait_learned(mem: Memory, timeout: float = 600) -> dict:
    deadline = time.monotonic() + timeout
    docs = mem.documents("Coding")
    doc = docs[0]["id"]
    while time.monotonic() < deadline:
        got = mem.client.documents.get(doc)
        run = got.get("learning_run") or {}
        if run.get("status") not in ("queued", "running"):
            return {"document": doc, "learned": got.get("learned"), "run": run}
        time.sleep(5)
    raise SystemExit("learning did not finish")


def main() -> None:
    mem = Memory(HERE.name, default_mode="hosted")
    if mem.documents("Coding"):
        raise SystemExit("the Coding memory is not empty: capture on a fresh account")
    if OUT.exists():
        shutil.rmtree(OUT / "work", ignore_errors=True)
    project = OUT / "work" / "quillmate"
    shutil.copytree(HERE / "video" / "quillmate", project)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    home = OUT / "work" / "membase-home"
    env = {
        **os.environ,
        "MEMBASE_HOME": str(home),
        "MEMBASE_CONTAINER": "Coding",
        "MEMBASE_MCP_URL": os.environ["MEMBASE_BASE_URL"].rstrip("/") + "/mcp-http",
        "MEMBASE_HOOK_PYTHON": sys.executable,
        "MEMBASE_RECALL_BUDGET": "30",
        # Claude Code's own auto-memory would also keep the decision, and the video could no
        # longer show that the second session knew it from Membase. Off for these runs.
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    }
    print("warming the hosted Memory")
    mem.recall("invoice numbers", container="Coding", wait=180)

    t0 = time.monotonic()
    log = home / "hooks.log"
    first = run_session(SESSIONS[0], project, env, t0)
    own = Path.home() / ".claude" / "projects" / str(project).replace("/", "-") / "memory"
    if own.exists() and any(own.iterdir()):
        raise SystemExit(f"Claude Code wrote its own memory ({own}); the run cannot show Membase")
    saving = round(time.monotonic() - t0, 3)
    saved = wait_saved(log)
    print("saved:", saved)
    learned = wait_learned(mem)
    learned_at = round(time.monotonic() - t0, 3)
    print("learned:", learned)
    mem.recall("invoice numbers", container="Coding", wait=60)  # keep the box warm for session 2
    second = run_session(SESSIONS[1], project, env, t0)
    prompt_hits = [x for x in log.read_text().splitlines() if " prompt " in x][-1:]
    print("session 2 recall:", prompt_hits)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "capture.json").write_text(
        json.dumps(
            {
                "sessions": [first, second],
                "between": {
                    "saving": saving,
                    "learned_at": learned_at,
                    "saved": saved,
                    "learning": learned,
                },
                "hook_log": log.read_text().splitlines(),
            },
            indent=1,
        )
    )
    print(OUT / "capture.json")


if __name__ == "__main__":
    main()
