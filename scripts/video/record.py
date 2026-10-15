"""Record a real run of a demo page: CDP screencast frames at 2x, a visible cursor, and a log of
what happened when (steps, camera focus, sped-up waits). compose.py turns it into the video.

A demo's video.py does:

    async with Recorder(page, out_dir, url_label="localhost:8708") as rec:
        rec.step(1, "Tell it once", "Maya mentions Thursday's interview")
        rec.focus("#chat")
        await rec.type("#q", "I have a job interview on Thursday")
        await rec.click("#send")
        await rec.wait("Wren answers", page.wait_for_selector(".msg.assistant:nth-of-type(2)"))

Times are seconds since the recording started. Nothing is staged: every step drives the real
page against the real API.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path

CURSOR = r"""
(() => {
  if (window.__mb) return;
  const make = () => {
    const c = document.createElement('div');
    c.id = '__mbcursor';
    c.innerHTML = '<svg width="28" height="28" viewBox="0 0 28 28"><path d="M5 3 L5 22 L10 17 L13.5 25 L17 23.5 L13.5 15.5 L20.5 15.5 Z" fill="#0f172b" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {position: 'fixed', left: '0', top: '0', zIndex: 2147483647, pointerEvents: 'none',
      transform: 'translate(720px, 520px)', transition: 'transform .6s cubic-bezier(.3,.7,.2,1)', filter: 'drop-shadow(0 2px 3px rgba(0,0,0,.25))'});
    const r = document.createElement('div');
    r.id = '__mbripple';
    Object.assign(r.style, {position: 'fixed', left: '0', top: '0', width: '44px', height: '44px', marginLeft: '-22px', marginTop: '-22px',
      borderRadius: '50%', border: '3px solid #3e61ff', zIndex: 2147483646, pointerEvents: 'none', opacity: '0'});
    // a heartbeat no one can see: the screencast only sends a frame when something repaints, so
    // a page that goes still right after a change can lose that last paint; two repaints a
    // second keep the final state on record without flooding the frame count
    const h = document.createElement('div');
    h.id = '__mbheartbeat';
    Object.assign(h.style, {position: 'fixed', right: '0', bottom: '0', width: '2px', height: '2px', zIndex: 2147483645,
      pointerEvents: 'none', background: '#000', opacity: '0'});
    h.animate([{opacity: 0}, {opacity: 0.01}], {duration: 1000, iterations: Infinity, easing: 'steps(2, jump-none)'});
    document.documentElement.append(c, r, h);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', make); else make();
  window.__mb = {
    move(x, y) { const c = document.getElementById('__mbcursor'); if (c) c.style.transform = `translate(${x - 5}px, ${y - 3}px)`; },
    click(x, y) {
      const r = document.getElementById('__mbripple'); if (!r) return;
      r.animate([{transform: `translate(${x}px, ${y}px) scale(.4)`, opacity: .9}, {transform: `translate(${x}px, ${y}px) scale(1.3)`, opacity: 0}],
                {duration: 450, easing: 'ease-out'});
    },
  };
})();
"""


class Recorder:
    def __init__(self, page, out_dir: str | Path, *, url_label: str) -> None:
        self.page = page
        self.out = Path(out_dir)
        self.url_label = url_label
        self.frames: list[dict] = []
        self.steps: list[dict] = []
        self.focuses: list[dict] = []
        self.waits: list[dict] = []
        self.t0 = 0.0
        self._cursor = (720.0, 520.0)
        self._acks: set[asyncio.Task] = set()
        self._target: tuple[str, float] | None = None

    # ---- lifecycle -------------------------------------------------------------------

    async def __aenter__(self) -> Recorder:
        (self.out / "frames").mkdir(parents=True, exist_ok=True)
        for old in (self.out / "frames").glob("*.jpg"):
            old.unlink()
        await self.page.context.add_init_script(CURSOR)
        await self.page.evaluate(CURSOR)
        self.cdp = await self.page.context.new_cdp_session(self.page)
        self.cdp.on("Page.screencastFrame", self._frame)
        vp = self.page.viewport_size
        self.view = {"w": vp["width"], "h": vp["height"]}
        self.t0 = time.time()
        await self.cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 90,
                "maxWidth": vp["width"] * 2,
                "maxHeight": vp["height"] * 2,
            },
        )
        await asyncio.sleep(0.5)
        self._tracker = asyncio.ensure_future(self._track())
        return self

    async def __aexit__(self, *exc) -> None:
        self._tracker.cancel()
        await asyncio.sleep(0.8)
        await self.cdp.send("Page.stopScreencast")
        await asyncio.gather(*self._acks, return_exceptions=True)
        end = self.now()
        (self.out / "timeline.json").write_text(
            json.dumps(
                {
                    "view": self.view,
                    "url": self.url_label,
                    "end": end,
                    "frames": self.frames,
                    "steps": self.steps,
                    "focus": self.focuses,
                    "waits": self.waits,
                },
                indent=1,
            )
        )

    def _frame(self, params: dict) -> None:
        n = len(self.frames)
        name = f"frames/{n:05d}.jpg"
        (self.out / name).write_bytes(base64.b64decode(params["data"]))
        ts = params.get("metadata", {}).get("timestamp") or time.time()
        self.frames.append({"t": round(ts - self.t0, 3), "file": name})
        task = asyncio.ensure_future(
            self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        )
        self._acks.add(task)
        task.add_done_callback(self._acks.discard)

    def now(self) -> float:
        return round(time.time() - self.t0, 3)

    # ---- what the video says -----------------------------------------------------------

    def step(self, n: int, title: str, detail: str = "") -> None:
        """The label at the bottom from now on: "1 · Tell it once"."""
        self.steps.append({"t": self.now(), "n": n, "title": title, "detail": detail})

    async def _box(self, target: str, pad: float) -> list[float] | None:
        b = await self.page.locator(target).first.bounding_box()
        if not b:
            return None
        box = [b["x"] - pad, b["y"] - pad, b["width"] + 2 * pad, b["height"] + 2 * pad]
        # only what is on screen can be framed
        x0, y0 = max(0.0, box[0]), max(0.0, box[1])
        x1, y1 = min(self.view["w"], box[0] + box[2]), min(self.view["h"], box[1] + box[3])
        return [x0, y0, max(40.0, x1 - x0), max(40.0, y1 - y0)]

    async def focus(self, target: str | list[float] | None, *, pad: float = 24) -> None:
        """Ease the camera onto a selector's box (or an [x, y, w, h] box in CSS px); None shows
        the whole page. A selector is followed: when the page scrolls or the element moves,
        the framing moves with it (see _track)."""
        box = None
        self._target = None
        if isinstance(target, str):
            loc = self.page.locator(target).first
            b = await loc.bounding_box()
            # scroll only when most of it is off screen: a scroll during a camera move shows as a jump
            if b and not self._mostly_visible(b):
                await loc.scroll_into_view_if_needed()
                await asyncio.sleep(0.5)
            box = await self._box(target, pad)
            self._target = (target, pad)
        elif target is not None:
            box = list(target)
        self.focuses.append({"t": self.now(), "box": box})

    async def _track(self) -> None:
        """Every half second, re-measure the focused element; if it moved, record the new box
        as a quick follow (the composer eases it in a quarter second, not a full camera move)."""
        while True:
            await asyncio.sleep(0.5)
            if not self._target or not self.focuses:
                continue
            try:
                box = await self._box(*self._target)
            except Exception:  # noqa: BLE001 - the element went away; keep the last framing
                continue
            last = self.focuses[-1]["box"]
            if box and last and max(abs(a - b) for a, b in zip(box, last, strict=True)) > 6:
                self.focuses.append({"t": self.now(), "box": box, "follow": True})

    def _mostly_visible(self, b: dict) -> bool:
        w = max(0.0, min(self.view["w"], b["x"] + b["width"]) - max(0.0, b["x"]))
        h = max(0.0, min(self.view["h"], b["y"] + b["height"]) - max(0.0, b["y"]))
        return w * h >= 0.6 * b["width"] * b["height"]

    # ---- driving the page --------------------------------------------------------------

    async def _move_to(self, selector: str) -> tuple[float, float]:
        loc = self.page.locator(selector).first
        await loc.scroll_into_view_if_needed()
        b = await loc.bounding_box()
        x, y = b["x"] + min(b["width"] / 2, 60), b["y"] + b["height"] / 2
        await self.page.evaluate(f"window.__mb && window.__mb.move({x}, {y})")
        self._cursor = (x, y)
        await asyncio.sleep(0.7)
        return x, y

    async def click(self, selector: str, *, pause: float = 0.35) -> None:
        x, y = await self._move_to(selector)
        await self.page.evaluate(f"window.__mb && window.__mb.click({x}, {y})")
        await self.page.locator(selector).first.click()
        await asyncio.sleep(pause)

    async def hover(self, selector: str, *, pause: float = 1.0) -> None:
        await self._move_to(selector)
        await self.page.locator(selector).first.hover()
        await asyncio.sleep(pause)

    async def type(
        self, selector: str, text: str, *, delay: float = 28, clear: bool = True
    ) -> None:
        await self.click(selector, pause=0.15)
        loc = self.page.locator(selector).first
        if clear:
            await loc.fill("")
        await loc.press_sequentially(text, delay=delay)
        await asyncio.sleep(0.3)

    async def press(self, key: str) -> None:
        await self.page.keyboard.press(key)

    async def wait(self, label: str, awaitable, *, min_fast: float = 2.5):
        """Wait for something real (a recall, a model call, a learning run). A wait longer than
        `min_fast` seconds is played sped up in the video, with `label` and its real length."""
        t0 = self.now()
        out = await awaitable
        t1 = self.now()
        if t1 - t0 >= min_fast:
            self.waits.append({"t0": t0, "t1": t1, "label": label})
        return out

    async def gap(self, label: str, real: float, *, shown: float = 2.0) -> None:
        """A wait that really took `real` seconds, played back (a replay of a captured run) in
        `shown` seconds. The video's badge reports the real length."""
        t0 = self.now()
        await asyncio.sleep(shown)
        self.waits.append({"t0": t0, "t1": self.now(), "label": label, "real": round(real, 1)})

    async def hide_cursor(self) -> None:
        await self.page.evaluate("document.getElementById('__mbcursor')?.remove()")

    async def pause(self, seconds: float) -> None:
        """Let a moment be read (the video holds the frame)."""
        await asyncio.sleep(seconds)
