"""Render the sample screenshots: six made-up screens from made-up apps, as PNGs.

    ~/miniconda3/bin/python 13-screen-memory/seed.py      # any Python with Playwright + Chromium

Writes `samples/*.png`, `samples/samples.json` (each screen's file and when it was "taken") and
`samples/text.json`, each screen's text layer: every visible word and its box in the 1280x800
image, the way an OS keeps the recognised text of a screenshot. The page uses it to highlight
where the answer is on the screenshot.
Every app, person, code and number on these screens is invented for the demo. The PNGs are
checked in, so the demo and its smoke run without Playwright; re-run this to change them.
"""
# ruff: noqa: E501 - prose and markup kept as written, one line per sentence or element

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "samples"

BASE_CSS = """
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 -apple-system, "Segoe UI", Inter, Arial, sans-serif; color: #1f2328; }
.chrome { height: 38px; background: #e9ebef; display: flex; align-items: center; gap: 8px; padding: 0 14px; border-bottom: 1px solid #d0d4da; }
.chrome i { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
.chrome .url { margin-left: 18px; background: #fff; border-radius: 6px; padding: 3px 12px; font-size: 13px; color: #555; width: 520px; }
.clock { margin-left: auto; font-size: 12.5px; color: #555; }
"""


# Every visible word on the rendered page and its box, in image pixels: the screenshot's text layer.
TEXT_LAYER = """() => {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const re = /\\S+/g;
    let m;
    while ((m = re.exec(n.data))) {
      const r = document.createRange();
      r.setStart(n, m.index); r.setEnd(n, m.index + m[0].length);
      const b = r.getBoundingClientRect();
      if (b.width < 1 || b.height < 1 || b.bottom < 0 || b.top > innerHeight) continue;
      out.push({ t: m[0], x: Math.round(b.left), y: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height) });
    }
  }
  return out;
}"""


def chrome(url: str, clock: str) -> str:
    return (
        '<div class="chrome"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i>'
        f'<i style="background:#28c840"></i><span class="url">{url}</span><span class="clock">{clock}</span></div>'
    )


