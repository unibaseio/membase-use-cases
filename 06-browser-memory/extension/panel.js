// The side panel. It reads the page in the active tab and talks to one place only: the
// companion server on 127.0.0.1, which holds the Membase key. Nothing is stored in the
// browser: no key, no answers, no history.

const COMPANION = "http://127.0.0.1:8706";
const $ = (sel) => document.querySelector(sel);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === undefined || c === null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}
const svg = (markup, size = 16) => {
  const t = document.createElement("template");
  t.innerHTML = `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${markup}</svg>`;
  return t.content.firstChild;
};
const CHECK = () => svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 14);
const dots = () => el("span", { class: "dots" }, el("i"), el("i"), el("i"));

// Chrome's own favicon for a page it has shown (the "favicon" permission)
// (the "favicon" permission), unless the page named its own icon when it was remembered
const favicon = (url, icon) => icon || chrome.runtime.getURL(`/_favicon/?pageUrl=${encodeURIComponent(url)}&size=32`);
const host = (url) => { try { return new URL(url).host; } catch { return url; } };

async function call(path, body) {
  let res;
  try {
    res = await fetch(COMPANION + path, body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("The companion is not running. Start it with: uv run 06-browser-memory/app.py");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || data.detail || `${res.status} ${res.statusText}`);
  }
  return res;
}

async function stream(path, body, onEvent) {
  const res = await call(path, body);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const line = buf.slice(0, i).split("\n").find((l) => l.startsWith("data: "));
      buf = buf.slice(i + 2);
      if (!line) continue;
      const event = JSON.parse(line.slice(6));
      if (event.type === "error") throw new Error(event.error);
      onEvent(event);
    }
  }
}

// ---- the page --------------------------------------------------------------------------

// The tab the panel is about: the active tab of the panel's window. `?tab=<id>` names one
// explicitly, for when panel.html is opened as a page rather than docked.
async function targetTab() {
  const pinned = new URLSearchParams(location.search).get("tab");
  if (pinned) return chrome.tabs.get(Number(pinned));
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

// Runs inside the page: what the companion needs to know about it.
function extract() {
  const main = document.querySelector("article, main, [role=main]") || document.body;
  const text = (main ? main.innerText : "").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
  return {
    url: location.href,
    title: document.title,
    selection: String(window.getSelection() || "").trim(),
    text: text.slice(0, 20000),
    icon: document.querySelector("link[rel~=icon]")?.href || "",
  };
}

let page = null;
let remembered = [];

async function readPage() {
  $("#page-error").hidden = true;
  $("#remember-out").replaceChildren();  // a note about the last page is not about this one
  $("#remember-out").className = "toast";
  $("#grant").hidden = true;
  page = null;
  const tab = await targetTab();
  $("#page-title").textContent = tab?.title || "No page";
  $("#page-url").textContent = tab?.url ? host(tab.url) : "";
  $("#page-meta").textContent = "";
  if (tab?.url) $("#page-fav").src = tab.favIconUrl || favicon(tab.url);
  if (!tab || !/^https?:/.test(tab.url || "")) {
    showPageError("Open a web page to ask about it.");
    return null;
  }
  try {
    const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: extract });
    page = result;
    $("#page-fav").src = favicon(page.url, tab.favIconUrl || page.icon);
    $("#page-title").textContent = page.title || page.url;
    $("#page-url").textContent = host(page.url);
    $("#page-meta").textContent = page.selection ? `${page.selection.length.toLocaleString()} characters selected` : "";
    rememberState();
    return page;
  } catch (e) {
    showPageError(`Browser Memory can’t read this page yet (${e.message}).`);
    $("#grant").hidden = false;
    return null;
  }
}

function showPageError(message) {
  $("#page-error").textContent = message;
  $("#page-error").hidden = false;
}

// The button says what it would do on this page: remember it, or that it is remembered.
function rememberState() {
  const b = $("#remember");
  const known = page && remembered.find((p) => p.url === page.url);
  b.classList.toggle("done", !!known);
  b.querySelector(".lbl").textContent = known ? "Remembered" : "Remember";
  b.title = known ? "This page is in your memory" : "Remember this page";
}

