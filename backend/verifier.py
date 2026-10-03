"""
Second-pass verification of a single tip candidate, plus audience reaction.

Only moments that already passed the tip policy reach this step, so it is rare
and can afford a stronger model with a skeptical prompt. A tip is paid only if
this pass confirms the claimed moment.

The same call gets the live chat from just before to shortly after the moment,
so Gemini sees video, audio and chat together and scores how the audience
reacted; a strong reaction raises the tip.
"""

from typing import Optional

from google.genai import types

from . import config
from .gemini_analyzer import generate_json
from .models import Moment, Verification

VERIFY_PROMPT = """You are an auditor checking claims before a brand pays a streamer.
You are given a short livestream clip and ONE claimed moment. Be skeptical: confirm
only if the clip clearly shows or contains exactly what is claimed, performed by a
real, live person, with the stated sentiment. Reject if the evidence is ambiguous,
the drink is only in the background, the brand cannot be verified, the praise is
sarcastic, or the footage looks like a replay, an ad, or an animation.

You may also get the live chat around the moment (times relative to the moment).
Rate audience_reaction to THIS moment specifically:
- high: many viewers react to the drink/brand (e.g. spamming "W Gatorade", emotes about it)
- medium: a few viewers clearly react to it
- low: chat is active but barely notices
- none: no chat, or nobody reacts
Generic chatter unrelated to the drink does not count. Chat never confirms a moment by
itself; confirmation must come from the clip."""


async def verify_moment(data: bytes, mime_type: str, moment: Moment, chat: Optional[str] = None) -> Verification:
    claim = (
        f"Claimed moment at about {moment.offset_seconds:.1f}s into the clip:\n"
        f"- category: {moment.category.value}\n"
        f"- description: {moment.description}\n"
        f"- brand: {moment.brand or 'unknown'}\n"
        f"- quote: {moment.quote or 'none'}\n"
        f"- sentiment: {moment.sentiment.value}\n"
        f"- subject: {moment.subject_type.value}\n\n"
        f"{chat or 'Live chat: (none available)'}\n\n"
        "Is this claim accurate, and how did chat react?"
    )
    contents = [types.Part.from_bytes(data=data, mime_type=mime_type), claim]
    return await generate_json(config.GEMINI_VERIFY_MODEL, VERIFY_PROMPT, contents, Verification)
