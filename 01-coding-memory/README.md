# Coding memory

Your coding CLI remembers across sessions on its own. When a session starts, it is told what you
decided about this project before. Each prompt is checked against memory, and anything relevant
is added to it. When a session ends, the session is saved. You don't run any commands and the
model doesn't have to decide to use memory.

This works in Claude Code and Codex CLI, both tested here. Gemini CLI is wired the same way but
was not tested, because it isn't installed on the test machine. In all three the agent can also
call the Membase tools itself over MCP.

**Shows:** automatic long-term memory for coding agents: recall at session start and on every
prompt, and one save per session.
**Base:** hosted (Membase with a developer key). It runs only on hosted.

## Video

https://github.com/user-attachments/assets/ac1ab9e6-ec28-454f-bf2b-4cb935630a95

66 s · hosted Membase and the real Claude Code, replayed in a terminal at the pace the two sessions ran (long waits are played short, with their real length on screen). The terminal is split: the plugin's own log (`tail -f ~/.membase/hooks.log`) at the top, the shell below, and the status bar shows the `Coding` memory's state.

1. **Session 1.** `claude -p` reads `billing/numbering.py`, and you decide that new invoice numbers are ULIDs made on the device (`INV-<ULID>`) and old numbers never change.
2. **The session ends.** The log shows the plugin saving it to the `Coding` memory, and the status bar shows the memory learning it (26 s, played sped up).
3. **Session 2.** `clear`, then a brand-new `claude` process. `cat billing/numbering.py` shows the code still says `max + 1`.
4. **It already knows.** The `UserPromptSubmit` hook's context, exactly as Claude Code received it, holds the decision from Membase, and the answer says to use `INV-<ULID>` and never renumber old invoices.

Claude Code's own auto-memory was switched off and checked empty, so the second session can only have learned the decision from Membase.

## What is in this folder

```
claude-plugin/                 the Claude Code plugin
  .claude-plugin/plugin.json
  hooks/hooks.json             SessionStart, UserPromptSubmit, SessionEnd
  hooks/run.sh                 starts the hook with a Python that has the Membase SDK
  hooks/membase_memory.py      the hook engine, shared by all three CLIs
  .mcp.json                    the hosted Membase MCP server, authorized with your key
.claude-plugin/marketplace.json  makes this folder a local plugin marketplace
install.py                     one-command install for claude | codex | gemini
fixtures/claude-session.jsonl  a sample Claude Code session (real transcript format)
smoke.py                       the end-to-end check
app.py, static/                a page that runs the same hooks on the sample session (port 8701)
video_capture.py, video.py     the video: two real `claude -p` runs, captured, then replayed in
  static/video.html            a terminal page
```

## Install

You need a developer key (`mbk_…`) from the Membase app, under **Connect › Developer keys**. A
*Read & write* or *Full access* key saves sessions; a *Read* key only recalls.

```bash
python3 01-coding-memory/install.py claude --key mbk_…   # Claude Code
python3 01-coding-memory/install.py codex  --key mbk_…   # Codex CLI
python3 01-coding-memory/install.py gemini --key mbk_…   # Gemini CLI
python3 01-coding-memory/install.py codex --uninstall    # remove it again
```

The installer uses only the standard library and works with any Python 3.9 or newer. Every CLI
shares one settings file, `~/.membase/config.env` (mode 600), and the hooks read the key from
there. The key is never written into a CLI's own config. Before changing a config file, the
installer backs it up as `<file>.membase-backup`.

The hooks need the Membase Python SDK. `run.sh` uses `uv` when it is installed: the first hook
takes a few seconds to build a cached environment, and later hooks start immediately. Without uv,
run `pip install unibaseio-membase`, or set `MEMBASE_HOOK_PYTHON=/path/to/python` in
`config.env`. The hooks need macOS or Linux; Windows is not supported.

The MCP server reads `MEMBASE_API_KEY` from the environment the CLI starts in (Claude Code
expands it in `.mcp.json`; Codex uses `bearer_token_env_var`). Export the key in your shell
profile so the agent can call the tools itself. The hooks work without either variable.

### Without the installer

- **Claude Code.** Run `claude plugin marketplace add ./01-coding-memory`, then
  `claude plugin install membase-memory@membase-demos`. To try it for one session only, run
  `claude --plugin-dir ./01-coding-memory/claude-plugin`.
- **Codex.** Copy `hooks/run.sh` and `hooks/membase_memory.py` to `~/.membase/hooks/`, add the
  four entries from `install.py` to `~/.codex/hooks.json`, then run
  `codex mcp add membase --url https://api.app.membase.ai/mcp-http --bearer-token-env-var MEMBASE_API_KEY`.
- **Gemini CLI.** The same, with the entries in the `hooks` block of `~/.gemini/settings.json`.

## What is automatic, per CLI

