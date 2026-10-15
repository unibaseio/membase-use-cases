"""End-to-end check of the hooks against the real API (hosted).

    DEMO_ENV_FILE=.secrets/01-coding-memory.env uv run 01-coding-memory/smoke.py
    ... --no-claude    skip the real `claude -p` run at the end

1. The SessionEnd hook is handed a Claude Code transcript (fixtures/claude-session.jsonl, the
   real JSONL format) about a made-up project decision. It must return at once and save the
   session from a detached process: user and assistant text only, no tool output.
2. Wait until Membase has learned it.
3. The UserPromptSubmit hook gets a related prompt; the context it injects must hold the fact.
4. If the `claude` CLI is installed and signed in: one real `claude -p` run with the plugin
   loaded (--plugin-dir). Reported, never failed on.

Every hook runs through claude-plugin/hooks/run.sh, exactly as a CLI starts it. Exits non-zero
with the reason on any failure of steps 1-3.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE / "claude-plugin" / "hooks"))
import membase_memory  # noqa: E402

from demokit import Memory  # noqa: E402

RUN = HERE / "claude-plugin" / "hooks" / "run.sh"
FIXTURE = HERE / "fixtures" / "claude-session.jsonl"
PROMPT = "I'm adding the invoice export endpoint. How should new invoice numbers be generated?"


def hook(env: dict, cli: str, event: str, payload: dict, timeout: float = 60) -> tuple[str, float]:
    started = time.monotonic()
    out = subprocess.run(
        [str(RUN), cli, event],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    assert out.returncode == 0, f"{event} hook exited {out.returncode}: {out.stderr[-500:]}"
    return out.stdout, time.monotonic() - started


def context_of(stdout: str) -> str:
    if not stdout.strip():
        return ""
    return json.loads(stdout)["hookSpecificOutput"]["additionalContext"]


def main() -> None:
    mem = Memory("01-coding-memory", default_mode="hosted")
    assert mem.mode == "hosted", "this demo runs on hosted Membase"
    home = Path(tempfile.mkdtemp(prefix="smoke-01-"))
    project = home / "quillmate"
    project.mkdir()
    env = {**os.environ, "MEMBASE_HOME": str(home / "membase")}
    log = home / "membase" / "hooks.log"
    print(
        f"base: hosted {os.environ.get('MEMBASE_BASE_URL', '')}  MEMBASE_HOME={env['MEMBASE_HOME']}"
    )

    # 0. What a session becomes: no tool calls, tool output, thinking or command noise.
    turns = membase_memory.claude_turns(FIXTURE)
    saved_text = membase_memory.condense(turns, header="header")
    for noise in (
        "TOOL-OUTPUT-SHOULD-NOT-BE-SAVED",
        "<command-name>",
        "system-reminder",
        "Let me look at the numbering code first",
        "Request interrupted",
    ):
        assert noise not in saved_text, f"{noise!r} would be saved"
    assert "INV-" in saved_text and "ULID" in saved_text
    print(
        f"transcript: {len(FIXTURE.read_text().splitlines())} lines -> {len(turns)} messages, "
        f"{len(saved_text)} chars to save"
    )

    # The fixture as this run's own session, in the project folder.
    session = str(uuid.uuid4())
    transcript = home / f"{session}.jsonl"
    with transcript.open("w") as f:
        for line in FIXTURE.read_text().splitlines():
            o = json.loads(line)
            if "cwd" in o:
                o["cwd"] = str(project)
            if "sessionId" in o:
                o["sessionId"] = session
            f.write(json.dumps(o) + "\n")
    base = {"session_id": session, "transcript_path": str(transcript), "cwd": str(project)}

    out, secs = hook(
        env,
        "claude",
        "session-start",
        {**base, "hook_event_name": "SessionStart", "source": "startup"},
    )
    print(f"SessionStart: {secs:.1f}s, {'context injected' if out.strip() else 'nothing injected'}")

    # 1. Save the session. The hook must hand off and return well inside Claude Code's budget.
    out, secs = hook(
        env,
        "claude",
        "session-end",
        {**base, "hook_event_name": "SessionEnd", "reason": "prompt_input_exit"},
    )
    assert out == "", f"SessionEnd printed {out!r}"
    print(f"SessionEnd: returned in {secs:.2f}s (the save runs detached)")
    deadline = time.monotonic() + 120
    document = None
    while time.monotonic() < deadline and not document:
        time.sleep(2)
        text = log.read_text() if log.is_file() else ""
        assert " flush " not in text, f"the detached save failed:\n{text}"
        m = re.search(r"saved\s+session \S+ -> (\S+) document=(\S+) status=(\S+) ([\d.]+)s", text)
        if m:
            document = m.group(2)
            print(
                f"saved: Memory {m.group(1)!r}, document {document}, status {m.group(3)}, "
                f"memories.add took {m.group(4)}s"
            )
    assert document, f"no save within 120s; log:\n{log.read_text() if log.is_file() else '(none)'}"

    # 2. Wait for learning.
    started = time.monotonic()
    while True:
        doc = mem.client.documents.get(document)
        run_info = doc.get("learning_run") or {}
        if doc.get("learned") or run_info.get("status") not in (None, "queued", "running"):
            break
        assert time.monotonic() - started < 900, f"not learned after 15 minutes: {doc}"
        time.sleep(10)
    if doc.get("learned"):
        print(
            f"learned after {time.monotonic() - started:.0f}s (run {run_info.get('id')} {run_info.get('status')})"
        )
    else:
        print(
            f"WARNING: learning run {run_info.get('id')} ended {run_info.get('status')!r} after "
            f"{time.monotonic() - started:.0f}s without learning {document}; testing recall anyway"
        )

    # 3. A new session's prompts get the fact. A prompt waits for memory up to the budget
    # (MEMBASE_RECALL_BUDGET, default 10 s); a search that takes longer is delivered with the
    # next prompt. That is what a user sees, so the check is: within a few prompts of a new
    # session, the decision is in the injected context, and no prompt is held past the budget.
    budget = float(os.environ.get("MEMBASE_RECALL_BUDGET") or 10)
    later = {**base, "session_id": str(uuid.uuid4())}
    context = ""
    for attempt in range(1, 7):
        out, secs = hook(
            env,
            "claude",
            "prompt",
            {**later, "hook_event_name": "UserPromptSubmit", "prompt": PROMPT},
        )
        context = context_of(out)
        print(f"UserPromptSubmit {attempt}: returned in {secs:.1f}s, {len(context)} chars injected")
        assert secs < budget + 4, f"the prompt hook held the user {secs:.1f}s (budget {budget:g}s)"
        if "ULID" in context:
            break
        time.sleep(5)
    assert "ULID" in context, (
        f"the injected context does not hold the decision:\n{context}\n{log.read_text()}"
    )
    print("injected:\n  " + context.replace("\n", "\n  "))

    if "--no-claude" not in sys.argv:
        real_claude(env, project)
    print("OK")


def real_claude(env: dict, project: Path) -> None:
    """One real Claude Code run with the plugin loaded. Reported, not asserted."""
    if not shutil.which("claude"):
        print("claude -p: skipped (claude is not installed)")
        return
    base = os.environ.get("MEMBASE_BASE_URL", "https://api.app.membase.ai").rstrip("/")
    env = {**env, "MEMBASE_MCP_URL": base + "/mcp-http"}
    question = (
        "How are new invoice numbers generated in this project, and what happens to old "
        "invoices? Two sentences, from the context you were given; do not use tools."
    )
    started = time.monotonic()
    try:
        out = subprocess.run(
            [
                "claude",
                "-p",
                "--plugin-dir",
                str(HERE / "claude-plugin"),
                "--output-format",
                "stream-json",
                "--verbose",
                question,
            ],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        print("claude -p: timed out after 300s")
        return
    events = [json.loads(x) for x in out.stdout.splitlines() if x.startswith("{")]
    init = next((e for e in events if e.get("subtype") == "init"), {})
    result = next((e for e in events if e.get("type") == "result"), {})
    hooks = [e.get("hook_event") for e in events if e.get("subtype") == "hook_response"]
    mcp = [s for s in init.get("mcp_servers", []) if "membase" in s.get("name", "")]
    print(
        f"claude -p: {time.monotonic() - started:.0f}s, exit {out.returncode}, hooks run {hooks}, "
        f"MCP {mcp}"
    )
    print(f"  answer: {result.get('result') or out.stderr[-300:]!r}")
    if result.get("result") and "ULID" in result["result"]:
        print("  the answer used the remembered decision")
    time.sleep(15)  # the SessionEnd save is detached; give it a moment before reading the log
    print(
        "  hook log:\n    "
        + (Path(env["MEMBASE_HOME"]) / "hooks.log").read_text().strip().replace("\n", "\n    ")
    )


if __name__ == "__main__":
    main()
