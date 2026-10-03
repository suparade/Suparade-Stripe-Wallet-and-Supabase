"""
Evidence for paid events: the analyzed clip plus a thumbnail at the moment,
written under EVIDENCE_DIR and served at /evidence by the API. Gemini then
draws bounding boxes around the product on the thumbnail.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from google.genai import types

from . import config
from .gemini_analyzer import generate_json
from .models import Box, BoxList

log = logging.getLogger("evidence")


async def _thumbnail(clip_path, thumb_path, offset: float) -> bool:
    # -ss after -i: MediaRecorder webm has no seek index, so input seeking is unreliable.
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(clip_path), "-ss", f"{max(0.0, offset):.2f}",
        "-frames:v", "1", "-q:v", "3", str(thumb_path),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0 or not thumb_path.exists():
        log.warning("thumbnail failed at %.1fs: %s", offset, err.decode(errors="replace")[-300:])
        return False
    return True


async def save_evidence(session_id: str, event_id: str, data: bytes, mime_type: str,
                        offset_in_clip: float) -> tuple[str, str | None]:
    """Returns (clip_url, thumbnail_url); thumbnail_url is None if ffmpeg failed."""
    ext = "webm" if "webm" in mime_type else "mp4"
    out = config.EVIDENCE_DIR / session_id
    out.mkdir(parents=True, exist_ok=True)
    clip_path = out / f"{event_id}.{ext}"
    thumb_path = out / f"{event_id}.jpg"
    clip_path.write_bytes(data)

    ok = await _thumbnail(clip_path, thumb_path, offset_in_clip)
    if not ok and offset_in_clip > 0:
        ok = await _thumbnail(clip_path, thumb_path, 0.0)

    base = f"/evidence/{session_id}/{event_id}"
    return f"{base}.{ext}", (f"{base}.jpg" if ok else None)


def path_for(url: str) -> Path:
    return config.EVIDENCE_DIR / url.removeprefix("/evidence/")


BOX_PROMPT = """Find where beverages and beverage brands appear in this livestream frame.
Return a box for the {brand} product or logo if visible, and for any other drink
container (bottle, can, cup, mug). Label each box briefly with brand and object,
e.g. "{brand} bottle", "Prime can", "water bottle", "mug". At most 5 boxes.
box_2d is [ymin, xmin, ymax, xmax] normalized to 0-1000. Return no boxes if no drink is visible."""


async def detect_boxes(thumbnail_url: str, brand: str) -> list[Box]:
    img = path_for(thumbnail_url).read_bytes()
    contents = [types.Part.from_bytes(data=img, mime_type="image/jpeg"), "Detect the beverages."]
    result = await generate_json(config.GEMINI_MODEL, BOX_PROMPT.format(brand=brand), contents, BoxList)
    return [b for b in result.boxes if len(b.box_2d) == 4][:5]
