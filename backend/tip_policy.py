"""
Tip policy: decides whether a detected moment (or a clip's sponsor exposure)
may be tipped. Returns the list of reasons it is blocked; empty means it is a
tip candidate (still subject to verification for moments).

`TipState` holds the per-session history the cooldown and repetition rules
need. Candidates reserve their slot immediately (`reserve`) so a later clip
can't double-tip while verification is running; `release` undoes it if the
verifier rejects.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from . import config
from .models import ClipAnalysis, Moment, MomentCategory, Sentiment

MENTION_CATEGORIES = {MomentCategory.sports_drink_mention, MomentCategory.verbal_beverage_mention}
VISUAL_SENTIMENTS = {Sentiment.positive, Sentiment.neutral}


@dataclass
class TipState:
    last_tip_offset: Optional[float] = None
    recent_tips: deque = field(default_factory=deque)  # (offset, category, brand_key)


def _brand_key(brand: Optional[str]) -> str:
    return (brand or "").strip().lower()


def clip_blocks(clip: ClipAnalysis) -> list[str]:
    """Blocks that apply to everything in a clip."""
    reasons = []
    if config.SAFETY_BLOCKS_TIPS:
        reasons += [f"safety:{flag}" for flag in clip.safety.active()]
    if clip.looks_prerecorded_or_looped:
        reasons.append("prerecorded_or_looped")
    return reasons


def evaluate(moment: Moment, clip: ClipAnalysis, offset: float, state: TipState,
             is_competitor: bool) -> list[str]:
    reasons = clip_blocks(clip)
    if moment.category in MENTION_CATEGORIES:
        if moment.sentiment != Sentiment.positive:
            reasons.append(f"sentiment:{moment.sentiment.value}")
    elif moment.sentiment not in VISUAL_SENTIMENTS:
        reasons.append(f"sentiment:{moment.sentiment.value}")
    if is_competitor:
        reasons.append("competitor_brand")
    if moment.subject_type.value not in config.ALLOWED_SUBJECT_TYPES:
        reasons.append(f"subject:{moment.subject_type.value}")
    if moment.looks_staged:
        reasons.append("looks_staged")

    key = (moment.category.value, _brand_key(moment.brand))
    window_start = offset - config.REPEAT_WINDOW_SECONDS
    repeats = sum(1 for o, c, b in state.recent_tips if o >= window_start and (c, b) == key)
    if repeats >= config.REPEAT_LIMIT:
        reasons.append("repetitive")

    if state.last_tip_offset is not None and abs(offset - state.last_tip_offset) < config.COOLDOWN_SECONDS:
        reasons.append("cooldown")
    return reasons


def evaluate_exposure(clip: ClipAnalysis) -> list[str]:
    reasons = clip_blocks(clip)
    if clip.on_screen_subject.value not in config.ALLOWED_SUBJECT_TYPES:
        reasons.append(f"subject:{clip.on_screen_subject.value}")
    return reasons


def reserve(state: TipState, moment: Moment, offset: float) -> tuple:
    entry = (offset, moment.category.value, _brand_key(moment.brand))
    prev = state.last_tip_offset
    state.last_tip_offset = offset
    state.recent_tips.append(entry)
    while state.recent_tips and state.recent_tips[0][0] < offset - config.REPEAT_WINDOW_SECONDS:
        state.recent_tips.popleft()
    return entry, prev


def release(state: TipState, reservation: tuple) -> None:
    entry, prev = reservation
    try:
        state.recent_tips.remove(entry)
    except ValueError:
        pass
    if state.last_tip_offset == entry[0]:
        state.last_tip_offset = prev
