"""Membase memory hooks for coding agents: Claude Code, Codex CLI and Gemini CLI.

    membase_memory.py <client> <event>          # a hook: the event's JSON arrives on stdin
    membase_memory.py <client> flush|search '<json>' # internal: detached workers

client: claude | codex | gemini
event:  session-start  inject what memory knows about the user and this project
        prompt         search memory for the prompt and inject the top hits (hard time budget)
        stop           remember the assistant's last reply (Codex / Gemini, which have no
                       transcript we can rely on)
        session-end    save the session once, from a detached process

One rule above all: a hook never blocks the user. Every failure is logged to
~/.membase/hooks.log and the hook exits 0 with no output.

Settings come from the environment, then from ~/.membase/config.env (KEY=VALUE lines):
    MEMBASE_API_KEY        a developer key (Connect > Developer keys); required
    MEMBASE_BASE_URL       default https://api.app.membase.ai
    MEMBASE_CONTAINER      the Memory to save to and search (name or id); see resolve_container()
    MEMBASE_RECALL_BUDGET  seconds a prompt search may take before the hook gives up (default 10)
    MEMBASE_AUTOSAVE       0 to stop saving sessions (recall still works)
    MEMBASE_HOME           where config.env, the log and the state live (default ~/.membase)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

HOME = Path(os.environ.get("MEMBASE_HOME") or Path.home() / ".membase").expanduser()
STATE = HOME / "state"
LOG = HOME / "hooks.log"

# Per-message and per-session caps for what gets saved: enough for decisions and their reasons,
# never a pasted log.
MSG_CHARS = 1500
SESSION_CHARS = 12000
MIN_SESSION_CHARS = 120
# A Codex / Gemini session with no SessionEnd is saved once it has been quiet this long.
IDLE_FLUSH_SECONDS = 20 * 60


# ---- settings and logging ---------------------------------------------------------------


def load_config() -> None:
    path = Path(os.environ.get("MEMBASE_CONFIG") or HOME / "config.env").expanduser()
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:]
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value


def log(client: str, event: str, msg: str) -> None:
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{stamp} {client:<6} {event:<13} {msg}\n")
    except OSError:
        pass


def membase():
    from membase import Membase  # noqa: PLC0415 - imported late so a missing SDK is logged

    key = os.environ.get("MEMBASE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("MEMBASE_API_KEY is not set (environment or ~/.membase/config.env)")
    return Membase(
        api_key=key, base_url=os.environ.get("MEMBASE_BASE_URL") or None, timeout=30, max_retries=0
    )


# ---- which project, which container -----------------------------------------------------


def project_of(cwd: str) -> tuple[str, str]:
    """(name, root): the git top level when there is one, else the working directory."""
    root = cwd or os.getcwd()
    try:
        out = subprocess.run(
            ["git", "-C", root, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            root = out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(root).name or root, root


def resolve_container(client, project: str) -> tuple[str | None, str]:
    """(id, name) of the Memory this project's sessions go to and are searched in.

    1. MEMBASE_CONTAINER, by id or by name (a name that does not exist is an error);
    2. a Memory named like the project (its git folder name), ignoring case;
    3. a Memory named "Coding";
    4. the only Memory the key reaches.
    Otherwise (None, ""): search everything in reach, save nothing, and say so in the log.
    """
    containers = client.containers.list()["containers"]
    wanted = os.environ.get("MEMBASE_CONTAINER", "").strip()
    if wanted:
        for c in containers:
            if wanted in (c["id"], c["name"]) or c["name"].lower() == wanted.lower():
                return c["id"], c["name"]
        names = ", ".join(c["name"] for c in containers) or "none"
        raise RuntimeError(
            f"MEMBASE_CONTAINER={wanted!r} is not a Memory this key reaches ({names})"
        )
    for target in (project.lower(), "coding"):
        for c in containers:
            if c["name"].lower() == target:
                return c["id"], c["name"]
    if len(containers) == 1:
        return containers[0]["id"], containers[0]["name"]
    return None, ""


# ---- reading memory, inside a time budget ------------------------------------------------


def within(seconds: float, fn, *args):
    """fn(*args) on a daemon thread; (result, None) or (None, error-or-'timeout')."""
    box: dict = {}

    def run() -> None:
        try:
            box["out"] = fn(*args)
        except Exception as e:  # noqa: BLE001 - reported to the caller
            box["err"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        return None, "timeout"
    return box.get("out"), box.get("err")


_WIKILINK = re.compile(r"\s*\[\[[^\]]+\]\]")


def hits_of(result: dict | None, limit: int) -> list[str]:
    out = []
    for r in (result or {}).get("results", [])[:limit]:
        text = _WIKILINK.sub("", str(r.get("content") or ""))
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            out.append(text[:600] + ("…" if len(text) > 600 else ""))
    return out


def emit(event_name: str, context: str) -> None:
    """Context for the model, in the JSON shape all three CLIs read."""
    if context:
        out = {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": context}}
        sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


def on_session_start(cli: str, data: dict) -> None:
    project, _ = project_of(data.get("cwd", ""))
    budget = float(os.environ.get("MEMBASE_RECALL_BUDGET") or 10)
    started = time.monotonic()
    client = membase()
    resolved, err = within(budget, resolve_cached, client, project)
    if err:
        raise err if isinstance(err, Exception) else RuntimeError(f"container lookup: {err}")
    cid, cname = resolved
    query = f"{project}: decisions, conventions, open work and the user's preferences"
    profile_box: dict = {}

    def profile() -> None:
        try:
            profile_box["out"] = client.profile()
        except Exception as e:  # noqa: BLE001 - a key without profile access is normal
            profile_box["err"] = e

    p = threading.Thread(target=profile, daemon=True)
    p.start()
    left = max(1.0, budget - (time.monotonic() - started))
    hits, answered = recall(cli, data.get("session_id") or "", query, project, left)
    p.join(max(0.5, budget - (time.monotonic() - started)))

    lines = []
    prof = profile_box.get("out") or {}
    facts = [_fact(f) for f in (prof.get("static") or [])[:8]] + [
        _fact(f) for f in (prof.get("dynamic") or [])[:4]
    ]
    if facts:
        lines.append("About the user:")
        lines += [f"- {f}" for f in facts]
    if hits:
        lines.append(f"From past sessions on {project}:")
        lines += [f"- {h}" for h in hits]
    # Not answered in time: the account's memory is waking or busy. The search keeps going
    # (it wakes the memory) and its result arrives with the first prompt.
    cold = not answered
    where = f'the "{cname}" Memory' if cname else "every Memory this key reaches"
    if lines:
        context = (
            f"<membase-memory>\nLong-term memory (Membase, {where}) for this project. "
            "It may be out of date; prefer the code when they disagree.\n"
            + "\n".join(lines)
            + "\nThe membase MCP tools (search_memories, add_memory) reach the same memory."
            "\n</membase-memory>"
        )
    elif cold:
        context = (
            "<membase-memory>Long-term memory (Membase) is still searching past sessions on this "
            "project; what it finds will be added to the next prompt.</membase-memory>"
        )
    else:
        context = ""
    emit(data.get("hook_event_name") or "SessionStart", context)
    log(
        cli,
        "session-start",
        f"project={project} memory={cname or '-'} facts={len(facts)} "
        f"hits={len(hits)} cold={cold} {time.monotonic() - started:.1f}s",
    )
    if cli != "claude":
        sweep_idle(cli, current=data.get("session_id", ""))
    flush_stale_pending(cli)


def on_prompt(cli: str, data: dict) -> None:
    prompt = (data.get("prompt") or "").strip()
    sid = data.get("session_id") or ""
    if cli != "claude":
        buffer_turn(cli, data, "user", prompt)
    # Commands and one-word replies ("yes", "go on") are not worth a search.
    if prompt.startswith("/") or len(prompt) < 12:
        return
    budget = float(os.environ.get("MEMBASE_RECALL_BUDGET") or 10)
    started = time.monotonic()
    project, _ = project_of(data.get("cwd", ""))
    late = take_late(cli, sid)
    hits, waited = recall(cli, sid, prompt[:1000], project, budget)
    seconds = time.monotonic() - started
    blocks = []
    if hits:
        blocks.append(
            "Possibly relevant, from past sessions in long-term memory (Membase). "
            "Use it if it applies; verify against the code.\n" + "\n".join(f"- {h}" for h in hits)
        )
    for item in late:
        blocks.append(
            f'Found by memory after an earlier message ("{item["query"][:80]}") '
            "had moved on:\n" + "\n".join(f"- {h}" for h in item["hits"])
        )
    if blocks:
        emit(
            data.get("hook_event_name") or "UserPromptSubmit",
            "<membase-memory>\n" + "\n\n".join(blocks) + "\n</membase-memory>",
        )
    log(
        cli,
        "prompt",
        (
            f"hits={len(hits)}"
            if waited
            else f"still searching after the {budget:g}s "
            "budget; the result goes with the next prompt"
        )
        + f" late={len(late)} {seconds:.1f}s",
    )


def recall(cli: str, sid: str, query: str, project: str, budget: float) -> tuple[list[str], bool]:
    """Search memory in a process of its own and wait for it up to `budget` seconds.

    (hits, True) when it answered in time. Otherwise (`[]`, False): the search keeps going,
    and its result waits in state/recall/ for this session's next prompt (take_late). One
    search per prompt either way; a slow memory costs a turn of delay, never a lost answer."""
    folder = STATE / "recall"
    out = folder / f"{cli}-{_safe(sid)}-{time.time_ns()}.json"
    folder.mkdir(parents=True, exist_ok=True)
    spawn(cli, "search", {"query": query, "project": project, "out": str(out)})
    deadline = time.monotonic() + budget
    while time.monotonic() < deadline:
        if out.is_file():
            result = _read(out, {})
            out.unlink(missing_ok=True)
            return result.get("hits", []), True
        time.sleep(0.1)
    return [], False


def run_search(cli: str, payload: dict) -> None:
    """The detached half of recall(): one search, its hits written atomically to `out`."""
    started = time.monotonic()
    client = membase()
    client._http.timeout = 120  # noqa: SLF001 - off the user's path, so it may take its time
    cid, _ = resolve_cached(client, payload["project"])
    found = client.search(payload["query"], container=cid, limit=5)
    hits = hits_of(found, 5)
    unheard = [c.get("error") for c in found.get("containers", []) if c.get("error")]
    _write(
        Path(payload["out"]),
        {
            "query": payload["query"],
            "hits": hits,
            "unheard": unheard,
            "seconds": round(time.monotonic() - started, 1),
        },
    )
    log(cli, "search", f"hits={len(hits)} unheard={len(unheard)} {time.monotonic() - started:.1f}s")


def take_late(cli: str, sid: str) -> list[dict]:
    """Results of this session's earlier searches that finished after their prompt moved on."""
    folder = STATE / "recall"
    late = []
    for path in sorted(folder.glob(f"{cli}-{_safe(sid)}-*.json")) if folder.is_dir() else []:
        item = _read(path, None)
        path.unlink(missing_ok=True)
        if item and item.get("hits"):
            late.append(item)
    return late[-2:]


