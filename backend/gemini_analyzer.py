"""
Gemini video understanding for short livestream clips.

Each clip (mp4 from the URL pipeline or webm from the browser) is sent inline
to Gemini with a JSON response schema. The model watches the video AND listens
to the audio, so it catches both visual moments (sipping water, holding a
bottle) and spoken mentions ("this Gatorade hits different"). Alongside the
moments it reports sponsor/competitor screen time, brand-safety flags,
anti-gaming signals, and a one-line summary that is fed into the next clip.

Transient errors (503 overloaded, 429 rate limit) are retried with exponential
backoff.

CLI test:  python -m backend.gemini_analyzer path/to/clip.mp4
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import sys
import time
from typing import Optional, TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from . import config
from .models import ClipAnalysis

log = logging.getLogger("gemini")

T = TypeVar("T", bound=BaseModel)


def build_prompt(sponsor: str, competitors: list[str]) -> str:
    return f"""You are a marketing analyst for {sponsor}, a sports drink brand.
You watch short clips from a livestream (video + audio) and report every moment
where the streamer does something beverage-related, so {sponsor} can tip them.
Known competitor brands: {", ".join(competitors) or "none"}.

MOMENTS. Report a moment for any of these categories:
- sports_drink_mention: streamer names or talks about a sports/energy drink ({sponsor} or any competitor)
- drinking_water: streamer visibly drinks water
- drinking_other: streamer visibly drinks any other beverage
- holding_or_showing_beverage: streamer holds, shows off, or points at a drink/bottle/can/cup without drinking
- verbal_beverage_mention: streamer talks about drinks, hydration, being thirsty, etc. without naming a sports drink

For each moment also report:
- sentiment: the streamer's attitude toward the drink. positive (enjoys/recommends it),
  neutral (just drinks or mentions it), negative (dislikes it), sarcastic (praise that is
  clearly ironic or mocking). Silent drinking is usually neutral.
- subject_type: real_person (a live human streamer on camera), animated_character
  (cartoon, VTuber model, illustration, game character), or video_playback (the streamer
  is playing someone else's video, an ad, or a clip on screen).
- looks_staged: true if the moment looks forced, exaggerated, or performed purely to
  trigger a reward (e.g. holding a can up to the camera repeatedly with no context).
- brand: name it only if visible or spoken, else null. Use the plain brand name (e.g. "Gatorade", "Prime").
- quote: exact spoken words if the moment involves speech, else null.
- offset_seconds: when the moment starts, relative to the clip start.
- confidence: 0.0-1.0; be calibrated.

BRAND EXPOSURE. For every beverage brand whose logo or product is visible at any point,
report visible_seconds (total seconds visible in this clip, at most the clip length) and
prominence:
- high: label clearly readable, facing the camera, near the center or held up
- medium: recognizable but partly turned, small, or off-center
- low: barely visible, in a corner, blurry, or mostly hidden
Background products count for exposure even though they are not moments.

SAFETY. Set each flag true only if it clearly appears in this clip: alcohol (drinking or
showing alcohol), vaping (vaping or smoking), nsfw (sexual content or nudity), slurs
(hate speech or slurs), gambling (casino, betting, or gambling sites). Put a short note in
notes when any flag is true.

SUBJECT. on_screen_subject: the main subject of the clip, using the same subject_type values.

LIVENESS. looks_prerecorded_or_looped: true if the footage looks like a rerun, a loop,
or a recording rather than a live broadcast.

SUMMARY. clip_summary: one sentence describing what happens in this clip; it will be
given to you as context for the next clip.

CHAT. You may also get the live chat messages posted during the clip (times relative to the
clip start). Use them as context only (e.g. chat asking "what are you drinking?"); a moment
must still be visible or audible in the clip itself.

Rules:
- Only report what actually happens in THIS clip. Do not guess.
- A bottle merely sitting on the desk in the background is NOT a moment (but it is exposure).
- If a moment clearly continues from the previous clip's summary (same sip, same sentence),
  do not report it again.
- If nothing beverage-related happens, return detected=false and an empty moments list."""


_client: genai.Client | None = None


def client() -> genai.Client:
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set (put it in backend/.env)")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, errors.APIError):
        return exc.code in (429, 500, 502, 503, 504)
    return isinstance(exc, (TimeoutError, ConnectionError))


async def generate_json(model: str, system: str, contents: list, schema: type[T]) -> T:
    """Call Gemini with a response schema, retrying transient errors."""
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.2,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    for attempt in range(config.GEMINI_MAX_RETRIES + 1):
        started = time.monotonic()
        log.info("generate_content model=%s schema=%s attempt=%d", model, schema.__name__, attempt)
        try:
            resp = await client().aio.models.generate_content(model=model, contents=contents, config=cfg)
        except Exception as exc:
            if attempt < config.GEMINI_MAX_RETRIES and _is_retryable(exc):
                delay = (2 ** attempt) + random.random()
                log.warning("Gemini error %s, retrying in %.1fs", exc, delay)
                await asyncio.sleep(delay)
                continue
            raise

        log.info("gemini output (%.0f ms): %s", (time.monotonic() - started) * 1000, resp.text)
        if isinstance(resp.parsed, schema):
            return resp.parsed
        return schema.model_validate_json(resp.text or "{}")

    raise RuntimeError("unreachable")


async def analyze_clip(data: bytes, mime_type: str, previous_summary: Optional[str] = None,
                       chat: Optional[str] = None) -> ClipAnalysis:
    """Send one clip (video + audio, plus live chat text if any) to Gemini."""
    context = f"Previous clip: {previous_summary}\n\n" if previous_summary else ""
    if chat:
        context += f"{chat}\n\n"
    contents = [
        types.Part.from_bytes(data=data, mime_type=mime_type),
        f"{context}Analyze this livestream clip.",
    ]
    system = build_prompt(config.SPONSOR_BRAND, config.COMPETITOR_BRANDS)
    return await generate_json(config.GEMINI_MODEL, system, contents, ClipAnalysis)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def matches_brand(name: Optional[str], brand: str) -> bool:
    if not name:
        return False
    a, b = _norm(name), _norm(brand)
    return bool(a and b) and (a in b or b in a)


def is_sponsor(name: Optional[str]) -> bool:
    return matches_brand(name, config.SPONSOR_BRAND)


def is_competitor(name: Optional[str]) -> bool:
    return not is_sponsor(name) and any(matches_brand(name, c) for c in config.COMPETITOR_BRANDS)


def mime_for(path: str) -> str:
    if path.endswith(".webm"):
        return "video/webm"
    if path.endswith(".mov"):
        return "video/quicktime"
    return "video/mp4"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) != 2:
        sys.exit("usage: python -m backend.gemini_analyzer <clip.mp4>")
    path = sys.argv[1]
    with open(path, "rb") as f:
        result = asyncio.run(analyze_clip(f.read(), mime_for(path)))
    print(result.model_dump_json(indent=2))
