# Membase use cases

Seventeen things that long-term memory makes possible, each built as a small app you can run.
Every app calls the real Membase API and a real model; nothing is mocked. Each one has a video
of about a minute.

## The two bases

Every demo is written once against the same SDK (`membase.Membase`) and runs on either base:

| Base | What it is | Use it for |
|---|---|---|
| **hosted** | The Membase service, with a developer key from the app (Connect › Developer keys) | One person and their AIs. This is the product itself. |
| **local** | The same API, answered in process by the local engine (`unibaseio-membase[local]`), one directory per end user | Apps that serve many people, such as companions and games, where each person's memory lives in its own directory |

Each demo has a default base. Set `MEMBASE_DEMO_MODE=local|hosted` to switch. Agent memory
(cases and skills learned from agent runs) exists only on the local engine today.

## Setup

```bash
uv sync                      # Python 3.12 or 3.13
cp .env.example .env         # set OPENAI_API_KEY, and MEMBASE_API_KEY for hosted demos
```

For the hosted demos, create the Memory a demo names in the Membase app and a developer key
under **Connect › Developer keys**, and put the key in `.env`.

## Use cases

| # | Demo | Shows | Base | Video |
|---|---|---|---|---|
| 01 | [Coding memory](01-coding-memory/) | Claude Code, Codex and Gemini CLI remember across sessions on their own | hosted | [▶ 66 s](#01-coding-memory) |
| 02 | [Book memory](02-book-memory/) | With memory vs without, side by side, with the passages used | hosted | [▶ 55 s](#02-book-memory) |
| 03 | [Study buddy](03-study-buddy/) | Course material plus what you keep getting wrong | hosted | [▶ 79 s](#03-study-buddy) |
| 04 | [Story bible](04-story-bible/) | One creative memory shared by every AI you write with | hosted | [▶ 66 s](#04-story-bible) |
| 05 | [Agent team](05-agent-team/) | Several agents share one memory; a read-only key cannot write | hosted | [▶ 60 s](#05-agent-team) |
| 06 | [Browser memory](06-browser-memory/) | Ask your memory about the page you are on | hosted | [▶ 63 s](#06-browser-memory) |
| 07 | [Memory graph](07-memory-graph/) | What memory holds, as people, places and links | local | [▶ 58 s](#07-memory-graph) |
| 08 | [Companion](08-companion/) | A character that remembers you and follows up | local | [▶ 57 s](#08-companion) |
| 09 | [Taste journal](09-taste-journal/) | Tastings become a palate profile and a star map | local | [▶ 70 s](#09-taste-journal) |
| 10 | [Quest log](10-quest-log/) | Daily plans as quests, shaped by your habits | local | [▶ 55 s](#10-quest-log) |
| 11 | [NPC mystery](11-npc-mystery/) | Characters remember what you told them and gossip | local | [▶ 81 s](#11-npc-mystery) |
| 12 | [Data technician](12-data-technician/) | An agent learns a scientist's corrections as skills | local | [▶ 64 s](#12-data-technician) |
| 13 | [Screen memory](13-screen-memory/) | Screenshots analysed, remembered and reused | local | [▶ 59 s](#13-screen-memory) |
| 14 | [Care companion](14-care-companion/) | Daily-life memory for someone who forgets | local | [▶ 65 s](#14-care-companion) |
| 15 | [Reunite](15-reunite/) | Matching two people's memories of the same past | local | [▶ 56 s](#15-reunite) |
| 16 | [Wearable diary](16-wearable-diary/) | A day of audio becomes conversation memory | local | [▶ 62 s](#16-wearable-diary) |
| 17 | [Run coach HUD](17-run-coach-hud/) | Glasses-style coach that remembers past runs | local | [▶ 53 s](#17-run-coach-hud) |

All the data in these demos is synthetic or public domain.

## Videos

Each demo has a video of about a minute, recorded from the real app on the real API and a real
model. Each starts with a card that shows how the app and Membase fit together, then follows one
concrete case to its payoff. Waits (learning, recall, model calls) play sped up, with their real
length shown. Each video plays right here; each demo's README lists what its video shows, step
by step.

<a name="01-coding-memory"></a>
### 01 · [Coding memory](01-coding-memory/) · 66 s

A new Claude Code session already knows yesterday's decision.

https://github.com/user-attachments/assets/6226abb2-9910-4134-9acd-5a0637e4f66d

<a name="02-book-memory"></a>
### 02 · [Book memory](02-book-memory/) · 55 s

A book the model never read: right with memory, wrong without.

https://github.com/user-attachments/assets/fe3475af-c4fb-40f5-bd5d-d5698fc62c9b

<a name="03-study-buddy"></a>
### 03 · [Study buddy](03-study-buddy/) · 79 s

The review goes straight to the two mistakes.

https://github.com/user-attachments/assets/42dfe50f-952c-4c9a-856e-aa89f62cd403

<a name="04-story-bible"></a>
### 04 · [Story bible](04-story-bible/) · 66 s

A draft checked against canon, and Claude Code reads the same canon.

https://github.com/user-attachments/assets/65917bdc-055c-4098-ba23-d0661d58c195

<a name="05-agent-team"></a>
### 05 · [Agent team](05-agent-team/) · 60 s

Fixer recalls the Investigator's finding; a read-only key gets 403.

https://github.com/user-attachments/assets/8a041cf0-aea6-43b5-921a-538c703981f9

<a name="06-browser-memory"></a>
### 06 · [Browser memory](06-browser-memory/) · 63 s

A forecast page answered from two pages read days earlier.

https://github.com/user-attachments/assets/b8a1006c-066d-4ffc-a70a-dbd426845919

<a name="07-memory-graph"></a>
### 07 · [Memory graph](07-memory-graph/) · 58 s

One new sentence lights up what it touched.

https://github.com/user-attachments/assets/d8717c7e-468f-40c1-9044-db5c2e53bfb0

<a name="08-companion"></a>
### 08 · [Companion](08-companion/) · 57 s

Wren asks about Maya's interview; Theo's Wren knows nothing.

https://github.com/user-attachments/assets/932d78fd-597a-4476-9514-a36e07e174a3

<a name="09-taste-journal"></a>
### 09 · [Taste journal](09-taste-journal/) · 70 s

A suggestion that cites the tastings behind it.

https://github.com/user-attachments/assets/4e7d1362-9378-4a89-a79c-f2497d50e3ad

<a name="10-quest-log"></a>
### 10 · [Quest log](10-quest-log/) · 55 s

Three skipped Mondays move the gym to 18:30.

https://github.com/user-attachments/assets/f622dbbc-4d0b-44ce-b0de-8792986f2bf5

<a name="11-npc-mystery"></a>
### 11 · [NPC mystery](11-npc-mystery/) · 81 s

Gossip reaches Elsie, not Tobias.

https://github.com/user-attachments/assets/3fadbbf1-5c19-4b0d-b49a-0789b9d70b7a

<a name="12-data-technician"></a>
### 12 · [Data technician](12-data-technician/) · 64 s

One correction becomes a skill: 6 → 8 of 12.

https://github.com/user-attachments/assets/2f793acd-c926-43f8-b104-aeccbdb0a21e

<a name="13-screen-memory"></a>
### 13 · [Screen memory](13-screen-memory/) · 59 s

"My flight number?" answered from the screenshot.

https://github.com/user-attachments/assets/4bad0e02-0315-4da7-8480-b72a8bc8d853

<a name="14-care-companion"></a>
### 14 · [Care companion](14-care-companion/) · 65 s

A fix to the log changes the next answer.

https://github.com/user-attachments/assets/82e1e890-8d0d-4ec1-bdd1-2faea4fd2892

<a name="15-reunite"></a>
### 15 · [Reunite](15-reunite/) · 56 s

"Fire engine" matches "fire truck"; a person decides.

https://github.com/user-attachments/assets/3fb5c8f6-ccaf-4519-828f-2f5ca88dc5cf

<a name="16-wearable-diary"></a>
### 16 · [Wearable diary](16-wearable-diary/) · 62 s

A later clip moved the meeting to 3:30.

https://github.com/user-attachments/assets/b5b698eb-2aa7-48b6-affd-1b0e71b64f9a

<a name="17-run-coach-hud"></a>
### 17 · [Run coach HUD](17-run-coach-hud/) · 53 s

A cue at km 6.5 from the 5 runs that faded.

https://github.com/user-attachments/assets/bba27630-6be4-4621-a147-3401925e9183

## Layout

- `demokit/`: what every demo shares. It holds settings, model calls (`llm`), memory on either
  base (`Memory`), the web shell (`web`), and the page assets served at `/kit`.
- `NN-name/`: one demo, with `app.py` (the server), `static/` (the page), its own `README.md`
  and `smoke.py`. The smoke script runs the demo's flow against the real API.
- `scripts/`: tooling for development, such as `bootstrap_hosted.py`.
