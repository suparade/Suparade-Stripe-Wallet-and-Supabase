"""
Session manager: one session per stream being watched.

Each session owns a source (URL or browser) and a chunk queue. A worker
analyzes chunks in order, one at a time, so each clip can be given the previous
clip's summary as context. If the backlog grows past MAX_BACKLOG, the oldest
chunks are skipped so analysis stays close to live.

Per clip:
- sponsor screen time is accumulated; enough prominent exposure earns a
  `sponsor_screen_time` bonus event
- moments below CONFIDENCE_THRESHOLD are dropped
- every other moment goes through tip_policy; candidates are re-checked by the
  verifier in the background and only paid if confirmed
- brand-safety flags are counted and broadcast as alerts

Live chat (Twitch, a demo script, or manual posts) is sent with each clip, and
the verifier waits CHAT_REACTION_SECONDS after a moment so it can score how
chat reacted. Paid events are then enriched in the background with product
bounding boxes and, for demo sessions, a spoken thank-you alert and card.

Paying: a confirmed tip goes to the payments API (app/ in this repo), which
logs it in Supabase, checks the campaign budget and sends a Stripe transfer to
the streamer's connected account (see payments.py).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from uuid import uuid4

from . import alerts, config, payments, tip_policy
from .chat import ChatLog, ChatMessage, format_chat, twitch_channel
from .event_sink import sink
from .evidence import detect_boxes, save_evidence
from .gemini_analyzer import analyze_clip, is_competitor, is_sponsor, matches_brand
from .models import BeverageEvent, ChunkStatus, ClipAnalysis, EventCategory, Moment
from .sources import Chunk
from .sources.browser_source import BrowserSource
from .sources.url_source import UrlSource
from .verifier import verify_moment

log = logging.getLogger("session")


@dataclass
class Session:
    id: str
    source_type: str
    streamer_id: str
    url: Optional[str]
    demo_alerts: bool = False
    chat: Optional[ChatLog] = None
    chat_feeds: list = field(default_factory=list)
    source: UrlSource | BrowserSource | None = None
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    worker: Optional[asyncio.Task] = None
    tasks: set = field(default_factory=set)
    tip_state: tip_policy.TipState = field(default_factory=tip_policy.TipState)
    previous_summary: Optional[str] = None
    exposure_by_brand: dict = field(default_factory=dict)  # brand -> {"seconds", "weighted_seconds"}
    safety_counts: dict = field(default_factory=dict)
    competitor_mentions: int = 0
    tips_cents: int = 0
    chunks_analyzed: int = 0
    chunks_skipped: int = 0
    events_detected: int = 0
    started_at: float = field(default_factory=time.time)

    def summary(self) -> dict:
        sponsor = self.exposure_by_brand.get(config.SPONSOR_BRAND, {})
        return {
            "id": self.id,
            "source": self.source_type,
            "streamer_id": self.streamer_id,
            "url": self.url,
            "chunks_analyzed": self.chunks_analyzed,
            "chunks_skipped": self.chunks_skipped,
            "events_detected": self.events_detected,
            "source_exited": bool(self.source and self.source.exited),
            "exit_reason": self.source.exit_reason if self.source else None,
            "started_at": self.started_at,
            "sponsor_brand": config.SPONSOR_BRAND,
            "sponsor_screen_seconds": round(sponsor.get("seconds", 0.0), 1),
            "sponsor_weighted_seconds": round(sponsor.get("weighted_seconds", 0.0), 1),
            "exposure_by_brand": {b: {k: round(v, 1) for k, v in e.items()}
                                  for b, e in self.exposure_by_brand.items()},
            "competitor_mentions": self.competitor_mentions,
            "safety_counts": self.safety_counts,
            "tips_cents": self.tips_cents,
            "demo_alerts": self.demo_alerts,
            "chat_feeds": self.chat_feeds,
            "chat_messages": len(self.chat.messages) if self.chat else 0,
            "local_file": bool(self.url and Path(self.url).is_file()),
        }


def _canonical_brand(name: str) -> str:
    if is_sponsor(name):
        return config.SPONSOR_BRAND
    for c in config.COMPETITOR_BRANDS:
        if matches_brand(name, c):
            return c
    return name.strip()


class SessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}

    async def create(self, source_type: str, streamer_id: str, url: Optional[str],
                     demo_alerts: bool = False, chat_script: Optional[str] = None) -> Session:
        s = Session(id=uuid4().hex[:12], source_type=source_type, streamer_id=streamer_id, url=url,
                    demo_alerts=demo_alerts)

        async def enqueue(chunk: Chunk) -> None:
            await s.queue.put(chunk)

        async def on_chat(msg: ChatMessage) -> None:
            await sink.broadcast({"type": "chat", "data": {
                "session_id": s.id, "user": msg.user, "text": msg.text, "at": msg.wall}})

        s.chat = ChatLog(on_chat)
        if chat_script:
            if not Path(chat_script).is_file():
                raise ValueError(f"chat script not found: {chat_script}")
            s.chat_feeds.append("script")
        if config.TWITCH_CHAT and url and twitch_channel(url):
            s.chat_feeds.append("twitch")

        if source_type == "url":
            if not url:
                raise ValueError("url is required for source=url")
            s.source = UrlSource(s.id, url, enqueue)
        else:
            s.source = BrowserSource(s.id, enqueue)

        await s.source.start()
        if "twitch" in s.chat_feeds:
            s.chat.start_twitch(url)
        if chat_script:
            s.chat.start_script(chat_script)
        s.worker = asyncio.create_task(self._work(s))
        self._spawn(s, self._watch_source(s))
        self.sessions[s.id] = s
        await sink.broadcast({"type": "session", "data": s.summary()})
        log.info("session %s started source=%s url=%s", s.id, source_type, url)
        return s

    async def stop(self, session_id: str) -> None:
        s = self.sessions.pop(session_id, None)
        if not s:
            return
        if s.source:
            await s.source.stop()
        if s.chat:
            await s.chat.stop()
        if s.worker:
            s.worker.cancel()
        for t in list(s.tasks):
            t.cancel()
        await sink.broadcast({"type": "session_stopped", "data": {"id": session_id}})

    def _spawn(self, s: Session, coro) -> None:
        t = asyncio.create_task(coro)
        s.tasks.add(t)
        t.add_done_callback(s.tasks.discard)

    async def _work(self, s: Session) -> None:
        while True:
            chunk = await s.queue.get()
            while s.queue.qsize() > config.MAX_BACKLOG:
                s.chunks_skipped += 1
                status = ChunkStatus(session_id=s.id, chunk_index=chunk.index,
                                     stream_offset_seconds=chunk.stream_offset_seconds, status="skipped")
                await sink.broadcast({"type": "chunk", "data": status.model_dump(mode="json")})
                chunk = s.queue.get_nowait()
            try:
                await self._analyze(s, chunk)
            except Exception:
                log.exception("chunk %s/%d processing failed", s.id, chunk.index)

    async def _watch_source(self, s: Session) -> None:
        await s.source.wait_exited()
        await sink.broadcast({"type": "session", "data": s.summary()})

    async def _analyze(self, s: Session, chunk: Chunk) -> None:
        status = ChunkStatus(session_id=s.id, chunk_index=chunk.index,
                             stream_offset_seconds=chunk.stream_offset_seconds, status="analyzing")
        await sink.broadcast({"type": "chunk", "data": status.model_dump(mode="json")})
        started = time.monotonic()
        clip_start = chunk.wall_end - config.CHUNK_SECONDS
        chat = None
        if s.chat and s.chat.messages:
            msgs = s.chat.window(clip_start - config.CHAT_CONTEXT_SECONDS, time.time())
            chat = format_chat(msgs, clip_start, "during this clip")
        try:
            result = await analyze_clip(chunk.data, chunk.mime_type, s.previous_summary, chat)
        except Exception as exc:
            log.exception("chunk %s/%d failed", s.id, chunk.index)
            status.status = "error"
            status.error = str(exc)[:300]
            status.latency_ms = int((time.monotonic() - started) * 1000)
            await sink.broadcast({"type": "chunk", "data": status.model_dump(mode="json")})
            return

        s.chunks_analyzed += 1
        s.previous_summary = result.clip_summary
        moments = [m for m in result.moments if m.confidence >= config.CONFIDENCE_THRESHOLD]
        flags = result.safety.active()
        status.latency_ms = int((time.monotonic() - started) * 1000)
        status.moments_found = len(moments)
        status.status = "detected" if moments else "nothing_found"
        status.safety_flags = flags
        status.summary = result.clip_summary
        await sink.broadcast({"type": "chunk", "data": status.model_dump(mode="json")})

        if flags:
            for f in flags:
                s.safety_counts[f] = s.safety_counts.get(f, 0) + 1
            await sink.broadcast({"type": "safety", "data": {
                "session_id": s.id, "streamer_id": s.streamer_id, "flags": flags,
                "notes": result.safety.notes, "stream_offset_seconds": chunk.stream_offset_seconds,
            }})

        await self._exposure(s, chunk, result)

        for m in sorted(moments, key=lambda m: m.offset_seconds):
            await self._moment(s, chunk, result, m)

        await sink.broadcast({"type": "session", "data": s.summary()})

    async def _exposure(self, s: Session, chunk: Chunk, result: ClipAnalysis) -> None:
        sponsor_seconds = sponsor_weighted = 0.0
        for e in result.brand_exposures:
            secs = max(0.0, min(e.visible_seconds, float(config.CHUNK_SECONDS)))
            weighted = secs * config.PROMINENCE_WEIGHTS.get(e.prominence.value, 0.0)
            brand = _canonical_brand(e.brand)
            totals = s.exposure_by_brand.setdefault(brand, {"seconds": 0.0, "weighted_seconds": 0.0})
            totals["seconds"] += secs
            totals["weighted_seconds"] += weighted
            if brand == config.SPONSOR_BRAND:
                sponsor_seconds += secs
                sponsor_weighted += weighted
        sponsor_seconds = min(sponsor_seconds, float(config.CHUNK_SECONDS))
        sponsor_weighted = min(sponsor_weighted, float(config.CHUNK_SECONDS))
        if sponsor_weighted < config.MIN_EXPOSURE_SECONDS:
            return

        blocks = tip_policy.evaluate_exposure(result)
        event = BeverageEvent(
            session_id=s.id,
            streamer_id=s.streamer_id,
            category=EventCategory.sponsor_screen_time,
            confidence=1.0,
            description=f"{config.SPONSOR_BRAND} on screen for {sponsor_seconds:.0f}s "
                        f"({sponsor_weighted:.1f}s prominence-weighted)",
            brand=config.SPONSOR_BRAND,
            stream_offset_seconds=round(chunk.stream_offset_seconds, 1),
            suggested_tip_cents=round(sponsor_weighted * config.EXPOSURE_CENTS_PER_SECOND),
            subject_type=result.on_screen_subject,
            is_sponsor=True,
            block_reasons=blocks,
            exposure_seconds=round(sponsor_seconds, 1),
        )
        if blocks:
            await self._publish(event)
        else:
            # In the background so a slow payment never delays the next clip's analysis.
            self._spawn(s, self._pay(s, chunk, event, config.CHUNK_SECONDS / 2))

    async def _moment(self, s: Session, chunk: Chunk, result: ClipAnalysis, m: Moment) -> None:
        offset = chunk.stream_offset_seconds + max(0.0, m.offset_seconds)
        competitor = is_competitor(m.brand)
        if competitor:
            s.competitor_mentions += 1
        blocks = tip_policy.evaluate(m, result, offset, s.tip_state, competitor)
        event = BeverageEvent(
            session_id=s.id,
            streamer_id=s.streamer_id,
            category=EventCategory(m.category.value),
            confidence=round(m.confidence, 3),
            description=m.description,
            quote=m.quote,
            brand=m.brand,
            stream_offset_seconds=round(offset, 1),
            suggested_tip_cents=config.TIP_CENTS_BY_CATEGORY.get(m.category.value, 0),
            sentiment=m.sentiment,
            subject_type=m.subject_type,
            is_sponsor=is_sponsor(m.brand),
            is_competitor=competitor,
            block_reasons=blocks,
        )
        s.events_detected += 1
        if blocks:
            await self._publish(event)
            return

        reservation = tip_policy.reserve(s.tip_state, m, offset)
        if not config.VERIFY_ENABLED:
            self._spawn(s, self._pay(s, chunk, event, m.offset_seconds, reservation))
            return
        event.status = "pending_verification"
        await self._publish(event)
        self._spawn(s, self._verify_and_pay(s, chunk, m, event, reservation))

    async def _verify_and_pay(self, s: Session, chunk: Chunk, m: Moment, event: BeverageEvent,
                              reservation: tuple) -> None:
        moment_wall = chunk.wall_end - config.CHUNK_SECONDS + max(0.0, m.offset_seconds)
        chat = None
        if s.chat and s.chat.active():
            await asyncio.sleep(max(0.0, moment_wall + config.CHAT_REACTION_SECONDS - time.time()))
            msgs = s.chat.window(moment_wall - config.CHAT_CONTEXT_SECONDS,
                                 moment_wall + config.CHAT_REACTION_SECONDS)
            chat = format_chat(msgs, moment_wall, "around the moment")
        try:
            v = await verify_moment(chunk.data, chunk.mime_type, m, chat)
            confirmed = v.confirmed and v.confidence >= config.CONFIDENCE_THRESHOLD
            event.verification_reason = v.reason
            if chat:
                event.audience_reaction = v.audience_reaction
                event.reaction_summary = v.reaction_summary
                event.chat_highlights = v.chat_highlights[:3]
                event.reaction_multiplier = config.REACTION_TIP_MULTIPLIERS.get(v.audience_reaction.value, 1.0)
                event.suggested_tip_cents = round(event.suggested_tip_cents * event.reaction_multiplier)
        except Exception as exc:
            log.exception("verification failed for %s", event.event_id)
            confirmed = False
            event.verification_reason = f"verification error: {str(exc)[:200]}"
        if confirmed:
            await self._pay(s, chunk, event, m.offset_seconds, reservation)
        else:
            tip_policy.release(s.tip_state, reservation)
            event.status = "rejected_by_verifier"
            await self._publish(event)
        await sink.broadcast({"type": "session", "data": s.summary()})

    async def _pay(self, s: Session, chunk: Chunk, event: BeverageEvent, offset_in_clip: float,
                   reservation: Optional[tuple] = None) -> None:
        """Pay a confirmed tip through the payments API (Supabase + Stripe), then enrich it.

        The dashboard sees the event go "paying" -> "tipped" (with the Stripe transfer id) or
        "payment_failed" (with the reason, e.g. insufficient_budget). A failed payment releases
        the tip-policy slot so the next real moment can still be paid.
        """
        try:
            event.clip_url, event.thumbnail_url = await save_evidence(
                s.id, event.event_id, chunk.data, chunk.mime_type, offset_in_clip)
        except Exception:
            log.exception("saving evidence failed for %s", event.event_id)

        cap = await payments.max_tip_cents()
        if cap is not None and event.suggested_tip_cents > cap:
            event.requested_tip_cents = event.suggested_tip_cents
            event.suggested_tip_cents = cap

        # Demo sessions: write the thank-you line first so it is also the on-screen tip message.
        if s.demo_alerts and event.category != EventCategory.sponsor_screen_time and not event.alert_message:
            try:
                event.alert_message = await alerts.write_message(event)
            except Exception:
                log.exception("writing thank-you message failed for %s", event.event_id)

        event.status = "paying"
        await self._publish(event)
        result = await payments.pay(event, s.url)
        payments.apply(event, result)

        if not result.ok:
            event.status = "payment_failed"
            if reservation:
                tip_policy.release(s.tip_state, reservation)
            await self._publish(event)
            return

        event.status = "tipped"
        s.tips_cents += event.suggested_tip_cents
        await sink.emit_tip(event)
        await self._publish(event)
        await sink.broadcast({"type": "session", "data": s.summary()})
        self._spawn(s, self._enrich(s, event))

    async def _enrich(self, s: Session, event: BeverageEvent) -> None:
        """Multimodal follow-ups on a paid event; each step re-publishes the event."""
        if config.BOXES_ENABLED and event.thumbnail_url:
            try:
                event.boxes = await detect_boxes(event.thumbnail_url, config.SPONSOR_BRAND)
                await self._publish(event)
            except Exception:
                log.exception("box detection failed for %s", event.event_id)

        if not s.demo_alerts or event.category == EventCategory.sponsor_screen_time:
            return
        try:
            if not event.alert_message:
                event.alert_message = await alerts.write_message(event)
            card = asyncio.create_task(alerts.make_card(event, event.alert_message)) if config.ALERT_CARDS else None
            event.alert_audio_url = await alerts.speak(event, event.alert_message)
            await self._publish(event)
            await sink.broadcast({"type": "alert", "data": event.model_dump(mode="json")})
            if card:
                event.card_url = await card
                if event.card_url:
                    await self._publish(event)
                    await sink.broadcast({"type": "alert", "data": event.model_dump(mode="json")})
        except Exception:
            log.exception("thank-you alert failed for %s", event.event_id)

    async def _publish(self, event: BeverageEvent) -> None:
        await sink.broadcast({"type": "event", "data": event.model_dump(mode="json"),
                              "tipped": event.status == "tipped"})


manager = SessionManager()
