"""Turn a recording (record.py's frames + timeline.json) into the demo's video, preview loop
and banner. Every output frame is rendered by compose.html: the field, the window, the camera,
the step label and the wait badge. ffmpeg writes the files.
"""

from __future__ import annotations

import bisect
import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
FPS = 25
INTRO, SLIDE, OUTRO = 2.8, 0.6, 2.4  # seconds
ARCH = 6.5  # seconds the architecture card stays, when a demo has one
EASE = 1.6  # seconds a camera move takes
BRIDGE = 3.0  # a return to the whole page this close before the next focus is skipped
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
PANELS = {"hosted": "#3e61ff", "local": "#1b2551"}
BASES = {"hosted": "Hosted Membase", "local": "Local engine"}


def smooth(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


class Clock:
    """Recording time <-> video time. A long wait plays sped up: it is shown for 1.2-2.6 s,
    whatever it really took, and the badge says how long it really was."""

    def __init__(self, waits: list[dict], end: float) -> None:
        self.parts: list[tuple[float, float, float, dict | None]] = []  # (src0, src1, factor, wait)
        t = 0.0
        for w in sorted(waits, key=lambda w: w["t0"]):
            if w["t0"] < t:
                continue
            if w["t0"] > t:
                self.parts.append((t, w["t0"], 1.0, None))
            took = w["t1"] - w["t0"]
            # a replayed wait was already shortened when it was recorded; play it as recorded
            shown = took if "real" in w else min(2.6, max(1.2, took / 10))
            self.parts.append((w["t0"], w["t1"], took / shown, w))
            t = w["t1"]
        if end > t:
            self.parts.append((t, end, 1.0, None))
        self.starts, u = [], 0.0
        for s0, s1, f, _ in self.parts:
            self.starts.append(u)
            u += (s1 - s0) / f
        self.length = u

    def src(self, u: float) -> tuple[float, dict | None, float]:
        k = max(0, bisect.bisect_right(self.starts, u) - 1)
        s0, s1, f, w = self.parts[k]
        return min(s1, s0 + (u - self.starts[k]) * f), w, f

    def out(self, t: float) -> float:
        for (s0, s1, f, _), u in zip(self.parts, self.starts, strict=True):
            if t <= s1:
                return u + max(0.0, t - s0) / f
        return self.length


async def render_video(rec_dir: Path, meta: dict, out_mp4: Path) -> list[float]:
    """Writes the mp4; returns when each step starts, in seconds of the video."""
    tl = json.loads((rec_dir / "timeline.json").read_text())
    frames = tl["frames"]
    if not frames:
        raise SystemExit(f"{rec_dir}: the recording has no frames")
    ftimes = [f["t"] for f in frames]
    start = max(0.0, (tl["steps"][0]["t"] if tl["steps"] else ftimes[0]) - 0.8)
    clock = Clock(tl["waits"], tl["end"])
    focus = [(clock.out(f["t"]), f["box"]) for f in tl["focus"]]
    follows = {clock.out(f["t"]) for f in tl["focus"] if f.get("follow")}
    # pan straight from one focus to the next instead of zooming out and back in between
    focus = [
        f
        for i, f in enumerate(focus)
        if f[1] is not None or i + 1 >= len(focus) or focus[i + 1][0] - f[0] > BRIDGE
    ]
    steps = [(clock.out(s["t"]), s) for s in tl["steps"]]
    u_start, u_end = clock.out(start), clock.length
    base = meta["base"]
    common = {
        "view": tl["view"],
        "url": f"<b>{tl['url']}</b>",
        "panel": PANELS[base],
        "title": meta["title_html"],
        "pitch": meta["pitch"],
        "kick": f"Membase use cases · {meta['n']:02d}",
        "base": BASES[base],
        "corner": f"use cases · {meta['n']:02d} {meta['title']}",
    }

    def frame_at(u: float) -> tuple[str, dict | None, float]:
        t, wait, factor = clock.src(u)
        k = max(0, bisect.bisect_right(ftimes, t) - 1)
        return str((rec_dir / frames[k]["file"]).resolve()), wait, factor

    def camera_at(u: float) -> dict:
        k = bisect.bisect_right([f[0] for f in focus], u) - 1
        if k < 0:
            return {"box": None, "prev": None, "k": 1}
        prev = focus[k - 1][1] if k > 0 else None
        follow = focus[k][0] in follows  # following a scroll, not a new framing
        ease = 0.25 if follow else EASE
        return {
            "box": focus[k][1],
            "prev": prev,
            "k": smooth((u - focus[k][0]) / ease),
            "slide": follow,
        }

    def step_at(u: float) -> dict | None:
        k = bisect.bisect_right([s[0] for s in steps], u) - 1
        if k < 0:
            return None
        s = steps[k][1]
        return {
            "n": s["n"],
            "title": s["title"],
            "detail": s["detail"],
            "alpha": smooth((u - steps[k][0]) / 0.35),
        }

    states: list[dict] = []
    intro_frame, _, _ = frame_at(u_start)
    n_intro = int(INTRO * FPS)
    for i in range(n_intro):
        x = i / FPS
        st = dict(
            common,
            mode="video",
            frame=intro_frame,
            box=None,
            intro=smooth((x - (INTRO - SLIDE)) / SLIDE) if x > INTRO - SLIDE else 0.0,
            enter=min(1.0, x / 1.1),
            introShot=meta.get("intro_shot") and str(meta["intro_shot"]),
        )
        states.append(st)
    if meta.get("arch"):  # the architecture card, between the intro and the recording
        a = meta["arch"]
        for i in range(int(ARCH * FPS)):
            x = i / FPS
            fade = min(1.0, x / 0.35, (ARCH - x) / 0.35)
            states.append(
                dict(
                    common,
                    mode="video",
                    frame=intro_frame,
                    box=None,
                    arch=smooth(fade),
                    archT=x,
                    archKick=a.get("kick", "How it works"),
                    archTitle=a["title"],
                    archNodes=a["nodes"],
                    archFoot=a.get("foot", ""),
                )
            )
    u = u_start
    while u < u_end:
        src, wait, factor = frame_at(u)
        cam = camera_at(u)
        st = dict(common, mode="video", frame=src, step=step_at(u), **cam)
        if wait:
            real = wait.get("real") or wait["t1"] - wait["t0"]
            shown = (wait["t1"] - wait["t0"]) / factor
            st["wait"] = {
                "text": f"{wait['label']} · {real:.0f} s",
                "x": f"{real / shown:.0f}× faster",
            }
        states.append(st)
        u += 1 / FPS
    last = dict(states[-1])
    for i in range(int(OUTRO * FPS)):
        states.append(dict(last, outro=smooth(i / FPS / 0.45), wait=None))

    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "image2pipe",
            "-framerate",
            str(FPS),
            "-c:v",
            "mjpeg",
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "19",
            "-preset",
            "medium",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ],
        stdin=subprocess.PIPE,
    )
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        await page.goto((HERE / "compose.html").as_uri())
        await page.evaluate("document.fonts.ready")
        prev_key, prev_png = None, b""
        for st in states:
            key = json.dumps(st, sort_keys=True)
            if key != prev_key:
                await page.evaluate("s => window.render(s)", st)
                prev_png = await page.screenshot(type="jpeg", quality=92)
                prev_key = key
            ff.stdin.write(prev_png)
        await browser.close()
    ff.stdin.close()
    if ff.wait() != 0:
        raise SystemExit("ffmpeg failed")
    print(f"{out_mp4}: {len(states) / FPS:.1f} s ({len(states)} frames)")
    lead = INTRO + (ARCH if meta.get("arch") else 0.0)
    return [round(lead + u - u_start, 2) for u, _ in steps]


