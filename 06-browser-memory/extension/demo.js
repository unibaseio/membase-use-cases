// The demo window: `?pages=<base url>&open=<file>,<file>,...` lists the tabs to show.
const params = new URLSearchParams(location.search);
const base = params.get("pages") || "http://127.0.0.1:18706";
const files = (params.get("open") || "larchmere-ridge-loop.html,corvid-38-review.html,larchmere-forecast.html").split(",");
let realTab = null;

function showUrl(url) {
  const u = new URL(url);
  const box = document.getElementById("url");
  const hostEl = document.createElement("b");
  hostEl.textContent = u.host;
  box.replaceChildren(hostEl, u.pathname + u.search);
}

async function show(file) {
  const url = `${base}/${file}`;
  document.getElementById("page").src = url;
  showUrl(url);
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.file === file));
  if (!realTab) {
    realTab = await chrome.tabs.create({ url, active: false });
    document.getElementById("panel").src = `panel.html?tab=${realTab.id}`;
  } else {
    await chrome.tabs.update(realTab.id, { url });
  }
}

const strip = document.getElementById("tabs");
for (const file of files) {
  const t = document.createElement("div");
  t.className = "tab";
  t.dataset.file = file;
  t.id = "tab-" + file.replace(/\.html$/, "");
  t.innerHTML = '<img alt=""><span class="t"></span><span class="x"><svg width="10" height="10" viewBox="0 0 10 10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M2 2l6 6M8 2l-6 6"/></svg></span>';
  t.querySelector(".t").textContent = file.replace(/\.html$/, "").replace(/-/g, " ");
  t.onclick = () => show(file);
  strip.insertBefore(t, document.getElementById("newtab"));
}
// tab labels and icons: the pages' own <title> and <link rel=icon>, once each is fetched
for (const file of files) {
  fetch(`${base}/${file}`).then((r) => r.text()).then((html) => {
    const tab = document.getElementById("tab-" + file.replace(/\.html$/, ""));
    const title = html.match(/<title>([^<]*)<\/title>/i);
    if (title) tab.querySelector(".t").textContent = title[1];
    const icon = html.match(/<link[^>]+rel="icon"[^>]+href="([^"]+)"/i);
    if (icon) tab.querySelector("img").src = new URL(icon[1], `${base}/${file}`).href;
  }).catch(() => {});
}
show(files[0]);
