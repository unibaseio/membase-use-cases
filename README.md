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
| 01 | [Coding memory](01-coding-memory/) | Claude Code, Codex and Gemini CLI remember across sessions on their own | hosted | [▶ 76 s](#01-coding-memory) |
| 02 | [Book memory](02-book-memory/) | With memory vs without, side by side, with the passages used | hosted | [▶ 55 s](#02-book-memory) |
| 03 | [Study buddy](03-study-buddy/) | Course material plus what you keep getting wrong | hosted | [▶ 85 s](#03-study-buddy) |
| 04 | [Story bible](04-story-bible/) | One creative memory shared by every AI you write with | hosted | [▶ 70 s](#04-story-bible) |
| 05 | [Agent team](05-agent-team/) | Several agents share one memory; a read-only key cannot write | hosted | [▶ 63 s](#05-agent-team) |
| 06 | [Browser memory](06-browser-memory/) | Ask your memory about the page you are on | hosted | [▶ 67 s](#06-browser-memory) |
| 07 | [Memory graph](07-memory-graph/) | What memory holds, as people, places and links | local | [▶ 63 s](#07-memory-graph) |
| 08 | [Companion](08-companion/) | A character that remembers you and follows up | local | [▶ 62 s](#08-companion) |
| 09 | [Taste journal](09-taste-journal/) | Tastings become a palate profile and a star map | local | [▶ 75 s](#09-taste-journal) |
| 10 | [Quest log](10-quest-log/) | Daily plans as quests, shaped by your habits | local | [▶ 59 s](#10-quest-log) |
| 11 | [NPC mystery](11-npc-mystery/) | Characters remember what you told them and gossip | local | [▶ 81 s](#11-npc-mystery) |
| 12 | [Data technician](12-data-technician/) | An agent learns a scientist's corrections as skills | local | [▶ 67 s](#12-data-technician) |
| 13 | [Screen memory](13-screen-memory/) | Screenshots analysed, remembered and reused | local | [▶ 65 s](#13-screen-memory) |
| 14 | [Care companion](14-care-companion/) | Daily-life memory for someone who forgets | local | [▶ 69 s](#14-care-companion) |
| 15 | [Reunite](15-reunite/) | Matching two people's memories of the same past | local | [▶ 59 s](#15-reunite) |
| 16 | [Wearable diary](16-wearable-diary/) | A day of audio becomes conversation memory | local | [▶ 66 s](#16-wearable-diary) |
| 17 | [Run coach HUD](17-run-coach-hud/) | Glasses-style coach that remembers past runs | local | [▶ 56 s](#17-run-coach-hud) |

All the data in these demos is synthetic or public domain.

## Videos

Each demo has a video of about a minute, recorded from the real app on the real API and a real
model. Each starts with a card that shows how the app and Membase fit together, then follows one
concrete case to its payoff. Waits (learning, recall, model calls) play sped up, with their real
length shown. Each video plays right here; each demo's README lists what its video shows, step
by step.

<a name="01-coding-memory"></a>
### 01 · [Coding memory](01-coding-memory/) · 76 s

A new Claude Code session already knows yesterday's decision.

https://github.com/user-attachments/assets/873b16d3-cfc4-40e7-9e31-f5a2c420253c

<a name="02-book-memory"></a>
### 02 · [Book memory](02-book-memory/) · 55 s

A book the model never read: right with memory, wrong without.

https://github.com/user-attachments/assets/fe3475af-c4fb-40f5-bd5d-d5698fc62c9b

<a name="03-study-buddy"></a>
### 03 · [Study buddy](03-study-buddy/) · 85 s

The review goes straight to the two mistakes.

https://github.com/user-attachments/assets/9ade94e4-a70a-4f99-947b-2e460dfdc279

<a name="04-story-bible"></a>
### 04 · [Story bible](04-story-bible/) · 70 s

A draft checked against canon, and Claude Code reads the same canon.

https://github.com/user-attachments/assets/c7a67370-2ec0-4abe-bc95-5227ef8b5f27

<a name="05-agent-team"></a>
### 05 · [Agent team](05-agent-team/) · 63 s

Fixer recalls the Investigator's finding; a read-only key gets 403.

https://github.com/user-attachments/assets/1b81a2db-8cfd-451e-884c-471c670105ea

<a name="06-browser-memory"></a>
### 06 · [Browser memory](06-browser-memory/) · 67 s

A forecast page answered from two pages read days earlier.

https://github.com/user-attachments/assets/db2ce7eb-7cb4-481f-8c74-34bc7a196a86

<a name="07-memory-graph"></a>
### 07 · [Memory graph](07-memory-graph/) · 63 s

One new sentence lights up what it touched.

https://github.com/user-attachments/assets/1833086a-2144-49d7-8f58-6ff9603a7554

<a name="08-companion"></a>
### 08 · [Companion](08-companion/) · 62 s

Wren asks about Maya's interview; Theo's Wren knows nothing.

https://github.com/user-attachments/assets/2ab8a549-70e8-4db2-9ace-9867701130f6

<a name="09-taste-journal"></a>
### 09 · [Taste journal](09-taste-journal/) · 75 s

A suggestion that cites the tastings behind it.

https://github.com/user-attachments/assets/5be70d9e-0792-4b1c-9f7e-06dc4854cdfc

<a name="10-quest-log"></a>
### 10 · [Quest log](10-quest-log/) · 59 s

Three skipped Mondays move the gym to 18:30.

https://github.com/user-attachments/assets/1080200b-5159-446f-beb0-c6366acaa4d2

<a name="11-npc-mystery"></a>
### 11 · [NPC mystery](11-npc-mystery/) · 81 s

Gossip reaches Elsie, not Tobias.

https://github.com/user-attachments/assets/3fadbbf1-5c19-4b0d-b49a-0789b9d70b7a

<a name="12-data-technician"></a>
### 12 · [Data technician](12-data-technician/) · 67 s

One correction becomes a skill: 6 → 8 of 12.

https://github.com/user-attachments/assets/9422ec0e-c766-4079-a58e-ef8845d642c9

<a name="13-screen-memory"></a>
### 13 · [Screen memory](13-screen-memory/) · 65 s

"My flight number?" answered from the screenshot.

https://github.com/user-attachments/assets/36baa455-333c-441d-9c7e-4c0c58214b36

<a name="14-care-companion"></a>
### 14 · [Care companion](14-care-companion/) · 69 s

A fix to the log changes the next answer.

https://github.com/user-attachments/assets/86483dff-a927-4537-a0ca-6cf16eaf0c1c

<a name="15-reunite"></a>
### 15 · [Reunite](15-reunite/) · 59 s

"Fire engine" matches "fire truck"; a person decides.

https://github.com/user-attachments/assets/d81d8124-bd24-43de-804d-63c5abb89611

<a name="16-wearable-diary"></a>
### 16 · [Wearable diary](16-wearable-diary/) · 66 s

A later clip moved the meeting to 3:30.

https://github.com/user-attachments/assets/3d542882-39dd-4b0a-8d37-8774f3a3ee3d

<a name="17-run-coach-hud"></a>
### 17 · [Run coach HUD](17-run-coach-hud/) · 56 s

A cue at km 6.5 from the 5 runs that faded.

https://github.com/user-attachments/assets/98269966-c9dc-474b-ac32-776173327b30

## Layout

- `demokit/`: what every demo shares. It holds settings, model calls (`llm`), memory on either
  base (`Memory`), the web shell (`web`), and the page assets served at `/kit`.
- `NN-name/`: one demo, with `app.py` (the server), `static/` (the page), its own `README.md`
  and `smoke.py`. The smoke script runs the demo's flow against the real API.
- `scripts/`: tooling for development, such as `bootstrap_hosted.py`.
