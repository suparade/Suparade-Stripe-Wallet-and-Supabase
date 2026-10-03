"""
Browser source: the frontend records webcam or screen-share with MediaRecorder,
restarting the recorder every CHUNK_SECONDS so each upload is a standalone
webm file, and POSTs each clip here.
"""

import asyncio
from typing import Awaitable, Callable

from . import Chunk


class BrowserSource:
    def __init__(self, session_id: str, on_chunk: Callable[[Chunk], Awaitable[None]]):
        self.session_id = session_id
        self.on_chunk = on_chunk
        self.next_index = 0
        self.offset = 0.0

    async def push(self, data: bytes, mime_type: str, duration_seconds: float) -> int:
        idx = self.next_index
        await self.on_chunk(Chunk(idx, self.offset, data, mime_type.split(";")[0] or "video/webm"))
        self.next_index += 1
        self.offset += duration_seconds
        return idx

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def wait_exited(self) -> None:
        await asyncio.Event().wait()

    @property
    def exited(self) -> bool:
        return False

    @property
    def exit_reason(self) -> None:
        return None