$("#grant").onclick = async () => {
  const granted = await chrome.permissions.request({ origins: ["<all_urls>"] });
  if (granted) readPage();
};

chrome.tabs.onActivated.addListener(() => readPage());
chrome.tabs.onUpdated.addListener(async (tabId, change) => {
  const tab = await targetTab();
  if (tab && tab.id === tabId && change.status === "complete") readPage();
});

// ---- ask -------------------------------------------------------------------------------

const question = $("#question");
const grow = () => { question.style.height = "auto"; question.style.height = `${question.scrollHeight}px`; };
question.addEventListener("input", grow);
question.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ask-form").requestSubmit(); }
});

let hits = [];

$("#ask-form").onsubmit = async (e) => {
  e.preventDefault();
  const button = $("#ask");
  if (button.disabled) return;
  button.disabled = true;
  const asked = question.value.trim();
  $("#remember-out").replaceChildren();
  $("#answer-card").hidden = false;
  // the question moves into the answer, as a chat does; the box is free for the next one
  $("#asked").replaceChildren(asked ? el("div", { class: "bubble", title: asked }, el("span", {}, asked)) : "");
  question.value = "";
  grow();
  $("#answer").replaceChildren();
  $("#mems-card").hidden = true;
  $("#saved").classList.add("folded");
  const status = $("#answer-status");
  status.replaceChildren(dots(), "Reading the page");
  let text = "";
  try {
    const current = await readPage();
    if (!current) throw new Error("There is no page to ask about.");
    status.replaceChildren(dots(), "Looking through your memory");
    hits = [];
    await stream("/api/ask", { ...current, question: asked }, (ev) => {
      if (ev.type === "memories") {
        hits = ev.hits;
        renderMemories([], ev);
        status.replaceChildren(dots(), hits.length ? `Found ${hits.length} things you saved` : "Nothing saved matches; answering from the page");
      } else if (ev.type === "delta") {
        text += ev.text;
        renderAnswer(text);
      } else if (ev.type === "used") {
        renderMemories(ev.passages);
        renderAnswer(text, true);
        status.replaceChildren();
      }
    });
  } catch (err) {
    status.replaceChildren();
    $("#answer").replaceChildren(el("div", { class: "err" }, err.message));
  } finally {
    button.disabled = false;
  }
};

// The answer: short paragraphs and bullets, **bold**, and [n] as a chip that opens the page
// the memory came from.
function inline(s, linked) {
  const out = [];
  for (const part of s.split(/(\*\*[^*]+\*\*|\[\d+(?:\s*,\s*\d+)*\])/g)) {
    if (!part) continue;
    if (/^\*\*.*\*\*$/.test(part)) out.push(el("b", {}, part.slice(2, -2)));
    else if (/^\[[\d,\s]+\]$/.test(part)) {
      for (const n of part.slice(1, -1).split(",").map((x) => Number(x.trim()))) {
        const p = (hits[n - 1]?.pages || [])[0];
        out.push(linked && p?.url ? el("a", { class: "cite", href: p.url, target: "_blank", title: p.title, "data-n": n }, String(n))
          : el("span", { class: "cite", "data-n": n }, String(n)));
      }
    } else out.push(part);
  }
  return out;
}
function renderAnswer(text, linked = false) {
  const box = $("#answer");
  box.replaceChildren();
  let list = null;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) { list = null; continue; }
    const item = line.match(/^[-*•]\s+(.*)$/);
    if (item) {
      if (!list) box.append((list = el("ul")));
      list.append(el("li", {}, inline(item[1], linked)));
    } else {
      list = null;
      box.append(el("p", {}, inline(line, linked)));
    }
  }
}