def _fact(f) -> str:
    if isinstance(f, dict):
        return str(f.get("content") or f.get("fact") or f.get("text") or json.dumps(f))
    return str(f)


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)


def resolve_cached(client, project: str) -> tuple[str | None, str]:
    """resolve_container(), remembered for ten minutes so a prompt search costs one request."""
    cache = STATE / "containers.json"
    key = f"{os.environ.get('MEMBASE_BASE_URL', '')}|{os.environ.get('MEMBASE_CONTAINER', '')}|{project}"
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    hit = saved.get(key)
    if hit and time.time() - hit["at"] < 600:
        return hit["id"], hit["name"]
    cid, name = resolve_container(client, project)
    saved[key] = {"id": cid, "name": name, "at": time.time()}
    STATE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(saved), encoding="utf-8")
    return cid, name


# ---- what a session said ----------------------------------------------------------------

_NOISE = (
    "<task-notification",
    "<command-name>",
    "<command-message>",
    "<local-command",
    "[Request interrupted",
)
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def claude_turns(transcript: Path) -> list[dict]:
    """User and assistant text from a Claude Code transcript (JSONL): no tool calls, tool
    output, thinking, meta lines, sub-agents or compaction summaries. Consecutive assistant
    lines (one per content block) join into one reply."""
    turns: list[dict] = []
    for raw in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            o = json.loads(raw)
        except ValueError:
            continue
        kind = o.get("type")
        if kind not in ("user", "assistant") or not isinstance(o.get("message"), dict):
            continue
        if o.get("isMeta") or o.get("isSidechain") or o.get("isCompactSummary"):
            continue
        text = _REMINDER.sub("", _text_of(o["message"].get("content"))).strip()
        if not text or text.startswith(_NOISE):
            continue
        uid = o.get("uuid") or str(hash(raw))
        if turns and turns[-1]["role"] == kind == "assistant":
            turns[-1]["text"] += "\n" + text
            turns[-1]["ids"].append(uid)
        else:
            turns.append({"role": kind, "text": text, "ids": [uid]})
    return turns


