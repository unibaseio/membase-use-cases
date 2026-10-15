"""Give the memory a life to map: four months of one person's notes and chats (synthetic).

    uv run 07-memory-graph/seed.py            # every note into the `Life` container
    uv run 07-memory-graph/seed.py --notes 5  # the first five (faster to try)

Lena Varga is a made-up product designer in Lisbon; every person, company and event below is
invented for this demo. Three standing facts go to her profile. On the local engine the notes
are read in together, each dated by the day it happened (about half a minute); hosted, each
note is learned before the next one is written, and is dated by the day it was written. Seeding twice writes the notes twice: use a fresh user (`--user`) or a
fresh DEMO_DATA_DIR to start over.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from membase.errors import MembaseError  # noqa: E402
from membase.local.backend import LocalBackend  # noqa: E402

from demokit import Memory  # noqa: E402
from demokit.dated import remember_sessions  # noqa: E402

CONTAINER = "Life"

# (title, the day it happened, text). Notes are written by Lena; chats are Lena talking to her
# assistant.
NOTES: list[tuple[str, str, str]] = [
    (
        "New job",
        "2026-05-25",
        "2026-05-25. Signed the offer from Northwind Labs today. I start on 2 June as a senior "
        "product designer in their Lisbon studio. My manager will be Tomás Reyes, who leads "
        "engineering and design for the client work. Moving my desk from home to the studio in "
        "Alfama after two years freelancing.",
    ),
    (
        "Atlas kickoff",
        "2026-06-02",
        "User: Kickoff for Project Atlas today, 2 June. It's a full redesign of Harbor Bank's "
        "mobile banking app.\n"
        "Assistant: Who is on the project?\n"
        "User: Aiko Mori is the product manager and runs the roadmap. I own the design. Clara "
        "Jensen is the sponsor on Harbor Bank's side, she's their head of digital channels. "
        "Tomás gave us until the end of August for a public beta.\n"
        "Assistant: Noted: Atlas, Harbor Bank, beta by end of August.",
    ),
    (
        "Mentoring Sam",
        "2026-06-09",
        "2026-06-09. Tomás asked me to mentor Sam Okoro, the design intern who joined this week. "
        "Sam will spend half their time on Beacon, Northwind's internal design system, which I "
        "am also taking over from the previous lead. We agreed on a weekly one-to-one every "
        "Thursday morning.",
    ),
    (
        "Climbing",
        "2026-06-11",
        "User: Joined the Lisbon Climbing Club tonight. My friend Felix Brandt has been "
        "climbing there for years and talked me into it.\n"
        "Assistant: How did the first session go?\n"
        "User: Hard but fun. Felix and I are going to climb together on Tuesday and Friday "
        "evenings. He wants to do an outdoor trip to Sintra in July.",
    ),
    (
        "Porto offsite",
        "2026-06-18",
        "2026-06-18 and 19. Northwind team offsite in Porto. Two days in a converted warehouse "
        "by the river. Aiko and I ran the Atlas journey-mapping workshop with Clara Jensen, who "
        "came up from Harbor Bank for the day. Big outcome: the money-transfer flow gets "
        "rebuilt from scratch, it was the top complaint in the bank's reviews.",
    ),
    (
        "Summit talk accepted",
        "2026-06-24",
        "User: My talk got accepted at the Design Systems Summit in Berlin, 14 July!\n"
        "Assistant: Congratulations. What is it about?\n"
        "User: How we rebuilt Beacon's colour tokens so client apps like Atlas can theme from "
        "one source. Sam is helping me with the example screens.",
    ),
    (
        "Sintra climbing trip",
        "2026-07-05",
        "2026-07-05. Outdoor climbing in Sintra with Felix and two others from the Lisbon "
        "Climbing Club. Granite slabs, much scarier than the gym. Felix led every route; I "
        "managed my first outdoor 5c.",
    ),
    (
        "Berlin",
        "2026-07-14",
        "2026-07-14. Gave the Beacon talk at the Design Systems Summit in Berlin. About 300 "
        "people in the room. Met Jonas Weber from Fernhill Studio afterwards, who wants to "
        "compare notes on token pipelines. Stayed two extra days in Berlin to visit my sister "
        "Nora, who lives in Kreuzberg.",
    ),
    (
        "Atlas crunch",
        "2026-08-07",
        "User: Atlas is behind. Clara wants biometric login in the beta and engineering says it "
        "needs three more weeks.\n"
        "Assistant: What did you decide?\n"
        "User: Tomás and Aiko agreed to move the public beta from 31 August to 20 August with "
        "biometric login left out, and ship it in October instead. Clara signed off on Friday.",
    ),
    (
        "Atlas beta",
        "2026-08-20",
        "2026-08-20. Atlas public beta went live for 5,000 Harbor Bank customers. The new "
        "transfer flow cut the average time to send money from 74 seconds to 31. Aiko is "
        "presenting the numbers to Harbor Bank's board in September. Celebrated with the team "
        "at a tasca in Alfama.",
    ),
    (
        "Nora's wedding",
        "2026-09-03",
        "User: Flying to Berlin on 11 September for Nora's wedding. She's marrying Malik Haddad, "
        "they met at the university hospital where they both work.\n"
        "Assistant: Are you part of the ceremony?\n"
        "User: I'm giving a toast. The wedding is on 12 September at a lake house outside Berlin.",
    ),
    (
        "Sam's review",
        "2026-09-24",
        "2026-09-24. Wrote Sam Okoro's end-of-internship review for Tomás. Sam built the dark "
        "theme for Beacon almost alone. I recommended Northwind offer Sam a junior designer "
        "role, and Tomás agreed.",
    ),
    (
        "Half marathon",
        "2026-10-04",
        "2026-10-04. Ran the Lisbon half marathon in 1:58:40, under two hours for the first "
        "time. Felix ran it too and finished ten minutes ahead of me. Training started in July "
        "with a plan from the club's running group.",
    ),
    (
        "Atlas next",
        "2026-10-09",
        "User: Harbor Bank just signed phase two of Atlas.\n"
        "Assistant: What is in phase two?\n"
        "User: Biometric login and a savings-goals feature, starting in November. Clara wants me "
        "to keep leading design, and Aiko stays on as PM. We'll run the planning week in Porto "
        "again.",
    ),
]


def record_fact(mem: Memory, text: str) -> str:
    """A standing fact into the profile. Hosted, the write can come back 422 ("the assistant
    reported the fact recorded but it is not in the profile") although the fact lands a few
    seconds later; so on that error the profile itself is read until it shows the fact."""
    try:
        mem.remember_fact(text)
        return "recorded"
    except MembaseError as e:
        if mem.mode != "hosted" or e.status != 422:
            raise
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            time.sleep(10)
            if text in (mem.profile().get("static") or []):
                return "recorded (the write reported 422, then the fact appeared in the profile)"
        raise


# Standing facts: the profile half of memory (the graph reads these first).
FACTS = [
    "Lives in Lisbon, in the Alfama neighbourhood.",
    "Works as a senior product designer at Northwind Labs.",
    "Has a sister, Nora, who lives in Berlin.",
]


# What Lena wrote, by the memory each note became: the page shows her own words, and the
# engine's rewrite of them ("On 2026-06-02, the user announced…") only as the source behind it.
OWN_NOTES = "notes.json"


def own_notes(mem: Memory) -> dict[str, dict]:
    """{memory id: {title, day, text}} for the notes this app wrote (local engine only)."""
    path = mem.path / OWN_NOTES if mem.path is not None else None
    if path is None or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def keep_notes(mem: Memory, written: dict[str, dict]) -> None:
    """Record which memories a written note became."""
    if mem.path is None or not written:
        return
    notes = own_notes(mem) | written
    (mem.path / OWN_NOTES).write_text(json.dumps(notes, ensure_ascii=False, indent=1), "utf-8")


def _running(mem: Memory, document_id: str) -> bool:
    run = mem.client.documents.get(document_id).get("learning_run") or {}
    return run.get("status") in ("queued", "running")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--notes", type=int, default=len(NOTES), help="how many notes to write")
    p.add_argument("--user", default="default", help="whose memory (a local directory per user)")
    a = p.parse_args()

    mem = Memory("07-memory-graph", user=a.user, default_mode="local")
    notes = NOTES[: a.notes]
    print(f"{len(notes)} note(s) into {CONTAINER!r} on the {mem.mode} base")
    if mem.mode == "local":
        # Each note dated by the day it happened, not the day it was seeded: the map's cards
        # show a note's date, and "new since the last build" is the only thing written today.
        started = time.monotonic()
        ids = remember_sessions(
            mem,
            [
                {
                    "session_id": f"note-{i}",
                    "session_date": f"{day}T19:00:00Z",
                    "turns": LocalBackend._turns(text, title),  # noqa: SLF001 - as memories.add
                }
                for i, (title, day, text) in enumerate(notes)
            ],
            container=CONTAINER,
        )
        empty = [notes[int(k[5:])][0] for k, v in ids.items() if not v]
        if empty:
            raise SystemExit(f"the engine kept nothing from: {empty}")
        keep_notes(
            mem,
            {
                mid: dict(zip(("title", "day", "text"), notes[int(sid[5:])], strict=True))
                for sid, mids in ids.items()
                for mid in mids
            },
        )
        print(f"  {sum(map(len, ids.values()))} memories in {time.monotonic() - started:.1f}s")
    for title, _day, text in notes if mem.mode == "hosted" else []:
        started = time.monotonic()
        out = mem.remember(text, container=CONTAINER, title=title)
        if out.get("document_id"):
            # A write while the Memory is still learning starts a second run, which fails
            # ("Another learning run is active"). So hosted writes go one learning run at a time.
            while _running(mem, out["document_id"]):
                time.sleep(10)
        print(f"  {title:<24} {out.get('status'):<8} {time.monotonic() - started:5.1f}s")
    for fact in FACTS:
        print(f"  fact: {fact:<44} {record_fact(mem, fact)}")
    if mem.mode == "hosted":
        print("Each note was learned before the next one was written.")


if __name__ == "__main__":
    main()
