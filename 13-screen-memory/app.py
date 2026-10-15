"""Screen memory: screenshots are read by a vision model, remembered with the time they were
taken, and recalled later to answer questions, citing the screenshot each answer came from.

A screenshot goes in (upload, drag or paste). The vision model says which app it is, what the
person was doing and the values on screen, and that becomes one memory in the `Screens`
container, dated when the screenshot was taken (not when it was added). A question is a recall
over that container. Each recalled memory maps back to its screenshot through the memory id the
write returned, so the page can show the image beside the answer.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from demokit import Memory, config, llm  # noqa: E402
from demokit.dated import recall as dated_recall  # noqa: E402
from demokit.dated import remember_sessions  # noqa: E402
from demokit.memory import is_narration  # noqa: E402
from demokit.web import create_app, run, sse  # noqa: E402

CONTAINER = "Screens"
SAMPLES = HERE / "samples"
MAX_BYTES = 8 * 1024 * 1024
TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}

mem = Memory("13-screen-memory", user="me", default_mode="local")
app = create_app("Screen memory", HERE, mode=mem.mode)
SHOTS = mem.path / "screens"
SHOTS.mkdir(parents=True, exist_ok=True)
INDEX = mem.path / "screens.json"
_lock = threading.Lock()  # one write at a time: ids, the index file and the local engine

VISION = (
    "This is a screenshot from someone's computer, taken {when}. Read it carefully and reply with "
    "JSON only, no prose:\n"
    '{{"app": "<app or website name>", "screen": "<what kind of screen: confirmation, error '
    'dialog, settings page, ...>", "activity": "<one sentence: what the person was doing or what '
    'happened>", "key_values": {{"<label>": "<value exactly as shown>", ...}}, "text": "<the '
    'important visible text, up to 80 words>", "summary": "<two sentences a person could search '
    'for later>"}}\n'
    "Put every code, number, name, date, time, setting and error message you can read into "
    "key_values, copied exactly."
)

ANSWER = (
    "You answer questions about what the user saw on their own screen, using only the memories "
    "of their screenshots below. Each memory names its screenshot, like [S2]. Answer like a "
    "search result: only what was asked, in at most 10 words, with the exact values as "
    "remembered, like 'Gate B12 [S4]' or 'Turned on two-step login [S2]'. No full sentences, "
    "and do not restate the question. Cite each screenshot you used in its own "
    "brackets, like [S2] [S3]. If the memories do not contain the answer, say so in a few words."
)


# The samples' text layers (seed.py): every word on the screenshot and its box. An uploaded
# screenshot has none, so nothing can be highlighted on it.
TEXT = (
    json.loads((SAMPLES / "text.json").read_text(encoding="utf-8"))
    if (SAMPLES / "text.json").is_file()
    else {}
)
_PUNCT = "\"'.,:;!?()[]{}\u25be\u2192"


def load() -> list[dict]:
    return json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.is_file() else []


def when(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%A %-d %B %Y at %H:%M")


def parse_json(text: str) -> dict:
    """The model's JSON, with or without a code fence around it."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError(f"the vision model did not return JSON: {text[:200]!r}")
    return json.loads(m.group(0))


def memory_text(sid: str, filename: str, captured_at: str, a: dict) -> str:
    values = "; ".join(f"{k}: {v}" for k, v in (a.get("key_values") or {}).items())
    return (
        f"Screenshot {sid} ({filename}), taken on {when(captured_at)}.\n"
        f"App: {a.get('app', '')}. Screen: {a.get('screen', '')}.\n"
        f"What was happening: {a.get('activity', '')}\n"
        f"Values on screen: {values}\n"
        f"Visible text: {a.get('text', '')}\n"
        f"Summary: {a.get('summary', '')}"
    )


def check(data: bytes, content_type: str, filename: str, captured_at: str) -> None:
    if content_type not in TYPES:
        raise HTTPException(415, f"{filename}: send a PNG, JPEG or WebP image, not {content_type}")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"{filename}: images up to 8 MB")
    try:
        datetime.fromisoformat(captured_at)
    except ValueError as err:
        raise HTTPException(
            400, f"captured_at must be an ISO time like 2026-09-18T09:03, not {captured_at!r}"
        ) from err


