"""
Data models.

- `Moment` / `ClipAnalysis`: the structured JSON schema Gemini must return
  for each analyzed clip.
- `Verification`: the schema for the stricter second-pass check.
- `BeverageEvent`: the contract sent to the payments API (Supabase + Stripe) and
  the webhook. Keep this stable; new fields must stay optional.
- `ChunkStatus`: per-clip pipeline health shown in the dashboard.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class MomentCategory(str, Enum):
    sports_drink_mention = "sports_drink_mention"
    drinking_water = "drinking_water"
    drinking_other = "drinking_other"
    holding_or_showing_beverage = "holding_or_showing_beverage"
    verbal_beverage_mention = "verbal_beverage_mention"


class EventCategory(str, Enum):
    sports_drink_mention = "sports_drink_mention"
    drinking_water = "drinking_water"
    drinking_other = "drinking_other"
    holding_or_showing_beverage = "holding_or_showing_beverage"
    verbal_beverage_mention = "verbal_beverage_mention"
    sponsor_screen_time = "sponsor_screen_time"

class Sentiment(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"
    sarcastic = "sarcastic"


class SubjectType(str, Enum):
    real_person = "real_person"
    animated_character = "animated_character"
    video_playback = "video_playback"


class Prominence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Moment(BaseModel):
    category: MomentCategory
    confidence: float = Field(description="0.0 to 1.0")
    offset_seconds: float = Field(description="Seconds from the start of this clip")
    description: str = Field(description="What happened, one sentence")
    quote: Optional[str] = Field(default=None, description="Exact words spoken, if any")
    brand: Optional[str] = Field(default=None, description="Beverage brand if identifiable")
    sentiment: Sentiment = Field(description="Streamer's attitude toward the beverage in this moment")
    subject_type: SubjectType = Field(description="Who performs the moment")
    looks_staged: bool = Field(description="True if the moment looks forced or performed just for a reward")


class BrandExposure(BaseModel):
    brand: str
    visible_seconds: float = Field(description="Total seconds the brand's logo or product is visible in this clip")
    prominence: Prominence
    description: str = Field(description="Where and how the brand appears, one sentence")


class SafetyFlags(BaseModel):
    alcohol: bool
    vaping: bool
    nsfw: bool
    slurs: bool
    gambling: bool
    notes: Optional[str] = Field(default=None, description="What was seen or heard, if any flag is true")

    def active(self) -> list[str]:
        return [k for k in ("alcohol", "vaping", "nsfw", "slurs", "gambling") if getattr(self, k)]


class ClipAnalysis(BaseModel):
    detected: bool
    moments: list[Moment]
    brand_exposures: list[BrandExposure]
    safety: SafetyFlags
    on_screen_subject: SubjectType = Field(description="Main subject shown in the clip")
    looks_prerecorded_or_looped: bool = Field(
        description="True if the footage looks like a rerun, a loop, or not a live broadcast"
    )
    clip_summary: str = Field(description="One sentence summary of the clip, used as context for the next clip")


class Reaction(str, Enum):
    none = "none"
    low = "low"
    medium = "medium"
    high = "high"


class Verification(BaseModel):
    confirmed: bool
    confidence: float = Field(description="0.0 to 1.0")
    reason: str = Field(description="One sentence justification")
    audience_reaction: Reaction = Field(description="How strongly live chat reacted to this moment")
    reaction_summary: str = Field(description="One sentence on how chat reacted, or 'no chat'")
    chat_highlights: list[str] = Field(description="Up to 3 chat messages that best show the reaction")


class Box(BaseModel):
    label: str
    box_2d: list[int] = Field(description="[ymin, xmin, ymax, xmax], normalized to 0-1000")


class BoxList(BaseModel):
    boxes: list[Box]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


EventStatus = Literal["tipped", "blocked", "pending_verification", "rejected_by_verifier",
                      "paying", "payment_failed"]
PaymentStatus = Literal["paid", "pending", "failed", "simulated"]


class BeverageEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    streamer_id: str
    category: EventCategory
    confidence: float
    description: str
    quote: Optional[str] = None
    brand: Optional[str] = None
    stream_offset_seconds: float
    detected_at: str = Field(default_factory=_now)
    suggested_tip_cents: int
    sentiment: Optional[Sentiment] = None
    subject_type: Optional[SubjectType] = None
    is_sponsor: bool = False
    is_competitor: bool = False
    status: EventStatus = "blocked"
    block_reasons: list[str] = Field(default_factory=list)
    verification_reason: Optional[str] = None
    exposure_seconds: Optional[float] = None
    thumbnail_url: Optional[str] = None
    clip_url: Optional[str] = None
    boxes: list[Box] = Field(default_factory=list)
    audience_reaction: Optional[Reaction] = None
    reaction_summary: Optional[str] = None
    chat_highlights: list[str] = Field(default_factory=list)
    reaction_multiplier: Optional[float] = None
    alert_message: Optional[str] = None
    alert_audio_url: Optional[str] = None
    card_url: Optional[str] = None
    # Filled in by the payments API (Supabase + Stripe). "simulated" when payments are not configured.
    payment_status: Optional[PaymentStatus] = None
    payment_error: Optional[str] = None
    stripe_transfer_id: Optional[str] = None
    tip_id: Optional[str] = None
    detection_id: Optional[str] = None
    requested_tip_cents: Optional[int] = None  # set when the campaign's max tip capped the suggestion


class ChunkStatus(BaseModel):
    session_id: str
    chunk_index: int
    stream_offset_seconds: float
    status: Literal["analyzing", "nothing_found", "detected", "error", "skipped"]
    latency_ms: Optional[int] = None
    moments_found: int = 0
    error: Optional[str] = None
    safety_flags: list[str] = Field(default_factory=list)
    summary: Optional[str] = None
    at: str = Field(default_factory=_now)
