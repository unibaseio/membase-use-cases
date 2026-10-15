#!/usr/bin/env python3
"""Give a coding CLI automatic long-term memory from Membase, in one command.

    python3 install.py claude  --key mbk_...      # Claude Code: the plugin (hooks + MCP)
    python3 install.py codex   --key mbk_...      # Codex CLI: hooks + MCP + an AGENTS.md block
    python3 install.py gemini  --key mbk_...      # Gemini CLI: hooks + MCP + a GEMINI.md block
    python3 install.py codex --uninstall          # take it out again (config.env stays)

Options: --container NAME (the Memory to use; see README), --base-url (another Membase API),
--home DIR (the CLI's config folder, default ~/.codex or ~/.gemini).

Every CLI shares one settings file, ~/.membase/config.env (mode 600), which the hooks read: the
key is never written into a CLI's own config. Standard library only; run it with any Python 3.9+.
Each config file it changes is backed up first as <file>.membase-backup.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE / "claude-plugin"
MEMBASE_HOME = Path(os.environ.get("MEMBASE_HOME") or Path.home() / ".membase").expanduser()
PROD = "https://api.app.membase.ai"
START, END = "<!-- membase-memory:start -->", "<!-- membase-memory:end -->"

INSTRUCTIONS = f"""{START}
## Long-term memory (Membase)

Hooks add what Membase remembers to your context on their own (blocks tagged
`<membase-memory>`) and save each session when it ends. You can also use the `membase` MCP tools:

- Before answering about earlier decisions, conventions or past work on this project, call
  `search_memories` with a plain-language question if nothing relevant was injected.
- When the user asks you to remember something, call `add_memory` with one short,
  self-contained sentence that names the project. Do not save secrets, code dumps or tool output.