def condense(turns: list[dict], *, header: str) -> str:
    """The session as `User:` / `Assistant:` lines, each message trimmed, the whole kept under
    SESSION_CHARS by dropping middle turns (the first request and the latest turns stay)."""

    def clip(t: str) -> str:
        t = re.sub(r"\n{3,}", "\n\n", t.strip())
        return t if len(t) <= MSG_CHARS else t[:MSG_CHARS] + " […]"

    lines = [f"{'User' if t['role'] == 'user' else 'Assistant'}: {clip(t['text'])}" for t in turns]
    keep_head = lines[:1]
    tail: list[str] = []
    size = len(header) + sum(len(x) for x in keep_head)
    for line in reversed(lines[1:]):
        if size + len(line) > SESSION_CHARS:
            break
        tail.insert(0, line)
        size += len(line)
    dropped = len(lines) - len(keep_head) - len(tail)
    gap = [f"[… {dropped} earlier messages left out …]"] if dropped else []
    return "\n\n".join([header, *keep_head, *gap, *tail])


# ---- saving: once per session, from a detached process ----------------------------------


def _session_state(cli: str, session_id: str) -> Path:
    return STATE / "sessions" / f"{cli}-{re.sub(r'[^A-Za-z0-9_.-]', '_', session_id)}.json"


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def buffer_turn(cli: str, data: dict, role: str, text: str) -> None:
    """Codex and Gemini: keep the session's turns ourselves (their transcript format is not a
    stable interface), from the prompt and the final reply each hook is handed."""
    text = (text or "").strip()
    sid = data.get("session_id") or ""
    if not text or not sid:
        return
    path = _session_state(cli, sid)
    state = _read(path, {"turns": [], "saved": 0})
    state.update(cwd=data.get("cwd") or state.get("cwd", ""), touched=time.time())
    state["turns"].append({"role": role, "text": text})
    _write(path, state)


