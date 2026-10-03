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