- Never call `forget_memory` or `delete_document` unless the user asks for that exact deletion.
{END}
"""


def backup(path: Path) -> None:
    if path.is_file():
        shutil.copy2(path, path.with_name(path.name + ".membase-backup"))


def write_config(a: argparse.Namespace) -> Path:
    """Merge the given settings into ~/.membase/config.env."""
    path = MEMBASE_HOME / "config.env"
    values: dict[str, str] = {}
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
    updates = {
        "MEMBASE_API_KEY": a.key or "",
        "MEMBASE_BASE_URL": a.base_url or "",
        "MEMBASE_CONTAINER": a.container or "",
    }
    updates = {k: v for k, v in updates.items() if v}
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates.pop(key)}")
        else:
            out.append(line)
            if "=" in line and not line.lstrip().startswith("#"):
                values[key] = line.split("=", 1)[1]
    if not lines:
        out.append(
            "# Membase settings, read by the memory hooks of Claude Code, Codex and Gemini CLI"
        )
    out += [f"{k}={v}" for k, v in updates.items()]
    MEMBASE_HOME.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    path.chmod(0o600)
    has_key = "MEMBASE_API_KEY" in values or a.key or os.environ.get("MEMBASE_API_KEY")
    if not has_key:
        print(f"  ! no key yet: add MEMBASE_API_KEY=mbk_... to {path} (Connect > Developer keys)")
    return path


def copy_hooks() -> Path:
    """The hook engine at a fixed place for Codex and Gemini (Claude runs it from the plugin)."""
    dest = MEMBASE_HOME / "hooks"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("membase_memory.py", "run.sh"):
        shutil.copy2(PLUGIN / "hooks" / name, dest / name)
    (dest / "run.sh").chmod(0o755)
    return dest / "run.sh"


def mcp_url(a: argparse.Namespace) -> str:
    return (a.base_url or PROD).rstrip("/") + "/mcp-http"


def edit_markdown(path: Path, *, remove: bool) -> None:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if START in text and END in text:
        head, _, rest = text.partition(START)
        text = (
            head.rstrip("\n") + ("\n" if head.strip() else "") + rest.partition(END)[2].lstrip("\n")
        )
    if not remove:
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + INSTRUCTIONS
    backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def is_ours(command: str) -> bool:
    return any(
        m in command
        for m in (
            "membase_memory",
            "/.membase/hooks/run.sh",
            str(MEMBASE_HOME / "hooks" / "run.sh"),
        )
    )


def merge_hooks(hooks: dict, ours: dict, *, remove: bool) -> dict:
    """Drop any earlier Membase entries, then (unless removing) add ours. Other hooks stay."""
    for event in list(hooks):
        groups = []
        for g in hooks[event]:
            kept = [h for h in g.get("hooks", []) if not is_ours(h.get("command", ""))]
            if kept:
                groups.append({**g, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not remove:
        for event, handler in ours.items():
            hooks.setdefault(event, []).append({"hooks": [handler]})
    return hooks


# ---- per CLI -----------------------------------------------------------------------------


def install_claude(a: argparse.Namespace) -> None:
    if a.uninstall:
        run(["claude", "plugin", "uninstall", "membase-memory@membase-demos"], check=False)
        run(["claude", "plugin", "marketplace", "remove", "membase-demos"], check=False)
        return
    write_config(a)
    run(["claude", "plugin", "marketplace", "add", str(HERE)], check=False)
    run(["claude", "plugin", "install", "membase-memory@membase-demos"])
    print(
        "\n  Claude Code: hooks are automatic from the next session. The bundled MCP server reads\n"
        "  MEMBASE_API_KEY (and MEMBASE_MCP_URL for another Membase API) from the environment Claude Code\n"
        '  starts in: export them in your shell profile, or put them in the "env" block of\n'
        "  ~/.claude/settings.json."
    )


def install_codex(a: argparse.Namespace) -> None:
    home = Path(a.home or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    home.mkdir(parents=True, exist_ok=True)
    runner = MEMBASE_HOME / "hooks" / "run.sh"
    if not a.uninstall:
        write_config(a)
        runner = copy_hooks()
    cmd = lambda ev: f'"{runner}" codex {ev}'  # noqa: E731
    ours = {
        "SessionStart": {"type": "command", "command": cmd("session-start"), "timeout": 30},
        "UserPromptSubmit": {"type": "command", "command": cmd("prompt"), "timeout": 15},
        "Stop": {"type": "command", "command": cmd("stop"), "timeout": 10},
        # Codex builds without SessionEnd ignore this entry; see the README.
        "SessionEnd": {"type": "command", "command": cmd("session-end"), "timeout": 3},
    }
    path = home / "hooks.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data["hooks"] = merge_hooks(data.get("hooks", {}), ours, remove=a.uninstall)
    backup(path)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"  hooks      {path}")

    env = {**os.environ, "CODEX_HOME": str(home)}
    if a.uninstall:
        run(["codex", "mcp", "remove", "membase"], check=False, env=env)
    else:
        added = run(
            [
                "codex",
                "mcp",
                "add",
                "membase",
                "--url",
                mcp_url(a),
                "--bearer-token-env-var",
                "MEMBASE_API_KEY",
            ],
            check=False,
            env=env,
        )
        if not added:
            print(
                "  ! `codex mcp add` failed; add this to config.toml yourself:\n"
                f'    [mcp_servers.membase]\n    url = "{mcp_url(a)}"\n'
                '    bearer_token_env_var = "MEMBASE_API_KEY"'
            )
    edit_markdown(home / "AGENTS.md", remove=a.uninstall)
    print(f"  agents.md  {home / 'AGENTS.md'}")
    if not a.uninstall:
        print(
            "\n  Codex: recall at session start and on every prompt is automatic, and so is saving\n"
            "  (on SessionEnd where your Codex has it, else once the session has been quiet for\n"
            "  20 minutes). The MCP server reads MEMBASE_API_KEY from the environment Codex starts in.\n"
            "  If Codex asks you to review new hooks (/hooks), approve the four Membase entries."
        )


def install_gemini(a: argparse.Namespace) -> None:
    home = Path(a.home or Path.home() / ".gemini").expanduser()
    home.mkdir(parents=True, exist_ok=True)
    runner = MEMBASE_HOME / "hooks" / "run.sh"
    if not a.uninstall:
        write_config(a)
        runner = copy_hooks()
    cmd = lambda ev: f'"{runner}" gemini {ev}'  # noqa: E731
    ours = {  # Gemini CLI timeouts are in milliseconds
        "SessionStart": {
            "name": "membase-recall",
            "type": "command",
            "command": cmd("session-start"),
            "timeout": 30000,
        },
        "BeforeAgent": {
            "name": "membase-search",
            "type": "command",
            "command": cmd("prompt"),
            "timeout": 15000,
        },
        "AfterAgent": {
            "name": "membase-turn",
            "type": "command",
            "command": cmd("stop"),
            "timeout": 10000,
        },
        "SessionEnd": {
            "name": "membase-save",
            "type": "command",
            "command": cmd("session-end"),
            "timeout": 10000,
        },
    }
    path = home / "settings.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data["hooks"] = merge_hooks(data.get("hooks", {}), ours, remove=a.uninstall)
    if not data["hooks"]:
        del data["hooks"]
    servers = data.setdefault("mcpServers", {})
    if a.uninstall:
        servers.pop("membase", None)
    else:
        servers["membase"] = {
            "httpUrl": mcp_url(a),
            "headers": {"Authorization": "Bearer ${MEMBASE_API_KEY}"},
        }
    if not servers:
        del data["mcpServers"]
    backup(path)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    edit_markdown(home / "GEMINI.md", remove=a.uninstall)
    print(f"  settings   {path}\n  gemini.md  {home / 'GEMINI.md'}")
    if not a.uninstall:
        print(
            "\n  Gemini CLI: recall at session start and before every prompt is automatic, and so\n"
            "  is saving at SessionEnd. The MCP server reads MEMBASE_API_KEY from the environment."
        )


def run(cmd: list[str], *, check: bool = True, env: dict | None = None) -> bool:
    print("  $ " + " ".join(cmd))
    if not shutil.which(cmd[0]):
        msg = f"{cmd[0]} is not on PATH"
        if check:
            sys.exit(f"error: {msg}")
        print(f"  ! {msg}")
        return False
    out = subprocess.run(cmd, env=env, capture_output=True, text=True)
    for line in (out.stdout + out.stderr).strip().splitlines()[-4:]:
        print(f"    {line}")
    if out.returncode and check:
        sys.exit(f"error: {' '.join(cmd)} exited {out.returncode}")
    return out.returncode == 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("cli", choices=["claude", "codex", "gemini"])
    p.add_argument(
        "--key", default=os.environ.get("MEMBASE_API_KEY", ""), help="developer key (mbk_...)"
    )
    p.add_argument(
        "--base-url", default=os.environ.get("MEMBASE_BASE_URL", ""), help=f"default {PROD}"
    )
    p.add_argument("--container", default="", help="the Memory to save to and search")
    p.add_argument("--home", default="", help="the CLI's config folder (Codex, Gemini)")
    p.add_argument("--uninstall", action="store_true")
    a = p.parse_args()
    print(f"{'Removing' if a.uninstall else 'Installing'} Membase memory for {a.cli}")
    {"claude": install_claude, "codex": install_codex, "gemini": install_gemini}[a.cli](a)
    if not a.uninstall:
        print(
            f"\n  settings   {MEMBASE_HOME / 'config.env'}\n  log        {MEMBASE_HOME / 'hooks.log'}"
        )


if __name__ == "__main__":
    main()