def analyse(
    data: bytes, content_type: str, filename: str, captured_at: str, text_layer: str | None = None
):
    """Vision, then one memory write dated when the screenshot was taken. Yields the reading
    (`read`), then the screen's record (`remembered`)."""
    started = time.monotonic()
    url = f"data:{content_type};base64,{base64.b64encode(data).decode()}"
    analysis = parse_json(llm.vision(VISION.format(when=when(captured_at)), url))
    vision_s = time.monotonic() - started
    yield {"type": "read", "file": filename, "analysis": analysis, "seconds": round(vision_s, 1)}
    with _lock:
        screens = load()
        sid = f"S{len(screens) + 1}"
        stored = f"{sid}{TYPES[content_type]}"
        (SHOTS / stored).write_bytes(data)
        text = memory_text(sid, filename, captured_at, analysis)
        title = f"Screenshot {sid}: {analysis.get('app', '')}"
        # One dated session per screenshot: the engine stamps its episodes with the time the
        # screenshot was taken. memories.add would stamp them with the time of this call.
        session = f"screen-{sid}-{uuid.uuid4().hex[:6]}"
        ids = remember_sessions(
            mem,
            [
                {
                    "session_id": session,
                    "session_date": datetime.fromisoformat(captured_at).isoformat(
                        timespec="seconds"
                    ),
                    "turns": [{"role": "user", "content": f"{title}\n\n{text}"}],
                }
            ],
            container=CONTAINER,
        )[session]
        if not ids:
            (SHOTS / stored).unlink(missing_ok=True)
            raise RuntimeError(f"{filename}: the memory engine kept nothing from this screenshot")
        record = {
            "id": sid,
            "file": filename,
            "stored": stored,
            "captured_at": captured_at,
            "analysis": analysis,
            "memory_ids": ids,
            "memory": text,
            "text_layer": text_layer,
            "seconds": {
                "vision": round(vision_s, 1),
                "memory": round(time.monotonic() - started - vision_s, 1),
            },
        }
        screens.append(record)
        INDEX.write_text(json.dumps(screens, indent=1), encoding="utf-8")
    yield {"type": "remembered", "screen": record}


@app.post("/api/screens")
async def upload(
    file: Annotated[UploadFile, File()], captured_at: Annotated[str, Form()] = ""
) -> dict:
    data = await file.read()
    captured = captured_at or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    name, kind = file.filename or "screenshot", file.content_type or ""
    check(data, kind, name, captured)
    # analyse() blocks for ~10 s (vision + a local write): run it off the event loop.
    import anyio  # noqa: PLC0415

    events = await anyio.to_thread.run_sync(lambda: list(analyse(data, kind, name, captured)))
    return events[-1]["screen"]


@app.get("/api/screens")
def screens() -> dict:
    return {"screens": load()}


@app.get("/api/screens/{sid}/image", include_in_schema=False)
def image(sid: str) -> FileResponse:
    for s in load():
        if s["id"] == sid:
            return FileResponse(SHOTS / s["stored"])
    raise HTTPException(404, f"no screenshot {sid}")


@app.get("/api/samples")
def samples() -> dict:
    index = json.loads((SAMPLES / "samples.json").read_text(encoding="utf-8"))
    taken = {s["file"] for s in load()}
    return {"samples": [{**s, "added": s["file"] in taken} for s in index]}


@app.get("/api/samples/{name}", include_in_schema=False)
def sample_image(name: str) -> FileResponse:
    path = SAMPLES / Path(name).name
    if path.suffix != ".png" or not path.is_file():
        raise HTTPException(404, f"no sample {name}")
    return FileResponse(path)


class Sample(BaseModel):
    file: str


@app.post("/api/samples/add")
def add_sample(body: Sample):
    """Streams `read` (what the vision model saw) and then `remembered` (the screen's record)."""
    index = {
        s["file"]: s for s in json.loads((SAMPLES / "samples.json").read_text(encoding="utf-8"))
    }
    s = index.get(body.file)
    if not s:
        raise HTTPException(404, f"no sample {body.file}")
    if any(x["file"] == s["file"] for x in load()):
        raise HTTPException(409, f"{s['file']} is already in memory")
    data = (SAMPLES / s["file"]).read_bytes()
    layer = s["file"] if s["file"] in TEXT else None
    return sse(analyse(data, "image/png", s["file"], s["captured_at"], text_layer=layer))


def by_memory() -> dict[str, dict]:
    """memory id -> its screenshot, from the ids each write returned."""
    return {mid: s for s in load() for mid in s["memory_ids"]}


def _norm(word: str) -> str:
    return word.strip(_PUNCT).lower()


def _find(words: list[dict], phrase: str) -> list[dict]:
    """Every place `phrase` appears in a text layer, as one box per occurrence."""
    want = [_norm(t) for t in phrase.split() if _norm(t)]
    found = []
    for i in range(len(words) - len(want) + 1):
        run = words[i : i + len(want)]
        if [_norm(w["t"]) for w in run] != want or abs(run[-1]["y"] - run[0]["y"]) > run[0]["h"]:
            continue
        x0, y0 = min(w["x"] for w in run), min(w["y"] for w in run)
        x1 = max(w["x"] + w["w"] for w in run)
        y1 = max(w["y"] + w["h"] for w in run)
        found.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
    return found


