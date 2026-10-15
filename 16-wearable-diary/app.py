"""Wearable diary: a day of audio from a recording pendant becomes conversation memory.

The page is Earshot, the pendant's companion app. Each clip (synced from the sample day, an
uploaded file, or a recording made in the browser) is transcribed with its timings, the model
says who spoke each line, and the speaker turns are remembered as one conversation dated when it
was recorded. The day shows as a diary entry and a timeline of conversations with their
waveforms and your to-dos. Questions ("What did I promise Sam?") are answered from recalled
conversation memory; each cited clip opens at the line the answer rests on, ready to play. A
clip can be forgotten: its memory and its audio go.

The people and conversations in the seeded day are made up; the audio is synthetic speech."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from demokit import Memory, llm  # noqa: E402
from demokit.config import DATA  # noqa: E402
from demokit.dated import recall, remember_sessions  # noqa: E402
from demokit.memory import is_narration  # noqa: E402
from demokit.web import create_app, run  # noqa: E402

DEMO = "16-wearable-diary"
CONTAINER = "Conversations"
WEARER = "Me"
#: The seeded day's wearer. Their turns are labelled "Me" whatever their name.
WEARER_NAME = "Alex"
AUDIO_TYPES = {".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".oga", ".mpeg", ".mpga", ".flac"}

mem = Memory(DEMO, user="me", default_mode="local")
app = create_app("Wearable diary", HERE, mode=mem.mode)
CLIPS = mem.path / "clips"
CLIPS.mkdir(exist_ok=True)
work = ThreadPoolExecutor(max_workers=2, thread_name_prefix="diary")


class Clips:
    """Clip records in `clips.json`: when, audio file, transcript, turns, summary, memory ids."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()

    def all(self) -> dict[str, dict]:
        with self.lock:
            return json.loads(self.path.read_text()) if self.path.is_file() else {}

    def put(self, clip: dict) -> dict:
        with self.lock:
            data = json.loads(self.path.read_text()) if self.path.is_file() else {}
            data[clip["id"]] = clip
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1))
            tmp.replace(self.path)
        return clip

    def update(self, clip_id: str, **changes) -> dict:
        clip = self.all()[clip_id]
        clip.update(changes)
        return self.put(clip)

    def drop(self, clip_id: str) -> None:
        with self.lock:
            data = json.loads(self.path.read_text())
            data.pop(clip_id, None)
            self.path.write_text(json.dumps(data, indent=1))


clips = Clips(mem.path / "clips.json")

SPLIT = """A wearable pendant recorded this conversation at {when}. The person wearing it is
{name}. The transcript comes as numbered segments, in order, with no speaker labels.

Say who spoke each segment. Label {name}'s segments "{wearer}", never "{name}". Name the other
people when the conversation shows their names (someone is addressed as "Priya", someone says
"it's Sam"); otherwise call them "Speaker A", "Speaker B". Work names out from context: someone
addressed by name usually answers next ("Marco, you go first" -> the next segment is Marco's),
and "thanks, Priya" means Priya was the one speaking. A segment that goes on a sentence the
segment before started is usually the same speaker.

Then give a short title (2-4 words, like a voice memo's name: "Stand-up", "Lunch with Jordan"),
a one-sentence summary in the second person ("You ..."), and every commitment made: what was
promised or agreed, by whom, and when it is due if said. Write each "what" as a short to-do
(at most 8 words: "Send Marco the staging keys").

Reply with JSON: {{"title": "...", "summary": "...", "speakers": ["..."],
"segments": [{{"n": 1, "speaker": "..."}}, {{"n": 2, "speaker": "..."}}, ...],
"commitments": [{{"who": "...", "what": "...", "when": "..."}}]}}
"segments" has one entry for every numbered segment, in order."""