def preview_gif(mp4: Path, gif: Path, start: float, length: float = 12.0) -> None:
    graph = (
        "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160:stats_mode=diff[p];"
        "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle"
    )
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.2f}",
            "-t",
            f"{length:.2f}",
            "-i",
            str(mp4),
            "-vf",
            graph,
            "-loop",
            "0",
            str(gif),
        ],
        check=True,
    )
    print(f"{gif}: {gif.stat().st_size / 1e6:.1f} MB")


async def render_banner(meta: dict, shot: Path, url: str, out_png: Path) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(
            viewport={"width": 1300, "height": 553}, device_scale_factor=1
        )
        await page.goto((HERE / "compose.html").as_uri())
        await page.evaluate("document.fonts.ready")
        await page.evaluate(
            "s => window.render(s)",
            {
                "mode": "banner",
                "panel": PANELS[meta["base"]],
                "tag": f"Membase use cases · {meta['n']:02d} · {BASES[meta['base']]}",
                "title": meta["title_html"],
                "pitch": meta["pitch"],
                "url": f"<b>{url}</b>",
                "shot": str(shot.resolve()),
            },
        )
        await page.screenshot(
            path=str(out_png), clip={"x": 0, "y": 0, "width": 1300, "height": 553}
        )
        await browser.close()
    print(f"{out_png}")
