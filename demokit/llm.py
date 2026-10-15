"""Model calls: one OpenAI-compatible client for every demo (OpenAI, OpenRouter, vLLM, ...)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from functools import lru_cache

from openai import OpenAI

from . import config


@lru_cache(maxsize=1)
def client() -> OpenAI:
    config.require("OPENAI_API_KEY", "every demo calls a model")
    return OpenAI(base_url=os.environ.get("OPENAI_BASE_URL") or None)


def chat(messages: list[dict], *, model: str | None = None, temperature: float = 0.4) -> str:
    out = client().chat.completions.create(
        model=model or config.model(), messages=messages, temperature=temperature
    )
    return out.choices[0].message.content or ""


def stream(
    messages: list[dict], *, model: str | None = None, temperature: float = 0.4
) -> Iterator[str]:
    """Token deltas as they arrive."""
    for chunk in client().chat.completions.create(
        model=model or config.model(), messages=messages, temperature=temperature, stream=True
    ):
        if chunk.choices and (delta := chunk.choices[0].delta.content):
            yield delta


def json_reply(messages: list[dict], *, model: str | None = None, temperature: float = 0.2) -> dict:
    """A JSON object from the model; the prompt must ask for one."""
    out = client().chat.completions.create(
        model=model or config.model(),
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    return json.loads(out.choices[0].message.content or "{}")


def vision(prompt: str, image_data_url: str, *, model: str | None = None) -> str:
    """One question about one image (a `data:image/...;base64,` URL)."""
    out = client().chat.completions.create(
        model=model or os.environ.get("DEMO_VISION_MODEL") or config.model(),
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ],
    )
    return out.choices[0].message.content or ""


def transcribe(audio: bytes, filename: str) -> str:
    """Speech to text (OpenAI's transcription endpoint, or a compatible one)."""
    out = client().audio.transcriptions.create(
        model=os.environ.get("DEMO_TRANSCRIBE_MODEL") or "whisper-1", file=(filename, audio)
    )
    return out.text
