"""The memory graph video, on the local engine. After the architecture card: Kith, a notes app
with a map of the people, places and things in Lena's notes. The map is built from what memory
returns; Clara Jensen's card lists the dated notes she came from; Lena writes one new note, and
after a rebuild the map marks what it brought in.

The new note is fixed. The take is kept only if the rebuilt map marks Clara Jensen and Porto as
new, and Clara's card shows the new note: otherwise record again.
"""

META = {
    "title": "Memory graph",
    "title_html": "Your memory,<br>mapped",
    "pitch": "People, places and projects drawn from what memory returns. Every one keeps the notes it came from.",
    "base": "local",
    "port": 8707,
    "banner_from_recording": True,
    "arch": {
        "kick": "How it works",
        "title": "A map drawn from recall, never stored in place of memory",
        "nodes": [
            {
                "t": "Life memory",
                "d": "four months of Lena's notes and chats, each dated, and three standing facts",
                "mb": True,
            },
            {
                "t": "Recall",
                "d": "the profile, eight broad searches, then one search per name found",
                "mb": True,
            },
            {
                "t": "Model",
                "d": "names people, places and links; anything no note states is dropped",
            },
            {
                "t": "Kith, the notes app",
                "d": "the map is a cache you can rebuild; a card shows the notes behind each node",
            },
        ],
        "foot": "Membase stays the source: delete a note, rebuild, and what came from it is gone.",
    },
}
SEED = ["07-memory-graph/seed.py"]
NEW = (
    "Clara Jensen told me she is moving to Harbor Bank's new Porto office in January, "
    "and she wants me to visit the team there in February."
)
BUILT = "() => !document.querySelector('#rebuild').disabled && !!document.querySelector('g.node')"
LIVE = "() => !document.querySelector('#live.busy')"


async def act(page, rec) -> None:
    await page.wait_for_selector("#build", timeout=60_000)

    rec.step(1, "Build the map from memory", "Kith asks Lena's memory who and what is in her notes")
    await rec.focus(None)
    await rec.pause(2.2)
    await rec.click("#build")
    await rec.focus("#map", pad=4)
    await rec.wait(
        "Recalling, then naming people and places",
        page.wait_for_function(BUILT, timeout=600_000),
    )
    await rec.focus(None)
    await rec.pause(3.2)

    rec.step(
        2,
        "Every person keeps her notes",
        "Clara Jensen: her links, and the dated notes behind them",
    )
    await rec.type("#search", "Clara Jensen", delay=45)
    await rec.press("Enter")
    await page.wait_for_selector("#who", timeout=10_000)
    await rec.focus("#detail", pad=4)
    await rec.wait("Searching memory for Clara now", page.wait_for_function(LIVE, timeout=120_000))
    await rec.pause(3.8)

    rec.step(3, "Write one new note", "Clara is moving to Harbor Bank's new Porto office")
    await rec.click("#back")
    await rec.focus("#detail", pad=4)
    await rec.type("#newnote", NEW, delay=14)
    await rec.click("#savenote")
    await rec.wait("Writing it to memory", page.wait_for_selector("#saved", timeout=120_000))
    await rec.pause(2.0)

    rec.step(
        4, "Rebuild: the new note joins the map", "Recall again; everything the note touched glows"
    )
    await rec.click("#rebuild")
    await rec.focus("#map", pad=4)
    await rec.wait("Recalling and naming again", page.wait_for_function(BUILT, timeout=600_000))
    fresh = await page.eval_on_selector_all("#newlist .conn", "els => els.map((e) => e.dataset.id)")
    if not {"clara-jensen", "porto"} <= set(fresh):
        raise SystemExit(f"the rebuilt map did not mark Clara and Porto as new: {fresh}")
    names = await page.eval_on_selector_all(
        "#newlist .conn > span", "els => els.map((e) => e.firstChild.textContent)"
    )
    if len(names) > 4:
        names = [*names[:3], f"{len(names) - 3} more"]
    shown = ", ".join(names[:-1]) + f" and {names[-1]}" if len(names) > 1 else names[0]
    rec.step(4, "Rebuild: the new note joins the map", f"{shown} glow, with their new links")
    await rec.focus(None)
    await rec.pause(3.0)
    await rec.focus("#newlist", pad=12)
    await rec.pause(3.0)

    await rec.click("#newlist .conn[data-id=clara-jensen]")
    await page.wait_for_selector("#who", timeout=10_000)
    notes = await page.locator("#fromnotes .note.fresh").all_inner_texts()
    if not any("Porto" in n for n in notes):
        raise SystemExit(f"Clara's card does not show the new note: {notes}")
    rec.step(4, "Rebuild: the new note joins the map", "Clara's card now opens with today's note")
    await rec.hover("#ownerav", pause=0.1)
    await rec.focus("#detail", pad=4)
    await rec.wait("Searching memory for Clara now", page.wait_for_function(LIVE, timeout=120_000))
    await rec.pause(2.6)
    await rec.focus(None)
    await rec.pause(2.4)
