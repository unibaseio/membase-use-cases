// Shared page helpers: JSON calls, server-sent event streams, chat bubbles, memory lists.
// Plain ES module, no build step: <script type="module"> import { ... } from "/kit/kit.js"

export const $ = (sel, root = document) => root.querySelector(sel);

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === undefined || c === null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export async function api(path, body, { method } = {}) {
  const opts = { method: method || (body === undefined ? "GET" : "POST"), headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || data.detail || `${res.status} ${res.statusText}`);
  return data;
}

// POST `body` to `path` and call `onEvent(event)` for each `data:` event of the reply.
export async function stream(path, body, onEvent) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `${res.status} ${res.statusText}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      const event = JSON.parse(line.slice(6));
      if (event.type === "error") throw new Error(event.error);
      onEvent(event);
    }
  }
}

// A chat transcript in `container`: add(role, text) returns the bubble so a stream can grow it.
export function chatLog(container) {
  return {
    add(role, text = "") {
      const bubble = el("div", { class: `msg ${role}` }, text);
      container.append(bubble);
      container.scrollTop = container.scrollHeight;
      return bubble;
    },
    grow(bubble, delta) {
      bubble.textContent += delta;
      container.scrollTop = container.scrollHeight;
    },
    clear() {
      container.replaceChildren();
    },
  };
}

// Memory hits ({content, container_name, ...}) as a list; `label` names what they are.
export function renderMemories(target, hits, { empty = "Nothing recalled.", seconds } = {}) {
  target.replaceChildren();
  if (!hits || !hits.length) {
    target.append(el("div", { class: "empty" }, empty));
    return;
  }
  if (seconds !== undefined) target.append(el("div", { class: "muted small" }, `recalled in ${seconds}s`));
  for (const h of hits) {
    target.append(memoryItem(h));
  }
}

// One memory hit; long passages (a whole document topic) are clamped with a toggle.
export function memoryItem(h, { clamp = 420 } = {}) {
  const label = [h.container_name, h.title].filter(Boolean).join(" · ");
  const text = el("span", {}, h.content);
  const item = el("div", { class: "mem" }, label ? el("span", { class: "k" }, label) : null, text);
  if (h.content && h.content.length > clamp) {
    let open = false;
    const toggle = el("button", { class: "linkish", type: "button" });
    const render = () => {
      text.textContent = open ? h.content : h.content.slice(0, clamp).trimEnd() + "…";
      toggle.textContent = open ? "Show less" : "Show more";
    };
    toggle.addEventListener("click", () => { open = !open; render(); });
    render();
    item.append(" ", toggle);
  }
  return item;
}

export function showError(target, e) {
  target.replaceChildren(el("div", { class: "err" }, e.message || String(e)));
}

export function busy(button, on, label) {
  if (on) {
    // Called again while busy (a new phase), keep the label from before the first call.
    if (!button.disabled) button.dataset.label = button.textContent;
    button.disabled = true;
    button.replaceChildren(el("span", { class: "spinner" }), " ", label || "Working");
  } else {
    button.disabled = false;
    button.textContent = button.dataset.label || button.textContent;
  }
}

// The mode badge in the header: GET /api/info -> {mode, demo}
export async function modeBadge(target) {
  try {
    const info = await api("/api/info");
    target.append(el("span", { class: `badge ${info.mode}` }, info.mode === "hosted" ? "Hosted Membase" : "Local engine"));
  } catch {
    /* the page works without the badge */
  }
}
