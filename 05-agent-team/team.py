"""The agent team: four LLM tool-calling agents sharing one Membase container ("Team").

    Investigator  finds the cause of ISSUE.md and records it in shared memory
    Fixer         searches shared memory first, patches the code, records the decision
    Reviewer      reads shared memory and the diff, runs the tests, approves or rejects
    Auditor       holds a READ-ONLY key: it can search, and its write is refused by Membase

Each agent calls Membase with its own key (MEMBASE_KEY_<ROLE> when set, else MEMBASE_API_KEY;
the Auditor always uses MEMBASE_READ_KEY). A hosted write is searchable only after Membase has
learned it, so the run waits for each writer's memory to be learned before the next agent
starts, and reports that wait as it happens.

`run()` yields events (dicts) that the page draws as a timeline and the smoke test checks.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from membase import Membase
from membase.errors import MembaseError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from demokit import config, llm  # noqa: E402

FIXTURE = HERE / "fixture"
CONTAINER = "Team"
MAX_STEPS = 12
MAX_SEARCHES = 3
LEARN_TIMEOUT = 900
WIKILINK = re.compile(r"\s*\[\[[^\]]+\]\]")  # the memory's own page links: noise to a reader
# The agents' model: DEMO_MODEL (demokit's default), unless TEAM_MODEL names another.
MODEL = os.environ.get("TEAM_MODEL") or config.model()


# ---- the agents ---------------------------------------------------------------------------

ROLES = {
    "Investigator": {
        "key": "write",
        "tools": ["list_files", "read_file", "run_tests", "search_memories", "add_memory"],
        "prompt": (
            "You are the Investigator on a small engineering team. Your job: find the root cause "
            "of the bug in ISSUE.md. Read the issue and the code, and run the tests. Do not fix "
            "anything. When you are sure of the cause, record exactly ONE finding in the team's "
            "shared memory with add_memory: name the file and function, the faulty line, why it "
            "causes the reported behavior, and which test shows it, in at most 60 words. Then post "
            "one short line to the team (under 20 words, plain, no preamble)."
        ),
        "task": "Investigate ISSUE-212.",
    },
    "Fixer": {
        "key": "write",
        "tools": [
            "search_memories",
            "list_files",
            "read_file",
            "propose_patch",
            "run_tests",
            "add_memory",
        ],
        "prompt": (
            "You are the Fixer on a small engineering team. Teammates record what they learn in "
            "shared memory. FIRST call search_memories to find what the team already knows about "
            "ISSUE-212 and build on it rather than re-investigating. Then read the file the finding "
            "names, fix the faulty line with propose_patch (by its line "
            "number), and run the tests. Only then record exactly ONE decision in shared memory with "
            "add_memory: what you changed, why, and the test result, in at most 50 words. Then "
            "post one short line to the team (under 20 words, plain, no preamble)."
        ),
        "task": "Fix ISSUE-212.",
    },
    "Reviewer": {
        "key": "write",
        "tools": ["search_memories", "show_diff", "read_file", "run_tests", "submit_verdict"],
        "prompt": (
            "You are the Reviewer on a small engineering team. Search shared memory for the "
            "investigation and the fix decision on ISSUE-212, look at the diff, and run the tests. "
            "Approve only if the patch fixes the root cause recorded in memory and the tests pass. "
            "Finish by calling submit_verdict with your reasons in at most two short sentences, "
            "citing what memory said. Do not write anything else."
        ),
        "task": "Review the fix for ISSUE-212.",
    },
    "Auditor": {
        "key": "read",
        "tools": ["search_memories", "add_memory"],
        "prompt": (
            "You are the Auditor. Search the team's shared memory for ISSUE-212 and check that "
            "the record holds a root cause and a fix decision. Then file a one-sentence audit "
            "note in shared memory with add_memory. Then report what happened in one short line "
            "(under 20 words), including any error."
        ),
        "task": "Audit the team's record of ISSUE-212.",
    },
}

TOOL_SPECS = {
    "list_files": ("List the files in the repository.", {}),
    "read_file": ("Read one file of the repository.", {"path": {"type": "string"}}),
    "run_tests": ("Run the test suite (python -m unittest) and return its output.", {}),
    "show_diff": ("The diff between the original code and the current working copy.", {}),
    "propose_patch": (
        "Replace one line of a file in the working copy (line numbers as read_file shows them).",
        {
            "path": {"type": "string"},
            "line": {"type": "integer", "description": "the line number to replace"},
            "new": {"type": "string", "description": "the corrected line"},
        },
    ),
    "search_memories": (
        "Search the team's shared long-term memory (Membase) in plain language.",
        {"query": {"type": "string"}},
    ),
    "add_memory": (
        "Record one fact in the team's shared long-term memory (Membase). One self-contained "
        "paragraph that names ISSUE-212.",
        {"content": {"type": "string"}},
    ),
    "submit_verdict": (
        "Approve or reject the fix, with reasons.",
        {"approve": {"type": "boolean"}, "reasons": {"type": "string"}},
    ),
}


def tool_schema(name: str) -> dict:
    desc, props = TOOL_SPECS[name]
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props, "required": list(props)},
        },
    }


# ---- one run --------------------------------------------------------------------------------


def keys() -> dict[str, str]:
    """Each agent's key: its own (MEMBASE_KEY_<ROLE>) when set, else the shared write key, or
    for the Auditor the read-only key."""
    write = config.require("MEMBASE_API_KEY", "the team's writers need a developer key")
    out = {}
    for role, spec in ROLES.items():
        own = os.environ.get(f"MEMBASE_KEY_{role.upper()}", "").strip()
        if spec["key"] == "read":
            out[role] = own or config.require(
                "MEMBASE_READ_KEY",
                "the Auditor needs a read-only developer key (bootstrap_hosted.py --read-key, "
                "or Connect > Developer keys > Read)",
            )
        else:
            out[role] = own or write
    return out


def key_card(role: str, key: str) -> dict:
    """What the page shows about an agent's key: whose it is, its level, its last characters."""
    own = bool(os.environ.get(f"MEMBASE_KEY_{role.upper()}", "").strip())
    return {
        "level": "read only" if ROLES[role]["key"] == "read" else "read & write",
        "own": own or ROLES[role]["key"] == "read",
        "hint": "…" + key[-4:],
    }


