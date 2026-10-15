"""Record and compose one demo's video, preview loop and banner.

    .venv/bin/python scripts/video/make.py 08-companion            # record, then compose
    .venv/bin/python scripts/video/make.py 08-companion --compose  # compose the last recording again
    DEMO_ENV_FILE=.secrets/x.env .venv/bin/python scripts/video/make.py 02-book-memory   # hosted

The demo's `video.py` holds META (title, pitch, base, preview window), SEED (scripts to run on a
fresh store first) and `async def act(page, rec)`, the real run. Local demos record on a fresh
data directory; hosted demos on the account DEMO_ENV_FILE names. Writes the demo's
docs/video.mp4, docs/preview.gif and docs/banner.png.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
from compose import preview_gif, render_banner, render_video  # noqa: E402
from record import Recorder  # noqa: E402

PY = sys.executable


def load(demo: str):
    spec = importlib.util.spec_from_file_location(f"video_{demo}", ROOT / demo / "video.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def wait_up(port: int, proc: subprocess.Popen, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"the demo server exited ({proc.returncode})")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/info", timeout=2)
            return
        except OSError:
            time.sleep(0.5)
    raise SystemExit("the demo server did not come up")


async def record(demo: str, mod, rec_dir: Path) -> None:
    meta = mod.META
    env = dict(os.environ, PORT=str(meta["port"]))
    if meta["base"] == "local":
        store = rec_dir / "store"
        if store.exists():
            subprocess.run(["rm", "-rf", str(store)], check=True)
        store.mkdir(parents=True)
        env.update(MEMBASE_DEMO_MODE="local", DEMO_DATA_DIR=str(store))
    for script in getattr(mod, "SEED", []):
        print("seed:", script)
        subprocess.run([PY, *script.split()], cwd=ROOT, env=env, check=True)
    # a server left running on this port would answer instead of ours, on whatever base it
    # was started with: refuse rather than record the wrong one
    import socket

    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", meta["port"])) == 0:
            raise SystemExit(f"port {meta['port']} is already in use: stop that server first")
    log = open(rec_dir / "server.log", "w")
    proc = subprocess.Popen(
        [PY, f"{demo}/app.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
    )
    try:
        wait_up(meta["port"], proc)
        if hasattr(mod, "setup"):  # anything the page needs besides the demo server
            mod.setup()
        async with async_playwright() as pw:
            # the screencast only comes at 2x with the device scale forced on the browser itself
            args = ["--force-device-scale-factor=2"]
            if meta.get("extension"):
                # an extension loads only in a persistent context, in Chromium's new headless
                ext = str(ROOT / meta["extension"])
                args += [f"--disable-extensions-except={ext}", f"--load-extension={ext}"]
                ctx = await pw.chromium.launch_persistent_context(
                    tempfile.mkdtemp(prefix="video-profile-"),
                    channel="chromium",
                    headless=True,
                    args=args,
                    viewport={"width": 1440, "height": 900},
                    device_scale_factor=2,
                )
            else:
                browser = await pw.chromium.launch(args=args)
                ctx = await browser.new_context(
                    viewport={"width": 1440, "height": 900}, device_scale_factor=2
                )
            page = await ctx.new_page()
            await page.goto(
                meta.get("start_url") or f"http://127.0.0.1:{meta['port']}/{meta.get('path', '')}"
            )
            # not "networkidle": a hosted page may hold a recall open for half a minute
            await page.wait_for_load_state("load")
            label = meta.get("url_label") or f"localhost:{meta['port']}"
            async with Recorder(page, rec_dir, url_label=label) as rec:
                await mod.act(page, rec)
            await ctx.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:  # a request still in flight to the hosted API
            proc.kill()
            proc.wait()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("demo")
    p.add_argument("--compose", action="store_true", help="compose the last recording, no new run")
    a = p.parse_args()
    demo = a.demo.rstrip("/")
    mod = load(demo)
    meta = dict(mod.META, n=int(demo[:2]))
    rec_dir = ROOT / "data" / "video" / demo
    rec_dir.mkdir(parents=True, exist_ok=True)
    if not a.compose:
        asyncio.run(record(demo, mod, rec_dir))
    docs = ROOT / demo / "docs"
    mp4 = docs / "video.mp4"
    if meta.get("banner_from_recording"):  # the payoff frame also opens the video
        tl = json.loads((rec_dir / "timeline.json").read_text())
        meta["intro_shot"] = str(rec_dir / tl["frames"][-1]["file"])
    step_times = asyncio.run(render_video(rec_dir, meta, mp4))
    # the preview loop: by default from just before step 2, for 12 s
    start, length = meta.get("preview") or (
        max(0.0, step_times[min(1, len(step_times) - 1)] - 0.5),
        12.0,
    )
    preview_gif(mp4, docs / "preview.gif", start, length)
    shot = docs / "screenshot.png"
    if meta.get("banner_from_recording"):  # the recording's last frame shows the payoff
        tl = json.loads((rec_dir / "timeline.json").read_text())
        shot = rec_dir / tl["frames"][-1]["file"]
    asyncio.run(render_banner(meta, shot, f"localhost:{meta['port']}", docs / "banner.png"))


if __name__ == "__main__":
    main()
