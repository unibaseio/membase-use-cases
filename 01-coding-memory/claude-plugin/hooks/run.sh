#!/bin/sh
# Starts a Membase memory hook with a Python that has the Membase SDK (unibaseio-membase):
#   1. $MEMBASE_HOOK_PYTHON, from the environment or ~/.membase/config.env;
#   2. uv, which keeps a cached environment with the SDK (the first run takes a few seconds);
#   3. python3, which must already have the SDK: pip install unibaseio-membase
# Usage: run.sh <claude|codex|gemini> <event>   (the hook's JSON arrives on stdin)
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
HOOK="$HERE/membase_memory.py"
CONFIG="${MEMBASE_HOME:-$HOME/.membase}/config.env"
if [ -z "$MEMBASE_HOOK_PYTHON" ] && [ -f "$CONFIG" ]; then
  MEMBASE_HOOK_PYTHON=$(sed -n 's/^[[:space:]]*\(export[[:space:]]*\)\{0,1\}MEMBASE_HOOK_PYTHON=//p' "$CONFIG" | tail -n 1 | tr -d "\"'")
fi
if [ -n "$MEMBASE_HOOK_PYTHON" ]; then
  exec "$MEMBASE_HOOK_PYTHON" "$HOOK" "$@"
fi
if command -v uv >/dev/null 2>&1; then
  exec uv run --quiet --no-project --with 'unibaseio-membase>=0.3.2' python "$HOOK" "$@"
fi
exec python3 "$HOOK" "$@"
