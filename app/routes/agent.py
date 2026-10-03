import hashlib
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import require_agent
from app.db import get_supabase
from app.schemas import DetectionIn, StreamEventIn, TipIn, VideoIn, VideoStatusIn
from app.services.stream_events import StreamEventError, handle_stream_event
from app.services.tips import TipError, reserve_tip, settle_tip

# Everything the finder agent and the tipper agent call lives here. Auth: X-Agent-Key header.
router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(require_agent)])


@router.get("/campaigns/{campaign_id}/context")
def campaign_context(campaign_id: UUID):
    """What the tipper agent needs before deciding: brand context, rules, budget left, recent tips."""
    sb = get_supabase()
    camp = sb.table("campaigns").select("*, brands(name)").eq("id", str(campaign_id)).limit(1).execute().data
    if not camp:
        raise HTTPException(404, "campaign_not_found")
    c = camp[0]
    bal = (
        sb.table("campaign_balances").select("balance_cents").eq("campaign_id", str(campaign_id)).limit(1).execute().data
    )
    recent = (
        sb.table("tips")
        .select("amount_cents,message,status,created_at")
        .eq("campaign_id", str(campaign_id))
        .order("created_at", desc=True)
        .limit(10)
        .execute()
        .data
    )
    return {
        "campaign_id": c["id"],
        "brand_name": (c.get("brands") or {}).get("name"),
        "type": c["type"],
        "status": c["status"],
        "brand_context": c["brand_context"],
        "tipper_instructions": c["tipper_instructions"],
        "max_tip_cents": c["max_tip_cents"],
        "currency": c["currency"],
        "balance_cents": bal[0]["balance_cents"] if bal else 0,
        "recent_tips": recent,
    }


@router.post("/videos", status_code=201)
def register_video(body: VideoIn):
    """Finder agent registers a video URL (we store URLs only, not files)."""
    row = {
        "url": body.url,
        "platform": body.platform,
        "title": body.title,
        "creator_id": str(body.creator_id) if body.creator_id else None,
    }
    res = get_supabase().table("videos").upsert(row, on_conflict="url").execute()
    return res.data[0]


@router.get("/videos")
def list_videos(status: Optional[str] = Query(default=None), limit: int = Query(default=20, ge=1, le=100)):
    q = get_supabase().table("videos").select("*").order("created_at").limit(limit)
    if status:
        q = q.eq("status", status)
    return q.execute().data


@router.patch("/videos/{video_id}")
def set_video_status(video_id: UUID, body: VideoStatusIn):
    res = get_supabase().table("videos").update({"status": body.status}).eq("id", str(video_id)).execute()
    if not res.data:
        raise HTTPException(404, "video_not_found")
    return res.data[0]


@router.post("/detections", status_code=201)
def create_detection(body: DetectionIn):
    """Log a moment worth tipping. Reporting the same moment twice returns the original row."""
    sb = get_supabase()

    camp = sb.table("campaigns").select("id,type").eq("id", str(body.campaign_id)).limit(1).execute().data
    if not camp:
        raise HTTPException(404, "campaign_not_found")
    if camp[0]["type"] != body.kind:
        raise HTTPException(422, "kind_does_not_match_campaign_type")

    key = body.idempotency_key or hashlib.sha256(
        f"{body.campaign_id}:{body.video_id}:{body.kind}:{int(body.timestamp_seconds // 5)}".encode()
    ).hexdigest()

    row = {
        "campaign_id": str(body.campaign_id),
        "video_id": str(body.video_id),
        "kind": body.kind,
        "timestamp_seconds": body.timestamp_seconds,
        "confidence": body.confidence,
        "description": body.description,
        "idempotency_key": key,
    }
    sb.table("detections").upsert(row, on_conflict="idempotency_key", ignore_duplicates=True).execute()
    detection = sb.table("detections").select("*").eq("idempotency_key", key).single().execute().data
    return detection


@router.post("/tips")
def create_tip(body: TipIn):
    """Tipper agent decides amount and message. We check budget, reserve it, pay the creator.

    Calling this again for the same detection is safe: it returns the existing tip and, if the
    transfer was left pending by a network error, retries it with the same idempotency key.
    """
    try:
        tip = reserve_tip(
            str(body.detection_id), body.amount_cents, body.message, body.reasoning, body.show_at_seconds
        )
    except TipError as e:
        raise HTTPException(e.status_code, e.code)
    return settle_tip(tip)


@router.post("/stream-events")
def stream_event(body: StreamEventIn):
    """The Gemini livestream detector reports a verified moment; we log it and pay the streamer.

    Idempotent on event_id: sending the same event again returns the same detection and tip.
    """
    try:
        return handle_stream_event(body)
    except StreamEventError as e:
        raise HTTPException(e.status_code, e.code)
