"""Make a throwaway hosted test account for the hosted demos (on the Membase API at MEMBASE_BASE_URL).

    uv run scripts/bootstrap_hosted.py --name book --containers "Book"
    DEMO_ENV_FILE=.secrets/book.env uv run 02-book-memory/app.py

Signs in with a fresh wallet (a real account), creates the named Memories, and mints developer
keys: a `manage` key that reaches all of them (MEMBASE_API_KEY: reads across them, the profile,
forgetting) and, per Memory, a Read & write key that reaches only it (MEMBASE_KEY_FOR_<NAME>:
the memory API never names a Memory in a request, so a write lands in the one Memory its key
reaches). With --read-key, also a key that can only read. Writes them to .secrets/<name>.env
(git-ignored). For your own account, skip this: create the Memories in the app and put keys
from Connect > Developer keys in .env.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demokit.memory import key_env  # noqa: E402 - the repo root, above


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--name", required=True, help="the .secrets/<name>.env file to write")
    p.add_argument("--containers", nargs="+", required=True, help="the Memories to create")
    p.add_argument("--read-key", action="store_true", help="also mint a read-only key")
    p.add_argument(
        "--keys",
        nargs="+",
        default=[],
        metavar="NAME[:read]",
        help="also mint one key per name, written as MEMBASE_KEY_<NAME> (write access unless :read)",
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get("MEMBASE_BASE_URL"),
        required="MEMBASE_BASE_URL" not in os.environ,
        help="the Membase API to make the account on (or set MEMBASE_BASE_URL)",
    )
    a = p.parse_args()

    acct = Account.create()
    c = httpx.Client(base_url=a.base_url, timeout=120)
    challenge = c.post("/v1/auth/wallet/challenge", json={"address": acct.address})
    message = challenge.raise_for_status().json()["message"]
    sig = Account.sign_message(encode_defunct(text=message), private_key=acct.key).signature.hex()
    # The owner's session: a cookie, and the CSRF token every write sends back.
    session = c.post(
        "/v1/auth/wallet/session",
        json={"message": message, "signature": "0x" + sig.removeprefix("0x")},
    )
    session = session.raise_for_status().json()
    c.headers["X-CSRF-Token"] = session["csrf_token"]
    account = c.get("/v1/session").raise_for_status().json()["account_id"]

    views = {}
    for name in a.containers:
        made = c.post("/v1/memory-views/create", json={"name": name})
        views[name] = made.raise_for_status().json()["id"]

    def mint(profile: str, label: str = "", view: str = "") -> str:
        body = {
            "name": f"demos-{a.name}-{label or profile}",
            "profile": profile,
            "profile_access": True,
            **({"view_ids": [view]} if view else {"all_views": True}),
        }
        return c.post("/v1/keys/create", json=body).raise_for_status().json()["token"]

    lines = [
        f"# hosted test account {account} ({acct.address})",
        f"MEMBASE_BASE_URL={a.base_url}",
        f"MEMBASE_API_KEY={mint('manage')}",
        "MEMBASE_DEMO_MODE=hosted",
        # The throwaway wallet that owns the account: signs in as the owner (to delete it).
        f"MEMBASE_OWNER_WALLET_KEY={acct.key.hex()}",
    ]
    for name, view in views.items():  # suggest = read & write
        lines.append(f"{key_env(name)}={mint('suggest', name.lower(), view)}")
    if a.read_key:
        lines.append(f"MEMBASE_READ_KEY={mint('read')}")
    for spec in a.keys:
        name, _, level = spec.partition(":")
        profile = "read" if level == "read" else "suggest"
        lines.append(f"MEMBASE_KEY_{name.upper()}={mint(profile, name.lower())}")
    out = ROOT / ".secrets" / f"{a.name}.env"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.chmod(0o600)
    print(f"account {account}: {', '.join(a.containers)} -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
