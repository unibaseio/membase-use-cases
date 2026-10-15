"""The Reunite video, on the local engine. After the architecture card: a caseworker's review
desk. Seeker S-01, Callum Price, in his own words; the reviewer pulls the family files that
could fit (memory recalls them, the model scores the top five); F-01 opens beside his file and
the worksheet lines up what agrees, with the same numbered marks in both files ("a little metal
fire engine" ≈ "a red tin toy fire truck"); the reviewer stamps it a match. Every record is
synthetic. A take whose top family is not F-01, or whose fire engine pair is missing, is not
kept."""

META = {
    "title": "Reunite",
    "title_html": "Two memories of<br>one childhood",
    "pitch": "Seekers and families describe what they remember. Memory finds the records that could fit, the details are lined up side by side, and a person decides.",
    "base": "local",
    "port": 8715,
    "path": "?seeker=S-01",
    "banner_from_recording": True,
    "arch": {
        "kick": "How it works",
        "title": "One operator's store, recall, a model comparison, a person's decision",
        "nodes": [
            {
                "t": "Families · Seekers",
                "d": "two containers in one operator's local store; each record is a document",
                "mb": True,
            },
            {
                "t": "Recall",
                "d": "the seeker's whole account, then each kind of detail, searched in Families",
                "mb": True,
            },
            {
                "t": "Model comparison",
                "d": "the top five, detail by detail: what agrees, what conflicts, a score",
            },
            {
                "t": "A person decides",
                "d": "a reviewer stamps a match or not; the system only suggests",
            },
        ],
        "foot": "Synthetic records. Matching across people's accounts on hosted Membase would cross the tenant boundary, so this runs locally.",
    },
}
SEED = ["15-reunite/seed.py --records-only"]
NOTE = "Toy, scar, dog, song and bakery all agree"


async def act(page, rec) -> None:
    await page.wait_for_selector("#find", timeout=60_000)

    rec.step(1, "What Callum remembers", "Every file on this desk is synthetic. A person decides")
    await rec.focus(None)
    await rec.pause(1.6)
    await rec.focus("#notice", pad=10)
    await rec.pause(2.6)
    rec.step(1, "What Callum remembers", "Seeker S-01, in his own words")
    await rec.focus("#seekerfolder", pad=10)
    await rec.pause(2.6)
    await rec.focus('[data-field="objects"]', pad=10)
    await rec.pause(2.4)

    rec.step(
        2,
        "Pull the family files that could fit",
        "Memory searches them six ways; the model scores the top five",
    )
    await rec.focus("#stage", pad=10)
    await rec.click("#find")
    await rec.wait(
        "Recalling family files, comparing the top five",
        page.wait_for_selector("#cands", timeout=300_000),
    )
    top = page.locator(".cand").first
    family = await top.get_attribute("data-family")
    score = int((await top.locator(".s").inner_text()).split()[0])
    if family != "F-01" or score < 80:
        raise SystemExit(f"the top suggestion is {family} at {score}, not F-01")
    await rec.focus("#cands", pad=10)
    await rec.pause(3.4)

    rec.step(
        3,
        "Both files side by side",
        f"F-01 scores {score}: the details that agree, numbered in both files",
    )
    await rec.click('.cand[data-family="F-01"]')
    await page.wait_for_selector("#pairs .pair", timeout=30_000)
    engine = page.locator("#pairs .pair.ov", has_text="fire engine").first
    if not await engine.count() or "fire truck" not in (await engine.inner_text()):
        raise SystemExit("the fire engine and fire truck are not paired")
    n = await engine.get_attribute("data-n")
    if (
        not await page.locator(f'#family mark[data-n="{n}"]').count()
        or not await page.locator(f'#seeker mark[data-n="{n}"]').count()
    ):
        raise SystemExit("the toy is not marked in both files")
    agree = await page.locator("#pairs .pair.ov").count()
    if agree < 4:
        raise SystemExit(f"only {agree} details agree; the take should show several")
    await rec.focus(None)
    await rec.pause(3.0)
    rec.step(
        3, "Both files side by side", "“a little metal fire engine” ≈ “a red tin toy fire truck”"
    )
    await rec.focus('#pairs .pair.ov:has-text("fire engine")', pad=10)
    await rec.pause(3.4)
    rec.step(
        3,
        "Both files side by side",
        "The family's file: each detail that agrees, under the same number",
    )
    await rec.focus("#familyfolder", pad=8)
    await rec.pause(3.2)

    rec.step(4, "A person decides", "The reviewer stamps F-01 a match. The system only suggested")
    await rec.focus("#stage", pad=10)
    await rec.type("#note", NOTE, delay=22)
    await rec.pause(0.6)
    await rec.click("#yes")
    await page.wait_for_selector("#verdict", timeout=30_000)
    await rec.focus("#verdict", pad=14)
    await rec.pause(3.6)
    await rec.focus(None)
    await rec.pause(2.8)
