"""Make a throwaway hosted test account for the hosted demos (on the Membase API at MEMBASE_BASE_URL).

    uv run scripts/bootstrap_hosted.py --name book --containers "Book"
    DEMO_ENV_FILE=.secrets/book.env uv run 02-book-memory/app.py

Signs in with a fresh wallet (a real account), creates the named containers (Memories), mints
a `manage` developer key that reaches all of them and, with --read-key, a second key that can
only read. Writes them to .secrets/<name>.env (git-ignored). For your own account, skip this:
create the Memories in the app and put a key from Connect > Developer keys in .env.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--name", required=True, help="the .secrets/<name>.env file to write")
    p.add_argument("--containers", nargs="+", required=True, help="Memories to create")
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
    session = c.post(
        "/v1/auth/wallet", json={"message": message, "signature": "0x" + sig.removeprefix("0x")}
    )
    session = session.raise_for_status().json()
    c.headers["Authorization"] = f"Bearer {session['token']}"

    for name in a.containers:
        c.post("/v1/memory-views", json={"name": name}).raise_for_status()

    def mint(profile: str, label: str = "") -> str:
        body = {
            "name": f"demos-{a.name}-{label or profile}",
            "profile": profile,
            "all_views": True,
            "profile_access": True,
        }
        return c.post("/v1/api-keys", json=body).raise_for_status().json()["token"]

    lines = [
        f"# hosted test account {session.get('account_id')} ({acct.address})",
        f"MEMBASE_BASE_URL={a.base_url}",
        f"MEMBASE_API_KEY={mint('manage')}",
        "MEMBASE_DEMO_MODE=hosted",
        # The throwaway wallet that owns the account: signs in as the owner to look at runs.
        f"MEMBASE_OWNER_WALLET_KEY={acct.key.hex()}",
    ]
    if a.read_key:
        lines.append(f"MEMBASE_READ_KEY={mint('read')}")
    for spec in a.keys:
        name, _, level = spec.partition(":")
        profile = "read" if level == "read" else "suggest"  # suggest = read & write
        lines.append(f"MEMBASE_KEY_{name.upper()}={mint(profile, name.lower())}")
    out = ROOT / ".secrets" / f"{a.name}.env"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.chmod(0o600)
    print(
        f"account {session.get('account_id')}: {', '.join(a.containers)} -> {out.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
