"""
Live chat for a session, so Gemini can see how the audience reacted.

Messages come from one or more feeds:
- Twitch chat, read anonymously over IRC-over-WebSocket (no account needed)
- a demo script: JSON list of {"t": seconds_from_start, "user", "text"},
  replayed in real time (see backend/demo/)
- manual posts from the dashboard (POST /api/sessions/{id}/chat)

Every message is stamped with wall-clock time so it can be matched to the clip
and moment it reacts to.
"""

import asyncio
import json
import logging
import random
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

import websockets

log = logging.getLogger("chat")

TWITCH_IRC = "wss://irc-ws.chat.twitch.tv:443"
MAX_PROMPT_MESSAGES = 150


@dataclass
class ChatMessage:
    wall: float
    user: str
    text: str


class ChatLog:
    def __init__(self, on_message: Callable[[ChatMessage], Awaitable[None]]):
        self.messages: deque[ChatMessage] = deque(maxlen=5000)
        self.on_message = on_message
        self.tasks: list[asyncio.Task] = []

    async def add(self, user: str, text: str, wall: Optional[float] = None) -> None:
        msg = ChatMessage(wall or time.time(), user[:40], text[:300])
        self.messages.append(msg)
        await self.on_message(msg)

    def window(self, start: float, end: float) -> list[ChatMessage]:
        return [m for m in self.messages if start <= m.wall <= end]

    def active(self, within_seconds: float = 120) -> bool:
        return bool(self.messages) and time.time() - self.messages[-1].wall < within_seconds

    def start_twitch(self, url: str) -> bool:
        channel = twitch_channel(url)
        if channel:
            self.tasks.append(asyncio.create_task(self._twitch(channel)))
        return channel is not None

    def start_script(self, path: str) -> None:
        self.tasks.append(asyncio.create_task(self._script(path)))

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()

    async def _twitch(self, channel: str) -> None:
        backoff = 1
        while True:
            try:
                async with websockets.connect(TWITCH_IRC) as ws:
                    await ws.send("PASS SCHMOOPIIE")
                    await ws.send(f"NICK justinfan{random.randint(10000, 99999)}")
                    await ws.send(f"JOIN #{channel}")
                    log.info("joined twitch chat #%s", channel)
                    backoff = 1
                    async for raw in ws:
                        for line in str(raw).split("\r\n"):
                            if line.startswith("PING"):
                                await ws.send("PONG :tmi.twitch.tv")
                            elif " PRIVMSG " in line and line.startswith(":"):
                                user = line[1:line.index("!")] if "!" in line else "viewer"
                                text = line.split(" :", 1)[1] if " :" in line else ""
                                await self.add(user, text)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("twitch chat #%s disconnected: %s", channel, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _script(self, path: str) -> None:
        try:
            lines = sorted(json.loads(Path(path).read_text()), key=lambda m: m["t"])
        except Exception as exc:
            log.warning("could not load chat script %s: %s", path, exc)
            return
        start = time.time()
        for m in lines:
            await asyncio.sleep(max(0.0, start + float(m["t"]) - time.time()))
            await self.add(m.get("user", "viewer"), m["text"])


def twitch_channel(url: str) -> Optional[str]:
    try:
        u = urlparse(url)
    except ValueError:
        return None
    if not u.hostname or not u.hostname.endswith("twitch.tv"):
        return None
    parts = [p for p in u.path.split("/") if p]
    return parts[0].lower() if parts else None


def format_chat(messages: list[ChatMessage], origin: float, label: str) -> str:
    """Render chat for a prompt, with times relative to `origin` (e.g. clip start or the moment)."""
    if not messages:
        return f"Live chat {label}: (no messages)"
    shown = messages[-MAX_PROMPT_MESSAGES:]
    body = "\n".join(f"[{m.wall - origin:+.1f}s] {m.user}: {m.text}" for m in shown)
    return f"Live chat {label} ({len(messages)} messages):\n{body}"
