"""The coding-memory video: two real Claude Code sessions (video_capture.py), replayed in a
terminal at the pace they ran. Session 1 makes a decision; session 2 is a new process whose
code still has the old numbering, and Membase hands it the decision. Waits are shortened and
badged with their real length.

    DEMO_ENV_FILE=.secrets/<name>.env .venv/bin/python 01-coding-memory/video_capture.py
    DEMO_ENV_FILE=.secrets/<name>.env .venv/bin/python scripts/video/make.py 01-coding-memory
"""

import asyncio
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAPTURE = HERE.parent / "data" / "video" / HERE.name / "capture.json"

META = {
    "title": "Coding memory",
    "title_html": "Claude Code remembers<br>what you decided",
    "pitch": "Decide something in one session. A brand-new session, with no shared context, already knows it.",
    "base": "hosted",
    "port": 8701,
    "path": "static/video.html",
    "banner_from_recording": True,
    "line": "Decide in one Claude Code session. The next one already knows.",
    "explain": {
        "title": "Every session saves, the next recalls",
        "actors": [
            {"id": "you", "icon": "user", "label": "You", "kind": "user", "at": [170, 560]},
            {
                "id": "s1",
                "icon": "terminal",
                "label": "Session 1",
                "kind": "app",
                "at": [560, 400],
                "size": 150,
                "tint": "#0f172b",
                "ink": "#fff",
                "labelColor": "#fff",
            },
            {
                "id": "s2",
                "icon": "terminal",
                "label": "Session 2",
                "kind": "app",
                "at": [560, 720],
                "size": 150,
                "tint": "#0f172b",
                "ink": "#fff",
                "labelColor": "#fff",
            },
            {
                "id": "cc",
                "icon": "terminal",
                "label": "Claude Code",
                "kind": "frame",
                "box": [360, 220, 400, 700],
                "tint": "#1e293b",
                "ink": "#fff",
            },
            {
                "id": "mb",
                "kind": "membase",
                "base": "hosted",
                "key": "Developer key",
                "box": [1180, 300, 600, 400],
                "slots": [{"id": "coding", "label": "Coding memory", "icon": "folder"}],
            },
        ],
        "beats": [
            {
                "say": "Session 1 ends: the plugin saves it",
                "membase": "learn",
                "facts": ["New: INV-&lt;ULID&gt;", "Never renumber old"],
                "flows": [
                    {
                        "from": "you",
                        "to": "s1",
                        "token": {"label": "a decision", "icon": "message-circle"},
                    },
                    {
                        "from": "s1",
                        "to": "mb",
                        "token": {"label": "the session", "icon": "file-text"},
                    },
                ],
            },
            {
                "say": "A brand-new session recalls it",
                "membase": "recall",
                "hit": 0,
                "flows": [
                    {
                        "from": "you",
                        "to": "s2",
                        "token": {"label": "a prompt", "icon": "message-circle"},
                    },
                    {
                        "from": "s2",
                        "to": "mb",
                        "token": {"label": "the prompt", "icon": "search"},
                    },
                    {"from": "mb", "to": "s2", "token": "the decision"},
                ],
            },
            {
                "say": "Its answer uses the decision",
                "flows": [
                    {
                        "from": "s2",
                        "to": "you",
                        "token": "the answer",
                        "result": "INV-&lt;ULID&gt;",
                    }
                ],
            },
        ],
    },
}
SEED: list[str] = []
MARKS = [
    "INV-<ULID>",
    "ULIDs",
    "never renumber existing invoices",
    "kept forever",
    "keep their old numbers forever",
]