def on_stop(cli: str, data: dict) -> None:
    reply = data.get("last_assistant_message") or data.get("prompt_response") or ""
    buffer_turn(cli, data, "assistant", reply)
    sweep_idle(cli, current=data.get("session_id", ""))


def on_session_end(cli: str, data: dict) -> None:
    if os.environ.get("MEMBASE_AUTOSAVE", "1").strip() == "0":
        log(cli, "session-end", "autosave is off (MEMBASE_AUTOSAVE=0)")
        return
    sid = data.get("session_id") or ""
    cwd = data.get("cwd") or ""
    if cli == "claude":
        path = Path(data.get("transcript_path") or "")
        if not path.is_file():
            log(cli, "session-end", f"no transcript at {path}")
            return
        turns = claude_turns(path)
        state_path = _session_state(cli, sid)
        state = _read(state_path, {"saved_ids": []})
        saved = set(state["saved_ids"])
        # A resumed session saves only what is new since its last save.
        fresh = [t for t in turns if not set(t["ids"]) <= saved]
        queue_save(cli, sid, cwd, fresh, reason=data.get("reason", ""))
        state["saved_ids"] = sorted(saved | {i for t in turns for i in t["ids"]})[-5000:]
        _write(state_path, state)
    else:
        save_buffer(cli, sid, reason=data.get("reason", "end"))


def save_buffer(cli: str, sid: str, *, reason: str) -> None:
    path = _session_state(cli, sid)
    state = _read(path, None)
    if not state:
        return
    fresh = state["turns"][state.get("saved", 0) :]
    queue_save(cli, sid, state.get("cwd", ""), fresh, reason=reason)
    state["saved"] = len(state["turns"])
    _write(path, state)


def sweep_idle(cli: str, *, current: str) -> None:
    """Codex builds without SessionEnd: save other sessions that have gone quiet."""
    folder = STATE / "sessions"
    if not folder.is_dir():
        return
    for path in folder.glob(f"{cli}-*.json"):
        state = _read(path, None)
        if not state or path.stem == f"{cli}-{current}":
            continue
        quiet = time.time() - state.get("touched", 0)
        if quiet > IDLE_FLUSH_SECONDS and state.get("saved", 0) < len(state.get("turns", [])):
            save_buffer(cli, path.stem[len(cli) + 1 :], reason=f"idle {int(quiet // 60)} min")