def regions(screen: dict, answer: str) -> dict | None:
    """Where the answer is on the screenshot: the values read from it that the answer quotes,
    found in its text layer; failing that, the answer's codes and names (words with a capital
    or a digit). Boxes are fractions of the image; `primary` is the most prominent one."""
    layer = TEXT.get(screen.get("text_layer") or "")
    if not layer:
        return None
    words, (width, height) = layer["words"], layer["size"]
    said = " " + " ".join(_norm(t) for t in answer.split()) + " "
    boxes, quoted = [], 0
    for value in (screen["analysis"].get("key_values") or {}).values():
        v = " ".join(_norm(t) for t in str(value).split() if _norm(t))
        if len(v) >= 2 and f" {v} " in said:
            hits = _find(words, str(value))
            quoted += bool(hits)
            boxes += hits
    if not boxes:
        for token in re.findall(r"[A-Za-z0-9][\w./-]*", answer):
            if (
                len(token) >= 3
                and re.search(r"\d|[A-Z]", token[1:])
                and not re.match(r"S\d+$", token)
            ):
                boxes += _find(words, token)
    unique = []
    for b in boxes:
        if b not in unique:
            unique.append(b)
    if not unique:
        return None
    # the prominent places only: a value repeated in small print elsewhere is not marked
    tallest = max(b["h"] for b in unique)
    unique = [b for b in unique if b["h"] >= 0.85 * tallest][:4]
    primary = max(range(len(unique)), key=lambda i: unique[i]["h"])
    return {
        "boxes": [
            [b["x"] / width, b["y"] / height, b["w"] / width, b["h"] / height] for b in unique
        ],
        "primary": primary,
        "quoted": quoted,
    }


class Ask(BaseModel):
    question: str


@app.post("/api/ask")
def ask(body: Ask):
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "ask a question")

    def events():
        started = time.monotonic()
        owners = by_memory()
        hits = []
        for h in dated_recall(mem, question, container=CONTAINER, limit=6):
            if is_narration(h["content"]):
                continue
            s = owners.get(h["memory_id"])
            hits.append({**h, "screen": s["id"] if s else None})
        yield {"type": "memories", "hits": hits, "seconds": round(time.monotonic() - started, 2)}
        lines = [f"[{h['screen'] or '?'}] {h['content']}" for h in hits]
        context = (
            "Memories of the user's screenshots:\n" + "\n".join(lines)
            if lines
            else "No memories were found."
        )
        answer = ""
        for delta in llm.stream(
            [
                {"role": "system", "content": ANSWER},
                {"role": "user", "content": f"{context}\n\nQuestion: {question}"},
            ],
            temperature=0.2,
        ):
            answer += delta
            yield {"type": "delta", "text": delta}
        cited = list(dict.fromkeys(re.findall(r"\bS\d+\b", answer)))
        cited = [c for c in cited if any(c == h["screen"] for h in hits)]
        shots = {s["id"]: s for s in load()}
        where = {c: regions(shots[c], answer) for c in cited if c in shots}
        where = {c: r for c, r in where.items() if r}
        # the screenshot to open: the one whose own values the answer quotes most, the latest
        # on a tie
        first = max(
            cited,
            key=lambda c: ((where.get(c) or {}).get("quoted", 0), shots[c]["captured_at"]),
            default=None,
        )
        yield {"type": "done", "cited": cited, "open": first, "regions": where}

    return sse(events())


# ---- redo a task: an agent finds the procedure across screenshots; saved runs become agent memory

AGENT = "howto"
PROCEDURES = "Procedures"
HOWTO = (
    "You help the user redo something they did before, using only the memory of their own "
    "screenshots. Search that memory, then open the screens that matter to read the exact "
    "settings, one tool call at a time. Answer with short numbered steps and cite screens like "
    "[S3]. If the user says it did not work, look again for anything else they set up."
)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_screens",
            "description": "Search the memory of the user's screenshots; returns screen ids "
            "and what was remembered.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_screen",
            "description": "Everything read from one screenshot: app, when, values on "
            "screen, visible text.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    },
]
_sessions: dict[str, list[dict]] = {}
_engine = threading.Lock()  # agent-memory search and ingest, one at a time


def call_tool(name: str, args: dict) -> object:
    if name == "search_screens":
        owners = by_memory()
        return [
            {"screen": (owners.get(h["memory_id"]) or {}).get("id"), "memory": h["content"]}
            for h in dated_recall(mem, str(args.get("query") or ""), container=CONTAINER, limit=4)
            if not is_narration(h["content"])
        ]
    if name == "open_screen":
        s = next((s for s in load() if s["id"] == str(args.get("id") or "")), None)
        if not s:
            return {"error": f"no screen {args.get('id')!r}"}
        return {"id": s["id"], "taken": when(s["captured_at"]), **s["analysis"]}
    return {"error": f"no tool {name}"}