def client_for(key: str) -> Membase:
    return Membase(api_key=key, base_url=os.environ.get("MEMBASE_BASE_URL") or None, timeout=180)


def team_container(client: Membase) -> str:
    for c in client.containers.list()["containers"]:
        if c["name"] == CONTAINER or c["id"] == CONTAINER:
            return c["id"]
    raise config.ConfigError(
        f"no Memory named {CONTAINER!r} reaches this key: create it in the app, or run "
        f"scripts/bootstrap_hosted.py --name 05-agent-team --containers {CONTAINER} --read-key"
    )


@dataclass
class Run:
    id: str
    workdir: Path
    container: str
    writes: list[dict] = field(default_factory=list)
    verdict: dict | None = None
    patched: bool = False
    searches: dict = field(default_factory=dict)


def run() -> Iterator[dict]:
    """The whole scenario, as events."""
    keyring = keys()
    clients = {role: client_for(k) for role, k in keyring.items()}
    container = team_container(clients["Investigator"])
    team_container(clients["Auditor"])  # the read key must reach the same Memory
    workdir = Path(tempfile.mkdtemp(prefix="agent-team-"))
    shutil.copytree(FIXTURE, workdir / "repo")
    r = Run(id=uuid.uuid4().hex[:6], workdir=workdir / "repo", container=container)
    yield {
        "type": "run",
        "run": r.id,
        "container": container,
        "agents": {role: key_card(role, keyring[role]) for role in ROLES},
    }
    try:
        for role in ROLES:
            before = len(r.writes)
            yield from agent(role, clients[role], r)
            if role == "Auditor" and not any(w["role"] == "Auditor" for w in r.writes):
                # The model chose not to write; show the platform's answer to the write anyway.
                yield {
                    "type": "note",
                    "role": role,
                    "text": "The Auditor did not try to write, so the run tries once with its key.",
                }
                yield from call_tool(
                    role,
                    clients[role],
                    r,
                    "add_memory",
                    {"content": f"ISSUE-212 audit note (run {r.id})."},
                )
            for w in r.writes[before:]:
                if w.get("document_id"):
                    yield from wait_learned(role, clients[role], w)
        yield {"type": "done", "run": r.id, "verdict": r.verdict, "writes": r.writes}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        for c in clients.values():
            c.close()


