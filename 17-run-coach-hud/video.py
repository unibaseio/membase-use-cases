"""The run coach video, on the local engine. After the explainer: Pacenote, a coach
for smart glasses. On the phone, the brief: it read Jamie's last runs from memory, and code
counts the ones that faded after km 7. Through the glasses, the run: a park path, the HUD at the
lens edges, and at km 6.5 the coach's cue with the five runs it counted. Back on the phone, the
finished run is saved to memory, dated now; the next brief reads it.

The count the cue states is checked against the seeded runs, worked out here from seed.py on
its own. A take whose cue, save or next brief is not what the captions say is not kept."""

import importlib.util
from pathlib import Path

META = {
    "title": "Run coach HUD",
    "title_html": "A running coach<br>that remembers",
    "pitch": "A coach in your glasses reads your past runs before you start, speaks up where they went wrong, and remembers today's.",
    "base": "local",
    "port": 8717,
    "banner_from_recording": True,
    "line": "Pacenote reads your past runs before you start, and cues you where they faded.",
    "explain": {
        "title": "Past runs in, today's run back",
        "actors": [
            {"id": "jamie", "icon": "user", "label": "Jamie", "kind": "user", "at": [170, 720]},
            {
                "id": "pacenote",
                "icon": "footprints",
                "label": "Pacenote",
                "kind": "app",
                "box": [360, 205, 1470, 725],
                "tint": "#14201a",
                "ink": "#e4f7c4",
            },
            {
                "id": "phone",
                "icon": "smartphone",
                "label": "Phone",
                "kind": "device",
                "at": [640, 380],
                "size": 150,
                "tint": "#c6f432",
                "ink": "#14201a",
                "labelAt": "left",
                "labelColor": "#e4f7c4",
            },
            {
                "id": "glasses",
                "icon": "glasses",
                "label": "Glasses",
                "kind": "device",
                "at": [640, 720],
                "size": 150,
                "tint": "#c6f432",
                "ink": "#14201a",
                "labelAt": "right",
                "labelColor": "#e4f7c4",
            },
            {
                "id": "mb",
                "kind": "membase",
                "base": "local",
                "tab": "Local engine, inside Pacenote",
                "folder": "Jamie's folder",
                "box": [940, 250, 850, 640],
                "slots": [
                    {
                        "id": "runs",
                        "label": "Jamie's runs",
                        "icon": "activity",
                        "facts": [
                            "Mon 12 Oct · faded after km 7",
                            "Tue 6 Oct · faded after km 7",
                            "Wed 30 Sep · faded after km 7",
                        ],
                    }
                ],
            },
        ],
        "beats": [
            {
                "say": "Before the run, the brief reads past runs",
                "membase": "recall",
                "hit": 0,
                "flows": [
                    {
                        "from": "phone",
                        "to": "mb",
                        "token": {"label": "recent runs", "icon": "search"},
                    },
                    {"from": "mb", "to": "phone", "token": "all 5 faded"},
                ],
            },
            {
                "say": "At km 6.5, a cue in the glasses",
                "flows": [
                    {
                        "from": "phone",
                        "to": "glasses",
                        "token": {"label": "the cue", "icon": "activity"},
                    },
                    {"from": "glasses", "to": "jamie", "token": "hold steady"},
                ],
            },
            {
                "say": "Today's run is saved, dated today",
                "membase": "learn",
                "facts": ["Today · held after km 7"],
                "flows": [
                    {
                        "from": "phone",
                        "to": "mb",
                        "token": {"label": "today's run", "icon": "file-text"},
                    }
                ],
            },
        ],
    },
}
SEED = ["17-run-coach-hud/seed.py"]


def expected_count() -> tuple[int, int]:
    """Faded runs over 7 km in the seeded history: km 8 on at least 15 s/km slower than km 3-7.
    Worked out from seed.py's RUNS, apart from the app's own code."""
    spec = importlib.util.spec_from_file_location(
        "seed17", Path(__file__).resolve().parent / "seed.py"
    )
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    faded = total = 0
    for _days, _hhmm, _kind, splits, *_ in seed.RUNS:
        s = [seed.m(x) for x in splits.split()]
        if len(s) <= 7:
            continue
        total += 1
        faded += sum(s[7:]) / len(s[7:]) - sum(s[2:7]) / 5 >= 15
    return faded, total


async def text(page, selector: str) -> str:
    return (await page.locator(selector).first.inner_text()).strip()


async def count(page) -> tuple[int, int, str]:
    c = page.locator("#count")
    return (
        int(await c.get_attribute("data-faded")),
        int(await c.get_attribute("data-of")),
        await c.get_attribute("data-latest"),
    )


async def act(page, rec) -> None:
    faded, total = expected_count()

    rec.step(1, "Before the run: the brief", "Pacenote reads Jamie's last runs from memory")
    await rec.focus("#phone", pad=10)
    await rec.wait("Recalling Jamie's runs", page.wait_for_selector("#start", timeout=180_000))
    got = await count(page)
    if got[:2] != (faded, total):
        raise SystemExit(f"the brief counts {got}, the seeded runs give {faded} of {total}")
    if "last 10 runs" not in await text(page, "#rcount"):
        raise SystemExit(f"recall did not return all ten runs: {await text(page, '#rcount')}")
    await rec.pause(3.0)
    rec.step(
        1,
        "Counted from those runs",
        f"{faded} of {total} runs over 7 km faded after km 7, counted in code from their splits",
    )
    await rec.focus("#pattern", pad=12)
    await rec.pause(4.2)

    rec.step(2, "The run, through the glasses", "Pace, distance and heart rate at the lens edges")
    await rec.click("#start")
    await rec.focus(None)
    await rec.pause(3.5)
    await rec.wait(
        "Kilometres 0 to 6.5",
        page.wait_for_selector('#cue.on[data-counted="1"]', timeout=180_000),
    )
    cue = await text(page, "#cue-t")
    if not cue.startswith(f"{faded} of your last {total} runs over 7 km faded after km 7"):
        raise SystemExit(f"the km 6.5 cue says {cue!r}")
    if await page.locator("#cue-runs .r").count() != total:
        raise SystemExit("the cue does not show every run it counted")
    rec.step(
        2,
        "km 6.5: the coach speaks up",
        f"In the lens: the {faded} past runs that faded after km 7. Hold 5:18 now",
    )
    await rec.focus("#cue", pad=24)
    await rec.pause(6.5)
    await rec.focus(None)
    await rec.wait("Kilometres 6.5 to 10", page.wait_for_selector("#saved", timeout=180_000))

    rec.step(3, "Saved to memory", "Today's 10 km held after km 7. Written to memory, dated now")
    felt = await text(page, "#felt")
    if "No fade after km 7" not in felt:
        raise SystemExit(f"the simulated run faded: {felt!r}")
    await rec.focus("#phone", pad=10)
    await rec.pause(5.5)

    rec.step(
        4,
        "The next brief reads it",
        f"Today's run is recalled: now {faded} of {total + 1} faded, and the latest held",
    )
    await rec.click("#next")
    await rec.wait(
        "Recalling, today's run included", page.wait_for_selector("#start", timeout=180_000)
    )
    if not await page.locator("#fresh").count():
        raise SystemExit("the next brief did not recall today's run")
    got = await count(page)
    if got != (faded, total + 1, "false"):
        raise SystemExit(
            f"the next brief counts {got}, expected {faded} of {total + 1}, latest held"
        )
    await rec.pause(1.5)
    await rec.focus("#pattern", pad=12)
    await rec.pause(5.0)
    await rec.focus(None)
    await rec.pause(2.5)
