"""Turn a moment from the Gemini livestream detector into a real Stripe tip.

The detector (backend/) watches the stream, filters and verifies moments, and calls
POST /agent/stream-events for each one it decides to tip. Here we:

1. resolve the streamer (creators.handle, or a creator uuid) and the campaign
2. register the stream as a video, linked to that creator
3. log the moment as a detection (idempotent on the detector's event_id)
4. reserve the tip against the campaign budget and send the Stripe transfer

The amount is the detector's suggestion, capped at the campaign's max_tip_cents. Every money rule
(budget lock, one tip per detection, payable creator, Stripe idempotency) is the same one the
plain /agent/tips route uses.
"""
import os
import re
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

from app.db import get_supabase
from app.schemas import StreamEventIn
from app.services.tips import TipError, reserve_tip, settle_tip

# Fields stored in their own columns or not useful for audits; everything else goes into meta.
_META_SKIP = {"campaign_id", "message", "reasoning", "source_url"}


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def resolve_creator(streamer_id: str) -> Optional[dict]:
    sb = get_supabase()
    cols = "id,display_name,handle,stripe_account_id,transfers_enabled"
    if _is_uuid(streamer_id):
        rows = sb.table("creators").select(cols).eq("id", streamer_id).limit(1).execute().data
        if rows:
            return rows[0]
    pattern = re.sub(r"([\\%_])", r"\\\1", streamer_id.strip())  # match the handle literally
    rows = sb.table("creators").select(cols).ilike("handle", pattern).limit(1).execute().data
    return rows[0] if rows else None


def platform_for(url: Optional[str]) -> str:
    if not url:
        return "browser"
    host = (urlparse(url).hostname or "").lower()
    for name in ("twitch", "youtube", "kick", "tiktok"):
        if name in host:
            return name
    if host == "youtu.be":
        return "youtube"
    return "web" if host else "local"


def video_url_for(event: StreamEventIn) -> str:
    """Stable key for the videos table. Webcam and local demo files get a synthetic URL."""
    url = (event.source_url or "").strip()
    if url.startswith(("http://", "https://")):
        return url
    if url:
        return f"local://{os.path.basename(url)}"
    return f"browser://{event.session_id}"


def _message(event: StreamEventIn, amount_cents: int) -> str:
    if event.message and event.message.strip():
        return event.message.strip()[:200]
    who = event.brand or "The sponsor"
    what = re.sub(r"\s+", " ", event.description).strip().rstrip(".")
    text = f"{who} tipped ${amount_cents / 100:.2f}" + (f" for: {what}" if what else "")
    return text[:200]


def _reasoning(event: StreamEventIn) -> str:
    if event.reasoning:
        return event.reasoning[:2000]
    extra = event.model_extra or {}
    parts = [f"Gemini flagged {event.category} at {event.stream_offset_seconds:.1f}s "
             f"(confidence {event.confidence:.2f})."]
    if extra.get("verification_reason"):
        parts.append(f"Verifier: {extra['verification_reason']}")
    if extra.get("reaction_summary"):
        parts.append(f"Chat: {extra['reaction_summary']}")
    return " ".join(parts)[:2000]


class StreamEventError(Exception):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def handle_stream_event(event: StreamEventIn) -> dict:
    sb = get_supabase()

    camp = (
        sb.table("campaigns")
        .select("id,type,status,max_tip_cents")
        .eq("id", str(event.campaign_id))
        .limit(1)
        .execute()
        .data
    )
    if not camp:
        raise StreamEventError("campaign_not_found", 404)
    campaign = camp[0]

    creator = resolve_creator(event.streamer_id)
    if not creator:
        raise StreamEventError("unknown_streamer", 409)

    url = video_url_for(event)
    video = (
        sb.table("videos")
        .upsert(
            {
                "url": url,
                "platform": platform_for(event.source_url),
                "title": f"Live session {event.session_id}",
                "creator_id": creator["id"],
            },
            on_conflict="url",
        )
        .execute()
        .data[0]
    )

    key = f"gemini:{event.event_id}"
    meta = {k: v for k, v in event.model_dump(mode="json").items() if k not in _META_SKIP}
    sb.table("detections").upsert(
        {
            "campaign_id": campaign["id"],
            "video_id": video["id"],
            "kind": campaign["type"],  # every sponsor moment counts toward the campaign's type
            "timestamp_seconds": event.stream_offset_seconds,
            "confidence": event.confidence,
            "description": event.description,
            "idempotency_key": key,
            "category": event.category,
            "brand": event.brand,
            "quote": event.quote,
            "meta": meta,
        },
        on_conflict="idempotency_key",
        ignore_duplicates=True,
    ).execute()
    detection = sb.table("detections").select("*").eq("idempotency_key", key).single().execute().data

    amount = min(int(event.suggested_tip_cents), int(campaign["max_tip_cents"]))
    result = {
        "detection_id": detection["id"],
        "video_id": video["id"],
        "creator_id": creator["id"],
        "requested_cents": event.suggested_tip_cents,
        "amount_cents": amount,
        "capped": amount < event.suggested_tip_cents,
    }
    if amount <= 0:
        return {**result, "tip": None, "status": "skipped_zero_amount"}

    try:
        tip = reserve_tip(detection["id"], amount, _message(event, amount), _reasoning(event),
                          event.stream_offset_seconds)
    except TipError as e:
        raise StreamEventError(e.code, e.status_code)
    tip = settle_tip(tip)
    return {**result, "tip": tip, "status": tip["status"]}