def agent(role: str, client: Membase, r: Run) -> Iterator[dict]:
    spec = ROLES[role]
    yield {"type": "agent", "role": role, "status": "start", "task": spec["task"]}
    files, _ = t_list_files(role, client, r)
    messages = [
        {
            "role": "system",
            "content": spec["prompt"] + " Only read paths that exist in the "
            "repository; the user message lists them.",
        },
        {"role": "user", "content": f"{spec['task']}\n\nRepository files:\n{files}"},
    ]
    tools = [tool_schema(t) for t in spec["tools"]]
    nudges = 0
    for _ in range(MAX_STEPS):
        out = llm.client().chat.completions.create(
            model=MODEL, messages=messages, tools=tools, temperature=0.2
        )
        msg = out.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if msg.content and msg.content.strip():
            yield {"type": "say", "role": role, "text": msg.content.strip()}
        if not msg.tool_calls:
            missing = unfinished(role, r)
            if missing and nudges < 2:
                # The model stopped before doing its job: remind it once or twice, visibly.
                nudges += 1
                yield {"type": "note", "role": role, "text": f"Reminder to the {role}: {missing}"}
                messages.append({"role": "user", "content": missing})
                continue
            break
        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except ValueError:
                args = {}
            result = None
            for event in call_tool(role, client, r, call.function.name, args):
                # Read it before yielding: whoever consumes the event may change it.
                result = event.get("result_for_model", result)
                yield event
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result or ""})
        if role == "Reviewer" and r.verdict:
            break
    yield {"type": "agent", "role": role, "status": "end"}


def unfinished(role: str, r: Run) -> str:
    """What the role was asked to do and has not done yet ("" when done)."""
    wrote = any(w["role"] == role and w.get("document_id") for w in r.writes)
    if role == "Investigator" and not wrote:
        return "You have not recorded your finding yet. Call add_memory with it now."
    if role == "Fixer" and not r.patched:
        return (
            "The code is not patched yet. Read the file, then call propose_patch with the "
            "number of the faulty line and the corrected line."
        )
    if role == "Fixer" and not wrote:
        return "Run the tests, then record your decision with add_memory."
    if role == "Reviewer" and not r.verdict:
        return "Call submit_verdict with your decision and reasons."
    return ""


def call_tool(role: str, client: Membase, r: Run, name: str, args: dict) -> Iterator[dict]:
    """Run one tool, yielding one `tool` event; its `result_for_model` goes back to the LLM."""
    started = time.monotonic()
    event: dict = {"type": "tool", "role": role, "name": name, "args": args}
    try:
        if name not in ROLES[role]["tools"]:
            raise ValueError(f"{role} has no tool {name}")
        result, shown = TOOLS[name](role, client, r, **args)
        event.update(ok=True, result=shown)
    except MembaseError as e:
        # The platform's own answer, shown as it came back (a read-only key's write is a 403).
        event.update(ok=False, refused=e.status == 403, status=e.status, error=str(e), body=e.body)
        result = f"Membase refused: HTTP {e.status} {json.dumps(e.body)}"
    except Exception as e:  # noqa: BLE001 - a bad tool call goes back to the model
        event.update(ok=False, error=f"{type(e).__name__}: {e}")
        result = f"error: {e}"
    event["seconds"] = round(time.monotonic() - started, 2)
    event["result_for_model"] = result if isinstance(result, str) else json.dumps(result)
    yield event


def wait_learned(role: str, client: Membase, write: dict) -> Iterator[dict]:
    """Poll the document until Membase has learned it, reporting the wait as it goes.

    A learning run that ends without learning (`failed`) is reported and the team goes on:
    the stored text is still there for search to read, and the next agent's search shows
    honestly whether it was found."""
    started = time.monotonic()
    doc_id = write["document_id"]
    while True:
        doc = client.documents.get(doc_id)
        elapsed = round(time.monotonic() - started)
        learned = bool(doc.get("learned"))
        run_info = doc.get("learning_run") or {}
        status = run_info.get("status")
        yield {
            "type": "wait",
            "role": role,
            "document_id": doc_id,
            "seconds": elapsed,
            "learned": learned,
            "run_status": status,
            "run_id": run_info.get("id"),
        }
        if learned:
            write["learned_after"] = elapsed
            return
        if status and status not in ("queued", "running"):
            write["learning_run"] = run_info
            yield {
                "type": "note",
                "role": role,
                "warn": True,
                "text": f"Membase's learning run {run_info.get('id')} ended '{status}' without "
                f"learning {doc_id} (after {elapsed}s). Going on: search can still read "
                "the stored text.",
            }
            return
        if elapsed > LEARN_TIMEOUT:
            raise RuntimeError(f"{doc_id} not learned after {LEARN_TIMEOUT}s")
        time.sleep(5)


# ---- tools ----------------------------------------------------------------------------------


def _path(r: Run, path: str) -> Path:
    p = (r.workdir / path.lstrip("/")).resolve()
    if r.workdir.resolve() not in p.parents and p != r.workdir.resolve():
        raise ValueError(f"{path} is outside the repository")
    return p


