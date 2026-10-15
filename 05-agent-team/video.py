"""The agent team video, on hosted Membase. After the architecture card: one real run of the
four agents, each with its own key. The Investigator writes the cause to the Team memory;
Membase learns it; the Fixer recalls it before touching the code and patches the bug; the
Reviewer recalls both and the tests pass; the Auditor's read-only key can search, and its write
comes back from Membase as HTTP 403.

Record on an account made with per-agent keys, e.g.
scripts/video/record_hosted.sh 05-agent-team --containers Team --read-key \
  --keys investigator fixer reviewer auditor:read
"""

META = {
    "title": "Agent team",
    "title_html": "Agents that hand off<br>through shared memory",
    "pitch": "Four agents fix a real bug through one Membase memory, each with its own key. The read-only one cannot write.",
    "base": "hosted",
    "port": 8705,
    "banner_from_recording": True,
    "arch": {
        "kick": "How it works",
        "title": "Four agents, four keys, one Team memory",
        "nodes": [
            {
                "t": "Investigator · Fixer · Reviewer",
                "d": "LLM agents with tools on the repo; each calls Membase with its own read & write key",
            },
            {
                "t": "Membase API",
                "d": "checks each key's scope on every call; a write is learned before search finds it",
                "mb": True,
            },
            {
                "t": "Team memory",
                "d": "the finding, the fix decision: what one agent learns, the next recalls",
                "mb": True,
            },
            {
                "t": "Auditor",
                "d": "read-only key: search works, a write is refused by Membase with 403",
            },
        ],
        "foot": "Permissions live in Membase, not in the agents: revoke or narrow a key and that agent stops at once.",
    },
}
SEED: list[str] = []


CAUSE = """(sel) => { const t = (document.querySelector(sel)?.textContent || '').toLowerCase();
  return (t.includes('refill') || t.includes('elapsed')) &&
    ['created', 'creation', 'updated_at', 'last refill'].some((w) => t.includes(w)); }"""


async def act(page, rec) -> None:
    await page.wait_for_selector("#feed .empty, #feed .pin, #feed .older", timeout=120_000)
    if not await page.locator("#feed .empty").count():
        raise SystemExit("the Team memory is not empty: record on a fresh account")

    rec.step(
        1,
        "The Investigator finds the cause",
        "An issue tracker; each agent is a member with its own key",
    )
    await rec.focus(None)
    await rec.pause(2.0)
    await rec.hover("#run", pause=0.6)
    await rec.click("#run")
    await rec.hide_cursor()  # the rest is the team's work: nothing more is clicked
    await rec.focus(".issue", pad=0)
    await rec.wait(
        "The Investigator reads the code and runs the tests",
        page.wait_for_selector("#wrote-Investigator", timeout=600_000),
    )
    rec.step(
        1, "The Investigator finds the cause", "Tests fail; it pins one finding to the Team notes"
    )
    await rec.focus("#wrote-Investigator", pad=14)
    await rec.pause(3.5)

    rec.step(2, "Membase learns it", "Only a learned note can be recalled by the next agent")
    await rec.focus("#notes", pad=4)
    await rec.wait(
        "Membase learns the finding",
        page.wait_for_function(
            "() => /learned the|could not/.test(document.querySelector('#learn-Investigator')?.textContent || '')",
            timeout=900_000,
        ),
    )
    if await page.locator(".warn").count():
        raise SystemExit(
            "a learning run failed in this take: " + await page.locator(".warn").first.inner_text()
        )
    await rec.pause(2.0)

    rec.step(
        3, "The Fixer recalls it first", "Its first move: search the Team notes, before any file"
    )
    await rec.wait(
        "The Fixer searches the Team notes",
        page.wait_for_selector("#recall-Fixer", timeout=600_000),
    )
    if not await page.evaluate(CAUSE, "#recall-Fixer"):
        raise SystemExit("the Fixer's recall does not hold the Investigator's finding")
    if not await page.locator("#recall-Fixer .from").count():
        raise SystemExit("the Fixer's recall is not shown as the Investigator's note")
    await rec.focus("#recall-Fixer", pad=14)
    await rec.pause(4.0)
    await rec.focus("#pin-Investigator", pad=10)
    await rec.pause(1.8)
    await rec.wait(
        "The Fixer patches the code", page.wait_for_selector("#check-Fixer", timeout=600_000)
    )
    rec.step(3, "The Fixer recalls it first", "Then one line changes, and the tests pass")
    await rec.focus("#patch", pad=14)
    await rec.pause(2.5)
    await rec.focus("#check-Fixer", pad=14)
    await rec.pause(1.5)

    await rec.wait(
        "Membase learns the fix",
        page.wait_for_function(
            "() => /learned the|could not/.test(document.querySelector('#learn-Fixer')?.textContent || '')",
            timeout=900_000,
        ),
    )
    if await page.locator(".warn").count():
        # a learning run that failed: the take cannot show the hand-off
        raise SystemExit(
            "a learning run failed in this take: " + await page.locator(".warn").first.inner_text()
        )
    rec.step(
        4,
        "The Reviewer checks it",
        "Recalls the finding and the fix, reads the diff, runs the tests",
    )
    await rec.focus(".issue", pad=0)
    await rec.wait(
        "The Reviewer checks",
        page.wait_for_selector("#verdict", timeout=900_000),
    )
    await rec.focus("#verdict", pad=14)
    await rec.pause(3.0)

    rec.step(
        5,
        "A read-only key cannot write",
        "The Auditor can search the notes; Membase refuses its note",
    )
    await rec.wait(
        "The Auditor searches, then tries to write",
        page.wait_for_selector("#refused", timeout=600_000),
    )
    if "403" not in await page.locator("#refused").inner_text():
        raise SystemExit("the Auditor's write was not refused with 403")
    await rec.focus("#refused", pad=14)
    await rec.pause(4.5)
    await rec.wait("The run ends", page.wait_for_selector("#closed", timeout=300_000))
    await rec.focus(None)
    await rec.pause(3.0)
