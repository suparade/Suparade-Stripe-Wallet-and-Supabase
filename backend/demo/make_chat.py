"""
Generate a realistic, timed demo chat script for a recorded demo video.

Gemini watches the video (video + audio) and writes the chat a live audience
would post, reacting at the right moments. Replay it with the video by passing
the output path as `chat_script` when creating the session.

Usage:  python -m backend.demo.make_chat demo.mp4 backend/demo/chat_demo.json
"""

import asyncio
import json
import sys

from google.genai import types
from pydantic import BaseModel, Field

from .. import config
from ..gemini_analyzer import generate_json, mime_for

PROMPT = """You write the live Twitch chat for a recorded stream, for a product demo.
Watch the video and listen to the audio, then write the chat a real audience would post:
about one message per second, short, casual, lowercase-heavy, with Twitch slang and
emote names (LUL, PogChamp, KEKW). Use 8-15 recurring usernames.
When the streamer drinks, shows, or talks about a drink, chat should notice and react
within a few seconds (e.g. "W {brand}", "hydration check"), more if the streamer is
enthusiastic. Otherwise chat talks about whatever is happening on stream.
t is seconds from the start of the video."""


class Line(BaseModel):
    t: float
    user: str
    text: str = Field(description="One chat message")


class Script(BaseModel):
    messages: list[Line]


async def main(video: str, out: str) -> None:
    data = open(video, "rb").read()
    contents = [types.Part.from_bytes(data=data, mime_type=mime_for(video)), "Write the chat for this video."]
    script = await generate_json(config.GEMINI_MODEL, PROMPT.format(brand=config.SPONSOR_BRAND), contents, Script)
    lines = sorted((m.model_dump() for m in script.messages), key=lambda m: m["t"])
    with open(out, "w") as f:
        json.dump(lines, f, indent=1)
    print(f"wrote {len(lines)} messages to {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -m backend.demo.make_chat <video> <out.json>")
    asyncio.run(main(sys.argv[1], sys.argv[2]))