function renderMemories(used, ev) {
  const box = $("#mems");
  $("#mems-card").hidden = false;
  box.replaceChildren();
  if (ev?.unheard?.length) box.append(el("div", { class: "err" }, "Your memory didn’t answer: " + ev.unheard.map((u) => u.error).join("; ")));
  if (!hits.length) return box.append(el("div", { class: "quiet" }, "Nothing you saved matches this page."));
  const item = (n) => {
    const h = hits[n - 1];
    const p = (h.pages || [])[0];
    return el("div", { class: `mem${used.includes(n) ? " used" : ""}`, id: `m${n}` },
      el("span", { class: "n" }, String(n)),
      el("div", { class: "from" }, p ? [el("img", { class: "fav", src: favicon(p.url, p.icon), alt: "" }), el("a", { href: p.url, target: "_blank", title: p.url }, p.title)] : "Saved note"),
      el("div", { class: "quote", title: h.content }, h.content));
  };
  if (!used.length) return hits.forEach((_, i) => box.append(item(i + 1)));
  // the memories the answer used, then the rest folded away
  used.forEach((n) => box.append(item(n)));
  const rest = hits.map((_, i) => i + 1).filter((n) => !used.includes(n));
  if (rest.length) box.append(el("details", { class: "rest" }, el("summary", {}, `${rest.length} more recalled, not used`), ...rest.map(item)));
}

// ---- remember --------------------------------------------------------------------------

$("#remember").onclick = async () => {
  const button = $("#remember");
  const out = $("#remember-out");
  button.disabled = true;
  out.className = "toast";
  out.replaceChildren(dots(), "Saving to your memory");
  try {
    const current = await readPage();
    if (!current) throw new Error("There is no page to remember.");
    out.replaceChildren(dots(), "Saving to your memory");
    const doc = await (await call("/api/remember", current)).json();
    out.replaceChildren(el("span", { class: "ok" }, CHECK()),
      doc.already ? "Already in your memory."
        : doc.status === "waiting" ? "Saved. It goes into your memory after the page before it."
        : "Saved to your memory. Membase is learning it.");
    await loadPages();
  } catch (e) {
    out.className = "toast bad";
    out.replaceChildren(e.message);
  } finally {
    button.disabled = false;
  }
};

// learned / learning (a run is queued or running) / waiting (the write waits behind the
// container's current run) / failed / not learned (a run ended without counting this one:
// more arrived while it ran).
const state = (d) => d.learned ? ["learned", "Learned"]
  : ["queued", "running"].includes(d.learning) ? ["learning", "Learning"]
  : d.learning === "waiting" ? ["waiting", "Waiting"]
  : d.learning === "failed" ? ["failed", "Couldn’t learn"]
  : ["learning", "Not learned yet"];
const pending = (d) => !d.learned && ["queued", "running", "waiting"].includes(d.learning);
const when = (iso) => {
  if (!iso) return "just now";
  const d = new Date(iso), days = Math.floor((Date.now() - d) / 864e5);
  return days < 1 ? "Today" : days < 2 ? "Yesterday" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

let poll;
async function loadPages() {
  clearTimeout(poll);
  const box = $("#pages");
  try {
    const { pages, error } = await (await call("/api/pages")).json();
    remembered = pages;
    rememberState();
    box.replaceChildren();
    $("#saved-count").textContent = pages.length ? String(pages.length) : "";
    if (error) return box.append(el("div", { class: "err" }, error));
    if (!pages.length) return box.append(el("div", { class: "quiet" }, "Nothing yet. Pages you remember show up here, and every answer can draw on them."));
    for (const p of pages) {
      const [cls, label] = state(p);
      box.append(el("a", { class: "page-row", href: p.url || "#", target: "_blank", title: p.url },
        el("img", { class: "fav", src: p.url ? favicon(p.url, p.icon) : "", alt: "" }),
        el("div", { class: "page-text" }, el("div", { class: "t" }, p.title), el("div", { class: "h" }, `${host(p.url)} · ${when(p.created_at)}`)),
        el("span", { class: "state", "data-state": cls, title: p.run_id || "" }, cls === "learned" ? CHECK() : cls === "failed" ? null : el("span", { class: "spin" }), label)));
    }
    if (pages.some(pending)) poll = setTimeout(loadPages, 5000);
  } catch (e) {
    box.replaceChildren(el("div", { class: "err" }, e.message));
  }
}

// ---- start -----------------------------------------------------------------------------

async function connect() {
  try {
    const info = await (await call("/api/info")).json();
    $("#badge").textContent = info.mode === "hosted" ? "Membase · hosted" : "Membase · local";
    $("#companion").hidden = true;
  } catch (e) {
    $("#badge").textContent = "offline";
    $("#companion").textContent = e.message;
    $("#companion").hidden = false;
  }
}

connect();
readPage();
loadPages();