def transcribe(audio: bytes, filename: str) -> tuple[str, list[dict], float | None]:
    """Speech to text with each segment's start and end (seconds), and the clip's length.

    whisper-1 gives timed segments (`verbose_json`); a transcriber that cannot (set by
    DEMO_TRANSCRIBE_MODEL) gives text only, split into sentences with no times, and the clip
    then plays from its start."""
    model = os.environ.get("DEMO_TRANSCRIBE_MODEL") or "whisper-1"
    if model == "whisper-1":
        out = llm.client().audio.transcriptions.create(
            model=model,
            file=(filename, audio),
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
        segments = [
            {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in out.segments or []
            if s.text.strip()
        ]
        return out.text.strip(), segments, out.duration
    text = llm.transcribe(audio, filename).strip()
    return (
        text,
        [{"start": None, "end": None, "text": t} for t in re.split(r"(?<=[.!?])\s+", text) if t],
        None,
    )


def turns_from(segments: list[dict], labels: list) -> list[dict]:
    """Consecutive segments by the same speaker joined into turns, keeping their times.
    `labels` is the model's [{n, speaker}], one per numbered segment."""
    who = {
        int(x["n"]): str(x.get("speaker") or "").strip()
        for x in labels
        if isinstance(x, dict) and str(x.get("n", "")).isdigit()
    }
    missing = [n for n in range(1, len(segments) + 1) if not who.get(n)]
    if missing:
        raise ValueError(f"no speaker for segment{'s' if len(missing) > 1 else ''} {missing}")
    turns: list[dict] = []
    for n, seg in enumerate(segments, 1):
        if turns and turns[-1]["speaker"] == who[n]:
            t = turns[-1]
            t["text"] += " " + seg["text"]
            t["end"] = seg["end"]
        else:
            turns.append({"speaker": who[n], **seg})
    return turns


def split(segments: list[dict], when: datetime) -> tuple[dict, list[dict]]:
    """The model's title, summary and commitments, and the speaker turns. A reply that leaves
    a segment without a speaker is sent back once or twice, saying which."""
    messages = [
        {
            "role": "system",
            "content": SPLIT.format(
                when=f"{when:%A %d %B %Y, %H:%M}", wearer=WEARER, name=WEARER_NAME
            ),
        },
        {
            "role": "user",
            "content": "\n".join(f"[{i}] {s['text']}" for i, s in enumerate(segments, 1)),
        },
    ]
    for attempt in range(3):
        out = llm.json_reply(messages)
        try:
            return out, turns_from(segments, out.get("segments") or [])
        except ValueError as e:
            if attempt == 2:
                raise
            messages += [
                {"role": "assistant", "content": json.dumps(out)},
                {
                    "role": "user",
                    "content": f"{e}. There are {len(segments)} segments: give a speaker for "
                    "every one, and reply with the whole JSON again.",
                },
            ]
    raise AssertionError("unreachable")


def new_clip(audio: bytes, filename: str, when: str) -> dict:
    suffix = Path(filename or "clip.webm").suffix.lower() or ".webm"
    if suffix not in AUDIO_TYPES:
        raise HTTPException(
            400,
            f"{suffix} is not an audio file the transcriber reads ({', '.join(sorted(AUDIO_TYPES))})",
        )
    if not audio:
        raise HTTPException(400, "the audio file is empty")
    try:
        at = datetime.fromisoformat(when) if when else datetime.now()
    except ValueError as e:
        raise HTTPException(400, f"when must be a date and time, not {when!r}") from e
    clip_id = uuid.uuid4().hex[:10]
    (CLIPS / f"{clip_id}{suffix}").write_bytes(audio)
    return clips.put(
        {
            "id": clip_id,
            "when": at.replace(second=0, microsecond=0).isoformat(timespec="minutes"),
            "file": f"{clip_id}{suffix}",
            "name": filename,
            "status": "transcribing",
            "memory_ids": [],
        }
    )


def process(clip_id: str) -> dict:
    """Transcribe, say who spoke each segment, remember dated by the clip's time."""
    clip = clips.all()[clip_id]
    try:
        started = time.monotonic()
        text, segments, duration = transcribe((CLIPS / clip["file"]).read_bytes(), clip["file"])
        if not text or not segments:
            raise ValueError("the transcriber heard no speech in this clip")
        clips.update(clip_id, status="splitting", transcript=text, duration=duration)
        when = datetime.fromisoformat(clip["when"])
        out, turns = split(segments, when)
        clips.update(
            clip_id,
            status="remembering",
            title=out.get("title") or "Conversation",
            summary=out.get("summary") or "",
            turns=turns,
            speakers=list(dict.fromkeys(t["speaker"] for t in turns)),
            commitments=[c for c in out.get("commitments") or [] if isinstance(c, dict)],
        )
        ids = remember_sessions(
            mem,
            [
                {
                    "session_id": f"clip-{clip_id}",
                    "session_date": when.isoformat(timespec="seconds"),
                    "turns": [{"role": t["speaker"], "content": t["text"]} for t in turns],
                }
            ],
            container=CONTAINER,
            owner=WEARER,
        )[f"clip-{clip_id}"]
        if not ids:
            raise ValueError("the engine kept no memory from this conversation")
        return clips.update(
            clip_id, status="saved", memory_ids=ids, seconds=round(time.monotonic() - started, 1)
        )
    except Exception as e:
        clips.update(clip_id, status="error", error=f"{type(e).__name__}: {e}")
        raise


def _logged(future) -> None:
    if future.exception():
        print(f"diary: {future.exception()}", file=sys.stderr)


ANSWER = """You are Earshot, the memory of someone who wears a recording pendant. You are
given conversations it recorded, recalled from memory for this question, numbered in the order
they happened, each dated. "Me" in them is the wearer, whom you address as "you". It is now
{now}.

First, in "mentions", list every conversation that says something about what was asked, and
every thing in it that answers the question (each plan, offer, agreement or time).

Then answer like a good notes app, not an assistant: one or two short lines, at most 26 words.
Start with the answer itself (a day, a time, a thing): never restate the question, never "You
promised Sam that", never "according to". Write days as words ("Saturday"), never dates. Write
times the way people say them, in 12-hour form: "9:00", "3:30", never "15:30". Give every thing
that answers it: a promise is anything the wearer said they would do, offered or agreed to,
whether or not the word "promise" was used. When an earlier conversation said something
different, the latest one is the current state: give it in "answer", name the conversation that
changed it in "changed_by" and what it was before in "was" (the app shows both). Times in the
conversations are the wearer's own clock: never mention a time zone. Never name a conversation
by its number. Call people by name. Use only these conversations; if they do not answer, say
"Nothing about that in your conversations."

Reply with JSON: {{"mentions": [{{"n": 1, "says": "..."}}], "answer": "...",
"used": [numbers of every conversation the answer relies on, the earlier ones it corrects included],
"changed_by": <number of the conversation that changed an earlier answer, or null>,
"was": "<what it was before that change, at most 4 words, or empty>"}}"""

#: Spoken numbers, so "nine" in a clip matches "9:00" in an answer.
NUMBERS = {
    w: str(i)
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve".split()
    )
} | {"thirty": "30", "fifteen": "15", "forty-five": "45", "half": "30"}
STOP = set(
    "a an and the to of in on at for is it its was be with you your i me my we our he she they "
    "what when where who did do does that this there then so as by from are or but not up".split()
)


def words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+(?:-[a-z]+)?", text.lower()):
        w = NUMBERS.get(w, w)
        if w not in STOP:
            out.add(w.removesuffix("s") if len(w) > 3 else w)
    return out


def moment(clip: dict, answer_text: str, question: str) -> dict | None:
    """The turn of the clip the answer rests on: the one sharing most words with the answer and
    the question, a word counting more the fewer of the clip's turns say it ("Sam" in every
    greeting counts little, "promise" a lot). The page shows that turn as the clip's own words
    and plays from its start."""
    turns = clip.get("turns") or []
    said = [words(t["text"]) for t in turns]
    want = words(answer_text) | words(question)
    best, score = None, 0.0
    for i, w in enumerate(said):
        n = sum(1 / sum(x in other for other in said) for x in want & w)
        if n > score:
            best, score = i, n
    if best is None:
        return None
    t = turns[best]
    return {
        "turn": best,
        "speaker": t["speaker"],
        "text": t["text"],
        "start": t.get("start"),
        "end": t.get("end"),
    }


def answer(question: str) -> dict:
    question = question.strip()
    if not question:
        raise HTTPException(400, "ask a question")
    started = time.monotonic()
    hits = [
        h
        for h in recall(mem, question, container=CONTAINER, limit=8)
        if not is_narration(h["content"])
    ]
    by_memory = {m: c for c in clips.all().values() for m in c.get("memory_ids", [])}
    hits.sort(key=lambda h: h["date"])  # numbered in the order they happened
    lines = []
    for i, h in enumerate(hits, 1):
        clip = by_memory.get(h["memory_id"])
        at = datetime.fromisoformat(h["date"])
        lines.append(
            f"[{i}] {at:%A %d %B, %H:%M}"
            + (f" ({clip['title']})" if clip else "")
            + f": {h['content']}"
        )
    now = datetime.now()
    reply = llm.json_reply(
        temperature=0,
        messages=[
            {"role": "system", "content": ANSWER.format(now=f"{now:%A %d %B %Y, %H:%M}")},
            {
                "role": "user",
                "content": ("\n".join(lines) or "(memory recalled nothing)")
                + f"\n\nQuestion: {question}",
            },
        ],
    )
    text = str(reply.get("answer") or "").strip()
    changed = reply.get("changed_by")
    changed_clip = None
    if isinstance(changed, int) and 1 <= changed <= len(hits):
        changed_clip = (by_memory.get(hits[changed - 1]["memory_id"]) or {}).get("id")
    cited: dict[str, dict] = {}
    for n in reply.get("used") or []:
        if isinstance(n, int) and 1 <= n <= len(hits):
            hit = hits[n - 1]
            clip = by_memory.get(hit["memory_id"])
            if not clip:
                continue
            c = cited.setdefault(
                clip["id"],
                {
                    k: clip.get(k)
                    for k in ("id", "when", "title", "file", "duration", "speakers", "turns")
                }
                | {
                    "passages": [],
                    "moment": moment(clip, text, question),
                    "changed_it": clip["id"] == changed_clip,
                },
            )
            # the memories the answer rests on, as recalled from this clip
            if hit["content"] not in c["passages"]:
                c["passages"].append(hit["content"])
    was = str(reply.get("was") or "").strip() if changed_clip in cited else ""
    change = ""
    if changed_clip in cited:
        c = cited[changed_clip]
        who = (c["moment"] or {}).get("speaker")
        change = (
            f"{'You' if who == WEARER else who or 'Someone'} changed it at {c['when'][11:16]}"
            + (f", from {was}." if was else ".")
        )
    return {
        "question": question,
        "answer": text,
        "change": change,
        "was": was,
        "cited": sorted(cited.values(), key=lambda c: c["when"]),
        "recalled": [
            {**h, "clip": (by_memory.get(h["memory_id"]) or {}).get("title", "")} for h in hits
        ],
        "seconds": round(time.monotonic() - started, 2),
    }


DIARY = """You keep a diary for someone who wears a recording pendant. From the day's
conversations below (time, title, summary, to-dos), write the day's entry: two or three short
sentences, at most 40 words, second person, plain and warm, like a friend's note. Say what
mattered and what you owe people; skip small talk. Say only what the summaries and to-dos say:
a to-do is still to do, not done, and nothing was "good progress" unless a summary says so.
Times as "9:30". No heading, no list. Reply with JSON: {{"entry": "..."}}"""
DIARY_LOCK = threading.Lock()


def diary(day: str) -> dict:
    """The day's diary entry, written from its saved conversations' summaries and to-dos (the
    clip records, not memory) and kept until the day's conversations change."""
    day_clips = [c for c in clips.all().values() if c["when"].startswith(day)]
    if not day_clips or any(c["status"] not in ("saved", "error") for c in day_clips):
        return {"day": day, "entry": "", "ready": False}
    saved = sorted((c for c in day_clips if c["status"] == "saved"), key=lambda c: c["when"])
    key = ",".join(c["id"] for c in saved)
    path = mem.path / f"diary-{day}.json"
    with DIARY_LOCK:
        if path.is_file() and (kept := json.loads(path.read_text())).get("key") == key:
            return kept | {"ready": True}
        if not saved:
            return {"day": day, "entry": "", "ready": True}
        lines = [
            f"{c['when'][11:]} {c['title']}: {c['summary']} To-dos: "
            + "; ".join(
                f"{p.get('who')}: {p.get('what')} ({p.get('when') or 'no date'})"
                for p in c.get("commitments") or []
            )
            for c in saved
        ]
        out = llm.json_reply(
            [{"role": "system", "content": DIARY}, {"role": "user", "content": "\n".join(lines)}]
        )
        kept = {"day": day, "key": key, "entry": str(out.get("entry") or "").strip()}
        path.write_text(json.dumps(kept))
        return kept | {"ready": True}


# ---- routes -----------------------------------------------------------------------------


class Ask(BaseModel):
    question: str


@app.get("/api/clips")
def list_clips(date: str = "") -> dict:
    every = sorted(clips.all().values(), key=lambda c: c["when"])
    days = sorted({c["when"][:10] for c in every}, reverse=True)
    day = date or (days[0] if days else datetime.now().date().isoformat())
    return {
        "day": day,
        "days": days,
        "clips": [c for c in every if c["when"].startswith(day)],
        "sample": SAMPLE.is_file(),
    }


@app.post("/api/clips")
async def upload(audio: UploadFile = File(...), when: str = Form("")) -> dict:
    clip = new_clip(await audio.read(), audio.filename or "clip.webm", when)
    work.submit(process, clip["id"]).add_done_callback(_logged)
    return clip


SAMPLE = DATA / DEMO / "seed-audio" / "manifest.json"


@app.post("/api/sample-day")
def sample_day() -> dict:
    """The seeded day's four clips (made by `seed.py --audio-only`), added as today's."""
    if not SAMPLE.is_file():
        raise HTTPException(
            409, "no sample audio yet: run  uv run 16-wearable-diary/seed.py --audio-only"
        )
    today = datetime.now().date().isoformat()
    if any(c["when"].startswith(today) for c in clips.all().values()):
        raise HTTPException(409, "today already has clips: forget them first, or record your own")
    made = []
    for m in json.loads(SAMPLE.read_text()):
        path = SAMPLE.parent / Path(m["file"]).name
        made.append(new_clip(path.read_bytes(), path.name, f"{today}T{m['time']}"))
    for clip in made:
        work.submit(process, clip["id"]).add_done_callback(_logged)
    return {"clips": made}


@app.get("/api/clips/{clip_id}/audio")
def audio(clip_id: str) -> FileResponse:
    clip = clips.all().get(clip_id)
    if not clip:
        raise HTTPException(404, "no such clip")
    return FileResponse(CLIPS / clip["file"])


@app.post("/api/clips/{clip_id}/forget")
def forget(clip_id: str) -> dict:
    """The clip's memories are forgotten and its audio deleted."""
    clip = clips.all().get(clip_id)
    if not clip:
        raise HTTPException(404, "no such clip")
    if clip["status"] not in ("saved", "error"):
        raise HTTPException(409, f"this clip is still {clip['status']}")
    for memory_id in clip.get("memory_ids", []):
        mem.forget(memory_id)
    (CLIPS / clip["file"]).unlink(missing_ok=True)
    clips.drop(clip_id)
    return {"forgotten": clip_id, "memories": len(clip.get("memory_ids", []))}


@app.get("/api/diary")
def get_diary(date: str) -> dict:
    return diary(date)


@app.post("/api/ask")
def ask(body: Ask) -> dict:
    return answer(body.question)


if __name__ == "__main__":
    run(app, port=8716)
