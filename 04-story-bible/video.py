"""The story bible video, on hosted Membase. After the explainer: Quire, a novelist's
writing app. The binder holds the Saltmarrow canon (the story bible, in a Membase memory);
Chapter Three is a draft with planted mistakes. Check continuity: each contradiction becomes a
margin comment that quotes the canon it breaks, and the fixes are accepted like suggestions.
Continue: new prose written from recalled canon. Add to canon: the scene is filed in the binder,
one write that Membase learns. Then a real Claude Code run, connected to the same Memory over
MCP with a read-only key, answers a question only the new scene can answer.

A take is kept only if the check does not flag the scene's new fact (the key stamped 41), the
scene is learned, and Claude Code's answer has the 41.

Record on a fresh account (record_hosted.sh runs seed.py first and retries on a new account):
scripts/video/record_hosted.sh 04-story-bible --containers "Story Bible" --read-key
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "video"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claude_replay import capture, replay, result_of, timeline  # noqa: E402

import demokit.config  # noqa: E402, F401  (loads .env and DEMO_ENV_FILE into this process too)

META = {
    "title": "Story bible",
    "title_html": "One canon for<br>every AI you write with",
    "pitch": "The story bible lives in Membase. Your writing app checks and continues the chapter against it, and any AI connected to the Memory reads the same canon.",
    "base": "hosted",
    "port": 8704,
    "banner_from_recording": True,
    "line": "Quire checks your chapter against the canon. Claude Code reads the same canon.",
    "intro_at": ["Check continuity", 30.0],  # each margin note quotes the canon it breaks
    "explain": {
        "title": "One canon, read by every AI",
        "actors": [
            {
                "id": "quire",
                "icon": "feather",
                "label": "Quire",
                "kind": "app",
                "at": [600, 400],
                "size": 200,
                "labelAt": "inside",
                "tint": "#22302e",
                "ink": "#f3e8cf",
                "key": "write key",
            },
            {
                "id": "cc",
                "icon": "terminal",
                "label": "Claude Code",
                "kind": "agent",
                "at": [600, 770],
                "labelAt": "left",
                "tint": "#0f172b",
                "ink": "#fff",
                "key": "read-only key",
            },
            {
                "id": "mb",
                "kind": "membase",
                "base": "hosted",
                "box": [1060, 300, 720, 470],
                "slots": [
                    {"id": "bible", "label": "Story Bible", "icon": "scroll-text", "facts": 3}
                ],
            },
        ],
        "beats": [
            {
                "say": "Quire checks the draft against canon",
                "membase": "recall",
                "hit": 1,
                "flows": [
                    {
                        "from": "quire",
                        "to": "mb",
                        "token": {"label": "its topics", "icon": "search"},
                    },
                    {
                        "from": "mb",
                        "to": "quire",
                        "token": "canon lines",
                        "result": "3 slips caught",
                    },
                ],
            },
            {
                "say": "A new scene is filed into canon",
                "membase": "learn",
                "facts": ["Iron key, stamped 41"],
                "flows": [
                    {
                        "from": "quire",
                        "to": "mb",
                        "token": {"label": "new scene", "icon": "file-text"},
                    }
                ],
            },
            {
                "say": "Claude Code, over MCP, finds the new scene",
                "membase": "recall",
                "hit": 3,
                "flows": [
                    {
                        "from": "cc",
                        "to": "mb",
                        "token": {"label": "what key?", "icon": "search"},
                    },
                    {"from": "mb", "to": "cc", "token": "key stamped 41"},
                ],
            },
        ],
    },
}
SEED: list[str] = []
QUESTION = "In my Saltmarrow story, what did Tobiah give Ilse, and what does it open? Look it up in my Membase memory."
LEARNED = "() => /In canon|failed|Already|does not count/.test(document.querySelector('#acceptstate')?.textContent || '')"


async def ask_claude() -> dict:
    """A real Claude Code run with only the Membase MCP server, on a read-only key."""
    base = os.environ["MEMBASE_BASE_URL"].rstrip("/")
    key = os.environ.get("MEMBASE_READ_KEY") or ""
    if not key:
        raise SystemExit(
            "MEMBASE_READ_KEY is not set: make the account with bootstrap_hosted.py --read-key"
        )
    work = Path(tempfile.mkdtemp(prefix="story-claude-"))
    cfg = {
        "mcpServers": {
            "membase": {
                "type": "http",
                "url": f"{base}/mcp-http",
                "headers": {"Authorization": f"Bearer {key}"},
            }
        }
    }
    (work / "mcp.json").write_text(json.dumps(cfg))
    env = {**os.environ, "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}  # only Membase may remember
    return await capture(
        QUESTION,
        cwd=work,
        env=env,
        args=[
            "--mcp-config",
            str(work / "mcp.json"),
            "--strict-mcp-config",
            "--allowedTools=mcp__membase__search_memories,mcp__membase__list_containers",
        ],
    )


async def act(page, rec) -> None:
    await rec.wait(
        "Opening the canon",
        page.wait_for_function(
            "() => /Canon in memory/.test(document.querySelector('#fBible').textContent)",
            timeout=300_000,
        ),
    )

    rec.step(
        1,
        "The canon lives in memory",
        "Quire's binder: the Saltmarrow story bible, in a Membase memory",
    )
    await rec.focus("#binder", pad=0)
    await rec.pause(2.4)
    rec.step(1, "The canon lives in memory", "Chapter Three: a draft with planted mistakes")
    await rec.focus("#sheet", pad=0)
    await rec.pause(2.2)

    rec.step(
        2, "Check continuity", "Membase recalls the canon this chapter touches; a model compares"
    )
    await rec.click("#check")
    await rec.wait(
        "Recalling canon, comparing", page.wait_for_selector("#mhead, #consistent", timeout=300_000)
    )
    if not await page.locator("#applyall").count():
        raise SystemExit("the check found fewer than two contradictions: record again")
    flagged = await page.locator("#text mark.cm").all_inner_texts()
    if any(w in q.lower() for q in flagged for w in ("41", "locker", "rib bridge", "eleven years")):
        # the key is the scene's new fact, not a contradiction: a take that flags it misleads
        raise SystemExit(f"the check flagged the new fact as a contradiction: {flagged}")
    rec.step(2, "Check continuity", "Each margin note quotes the canon line the sentence breaks")
    await rec.focus("#row", pad=0)
    await rec.pause(4.2)
    rec.step(2, "Check continuity", "The fixes are accepted like suggestions")
    await rec.click("#applyall")
    await rec.focus("#sheet", pad=0)
    await rec.pause(2.4)

    rec.step(
        3, "Continue from canon", "New prose, written only from recalled canon and the style guide"
    )
    await rec.click("#continue")
    await rec.focus("#row", pad=0)
    await rec.wait(
        "Recalling canon, writing in its voice",
        page.wait_for_selector("#append", timeout=300_000),
    )
    rec.step(3, "Continue from canon", "The margin lists the canon notes it was written from")
    await rec.pause(3.0)
    await rec.click("#append")

    rec.step(4, "Add the scene to canon", "Filed in the binder: one write, then Membase learns it")
    await rec.click("#accept")
    await page.wait_for_selector("#acceptstate", timeout=120_000)
    await rec.focus(None)
    await rec.wait("Membase learns the scene", page.wait_for_function(LEARNED, timeout=900_000))
    if "In canon" not in await page.locator("#acceptstate").inner_text():
        raise SystemExit("the scene was not learned: record again on a fresh account")
    rec.step(4, "Add the scene to canon", "In canon: the binder lists the new scene")
    await rec.pause(2.8)

    rec.step(5, "Another AI reads the same canon", "Claude Code over MCP, with a read-only key")
    session = await rec.wait("Claude Code asks Membase", ask_claude())
    answer = result_of(session)
    if "41" not in answer:
        raise SystemExit(f"Claude's answer did not come from the new scene: {answer!r}")
    await rec.focus(None)
    await page.goto(page.url.split("/")[0] + "//" + page.url.split("/")[2] + "/kit/terminal.html")
    await page.wait_for_function("() => window.term")
    await rec.hide_cursor()
    await page.evaluate(
        "() => { term.cwd('~/notes'); term.session('Claude Code', 'connected to the Story Bible memory over MCP · read-only key'); }"
    )
    await page.evaluate("([p, id]) => term.cmd(p, id, 70)", [f'claude "{QUESTION}"', "cmd"])
    await rec.focus("#cmd", pad=16)
    await rec.pause(len(QUESTION) / 70 + 0.6)
    last = await replay(
        page,
        rec,
        timeline(session),
        "answer",
        thinking="Claude Code searches Membase",
        marks=["41", "Corin", "third Rib Bridge", "locker"],
    )
    await rec.focus(f"#{last}", pad=20)
    await rec.pause(5.0)
    await rec.focus(None)
    await rec.pause(1.0)