def t_list_files(role, client, r: Run):
    files = sorted(
        str(p.relative_to(r.workdir))
        for p in r.workdir.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    return "\n".join(files), files


def t_read_file(role, client, r: Run, path: str):
    text = _path(r, path).read_text(encoding="utf-8")
    numbered = "\n".join(f"{i:>4}| {line}" for i, line in enumerate(text.splitlines(), 1))
    return numbered, {"path": path, "lines": text.count("\n") + 1}


def t_run_tests(role, client, r: Run):
    out = subprocess.run(
        [sys.executable, "-m", "unittest", "-v"],
        cwd=r.workdir,
        capture_output=True,
        text=True,
        timeout=60,
    )
    text = (out.stdout + out.stderr)[-3000:]
    summary = text.strip().splitlines()[-1] if text.strip() else ""
    return text, {"passed": out.returncode == 0, "summary": summary}


def t_show_diff(role, client, r: Run):
    chunks = []
    for p in sorted(r.workdir.rglob("*.py")):
        rel = p.relative_to(r.workdir)
        orig = FIXTURE / rel
        a = orig.read_text().splitlines(keepends=True) if orig.exists() else []
        b = p.read_text().splitlines(keepends=True)
        chunks += difflib.unified_diff(a, b, f"a/{rel}", f"b/{rel}")
    diff = "".join(chunks) or "(no changes)"
    return diff, {"diff": diff}


def t_propose_patch(role, client, r: Run, path: str, line: int, new: str):
    """Replace line `line` (1-based, as read_file numbers it) with `new` (one or more lines)."""
    p = _path(r, path)
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    if not 1 <= int(line) <= len(lines):
        raise ValueError(f"{path} has lines 1-{len(lines)}; line {line} does not exist")
    old = lines[int(line) - 1]
    indent = old[: len(old) - len(old.lstrip())]
    body = new if new.startswith((" ", "\t")) or not indent else indent + new.lstrip()
    lines[int(line) - 1] = body.rstrip("\n") + "\n"
    p.write_text("".join(lines), encoding="utf-8")
    r.patched = True
    diff, _ = t_show_diff(role, client, r)
    return f"patched {path}\n{diff}", {"path": path, "diff": diff}


def t_search_memories(role, client, r: Run, query: str):
    count = r.searches.get(role, 0) + 1
    if count > MAX_SEARCHES:
        raise ValueError(f"search limit reached ({MAX_SEARCHES} per agent in this demo)")
    r.searches[role] = count
    out = client.search(query, container=r.container, limit=6)
    hits = [
        {"content": WIKILINK.sub("", h.get("content") or "").strip(), "score": h.get("score")}
        for h in out.get("results", [])
    ]
    unheard = [c.get("error") for c in out.get("containers", []) if c.get("error")]
    text = "\n".join(f"- {h['content']}" for h in hits) or "(nothing in memory matches)"
    if unheard:
        text += "\n(memory did not answer: " + "; ".join(unheard) + ")"
    return text, {"hits": hits, "unheard": unheard}


def t_add_memory(role, client, r: Run, content: str):
    if any(w["role"] == role and w.get("document_id") for w in r.writes):
        raise ValueError("one memory per agent in this demo; it is already recorded")
    if role == "Fixer" and not r.patched:
        raise ValueError(
            "record the decision after the fix: apply it with propose_patch and run the tests first"
        )
    attempt = {"role": role, "content": content}
    r.writes.append(attempt)
    out = client.memories.add(
        f"{role}: {content}", container=r.container, title=f"{role} · ISSUE-212 · run {r.id}"
    )
    attempt.update(document_id=out.get("document_id"), status=out.get("status"))
    return out, {
        "document_id": out.get("document_id"),
        "status": out.get("status"),
        "learning_run": (out.get("learning_run") or {}).get("status"),
    }


def t_submit_verdict(role, client, r: Run, approve: bool, reasons: str):
    r.verdict = {"approve": bool(approve), "reasons": reasons}
    return "verdict recorded", r.verdict


TOOLS = {
    "list_files": t_list_files,
    "read_file": t_read_file,
    "run_tests": t_run_tests,
    "show_diff": t_show_diff,
    "propose_patch": t_propose_patch,
    "search_memories": t_search_memories,
    "add_memory": t_add_memory,
    "submit_verdict": t_submit_verdict,
}


def feed(limit: int = 12) -> list[dict]:
    """What the Team Memory holds, newest first, with whether each is learned yet."""
    with client_for(config.require("MEMBASE_API_KEY", "the feed reads the Team Memory")) as c:
        container = team_container(c)
        docs = c.documents.list(container=container)["documents"][:limit]
        out = []
        for d in docs:
            # The list does not carry `learned`; one document read does.
            full = c.documents.get(d["id"])
            out.append(
                {
                    "id": d["id"],
                    "title": d.get("title"),
                    "created_at": d.get("created_at"),
                    "learned": bool(full.get("learned")),
                }
            )
        return out