| | Claude Code (plugin) | Codex CLI (hooks) | Gemini CLI (hooks) |
|---|---|---|---|
| Recall at session start: profile and project memory | automatic (`SessionStart`) | automatic (`SessionStart`) | automatic (`SessionStart`)\* |
| Recall on every prompt | automatic (`UserPromptSubmit`) | automatic (`UserPromptSubmit`) | automatic (`BeforeAgent`)\* |
| Save the session | automatic, once, at `SessionEnd`, from the transcript | automatic, from turns gathered at `UserPromptSubmit` and `Stop`. Saved at `SessionEnd` on Codex builds that have it; on 0.125, once the session has been quiet for 20 minutes (checked when another Codex session starts or ends a turn) | automatic (`AfterAgent` gathers turns, `SessionEnd` saves)\* |
| Search, add or forget on request | model-initiated, over MCP (`search_memories`, `add_memory`, …) | model-initiated, over MCP; an `AGENTS.md` block says when | model-initiated, over MCP; a `GEMINI.md` block says when\* |
| Tested here | yes: hooks and MCP in a real `claude -p` run (2.1.226) | yes: hooks and MCP in real `codex exec` runs (0.125.0) | no, not installed here |

\* From the Gemini CLI hooks reference (`hookSpecificOutput.additionalContext`, timeouts in ms,
`SessionEnd` best effort). Untested here. Gemini only expands `$VAR` in an MCP server's `env`
block for certain, so `Bearer ${MEMBASE_API_KEY}` in `headers` may need the key written in
literally.

Codex 0.125 runs hooks, but does not have `SessionEnd` or `PreCompact` yet: they appear in the
current Codex docs, and 0.125 ignores entries it does not know. The installer registers
`SessionEnd` anyway, so it starts working once Codex supports it.

## How the hooks behave

- **They never block you.** Any failure goes to `~/.membase/hooks.log` and the hook exits 0
  with no output.
- **Recall has a time budget.** `MEMBASE_RECALL_BUDGET` defaults to 10 seconds. A hosted search
  is a turn in your account's agent: about 7–10 s when the account is awake, and up to about
  90 s when it is waking. The search runs in its own process. If it answers in time, its hits
  go with this prompt. If not, it keeps going, and what it finds is added to the next prompt,
  marked as late. A slow memory costs one prompt of delay; the answer is not lost, and the
  search is never repeated. At session start this search also wakes the account.
- **One save per session.** Each hosted write starts a learning run, so the session is written
  once with `memories.add`, when it ends. Only user and assistant text is kept: no tool calls,
  tool output, thinking, slash commands or `<system-reminder>` text. Each message is cut at
  1,500 characters and the session at 12,000; the first request and the latest turns are kept.
  The page at port 8701 shows what is kept and what is dropped. A resumed session saves only
  what is new.
- **The save runs detached.** Claude Code gives `SessionEnd` hooks about 1.5 s, Codex gives
  1–3 s, and Gemini does not wait at all. The hook writes the session to `~/.membase/state/pending/`
  and starts a separate process that saves it. If the save fails (no network, no container),
  the file stays and is retried at the next session start.
- **No `PreCompact` hook.** Compacting does not remove lines from the transcript file, so
  `SessionEnd` still sees the whole session. Saving before compaction too would cost a second
  write and a second learning run.

### Which Memory (container)

1. `MEMBASE_CONTAINER` (a name or an id), if set. A name the key cannot reach is an error, and
   the error is logged.
2. Otherwise, a Memory named like the project, meaning its git folder name, matched without
   regard to case.
3. Otherwise, a Memory named `Coding`.
4. Otherwise, the only Memory the key reaches.

If none of these matches, recall searches every Memory the key reaches and sessions are not
saved; the log says why. To give each repository its own Memory, create one with the
repository's name, or set `MEMBASE_CONTAINER` in that project's environment.

### Settings (`~/.membase/config.env` or the environment)

| | |
|---|---|
| `MEMBASE_API_KEY` | the developer key (required) |
| `MEMBASE_BASE_URL` | default `https://api.app.membase.ai` |
| `MEMBASE_CONTAINER` | the Memory to use (see above) |
| `MEMBASE_RECALL_BUDGET` | seconds a prompt waits for memory (default 10) |
| `MEMBASE_AUTOSAVE` | `0` turns off saving; recall still works |
| `MEMBASE_HOOK_PYTHON` | a Python with `unibaseio-membase`, instead of uv |
| `MEMBASE_HOME` | where the settings, log and state live (default `~/.membase`) |

## Try it

```bash
uv run 01-coding-memory/smoke.py      # MEMBASE_API_KEY in .env, with a Memory named Coding
uv run 01-coding-memory/app.py        # http://127.0.0.1:8701
```

The smoke gives the `SessionEnd` hook the sample transcript and checks that the hook returns at
once and that the detached save lands. It then waits until Membase has learned the session and
sends a related prompt through `UserPromptSubmit`. The decision must be in the injected context.
Last, if `claude` is installed, it does one real `claude -p --plugin-dir` run and reports what
the hooks and MCP did. The page runs the same hooks on the same sample: end the session, then
send a prompt from a new one. It keeps its own hook state under `data/01-coding-memory/`.

What to try in a real session: decide something specific (a naming rule, why a library was
chosen), then quit. Start a new session in the same repository and ask about it without
mentioning it.