SCREENS = [
    {
        "file": "flight-confirmation.png",
        "captured_at": "2026-10-02T19:12:00",
        "html": chrome("https://www.skylark-air.example/manage/QX7P2M", "Fri 2 Oct 19:12")
        + """
<style>
.wrap { background: #f3f6fb; height: 762px; padding: 36px 70px; }
.brand { font-weight: 800; color: #0b5cad; font-size: 22px; letter-spacing: -0.02em; }
.ok { margin-top: 18px; background: #e6f4ea; color: #137333; border-radius: 10px; padding: 14px 18px; font-weight: 600; }
.card { margin-top: 18px; background: #fff; border-radius: 14px; padding: 26px 30px; box-shadow: 0 2px 10px rgba(0,0,0,.06); }
.route { display: flex; align-items: center; gap: 40px; font-size: 40px; font-weight: 700; }
.route small { display: block; font-size: 14px; color: #666; font-weight: 400; }
.grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 18px; margin-top: 24px; }
.grid div { font-size: 13px; color: #666; } .grid b { display: block; font-size: 19px; color: #1f2328; }
</style>
<div class="wrap">
  <div class="brand">SkyLark Air</div>
  <div class="ok">Booking confirmed. A receipt was sent to j.avery@example.com</div>
  <div class="card">
    <div class="route"><div>LIS<small>Lisbon</small></div><div style="color:#0b5cad">&rarr;</div><div>KEF<small>Reykjavik Keflavik</small></div></div>
    <div class="grid">
      <div>Flight<b>SL 482</b></div><div>Date<b>Sat 14 Nov 2026</b></div>
      <div>Departs<b>07:45</b></div><div>Arrives<b>10:20</b></div>
      <div>Passenger<b>Jordan Avery</b></div><div>Seat<b>17C</b></div>
      <div>Booking reference<b>QX7P2M</b></div><div>Gate closes<b>07:15</b></div>
    </div>
  </div>
  <div class="card" style="font-size:14px;color:#555">Checked bag: 1 x 23 kg included. Online check-in opens 48 hours before departure.</div>
</div>""",
    },
    {
        "file": "vpn-error.png",
        "captured_at": "2026-09-18T09:03:00",
        "html": """
<style>
.desk { height: 800px; background: linear-gradient(135deg, #2c3e50, #4b6584); display: grid; place-items: center; }
.dlg { width: 560px; background: #fff; border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,.4); overflow: hidden; }
.bar { background: #f1f2f4; padding: 10px 16px; font-size: 13px; color: #444; border-bottom: 1px solid #ddd; }
.body { padding: 22px 24px; display: flex; gap: 16px; }
.icon { width: 44px; height: 44px; border-radius: 50%; background: #d93025; color: #fff; font-weight: 800; font-size: 26px; display: grid; place-items: center; flex: none; }
h2 { margin: 0 0 6px; font-size: 18px; }
.code { font-family: Menlo, monospace; font-size: 13px; background: #f6f8fa; border-radius: 6px; padding: 8px 10px; margin-top: 10px; color: #444; }
.btns { display: flex; justify-content: flex-end; gap: 10px; padding: 0 24px 20px; }
.btns span { border: 1px solid #ccc; border-radius: 7px; padding: 6px 16px; font-size: 14px; }
.btns .p { background: #1a73e8; color: #fff; border-color: #1a73e8; }
.task { position: absolute; bottom: 0; left: 0; right: 0; height: 40px; background: rgba(0,0,0,.55); color: #eee; font-size: 13px; display: flex; align-items: center; justify-content: flex-end; padding: 0 16px; }
</style>
<div class="desk">
  <div class="dlg">
    <div class="bar">NimbusVPN</div>
    <div class="body"><div class="icon">!</div><div>
      <h2>Couldn't connect to eu-west-3.nimbus.example</h2>
      <div>Error 809: the network connection between your computer and the VPN server could not be established. The IKEv2 handshake timed out.</div>
      <div class="code">Protocol: IKEv2 (UDP 500/4500)  ·  Network: Fernhouse-5G  ·  Attempts: 3</div>
    </div></div>
    <div class="btns"><span>Settings</span><span class="p">Retry</span></div>
  </div>
  <div class="task">Fri 18 Sep 09:03</div>
</div>""",
    },
    {
        "file": "vpn-settings.png",
        "captured_at": "2026-09-18T09:11:00",
        "html": """
<style>
.win { height: 800px; background: #f6f7f9; display: flex; }
.side { width: 220px; background: #eef0f3; padding: 22px 14px; font-size: 14px; color: #444; }
.side div { padding: 8px 10px; border-radius: 7px; } .side .on { background: #dfe6f3; color: #1a4fb3; font-weight: 600; }
.main { flex: 1; padding: 28px 40px; }
h1 { font-size: 22px; margin: 0 0 4px; } .sub { color: #666; font-size: 14px; }
.status { margin: 18px 0; display: inline-block; background: #e6f4ea; color: #137333; border-radius: 99px; padding: 6px 14px; font-weight: 600; font-size: 14px; }
.row { display: flex; justify-content: space-between; align-items: center; background: #fff; border: 1px solid #e3e5e8; border-radius: 10px; padding: 14px 18px; margin-top: 10px; }
.row small { display: block; color: #777; font-size: 12.5px; }
.sel { border: 1px solid #c8ccd2; border-radius: 7px; padding: 5px 12px; min-width: 160px; }
.tog { width: 42px; height: 24px; border-radius: 99px; background: #1a73e8; position: relative; }
.tog::after { content: ""; position: absolute; right: 3px; top: 3px; width: 18px; height: 18px; border-radius: 50%; background: #fff; }
.note { margin-top: 16px; font-size: 13px; color: #8a5a00; background: #fff6e0; border-radius: 8px; padding: 10px 14px; }
</style>
<div class="win">
  <div class="side"><div><b>NimbusVPN</b></div><div>Home</div><div class="on">Connection</div><div>Account</div><div>Help</div></div>
  <div class="main">
    <h1>Connection settings</h1><div class="sub">Changes apply on the next connect.</div>
    <div class="status">Connected to eu-west-3.nimbus.example at 09:11</div>
    <div class="row"><div>Protocol<small>Was IKEv2. WireGuard works on networks that block IKE.</small></div><div class="sel">WireGuard &#9662;</div></div>
    <div class="row"><div>Port<small>WireGuard UDP port</small></div><div class="sel">51820</div></div>
    <div class="row"><div>Use alternate port if blocked<small>Falls back to UDP 443</small></div><div class="tog"></div></div>
    <div class="row"><div>Kill switch<small>Block traffic if the VPN drops</small></div><div class="tog"></div></div>
    <div class="note">Tip: if you see error 809 on home routers, switch the protocol from IKEv2 to WireGuard.</div>
  </div>
</div>""",
    },
    {
        "file": "analytics-dashboard.png",
        "captured_at": "2026-10-09T16:40:00",
        "html": chrome("https://app.orbit-analytics.example/reports/weekly", "Fri 9 Oct 16:40")
        + """
<style>
.wrap { background: #0f172a; color: #e2e8f0; height: 762px; padding: 30px 40px; }
h1 { margin: 0; font-size: 22px; } .sub { color: #94a3b8; font-size: 14px; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-top: 22px; }
.kpi { background: #1e293b; border-radius: 12px; padding: 18px; }
.kpi div { color: #94a3b8; font-size: 13px; } .kpi b { font-size: 30px; display: block; margin-top: 4px; }
.kpi span { font-size: 13px; color: #4ade80; } .kpi span.down { color: #f87171; }
.chart { margin-top: 18px; background: #1e293b; border-radius: 12px; padding: 18px; height: 330px; }
.bars { display: flex; align-items: flex-end; gap: 18px; height: 250px; margin-top: 14px; }
.bars div { flex: 1; background: #38bdf8; border-radius: 6px 6px 0 0; position: relative; }
.bars div::after { content: attr(data-d); position: absolute; bottom: -22px; left: 0; right: 0; text-align: center; color: #94a3b8; font-size: 12px; }
</style>
<div class="wrap">
  <h1>Weekly report</h1><div class="sub">Orbit Analytics · Week of 5 Oct 2026 · Workspace: Fernhouse Labs</div>
  <div class="kpis">
    <div class="kpi"><div>Signups</div><b>1,284</b><span>+12% vs last week</span></div>
    <div class="kpi"><div>Churn</div><b>3.1%</b><span class="down">+0.4 pts</span></div>
    <div class="kpi"><div>MRR</div><b>$48,210</b><span>+5.2%</span></div>
    <div class="kpi"><div>Top channel</div><b>Referral</b><span>38% of signups</span></div>
  </div>
  <div class="chart"><div style="color:#94a3b8;font-size:13px">Signups per day</div>
    <div class="bars"><div style="height:52%" data-d="Mon"></div><div style="height:61%" data-d="Tue"></div><div style="height:74%" data-d="Wed"></div><div style="height:92%" data-d="Thu"></div><div style="height:66%" data-d="Fri"></div><div style="height:38%" data-d="Sat"></div><div style="height:31%" data-d="Sun"></div></div>
  </div>
</div>""",
    },
    {
        "file": "mail-vacation.png",
        "captured_at": "2026-10-11T11:25:00",
        "html": chrome("https://mail.pebble.example/settings/vacation", "Sun 11 Oct 11:25")
        + """
<style>
.wrap { background: #fff; height: 762px; display: flex; }
.side { width: 230px; border-right: 1px solid #eee; padding: 24px 16px; font-size: 14px; color: #555; }
.side div { padding: 7px 10px; } .side .on { background: #fdf0e6; color: #c25e00; border-radius: 7px; font-weight: 600; }
.main { padding: 28px 40px; flex: 1; }
h1 { font-size: 22px; margin: 0 0 18px; }
label { display: block; font-size: 13px; color: #666; margin: 14px 0 4px; }
.f { border: 1px solid #d5d8dc; border-radius: 8px; padding: 9px 12px; font-size: 15px; }
.on-pill { display: inline-block; background: #c25e00; color: #fff; border-radius: 99px; padding: 3px 12px; font-size: 13px; font-weight: 600; }
.save { margin-top: 18px; display: inline-block; background: #c25e00; color: #fff; border-radius: 8px; padding: 8px 18px; }
.saved { margin-left: 10px; color: #137333; font-size: 14px; }
</style>
<div class="wrap">
  <div class="side"><div><b>Pebble Mail</b></div><div>General</div><div>Filters</div><div class="on">Vacation responder</div><div>Forwarding</div></div>
  <div class="main">
    <h1>Vacation responder <span class="on-pill">On</span></h1>
    <label>First day</label><div class="f">Tue 20 Oct 2026</div>
    <label>Last day</label><div class="f">Tue 27 Oct 2026</div>
    <label>Subject</label><div class="f">Away until 27 October</div>
    <label>Message</label><div class="f" style="height:110px">Hi, I'm away until Tuesday 27 October with limited email. For anything urgent, please write to ops-desk@fernhouse.example. Thanks! Jordan</div>
    <label>Only send to</label><div class="f">People in my contacts</div>
    <div><span class="save">Save changes</span><span class="saved">Saved</span></div>
  </div>
</div>""",
    },
    {
        "file": "router-wifi.png",
        "captured_at": "2026-09-27T21:48:00",
        "html": chrome("http://192.168.8.1/#/wireless/guest", "Sun 27 Sep 21:48")
        + """
<style>
.wrap { background: #f4f5f7; height: 762px; padding: 28px 50px; }
.top { display: flex; justify-content: space-between; align-items: center; }
.brand { font-weight: 800; color: #00897b; font-size: 20px; }
.card { background: #fff; border-radius: 12px; padding: 22px 26px; margin-top: 18px; box-shadow: 0 1px 6px rgba(0,0,0,.06); }
.kv { display: grid; grid-template-columns: 230px 1fr; row-gap: 14px; font-size: 15px; }
.kv div:nth-child(odd) { color: #666; }
.pw { font-family: Menlo, monospace; background: #eef7f6; padding: 2px 8px; border-radius: 5px; }
</style>
<div class="wrap">
  <div class="top"><div class="brand">Tidewater Router · Admin</div><div style="color:#666;font-size:14px">Firmware 3.2.7</div></div>
  <div class="card"><h2 style="margin:0 0 14px;font-size:18px">Guest network</h2>
    <div class="kv">
      <div>Guest network</div><div><b>Enabled</b></div>
      <div>Network name (SSID)</div><div>Fernhouse-Guest</div>
      <div>Password</div><div><span class="pw">tidal-maple-42</span></div>
      <div>Band</div><div>5 GHz, channel 36</div>
      <div>Guests can see each other</div><div>No</div>
      <div>Turns off automatically</div><div>Every day at 23:00</div>
    </div>
  </div>
  <div class="card"><h2 style="margin:0 0 14px;font-size:18px">Main network</h2>
    <div class="kv"><div>Network name (SSID)</div><div>Fernhouse-5G</div><div>Security</div><div>WPA3-Personal</div></div>
  </div>
</div>""",
    },
]


def main() -> None:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415 - only this script needs it

    OUT.mkdir(exist_ok=True)
    layers: dict[str, list] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        for s in SCREENS:
            page.set_content(
                f"<!doctype html><html><head><style>{BASE_CSS}</style></head><body>{s['html']}</body></html>"
            )
            page.screenshot(path=str(OUT / s["file"]))
            words = page.evaluate(TEXT_LAYER)
            layers[s["file"]] = {"size": [1280, 800], "words": words}
            print("  wrote", s["file"], f"({len(words)} words)")
        browser.close()
    index = [{"file": s["file"], "captured_at": s["captured_at"]} for s in SCREENS]
    (OUT / "samples.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    (OUT / "text.json").write_text(
        json.dumps(layers, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(f"{len(SCREENS)} screens in {OUT}")


if __name__ == "__main__":
    main()
