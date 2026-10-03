from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

CampaignType = Literal["brand_mention", "cool_moment"]


class VideoIn(BaseModel):
    url: str = Field(min_length=5, max_length=2000)
    platform: Optional[str] = None
    title: Optional[str] = None
    creator_id: Optional[UUID] = None


class VideoStatusIn(BaseModel):
    status: Literal["pending", "scanning", "done", "failed"]


class DetectionIn(BaseModel):
    campaign_id: UUID
    video_id: UUID
    kind: CampaignType
    timestamp_seconds: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    description: str = Field(default="", max_length=1000)
    # Optional. If omitted we derive one from campaign, video, kind and a 5 second window,
    # so the same moment reported twice never produces two detections.
    idempotency_key: Optional[str] = Field(default=None, max_length=200)


class TipIn(BaseModel):
    detection_id: UUID
    amount_cents: int = Field(gt=0)
    message: str = Field(min_length=1, max_length=200)  # shown on screen next to the tip
    reasoning: str = Field(default="", max_length=2000)
    show_at_seconds: Optional[float] = Field(default=None, ge=0)


class CreatorIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


class FundIn(BaseModel):
    amount_cents: int = Field(gt=0, le=500_000)  # 5,000.00 is Link's documented per request ceiling


class DevCreditIn(BaseModel):
    amount_cents: int = Field(gt=0, le=500_000)


class StreamEventIn(BaseModel):
    """A tip-worthy moment from the Gemini livestream detector (backend/), sent by its tipper step.

    Mirrors the detector's BeverageEvent contract; unknown fields are kept in detections.meta.
    """

    model_config = {"extra": "allow"}

    campaign_id: UUID
    event_id: str = Field(min_length=1, max_length=100)
    session_id: str = Field(min_length=1, max_length=100)
    streamer_id: str = Field(min_length=1, max_length=100)  # creators.handle (or a creator uuid)
    category: str = Field(min_length=1, max_length=60)
    confidence: float = Field(ge=0, le=1)
    description: str = Field(default="", max_length=1000)
    quote: Optional[str] = Field(default=None, max_length=1000)
    brand: Optional[str] = Field(default=None, max_length=100)
    stream_offset_seconds: float = Field(ge=0)
    suggested_tip_cents: int = Field(ge=0)
    source_url: Optional[str] = Field(default=None, max_length=2000)  # stream URL or file; empty for webcam
    message: Optional[str] = Field(default=None, max_length=200)  # on screen tip message
    reasoning: Optional[str] = Field(default=None, max_length=2000)