def agent_loop(messages: list[dict]):
    client = llm.client()
    for _ in range(8):
        msg = (
            client.chat.completions.create(
                model=config.model(),
                messages=messages,
                tools=TOOLS,
                parallel_tool_calls=False,
                temperature=0.2,
            )
            .choices[0]
            .message
        )
        if not msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content or ""})
            yield {"type": "answer", "text": msg.content or ""}
            return
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.function.name, "arguments": c.function.arguments},
                    }
                    for c in msg.tool_calls
                ],
            }
        )
        for c in msg.tool_calls:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool_call", "name": c.function.name, "args": args}
            result = call_tool(c.function.name, args)
            messages.append(
                {"role": "tool", "tool_call_id": c.id, "content": json.dumps(result)[:4000]}
            )
            yield {"type": "tool_result", "name": c.function.name, "result": result}
    raise RuntimeError("the agent did not answer within 8 steps")


def procedures_saved() -> bool:
    return any(r.get("cases") for r in load_procedures())


def load_procedures() -> list[dict]:
    path = mem.path / "procedures.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


class HowTo(BaseModel):
    message: str
    session: str | None = None


@app.post("/api/howto")
def howto(body: HowTo):
    """A new task (no session), or the user's reply to the run in `session`."""
    text = body.message.strip()
    if not text:
        raise HTTPException(400, "say what you want to redo")
    if body.session and body.session not in _sessions:
        raise HTTPException(404, "that run is gone (the server restarted?): start again")

    def events():
        if body.session:
            sid, messages = body.session, _sessions[body.session]
            messages.append({"role": "user", "content": text})
        else:
            sid = uuid.uuid4().hex[:10]
            notes, used = "", {"cases": [], "skills": [], "seconds": 0.0}
            if procedures_saved():
                started = time.monotonic()
                with _engine:
                    out = mem.agent_search(text, agent_id=AGENT, container=PROCEDURES, limit=3)
                used = {
                    "cases": [
                        {
                            "task_intent": c["task_intent"],
                            "approach": c["approach"],
                            "score": c.get("score"),
                        }
                        for c in out.get("cases", [])
                    ],
                    "skills": [
                        {
                            "name": k["name"],
                            "description": k["description"],
                            "content": k["content"],
                        }
                        for k in out.get("skills", [])[:2]
                    ],
                    "seconds": round(time.monotonic() - started, 2),
                }
                parts = [f"Procedure '{k['name']}': {k['content'][:2000]}" for k in used["skills"]]
                parts += [f"Past run: {c['task_intent']}\n{c['approach']}" for c in used["cases"]]
                if parts:
                    notes = (
                        "\n\nProcedures you worked out before (from agent memory):\n\n"
                        + "\n\n".join(parts)
                    )
            yield {"type": "procedures", **used}
            messages = [
                {"role": "system", "content": HOWTO + notes},
                {"role": "user", "content": text},
            ]
            _sessions[sid] = messages
        yield {"type": "session", "session": sid}
        yield from agent_loop(messages)
        rounds = sum(1 for m in messages if m["role"] == "assistant" and m.get("tool_calls"))
        yield {"type": "done", "rounds": rounds}

    return sse(events())


class Save(BaseModel):
    session: str


@app.post("/api/howto/save")
def save_howto(body: Save) -> dict:
    """The run so far, as agent memory: the engine keeps it as a case (and a skill) when it shows
    exploration or the user's correction and used at least three tool rounds."""
    messages = _sessions.get(body.session)
    if not messages:
        raise HTTPException(404, "that run is gone: start again")
    trace = [
        m for m in messages if m["role"] != "system"
    ]  # the engine takes user/assistant/tool turns
    started = time.monotonic()
    with _engine:
        out = mem.agent_ingest(trace, agent_id=AGENT, session_id=body.session, container=PROCEDURES)
    record = {
        "session": body.session,
        "task": next(m["content"] for m in trace if m["role"] == "user"),
        "at": time.time(),
        "seconds": round(time.monotonic() - started, 1),
        **{
            k: out.get(k)
            for k in ("status", "cases", "skills_added", "skills_updated", "skipped", "failed")
        },
    }
    path = mem.path / "procedures.json"
    with _lock:
        path.write_text(json.dumps([*load_procedures(), record], indent=1), encoding="utf-8")
    return record


@app.get("/api/howto/skills")
def howto_skills() -> dict:
    if not procedures_saved():
        return {"skills": [], "saved": load_procedures()}
    with _engine:
        skills = mem.agent_skills(agent_id=AGENT, container=PROCEDURES)
    return {"skills": skills, "saved": load_procedures()}


if __name__ == "__main__":
    run(app, port=8713)