def queue_save(cli: str, sid: str, cwd: str, turns: list[dict], *, reason: str) -> None:
    project, root = project_of(cwd)
    users = [t for t in turns if t["role"] == "user"]
    if not users:
        log(cli, "session-end", f"session {sid[:8]}: nothing new to save")
        return
    branch = ""
    try:
        out = subprocess.run(
            ["git", "-C", root, "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        branch = out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    name = {"claude": "Claude Code", "codex": "Codex", "gemini": "Gemini CLI"}[cli]
    header = (
        f"{name} session on project {project} ({root}"
        + (f", branch {branch}" if branch else "")
        + f"), {day}. User and assistant messages only; tool calls and output left out."
    )
    text = condense(turns, header=header)
    if len(text) - len(header) < MIN_SESSION_CHARS:
        log(cli, "session-end", f"session {sid[:8]}: too short to save ({len(text)} chars)")
        return
    title = f"{name} · {project} · {day} · {users[0]['text'][:60].strip()}"
    job = {
        "cli": cli,
        "session": sid,
        "project": project,
        "cwd": root,
        "title": title,
        "text": text,
        "reason": reason,
        "queued": time.time(),
    }
    pending = (
        STATE / "pending" / f"{cli}-{re.sub(r'[^A-Za-z0-9_.-]', '_', sid)}-{int(time.time())}.json"
    )
    _write(pending, job)
    spawn(cli, "flush", {"file": str(pending)})
    log(
        cli,
        "session-end",
        f"session {sid[:8]}: {len(turns)} messages, {len(text)} chars queued ({reason})",
    )


def spawn(cli: str, event: str, payload: dict) -> None:
    """Run `event` in a process of its own that outlives the CLI (SessionEnd hooks get about
    1.5 s in Claude Code, 1–3 s in Codex, and none in Gemini CLI)."""
    if os.environ.get("MEMBASE_HOOK_INLINE") == "1":  # tests: run it here and now
        RUNNERS[event](cli, payload)
        return
    # Through the launcher again, not sys.executable: under `uv run --with` that interpreter
    # lives in a temporary environment uv deletes as soon as this hook exits.
    launcher = Path(__file__).with_name("run.sh")
    cmd = [str(launcher)] if launcher.is_file() else [sys.executable, os.path.abspath(__file__)]
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("VIRTUAL_ENV", "UV_RUN_RECURSION_DEPTH", "PYTHONHOME")
    }
    subprocess.Popen(
        [*cmd, cli, event, json.dumps(payload)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        env=env,
    )


def run_flush(cli: str, payload: dict) -> None:
    path = Path(payload["file"])
    job = _read(path, None)
    if not job:
        return
    started = time.monotonic()
    client = membase()
    cid, cname = resolve_cached(client, job["project"])
    if not cid:
        n = len(client.containers.list()["containers"])
        raise RuntimeError(
            f"not saved: this key reaches {n} Memories and none is named {job['project']!r} or "
            "'Coding'; set MEMBASE_CONTAINER (the session stays queued in "
            f"{path.parent} and is retried at the next session start)"
        )
    out = client.memories.add(job["text"], container=cid, title=job["title"][:200])
    path.unlink(missing_ok=True)
    log(
        cli,
        "saved",
        f"session {job['session'][:8]} -> {cname} document={out.get('document_id')} "
        f"status={out.get('status')} {time.monotonic() - started:.1f}s",
    )


def flush_stale_pending(cli: str) -> None:
    """Retry saves that did not go through (offline, no container yet), and drop search
    results no prompt came back for."""
    recalls = STATE / "recall"
    for path in recalls.glob("*.json") if recalls.is_dir() else []:
        if time.time() - path.stat().st_mtime > 3600:
            path.unlink(missing_ok=True)
    folder = STATE / "pending"
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        if time.time() - path.stat().st_mtime > 120:
            path.touch()
            spawn(cli, "flush", {"file": str(path)})


RUNNERS = {"flush": run_flush, "search": run_search}
EVENTS = {
    "session-start": on_session_start,
    "prompt": on_prompt,
    "stop": on_stop,
    "session-end": on_session_end,
}


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] not in ("claude", "codex", "gemini"):
        print(__doc__, file=sys.stderr)
        return 2
    cli, event = sys.argv[1], sys.argv[2]
    load_config()
    try:
        if event in RUNNERS:
            RUNNERS[event](cli, json.loads(sys.argv[3]))
            return 0
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        EVENTS[event](cli, data)
    except Exception as e:  # noqa: BLE001 - a memory hook must never stop the agent
        log(cli, event, f"error: {type(e).__name__}: {e}")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    code = main()
    # Daemon threads may still hold a slow request; leave without waiting for them.
    os._exit(code)
