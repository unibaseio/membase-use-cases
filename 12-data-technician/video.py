"""The data technician video, on the local engine. The page is Benchlog, a lab notebook. After the
explainer: the QC agent labels window T01 with tool calls and gets it wrong (a lone
outlier it calls a spike); Dr. Ito corrects it in one handwritten sentence, the lab's rule; the
corrected run is ingested as agent memory and an SOP card (the skill) is filed in the binder;
window T07, the same kind, is labelled with that SOP read first and comes out right; the
validation plate (the held-out batch) runs again and the page shows both measured scores.

The baseline held-out score is measured in `setup()`, on the same fresh lab, just before the
recording starts; the page labels it "before teaching". The scientist's sentence is the lab's own
rule from windows.py. The take checks every payoff on the page and stops if T01 comes out right,
nothing is learned, T07 is still wrong, or the held-out score did not rise: record it again.
"""

import json
import urllib.request

LAB = "video-lab"
META = {
    "title": "Data technician",
    "title_html": "An agent that learns<br>from one correction",
    "pitch": "The scientist corrects one label with a reason. The run becomes an SOP the agent reads first, and the next window of that kind comes out right.",
    "base": "local",
    "port": 8712,
    "path": f"?lab={LAB}",
    "banner_from_recording": True,
    "line": "One correction, with a reason, becomes a skill the agent reads first.",
    "explain": {
        "title": "Corrected runs become skills",
        "actors": [
            {"id": "ito", "icon": "user", "label": "Dr. Ito", "kind": "user", "at": [170, 560]},
            {
                "id": "lab",
                "icon": "flask-conical",
                "label": "Benchlog",
                "kind": "app",
                "box": [360, 205, 1470, 725],
                "tint": "#f4f1e8",
                "ink": "#1f3a33",
            },
            {
                "id": "agent",
                "icon": "bot",
                "label": "QC agent",
                "kind": "agent",
                "at": [640, 540],
                "size": 170,
                "tint": "#1f3a33",
                "ink": "#fff",
            },
            {
                "id": "mb",
                "kind": "membase",
                "base": "local",
                "tab": "Local engine, inside Benchlog",
                "folder": "This lab's folder",
                "box": [940, 290, 850, 520],
                "slots": [{"id": "lab", "label": "Agent memory", "icon": "bot"}],
            },
        ],
        "beats": [
            {
                "say": "Dr. Ito corrects one label, and says why",
                "flows": [
                    {"from": "agent", "to": "ito", "token": {"label": "T01: spike", "icon": "x"}},
                    {
                        "from": "ito",
                        "to": "agent",
                        "token": {"label": "only z ≥ 8", "icon": "pen-line"},
                    },
                ],
            },
            {
                "say": "The run becomes a case, then a skill",
                "membase": "learn",
                "facts": ["Case: T01, corrected", "Skill: SOP-01"],
                "flows": [
                    {
                        "from": "agent",
                        "to": "mb",
                        "token": {"label": "the run", "icon": "file-text"},
                    }
                ],
            },
            {
                "say": "On T07, it reads the skill first",
                "membase": "recall",
                "hit": 1,
                "flows": [
                    {
                        "from": "agent",
                        "to": "mb",
                        "token": {"label": "T07's shape", "icon": "search"},
                    },
                    {"from": "mb", "to": "agent", "token": "SOP-01", "result": "T07: clean"},
                ],
            },
        ],
    },
}
SEED: list[str] = []


def setup() -> None:
    """The baseline: the held-out batch on the new, empty lab, measured before recording."""
    base = f"http://127.0.0.1:{META['port']}"
    urllib.request.urlopen(f"{base}/api/lab?lab={LAB}", timeout=60).read()
    req = urllib.request.Request(
        f"{base}/api/evaluate",
        data=json.dumps({"lab": LAB}).encode(),
        headers={"Content-Type": "application/json"},
    )
    point = None
    with urllib.request.urlopen(req, timeout=600) as r:
        for line in r:
            if line.startswith(b"data: "):
                ev = json.loads(line[6:])
                if ev["type"] == "error":
                    raise SystemExit(f"baseline failed: {ev['error']}")
                if ev["type"] == "point":
                    point = ev
    if not point:
        raise SystemExit("baseline returned no score")
    print(f"baseline: {point['correct']}/{point['total']}")


VERDICT = "#verdict-ok, #verdict-bad"


