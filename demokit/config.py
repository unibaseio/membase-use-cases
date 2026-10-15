"""Settings every demo reads: the repo's `.env`, then the process environment.

Nothing here has a silent default that changes behavior: a missing model key or a hosted demo
without a Membase key fails at startup with the line to add, not on the first request.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DEMO_DATA_DIR") or ROOT / "data")


def load_env(path: Path = ROOT / ".env") -> None:
    """KEY=VALUE lines into os.environ, never overriding what the shell already set."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


# A second file first, so it wins over .env: scripts/bootstrap_hosted.py writes one per test
# account (DEMO_ENV_FILE=.secrets/<name>.env).
if os.environ.get("DEMO_ENV_FILE"):
    load_env(Path(os.environ["DEMO_ENV_FILE"]).expanduser())
load_env()


class ConfigError(RuntimeError):
    """A setting the demo cannot run without; the message says what to add where."""


def _excepthook(kind, value, tb, _default=sys.excepthook):
    # A script stopped by a missing setting prints the one line that fixes it, not a traceback.
    if isinstance(value, ConfigError):
        print(f"error: {value}", file=sys.stderr)
        return
    _default(kind, value, tb)


sys.excepthook = _excepthook


def require(name: str, why: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} is not set: {why}. Add it to {ROOT / '.env'} (see .env.example)."
        )
    return value


def model() -> str:
    return os.environ.get("DEMO_MODEL", "").strip() or "gpt-4.1-mini"


def mode(default: str) -> str:
    """`local` or `hosted`: MEMBASE_DEMO_MODE wins, else the demo's own default."""
    chosen = (os.environ.get("MEMBASE_DEMO_MODE") or default).strip().lower()
    if chosen not in ("local", "hosted"):
        raise ConfigError(f"MEMBASE_DEMO_MODE must be local or hosted, not {chosen!r}")
    return chosen
