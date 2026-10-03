"""
Stream sources. Each source pushes `Chunk`s into a session's queue.
"""

import time
from dataclasses import dataclass, field


@dataclass
class Chunk:
    index: int
    stream_offset_seconds: float
    data: bytes
    mime_type: str
    wall_end: float = field(default_factory=time.time)  # wall-clock time the clip finished, for matching chat