async def classify(page, rec, label: str) -> bool:
    await rec.click("#classify")
    await rec.focus("#stage", pad=6)
    await rec.wait(label, page.wait_for_selector(VERDICT, timeout=180_000))
    return await page.locator("#verdict-ok").count() > 0


async def act(page, rec) -> None:
    await page.wait_for_selector("#tile-T01", timeout=60_000)
    state = await page.evaluate(f"() => fetch('/api/lab?lab={LAB}').then((r) => r.json())")
    if not state["curve"]:
        raise SystemExit("no baseline on the validation plate")
    before = state["curve"][0]["correct"]
    await page.evaluate("document.fonts.ready")

    rec.step(
        1,
        "The QC agent labels window T01",
        "It inspects the readings with its tools. The SOP binder is empty",
    )
    await rec.focus(None)
    await rec.pause(2.2)
    if await classify(page, rec, "The agent calls its tools"):
        raise SystemExit("the agent got T01 right on its own: nothing to teach, record again")
    rec.step(1, "The QC agent labels window T01", "It finds one reading at z 6 and says spike")
    await rec.focus(".plotbox", pad=8)
    await rec.pause(2.4)
    rec.step(1, "The QC agent labels window T01", "Its label: spike. The lab's label: clean")
    await rec.focus("#verdict-bad", pad=12)
    await rec.pause(2.2)

    rec.step(2, "Dr. Ito says why", "One handwritten sentence: the lab's rule for a lone outlier")
    rule = await page.input_value("#fix-reason")
    await rec.focus("#verdict-bad", pad=12)
    await rec.type("#fix-reason", rule, delay=14)
    await rec.pause(0.8)
    await rec.click("#teach")
    await rec.pause(1.2)

    rec.step(
        3, "The run becomes an SOP", "The agent re-checks; the corrected run goes into agent memory"
    )
    await rec.focus("#stage", pad=6)
    await rec.wait(
        "The agent re-checks; the run is ingested",
        page.wait_for_selector("#learned", timeout=240_000),
    )
    if await page.locator("#learned.learned").count() == 0:
        text = await page.locator("#learned").inner_text()
        raise SystemExit(f"the engine kept nothing from the run: {text!r}")
    await page.wait_for_selector("#skills .sop blockquote", timeout=30_000)
    await rec.focus("#learned", pad=12)
    await rec.pause(2.0)
    rec.step(3, "The run becomes an SOP", "Filed in the binder, with Dr. Ito's note and signature")
    await rec.focus("#sop-1", pad=12)
    await rec.pause(3.2)

    rec.step(4, "Window T07, the same kind", "The agent reads the SOP before it starts")
    await rec.focus(None)
    await rec.click("#tile-T07")
    await rec.pause(0.6)
    await rec.click("#classify")
    await rec.focus("#stage", pad=6)
    await rec.wait(
        "Searching agent memory", page.wait_for_selector("#notes-skill", timeout=180_000)
    )
    await rec.focus("#notes-skill", pad=12)
    await rec.pause(2.6)
    await rec.focus("#stage", pad=6)
    await rec.wait("The agent calls its tools", page.wait_for_selector(VERDICT, timeout=180_000))
    if await page.locator("#verdict-ok").count() == 0:
        raise SystemExit("T07 is still wrong after the correction: record again")
    rec.step(4, "Window T07, the same kind", "Clean, as the lab labels it: it followed the SOP")
    await rec.focus("#verdict-ok", pad=12)
    await rec.pause(2.6)

    rec.step(5, "The validation plate", "Twelve windows the agent is never corrected on")
    await rec.focus(None)
    await rec.click("#plate-link")
    await rec.pause(1.6)
    await rec.click("#evaluate")
    await rec.focus("#stage", pad=6)
    await rec.wait(
        "The agent labels 12 held-out windows",
        page.wait_for_selector("#heldnum", timeout=600_000),
    )
    after = int((await page.locator("#heldnum").inner_text()).split("/")[0])
    if after <= before:
        raise SystemExit(f"held-out did not rise ({before} -> {after}): record again")
    rec.step(
        5,
        "The validation plate",
        f"{before} of 12 right before teaching, {after} after one correction",
    )
    await rec.hide_cursor()  # the closing frame is the banner: nothing over the scores
    await rec.focus("#score", pad=12)
    await rec.pause(3.0)
    await rec.focus(None)
    await rec.pause(2.4)
