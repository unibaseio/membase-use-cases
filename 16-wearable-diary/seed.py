"""A synthetic day as audio: four conversations, spoken by different synthetic voices.

    uv run 16-wearable-diary/seed.py               # make the audio, then put the day in the diary
    uv run 16-wearable-diary/seed.py --audio-only  # only make the audio (to upload it yourself)
    uv run 16-wearable-diary/seed.py --reset       # start over (deletes this demo's local memory)
    uv run 16-wearable-diary/seed.py --audio-only --reuse DIR   # copy clips made before from DIR

Text-to-speech does not always say the line it is given: a take once came out as "Okay, I guess
I'll bring the tape" in place of the promise to Sam. So each clip is transcribed after it is
made and made again (up to three times) until the lines the demo asks about can be heard in it.

Each line is spoken by the model's text-to-speech in the speaker's voice and the lines of one
conversation are joined into one WAV file, with the time it was "recorded" today. The wearer is
Alex; Priya, Marco, Jordan and Sam are made up. The files land in
data/16-wearable-diary/seed-audio/ and are reused on later runs.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from demokit import llm  # noqa: E402
from demokit.config import DATA  # noqa: E402

AUDIO = DATA / "16-wearable-diary" / "seed-audio"
VOICES = {"Alex": "echo", "Priya": "nova", "Marco": "onyx", "Jordan": "fable", "Sam": "shimmer"}

DAY = [
    (
        "09:30",
        "standup",
        [
            ("Priya", "Morning, everyone. Quick stand-up. Marco, you go first."),
            (
                "Marco",
                "Thanks, Priya. Yesterday I finished the export screen. Today I'm on the search "
                "bug. I'm blocked on the staging keys though. Alex, can you share them?",
            ),
            ("Alex", "Yes, Marco, I'll send you the staging keys right after this."),
            ("Priya", "Great. Alex, what about you?"),
            (
                "Alex",
                "I'm finishing the onboarding mockups. They'll be ready for the design review.",
            ),
            (
                "Priya",
                "Good. Reminder, everyone: the design review is on Thursday at three in the "
                "afternoon. Bring the onboarding flow and the new icons.",
            ),
            ("Marco", "Got it, Priya."),
        ],
    ),
    (
        "12:40",
        "lunch",
        [
            ("Alex", "Hey Jordan, mind if I sit with you?"),
            ("Jordan", "Sure! Alex, have you tried the new ramen place on Fifth Street yet?"),
            ("Alex", "Not yet. Is it any good?"),
            (
                "Jordan",
                "It's really good. Get the miso one. Oh, and my sister is visiting next weekend. "
                "She's a big hiker.",
            ),
            (
                "Alex",
                "Take her up Granite Ridge. The view at sunrise is amazing. And you should read "
                "Piranesi, the book I was telling you about.",
            ),
            ("Jordan", "Piranesi. Okay, I'm writing that down."),
        ],
    ),
    (
        "15:10",
        "hallway",
        [
            (
                "Priya",
                "Hey Alex, heads up. The design review got pushed to three thirty on Thursday, "
                "and it's in the Atlas room now.",
            ),
            ("Alex", "Three thirty in Atlas. Got it, thanks Priya."),
        ],
    ),
    (
        "17:15",
        "call-sam",
        [
            ("Sam", "Hey Alex, it's Sam. Are you around on Saturday?"),
            ("Alex", "Hi Sam! Yes, what's up?"),
            ("Sam", "I'm moving flats on Saturday and the man with the van just cancelled on me."),
            (
                "Alex",
                "Oh no. Okay, I promise I'll be at yours at nine with my car to help carry the "
                "boxes. I'll bring the tape and the trolley too.",
            ),
            ("Sam", "You're a lifesaver. And could you send me the photos from the lake trip?"),
            ("Alex", "I'll send them tonight."),
            ("Sam", "Thanks, Alex. See you Saturday at nine."),
        ],
    ),
]


#: What must be heard in each clip for the demo's questions to have an answer.
MUST_HEAR = {
    "standup": [r"design review", r"thursday at (three|3)\b"],
    "lunch": [r"ramen"],
    "hallway": [r"(three|3)[ .:]?(thirty|30)", r"atlas"],
    "call-sam": [r"i promise", r"\b(nine|9)\b", r"\bcar\b"],
}


def heard(slug: str, audio: bytes) -> list[str]:
    """The MUST_HEAR phrases the transcriber cannot find in a clip."""
    text = llm.transcribe(audio, f"{slug}.wav").lower()
    return [p for p in MUST_HEAR.get(slug, []) if not re.search(p, text)]


def speak(speaker: str, text: str) -> bytes:
    out = llm.client().audio.speech.create(
        model="gpt-4o-mini-tts", voice=VOICES[speaker], input=text, response_format="wav"
    )
    return out.content


def join_wavs(parts: list[bytes], gap: float = 0.45) -> bytes:
    """One WAV from several (same format), with a short silence between turns."""
    frames, params = [], None
    for p in parts:
        with wave.open(io.BytesIO(p)) as w:
            params = params or w.getparams()
            frames.append(w.readframes(w.getnframes()))
    silence = b"\0" * int(params.framerate * gap) * params.sampwidth * params.nchannels
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        # Not setparams: streamed TTS WAVs carry a placeholder frame count.
        w.setnchannels(params.nchannels)
        w.setsampwidth(params.sampwidth)
        w.setframerate(params.framerate)
        w.writeframes(silence.join(frames))
    return buf.getvalue()


def make_audio(reuse: Path | None = None) -> list[dict]:
    """The day's clips as WAV files; reuses what an earlier run made (or what is in `reuse`).
    Returns the manifest."""
    AUDIO.mkdir(parents=True, exist_ok=True)
    manifest = []
    for hhmm, slug, lines in DAY:
        path = AUDIO / f"{hhmm.replace(':', '')}-{slug}.wav"
        if not path.is_file() and reuse and (reuse / path.name).is_file():
            shutil.copyfile(reuse / path.name, path)
        if not path.is_file():
            for _attempt in range(3):
                with ThreadPoolExecutor(max_workers=6) as pool:
                    parts = list(pool.map(lambda line: speak(*line), lines))
                audio = join_wavs(parts)
                missing = heard(slug, audio)
                if not missing:
                    break
                print(f"  {path.name}: the speech lost {missing}; making it again")
            else:
                sys.exit(f"{path.name}: text-to-speech kept losing {missing}")
            path.write_bytes(audio)
        manifest.append(
            {"time": hhmm, "file": str(path), "speakers": sorted({s for s, _ in lines})}
        )
    (AUDIO / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--audio-only", action="store_true", help="make the audio files and stop")
    p.add_argument("--reset", action="store_true", help="delete this demo's local memory first")
    p.add_argument("--reuse", type=Path, help="a folder of clips made before, to copy instead")
    a = p.parse_args()

    started = time.monotonic()
    manifest = make_audio(a.reuse)
    print(
        f"{len(manifest)} clips of synthetic speech in {AUDIO} ({time.monotonic() - started:.0f}s)"
    )
    if a.audio_only:
        return
    if a.reset:
        shutil.rmtree(DATA / "16-wearable-diary" / "me", ignore_errors=True)
    sys.path.insert(0, str(HERE))
    import app as demo  # noqa: PLC0415 - after any reset

    if demo.clips.all():
        sys.exit(f"{demo.clips.path} already has clips: run with --reset to start over")
    today = datetime.now().date().isoformat()
    started = time.monotonic()
    made = [
        demo.new_clip(Path(m["file"]).read_bytes(), Path(m["file"]).name, f"{today}T{m['time']}")
        for m in manifest
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        done = list(pool.map(lambda c: demo.process(c["id"]), made))
    for c in done:
        print(f"  {c['when'][11:]}  {c['title']:<36} {', '.join(c['speakers'])}")
    print(f"{len(done)} conversations in memory in {time.monotonic() - started:.0f}s")


if __name__ == "__main__":
    main()
