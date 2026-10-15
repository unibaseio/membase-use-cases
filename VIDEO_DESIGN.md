# Demo videos: design

Each demo gets three assets: a **banner** for the README grid, a **video** of a real run, and a
short **preview loop** for the demo's own README. The layout follows the EverOS use-case gallery
(a solid colour panel with the title on the left, the product in a browser window on a textured
field on the right; real recordings with stage captions). The look is Membase's own: brand blue
`#3E61FF` and ink `#0F172B`, Bricolage Grotesque for titles and Instrument Sans for text, and the
hatched-line clouds and glow field from membase.ai instead of EverOS's oil-paint texture.

## What EverOS does, and what we keep

- **Banners.** EverOS uses a 1300×553 card for every use case. The left ~50% is a muted solid
  colour with a white two-line title and a two- or three-line pitch. On the right a screenshot
  sits in a macOS window, bleeding off the edge, on a painted texture. *We keep:* the size, the
  split, the browser window and the bleed. *We change:* brand-blue and ink panels instead of earth
  tones, and hatched clouds instead of paint.
- **Video.** EverOS's one video (58 s, 960×720) is a real terminal session in a macOS window on
  the same texture. The camera pushes in on the part being used, and large stage labels name
  each step ("Ingest", "Index", "Memory Recalled"). *We keep:* real recordings, a slow push-in
  on the active area, and one stage label per step. *We change:* 1920×1080, a visible cursor
  (ours is a web UI, not a terminal), and an honest marker on every wait that was sped up.

## The grammar every video follows

Memory only shows over time, so every video tells the same three-step story in about 25–40 s:

1. **Tell it**: something goes into memory (a conversation, a document, a correction).
2. **Later**: a new session, another agent, another person or another page.
3. **It remembers**: the answer uses what was stored and shows where it came from.

Each video has four parts:

- **Intro (2.5 s).** The banner itself: title and pitch, with the window sliding in.
- **Main (20–35 s).** The window on the cloud field. A step label sits at the bottom
  ("1 · Tell it once"), and the camera eases in on the element in use.
- **Waits.** Recall, learning and model calls are played fast, with a corner badge such as
  "⏩ 26 s wait · 12× faster". Nothing is cut silently, and nothing is staged.
- **Outro (2 s).** The demo's name and number, its base (Hosted Membase or Local engine), and
  "github.com/unibaseio/membase-use-cases".

**Preview loop.** About 12 s from the main part, at 960 px wide and 12 fps (GIF), for each demo
README.

## Storyboards

The three beats of each demo. *Focus* is where the camera goes.

| # | Demo | 1 · Tell it | 2 · Later | 3 · It remembers |
|---|---|---|---|---|
| 01 | Coding memory | A session ends; the saved lines are kept and tool output is left out *(focus: transcript)* | New session, a new prompt is sent | The `<membase-memory>` block with last session's decision is injected *(focus: block)* |
| 02 | Book memory | Twelve stories are in memory *(focus: library line)* | A question is typed and the passages are recalled *(focus: passages)* | Two answers side by side; the left one cites the story *(focus: left answer)* |
| 03 | Study buddy | A quiz built from course passages; wrong answers | Each mistake is remembered as one line *(focus: "Remembered: …")* | Weak spots, then a review quiz aimed at them *(focus: weak-spot list)* |
| 04 | Story bible | A draft with planted mistakes; Check consistency | Contradictions, each citing the bible *(focus: issues)* | Continue the scene using bible-only details; accept into canon |
| 05 | Agent team | Run the team; the Investigator writes its finding | The Fixer recalls the finding, patches, and the tests pass | The Auditor's read-only write is refused with 403 *(focus: red card)*; the verdict is Approved |
| 06 | Browser memory | Remember two pages from the side panel | On a third page, ask a question | The answer cites both remembered pages *(focus: "From your memory")* |
| 07 | Memory graph | Rebuild: the graph forms from recalled passages | Search "Aiko" and the node centres | The side panel shows the memories behind the node and how the graph was built |
| 08 | Companion | Maya tells Wren about Thursday's interview | End session: the follow-ups are extracted *(focus: follow-ups)* | New session: Wren opens with the interview; switch to Theo, who is a stranger to Wren |
| 09 | Taste journal | Log a tasting; its star lands on the map | Hover a constellation | "What should I try next?" cites past tastings *(focus: citations)* |
| 10 | Quest log | Type Monday's plan and generate quests | Quests are adapted: "Monday gym skipped 3 of 3" *(focus: Adapted)* | Read my habits gives the evidence; Done adds XP |
| 11 | NPC mystery | Tell Mara about the green glass button | Let time pass; gossip goes Mara → Elsie *(focus: gossip feed)* | Elsie knows, citing Mara; Tobias doesn't |
| 12 | Data technician | The agent labels a window with tool calls and gets it wrong | The scientist corrects it with a reason, and a skill is learned *(focus: skills)* | The held-out curve rises *(focus: chart)* |
| 13 | Screen memory | Add six screenshots; each is read and remembered | Ask "What was my flight number?" | Answered from screenshot S1 *(focus: thumbnail)*; the VPN task reuses a procedure |
| 14 | Care companion | The caregiver logs "Morning pills taken, 08:15" | Margaret asks "Did I take my pills this morning?" | A correction (doctor moved to Friday) changes the next answer *(focus: struck-out answer)* |
| 15 | Reunite | A seeker's earliest memories | Matching finds family F-01 at 90 *(focus: scores)* | Paraphrases line up (metal fire engine ≈ tin fire truck); a person decides |
| 16 | Wearable diary | A day of clips becomes a diary | "What did I promise Sam?" | The answer and its clip; the design review is at 3:30 because the later clip moved it |
| 17 | Run coach HUD | The pre-run brief from past runs | The run streams into the HUD; at km 6.5 the cue says hold steady *(focus: cue)* | The run is saved; the next brief says this time there was no fade |

## Production

`scripts/video/` holds the pipeline. Each demo's `video.py` drives its own page; the beats and
captions live there too.

- **`record.py`.** Drives the page with Playwright and records CDP screencast frames at 2×
  device scale, so a zoom stays sharp. It draws a cursor in the page, and logs beats, focus boxes
  and waits.
- **`compose.html` + `compose.py`.** Render every output frame: the field, the window, the camera,
  the step label and the wait badge. ffmpeg then writes `docs/video.mp4` (H.264, 1920×1080,
  25 fps) and `docs/preview.gif`.
- **`banner.py`.** Renders `docs/banner.png` (1300×553) from the demo's title, pitch and
  screenshot.

Every recording is a real run against the demo's default base. A run whose result is wrong is
not kept; it is recorded again.