def results(session: dict) -> dict[str, str]:
    """Each tool call's output, by tool_use id, as Claude Code got it."""
    out = {}
    for e in session["events"]:
        ev = e["ev"]
        if ev.get("type") == "user":
            for b in ev["message"]["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    c = b.get("content")
                    if isinstance(c, list):
                        c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                    out[b["tool_use_id"]] = str(c or "")
    return out


def shown_result(name: str, text: str) -> list[str]:
    """What Claude Code prints under a tool call: a count for Read, the first lines for Bash."""
    text = re.sub(r"\S*/quillmate/", "", text).rstrip("\n")
    lines = text.splitlines()
    if name == "Read":
        return [f"Read {len(lines)} lines"]
    head = [ln.replace("\t", "  ")[:96] for ln in lines if ln.strip()][:2]
    more = len(lines) - len(head)
    return head + ([f"… +{more} lines (ctrl+o to expand)"] if more > 0 else [])


def clock(line: str) -> float:
    h, m, s = line.split()[1].split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def logged(cap: dict) -> list[tuple[float, str]]:
    """The plugin's log lines, each placed on the capture's clock: the session-end line is
    written as session 1's process exits."""
    lines = cap["hook_log"]
    end = next(ln for ln in lines if " session-end " in ln)
    zero = clock(end) - cap["sessions"][0]["ended"]
    return [(clock(ln) - zero, ln) for ln in lines]


def timeline(session: dict, log: list[tuple[float, str]], until: float) -> list:
    """(seconds after the session started, kind, value), in the order things happened: a tool
    call with its output, the text of the current answer block (a new block starts after a
    tool), and the plugin's log lines."""
    out, text, block = [], "", 0
    res = results(session)
    for e in session["events"]:
        t, ev = e["t"] - session["started"], e["ev"]
        if ev.get("type") == "assistant":
            for b in ev["message"]["content"]:
                if b.get("type") == "tool_use":
                    arg = b["input"].get("file_path") or b["input"].get("command") or ""
                    arg = re.sub(r"\S*/quillmate/", "", arg)
                    arg = arg if len(arg) < 76 else arg[:73] + "…"
                    out.append(
                        (t, "tool", (b["name"], arg, shown_result(b["name"], res.get(b["id"], ""))))
                    )
                    if text:
                        text, block = "", block + 1
        sev = ev.get("event") or {}
        if ev.get("type") == "stream_event" and sev.get("type") == "content_block_delta":
            d = sev.get("delta") or {}
            if d.get("type") == "text_delta":
                text += d["text"]
                out.append((t, "text", (block, text)))
    for t, line in log:
        if session["started"] <= t <= until:
            out.append((t - session["started"], "log", line))
    return sorted(out, key=lambda x: x[0])


async def replay(page, rec, items, prefix: str, *, on_log=None) -> str:
    """Play the items at the pace they happened; returns the last answer block's id. A wait
    of more than 3 s is played short, with its real length on the badge."""
    clock_, shown, last, spinning, started = 0.0, set(), "", False, False
    for t, kind, value in items:
        gap = t - clock_
        if gap > 3:
            if not spinning:
                await page.evaluate("() => term.spin('Thinking', 'spin')")
                spinning = True
            label = (
                "Claude Code works" if started else "Claude Code starts; the plugin asks Membase"
            )
            await rec.gap(label, gap, shown=1.6)
        elif gap > 0:
            await asyncio.sleep(min(gap, 0.25))
        clock_ = t
        if kind == "log":
            await page.evaluate("l => term.log(l)", value)
            if on_log:
                await on_log(value)
            continue
        started = True
        if spinning:
            await page.evaluate("() => term.unspin('spin')")
            spinning = False
        if kind == "tool":
            await page.evaluate("([n, a, r]) => term.tool(n, a, r)", list(value))
            continue
        block, text = value
        last = f"{prefix}-{block}"
        if last not in shown:
            await page.evaluate("id => term.answer(id)", last)
            await rec.focus(f"#{last}", pad=16)
            shown.add(last)
        await page.evaluate("([id, s, m]) => term.text(id, s, m)", [last, text.strip(), MARKS])
    if spinning:
        await page.evaluate("() => term.unspin('spin')")
    return last


def context(injected: list[dict], hook: str) -> list[str]:
    """What a hook added to the prompt, line by line, as Claude Code received it."""
    content = next((i["content"] for i in injected if i["hook"] == hook), "")
    return [ln.rstrip() for ln in content.splitlines() if ln.strip()]


def hhmm(line: str) -> str:
    return line.split()[1][:5]


async def act(page, rec) -> None:
    cap = json.loads(CAPTURE.read_text())
    s1, s2 = cap["sessions"]
    log = logged(cap)
    recall = context(s2["injected"], "UserPromptSubmit")
    if not any("INV-<ULID>" in ln for ln in recall):
        raise SystemExit(f"session 2's prompt was not given the decision: {recall}")
    if "INV-<ULID>" not in s2["events"][-1]["ev"].get("result", ""):
        raise SystemExit("session 2's answer does not use the decision")
    await page.wait_for_function("() => window.term")
    await page.evaluate("() => document.fonts.ready")
    await rec.hide_cursor()  # a terminal: nothing is clicked

    await page.evaluate(
        "([c]) => { term.clock(c); term.memory('Membase · Coding'); term.logCmd('tail -f ~/.membase/hooks.log'); term.idle(); }",
        [hhmm(cap["hook_log"][0])],
    )
    rec.step(
        1,
        "Session 1: make a decision",
        "You tell Claude Code how invoice numbers work from now on",
    )
    await rec.focus(None)
    await rec.pause(1.2)
    await page.evaluate(
        "([p, id]) => term.cmd(p, id, 95)", [f'claude -p "{s1["prompt"]}"', "cmd-1"]
    )
    await rec.focus("#cmd-1", pad=14)
    await asyncio.sleep(len(s1["prompt"]) / 95 + 0.9)
    await page.evaluate("() => term.title('quillmate — claude', true)")

    async def tick(line):
        await page.evaluate("c => term.clock(c)", hhmm(line))

    last = await replay(page, rec, timeline(s1, log, s1["ended"]), "answer-1", on_log=tick)
    await rec.focus(f"#{last}", pad=16)
    await rec.pause(3.5)

    rec.step(
        2,
        "The session ends; Membase keeps it",
        "The plugin saves it (its log, at the top) and the Memory learns it",
    )
    await page.evaluate("() => { term.title('quillmate — zsh'); term.idle(); }")
    await rec.focus("#log", pad=4)
    between = [(t, ln) for t, ln in log if s1["ended"] < t <= cap["between"]["learned_at"]]
    for _t, line in between:
        await page.evaluate("l => term.log(l)", line)
        await tick(line)
        if " saved " in line:
            await page.evaluate("() => term.memory('Membase · Coding · learning…', 'learning')")
        await rec.pause(1.0)
    await rec.focus("#mem", pad=10)
    await rec.gap(
        "Membase learns the session",
        cap["between"]["learned_at"] - cap["between"]["saving"],
        shown=2.2,
    )
    await page.evaluate("() => term.memory('Membase · Coding · learned', 'learned')")
    await rec.pause(2.2)

    rec.step(
        3,
        "Session 2: a brand-new process",
        "Nothing carried over. The code still says max + 1",
    )
    await rec.focus(None)
    await page.evaluate("([p]) => term.cmd(p, null, 30)", ["clear"])
    await asyncio.sleep(0.6)
    await page.evaluate("() => { term.clear(); term.idle(); }")
    await page.evaluate("([p, id]) => term.cmd(p, id, 40)", ["cat billing/numbering.py", "cmd-cat"])
    await asyncio.sleep(1.1)
    code = (
        (HERE / "video" / "quillmate" / "billing" / "numbering.py")
        .read_text()
        .rstrip()
        .splitlines()
    )
    await page.evaluate("([l, id]) => { term.out(l, id); term.idle(); }", [code, "code"])
    await rec.focus("#code", pad=14)
    await rec.pause(3.0)
    await page.evaluate(
        "([p, id]) => term.cmd(p, id, 95)", [f'claude -p "{s2["prompt"]}"', "cmd-2"]
    )
    await rec.focus("#cmd-2", pad=14)
    await asyncio.sleep(len(s2["prompt"]) / 95 + 0.9)
    await page.evaluate("() => term.title('quillmate — claude', true)")

    async def recalled(line):
        await tick(line)
        if " prompt " in line:  # the UserPromptSubmit hook has answered: its context is in
            rec.step(
                4,
                "It already knows",
                "The plugin's hook adds the decision from Membase to the prompt",
            )
            await page.evaluate(
                "([l, id]) => term.hook('UserPromptSubmit', l, id)", [recall, "mb-recall"]
            )
            await rec.focus("#mb-recall", pad=14)
            await rec.pause(4.0)

    last = await replay(page, rec, timeline(s2, log, s2["ended"] + 5), "answer-2", on_log=recalled)
    await page.evaluate("() => { term.title('quillmate — zsh'); term.idle(); }")
    rec.step(4, "It already knows", "A new session answers with session 1's decision")
    await rec.focus(f"#{last}", pad=10)
    await rec.pause(5.0)
    await rec.focus(None)
    await rec.pause(1.5)
