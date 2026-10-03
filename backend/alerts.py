"""
Demo-mode thank-you alerts: the multimodal output side of the pipeline.

When a tip is confirmed on a session created with demo_alerts=true:
1. Gemini writes a short stream-alert line from the event.
2. Gemini TTS speaks it (WAV).
3. Gemini image generation turns the evidence thumbnail into a thank-you card.

Real streams have their own donation alerts, so this is only for demo videos.
"""

import io
import logging
import wave
from typing import Optional

from google.genai import types

from . import config
from .evidence import path_for
from .gemini_analyzer import client
from .models import BeverageEvent

log = logging.getLogger("alerts")

MESSAGE_PROMPT = """Write ONE hype livestream alert line (max 20 words) announcing that
{brand} just tipped the streamer. Mention the amount and, playfully, what the streamer
did. No hashtags, no emojis, no quotes around it."""


def _dollars(cents: int) -> str:
    return f"${cents / 100:.2f}".replace(".00", "")


async def write_message(event: BeverageEvent) -> str:
    facts = (f"Amount: {_dollars(event.suggested_tip_cents)}\nWhat happened: {event.description}\n"
             f"Quote: {event.quote or 'none'}\nChat reaction: {event.reaction_summary or 'unknown'}")
    resp = await client().aio.models.generate_content(
        model=config.GEMINI_TEXT_MODEL,
        contents=facts,
        config=types.GenerateContentConfig(
            system_instruction=MESSAGE_PROMPT.format(brand=config.SPONSOR_BRAND), temperature=0.9),
    )
    text = (resp.text or "").strip().strip('"')
    return text or f"{config.SPONSOR_BRAND} just tipped you {_dollars(event.suggested_tip_cents)}!"


def _to_wav(data: bytes, mime_type: str) -> bytes:
    if "wav" in mime_type:
        return data
    # Older TTS models return raw 16-bit mono PCM, e.g. "audio/L16;rate=24000".
    rate = 24000
    for part in mime_type.split(";"):
        if part.strip().startswith("rate="):
            rate = int(part.split("=")[1])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data)
    return buf.getvalue()


async def speak(event: BeverageEvent, message: str) -> str:
    resp = await client().aio.models.generate_content(
        model=config.GEMINI_TTS_MODEL,
        contents=f"Read this like an excited livestream donation alert: {message}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config.TTS_VOICE))),
        ),
    )
    audio = resp.candidates[0].content.parts[0].inline_data
    url = f"/evidence/{event.session_id}/{event.event_id}_alert.wav"
    path_for(url).write_bytes(_to_wav(audio.data, audio.mime_type or ""))
    return url


async def make_card(event: BeverageEvent, message: str) -> Optional[str]:
    if not event.thumbnail_url:
        return None
    thumb = path_for(event.thumbnail_url).read_bytes()
    prompt = (f"Turn this livestream frame into a bold, shareable square thank-you card from "
              f"{config.SPONSOR_BRAND}. Keep the streamer recognizable. Add the headline "
              f"\"Thanks for staying hydrated!\" and the line \"{message}\". "
              f"Energetic sports-drink branding, clean readable text.")
    resp = await client().aio.models.generate_content(
        model=config.GEMINI_IMAGE_MODEL,
        contents=[types.Part.from_bytes(data=thumb, mime_type="image/jpeg"), prompt],
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )
    for part in resp.candidates[0].content.parts:
        if part.inline_data and (part.inline_data.mime_type or "").startswith("image/"):
            ext = "png" if "png" in part.inline_data.mime_type else "jpg"
            url = f"/evidence/{event.session_id}/{event.event_id}_card.{ext}"
            path_for(url).write_bytes(part.inline_data.data)
            return url
    log.warning("image model returned no image for %s", event.event_id)
    return None
