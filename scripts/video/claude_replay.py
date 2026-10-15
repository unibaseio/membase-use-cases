"""Capture a real `claude -p` run and replay it in the kit's terminal page (/kit/terminal.html)
at the pace it ran: tool calls, what the tools returned, the answer streaming. Waits longer
than three seconds are shortened and badged with their real length (Recorder.gap).

    session = await capture(prompt, cwd=..., env=..., args=["--mcp-config", path, ...])
    await page.goto(f"{base}/kit/terminal.html")
    await replay(page, rec, timeline(session), "answer", thinking="Claude Code thinks")
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path


async def capture(prompt: str, *, cwd: Path, env: dict, args: list[str]) -> dict:
    """One `claude -p` run; every stream-json event with the second it arrived."""
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        *args,
        prompt,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    events = []
    async for line in proc.stdout:
        text = line.decode(errors="replace")
        if text.startswith("{"):
            events.append({"t": round(time.monotonic() - started, 3), "ev": json.loads(text)})
    err = (await proc.stderr.read()).decode(errors="replace")
    if await proc.wait() != 0:
        raise SystemExit(f"claude exited {proc.returncode}: {err[-400:]}")
    return {"prompt": prompt, "events": events}


def result_of(session: dict) -> str:
    return next(
        (e["ev"].get("result") or "" for e in session["events"] if e["ev"].get("type") == "result"),
        "",
    )


def tools_used(session: dict) -> list[str]:
    return [
        b["name"]
        for e in session["events"]
        if e["ev"].get("type") == "assistant"
        for b in e["ev"]["message"]["content"]
        if b.get("type") == "tool_use"
    ]


def _short(name: str) -> str:
    return re.sub(r"^mcp__([^_]+)__", r"\1 · ", name)


def timeline(session: dict) -> list[tuple[float, str, object]]:
    """(seconds, kind, value) in the order Claude Code produced them: a tool call, what it
    returned, or the text of the current answer block (a new block starts after a tool)."""
    out, text, block = [], "", 0
    hidden: set[str] = (
        set()
    )  # tool calls not shown (ToolSearch), whose results are not shown either
    for e in session["events"]:
        t, ev = e["t"], e["ev"]
        if ev.get("type") == "assistant":
            for b in ev["message"]["content"]:
                if b.get("type") == "tool_use" and b["name"] == "ToolSearch":
                    hidden.add(b.get("id"))
                if b.get("type") == "tool_use" and b["name"] != "ToolSearch":
                    arg = (
                        b["input"].get("q")
                        or b["input"].get("file_path")
                        or b["input"].get("command")
                        or ""
                    )
                    out.append((t, "tool", (_short(b["name"]), str(arg)[:90])))
                    if text:
                        text, block = "", block + 1
        if ev.get("type") == "user":
            for b in (ev.get("message") or {}).get("content") or []:
                if (
                    isinstance(b, dict)
                    and b.get("type") == "tool_result"
                    and b.get("tool_use_id") not in hidden
                ):
                    body = b.get("content")
                    raw = body if isinstance(body, str) else json.dumps(body)
                    n = len(re.findall(r'\\?"content\\?"\s*:', raw))
                    if "membase" in raw.lower() or n:
                        out.append(
                            (
                                t,
                                "result",
                                f"{n} passages from Membase" if n else "results from Membase",
                            )
                        )
        sev = ev.get("event") or {}
        if ev.get("type") == "stream_event" and sev.get("type") == "content_block_delta":
            d = sev.get("delta") or {}
            if d.get("type") == "text_delta":
                text += d["text"]
                out.append((t, "text", (block, text)))
    return out


async def replay(page, rec, items, prefix: str, *, thinking: str, marks: list[str] = ()) -> str:
    """Play the items at the pace they happened; returns the last answer block's id."""
    clock, shown, last = 0.0, set(), ""
    for t, kind, value in items:
        gap = t - clock
        if gap > 3:
            await rec.gap(thinking if not shown else "Claude Code working", gap, shown=1.6)
        elif gap > 0:
            await asyncio.sleep(min(gap, 0.25))
        clock = t
        if kind == "tool":
            await page.evaluate("([n, a]) => term.tool(n, a)", list(value))
            continue
        if kind == "result":
            await page.evaluate("t => term.result(t)", value)
            continue
        block, text = value
        last = f"{prefix}-{block}"
        if last not in shown:
            await page.evaluate("id => term.answer(id)", last)
            await rec.focus(f"#{last}", pad=20)
            shown.add(last)
        await page.evaluate(
            "([id, s, m]) => term.text(id, s, m)", [last, text.strip(), list(marks)]
        )
    return last
