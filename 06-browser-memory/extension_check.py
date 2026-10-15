"""Drive the real extension in Chromium: load it unpacked, open its side panel beside a page,
remember a page and ask about another, then save a screenshot of the page and the docked panel.

    ~/miniconda3/bin/python 06-browser-memory/extension_check.py   # any Python with Playwright

Needs the companion running on 127.0.0.1:8706 (`uv run 06-browser-memory/app.py`) with the
pages from smoke.py already remembered. Chromium only opens a side panel on a user gesture, so
the script clicks a button in an extension page to open it, then talks to the docked panel over
the DevTools protocol (Playwright does not attach to side panels). Headless Chromium draws the
tab and the panel separately; docs/screenshot.png puts the two real renders side by side.
"""

from __future__ import annotations

import base64
import functools
import http.server
import io
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import urlopen

import websocket
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
EXT = HERE / "extension"
EXT_ID = "lhojclgfedbhfpkjklfgjgnikckelabe"
PAGES_PORT = 18706  # 87NN ports belong to the demos
QUESTION = (
    "I want to hike the loop I saved this weekend, carrying the pack I read about. "
    "Which day should I go, and what do I need to plan for water and gear?"
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_pages() -> str:
    # A fixed port: a page's URL is its identity in memory, so the same page is the same URL
    # on every run (and remembering it again is not a second write).
    port = PAGES_PORT
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(HERE / "pages"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}"


class Panel:
    """The docked side panel, over a raw DevTools websocket."""

    def __init__(self, debug_port: int) -> None:
        targets = json.load(urlopen(f"http://127.0.0.1:{debug_port}/json/list"))
        panel = [
            t for t in targets if t["url"].startswith(f"chrome-extension://{EXT_ID}/panel.html")
        ]
        assert len(panel) == 1, f"expected one docked panel, found {[t['url'] for t in targets]}"
        self.ws = websocket.create_connection(
            panel[0]["webSocketDebuggerUrl"], timeout=60, suppress_origin=True
        )
        self._id = 0

    def send(self, method: str, **params):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg["result"]

    def js(self, expression: str):
        out = self.send(
            "Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True
        )
        if "exceptionDetails" in out:
            raise RuntimeError(out["exceptionDetails"])
        return out["result"].get("value")

    def wait(self, expression: str, timeout: float = 300) -> None:
        deadline = time.monotonic() + timeout
        while not self.js(expression):
            assert time.monotonic() < deadline, f"timed out waiting for {expression}"
            time.sleep(1)

    def screenshot(self) -> Image.Image:
        data = self.send("Page.captureScreenshot", format="png", captureBeyondViewport=True)["data"]
        return Image.open(io.BytesIO(base64.b64decode(data)))


def main() -> None:
    try:
        info = json.load(urlopen("http://127.0.0.1:8706/api/info"))
    except OSError:
        sys.exit("start the companion first: uv run 06-browser-memory/app.py")
    print("companion:", info)
    pages = serve_pages()
    debug_port = free_port()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            tempfile.mkdtemp(prefix="browser-memory-"),
            channel="chromium",
            headless=True,
            viewport={"width": 900, "height": 860},
            args=[
                f"--disable-extensions-except={EXT}",
                f"--load-extension={EXT}",
                f"--remote-debugging-port={debug_port}",
            ],
        )
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        assert sw.url.startswith(f"chrome-extension://{EXT_ID}/"), (
            f"unexpected extension id: {sw.url}"
        )
        tab = ctx.pages[0]
        tab.goto(f"{pages}/larchmere-ridge-loop.html")

        # A side panel opens only on a user gesture: a real click in an extension page.
        opener = ctx.new_page()
        opener.goto(f"chrome-extension://{EXT_ID}/panel.html")
        opener.evaluate(
            """() => { const b = document.createElement('button'); b.id = 'open-panel';
              b.onclick = async () => { const w = await chrome.windows.getCurrent();
                await chrome.sidePanel.open({ windowId: w.id }); document.title = 'opened'; };
              document.body.prepend(b); }"""
        )
        opener.click("#open-panel")
        opener.wait_for_function("document.title === 'opened'")
        opener.close()
        tab.bring_to_front()
        time.sleep(1)

        panel = Panel(debug_port)
        panel.js("location.reload()")
        time.sleep(1)
        panel.wait(
            "document.querySelector('#page-title').textContent.includes('Larchmere Ridge')", 30
        )
        panel.js("document.querySelector('#remember').click()")
        panel.wait("document.querySelector('#remember-out .ok, #remember-out.bad') !== null", 120)
        print("remember:", panel.js("document.querySelector('#remember-out').textContent"))
        assert "memory" in panel.js("document.querySelector('#remember-out').textContent")

        tab.goto(f"{pages}/larchmere-forecast.html")
        panel.wait("document.querySelector('#page-title').textContent.includes('forecast')", 30)
        panel.js(f"document.querySelector('#question').value = {json.dumps(QUESTION)}")
        panel.js("document.querySelector('#ask').click()")
        panel.wait(
            "!document.querySelector('#ask').disabled && document.querySelector('#answer').textContent.length > 0",
            300,
        )
        answer = panel.js("document.querySelector('#answer').textContent")
        used = panel.js(
            "[...document.querySelectorAll('.mem.used .from a')].map(a => a.textContent)"
        )
        print("answer:", answer.replace("\n", " ")[:600])
        print("memories used, from pages:", used)
        assert "tamsin" in answer.lower(), (
            "the side panel's answer did not use the remembered trail notes"
        )
        panel.wait("document.querySelector('#pages .page-row') !== null", 30)

        # The two real renders, side by side as Chrome docks them.
        panel_img = panel.screenshot()
        tab.set_viewport_size({"width": 900, "height": panel_img.height})
        page_img = Image.open(io.BytesIO(tab.screenshot()))
        height = max(page_img.height, panel_img.height)
        out = Image.new("RGB", (page_img.width + 1 + panel_img.width, height), "#dadce0")
        out.paste(page_img, (0, 0))
        out.paste(panel_img, (page_img.width + 1, 0))
        ImageDraw.Draw(out).line([(page_img.width, 0), (page_img.width, height)], fill="#c4c7c5")
        target = HERE / "docs" / "screenshot.png"
        target.parent.mkdir(exist_ok=True)
        out.save(target)
        print(f"panel {panel_img.size}, page {page_img.size} -> {target}")
        ctx.close()
    print("OK")


if __name__ == "__main__":
    main()
