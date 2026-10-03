"""
Event sink: fan-out of pipeline output.

- WebSocket broadcast to every connected dashboard (events, chunk statuses,
  session updates).
- Append tip-worthy events to events.jsonl (a durable local record).
- POST tip-worthy events to EVENT_WEBHOOK_URL, the handoff point for the
  Supabase + Stripe teammates. Payload is exactly `BeverageEvent`.
"""

import asyncio
import json
import logging
from typing import Any

import httpx
from fastapi import WebSocket

from . import config
from .models import BeverageEvent

log = logging.getLogger("event_sink")


class EventSink:
    def __init__(self) -> None:
        self.sockets: set[WebSocket] = set()
        self.recent: list[dict[str, Any]] = []
        self.http = httpx.AsyncClient(timeout=10)

    async def broadcast(self, msg: dict[str, Any]) -> None:
        if msg["type"] == "event":
            event_id = msg["data"]["event_id"]
            self.recent = ([m for m in self.recent if m["data"]["event_id"] != event_id] + [msg])[-200:]
        text = json.dumps(msg)
        dead = []
        for ws in self.sockets:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.sockets.discard(ws)

    async def emit_tip(self, event: BeverageEvent) -> None:
        payload = event.model_dump(mode="json")
        with open(config.EVENTS_LOG, "a") as f:
            f.write(json.dumps(payload) + "\n")
        if config.EVENT_WEBHOOK_URL:
            asyncio.create_task(self._post(payload))

    async def _post(self, payload: dict[str, Any]) -> None:
        try:
            r = await self.http.post(config.EVENT_WEBHOOK_URL, json=payload)
            log.info("webhook %s -> %s", payload["event_id"], r.status_code)
        except Exception as exc:
            log.warning("webhook failed: %s", exc)


sink = EventSink()
