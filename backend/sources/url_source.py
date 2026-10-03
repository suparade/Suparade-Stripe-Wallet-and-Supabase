"""
URL source: pulls a live stream and cuts it into fixed-length mp4 clips.

    streamlink --stdout <url> best | ffmpeg ... -f segment out_%05d.mp4

streamlink handles Twitch, YouTube Live, Kick and most other platforms.
ffmpeg re-encodes to 480p with a forced keyframe at every segment boundary so
each clip is a small, standalone, playable mp4. ffmpeg appends every
*finished* segment to a CSV segment list, which we tail to know when a clip
is safe to read.

If `url` is a local file path, it is replayed in real time (`ffmpeg -re`),
which is handy for demos and testing without a live stream.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Awaitable, Callable

from .. import config
from . import Chunk

log = logging.getLogger("url_source")


def _ffmpeg_args(input_spec: str, out_dir: Path, realtime: bool) -> list[str]:
    seg = config.CHUNK_SECONDS
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if realtime:
        args.append("-re")
    args += [
        "-i", input_spec,
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", "scale=-2:480", "-r", "5",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-force_key_frames", f"expr:gte(t,n_forced*{seg})",
        "-c:a", "aac", "-b:a", "64k", "-ac", "1",
        "-f", "segment", "-segment_time", str(seg), "-reset_timestamps", "1",
        "-segment_list", str(out_dir / "segments.csv"), "-segment_list_type", "csv",
        str(out_dir / "seg_%05d.mp4"),
    ]
    return args


class UrlSource:
    def __init__(self, session_id: str, url: str, on_chunk: Callable[[Chunk], Awaitable[None]]):
        self.session_id = session_id
        self.url = url
        self.on_chunk = on_chunk
        self.out_dir = config.CHUNKS_DIR / session_id
        self.proc: asyncio.subprocess.Process | None = None
        self.task: asyncio.Task | None = None
        self.exit_reason: str | None = None

    async def start(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        local = os.path.isfile(self.url)
        if local:
            cmd = shlex.join(_ffmpeg_args(self.url, self.out_dir, realtime=True))
        else:
            venv_bin = str(Path(sys.executable).parent)
            streamlink = shutil.which("streamlink", path=f"{venv_bin}{os.pathsep}{os.environ.get('PATH', '')}")
            if not streamlink:
                raise RuntimeError("streamlink not installed (pip install streamlink)")
            sl = shlex.join([
                streamlink, "--stdout", "--loglevel", "error",
                "--hls-live-edge", "2", "--twitch-low-latency",
                "--retry-open", "3", "--retry-streams", "5", "--retry-max", "6",
                "--stream-segment-threads", "2",
                self.url, "480p,720p,best",
            ])
            ff = shlex.join(_ffmpeg_args("pipe:0", self.out_dir, realtime=False))
            cmd = f"{sl} | {ff}"
        log.info("starting pipeline: %s", cmd)
        self.proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        self.task = asyncio.create_task(self._watch())

    async def _watch(self) -> None:
        seg_list = self.out_dir / "segments.csv"
        seen = 0
        offset = 0.0
        while True:
            done = self.proc is not None and self.proc.returncode is not None
            if seg_list.exists():
                lines = [l for l in seg_list.read_text().splitlines() if l.strip()]
                for line in lines[seen:]:
                    # csv columns: filename,start_time,end_time
                    name, start, end = line.split(",")[:3]
                    path = self.out_dir / name
                    data = path.read_bytes()
                    await self.on_chunk(Chunk(seen, offset, data, "video/mp4"))
                    offset += float(end) - float(start)
                    seen += 1
                    path.unlink(missing_ok=True)
            if done:
                err = (await self.proc.stderr.read()).decode(errors="replace").strip() if self.proc.stderr else ""
                log.info("pipeline exited code=%s %s", self.proc.returncode, err[-500:])
                self.exit_reason = self._reason(self.proc.returncode, err)
                shutil.rmtree(self.out_dir, ignore_errors=True)
                return
            await asyncio.sleep(0.5)

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                os.killpg(self.proc.pid, 15)
            except ProcessLookupError:
                pass
        if self.task:
            try:
                await asyncio.wait_for(self.task, timeout=5)
            except (asyncio.TimeoutError, Exception):
                self.task.cancel()
        shutil.rmtree(self.out_dir, ignore_errors=True)

    def _reason(self, code: int | None, err: str) -> str:
        low = err.lower()
        if "no playable streams" in low or "offline" in low:
            return "stream offline"
        if "no plugin can handle" in low:
            return "unsupported URL"
        if code == 0 or not err:
            return "file finished" if os.path.isfile(self.url) else "stream ended"
        return f"error: {err.splitlines()[-1][:200]}"

    async def wait_exited(self) -> None:
        if self.task:
            await asyncio.shield(self.task)

    @property
    def exited(self) -> bool:
        return self.task is not None and self.task.done()
