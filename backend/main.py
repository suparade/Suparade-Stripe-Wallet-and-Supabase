"""
FastAPI app: HTTP + WebSocket API for the beverage detector.

Run:  .venv/bin/uvicorn backend.main:app --reload --port 8000
"""

import hmac
import logging
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, payments
from .event_sink import sink
from .session_manager import manager
from .sources.browser_source import BrowserSource

DEFAULT_CHAT_SCRIPT = config.BACKEND_DIR / "demo" / "chat_sample.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Livestream Beverage Detector")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])
config.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/evidence", StaticFiles(directory=config.EVIDENCE_DIR), name="evidence")


def require_key(x_detector_key: str = Header(default="")) -> None:
    """Guards everything that starts, feeds or stops a session. Open when DETECTOR_KEY is unset (local dev)."""
    if config.DETECTOR_KEY and not hmac.compare_digest(x_detector_key.encode(), config.DETECTOR_KEY.encode()):
        raise HTTPException(401, "invalid_detector_key")


class CreateSession(BaseModel):
    source: Literal["url", "browser"]
    url: Optional[str] = None
    streamer_id: str = "demo-streamer"
    demo_alerts: bool = False
    chat_script: Optional[str] = None


class ChatPost(BaseModel):
    user: str = "viewer"
    text: Optional[str] = None
    messages: list[dict] = []


@app.get("/api/health")
async def health():
    return {"ok": True, "model": config.GEMINI_MODEL, "chunk_seconds": config.CHUNK_SECONDS,
            "api_key_set": bool(config.GEMINI_API_KEY), "sponsor_brand": config.SPONSOR_BRAND,
            "verify_model": config.GEMINI_VERIFY_MODEL if config.VERIFY_ENABLED else None,
            "default_chat_script": str(DEFAULT_CHAT_SCRIPT) if DEFAULT_CHAT_SCRIPT.is_file() else None,
            "payments_enabled": config.PAYMENTS_ENABLED}


@app.get("/api/payments")
async def payments_status():
    """Campaign budget and Stripe payout status from the payments API (agent key stays server side)."""
    return await payments.campaign_status()


@app.post("/api/sessions", dependencies=[Depends(require_key)])
async def create_session(body: CreateSession):
    # Local files only from backend/demo/: /media serves a session's file, and the portal's key route lets
    # anyone start a session, so any other path would let them download any file (/proc/self/environ).
    demo_dir = (config.BACKEND_DIR / "demo").resolve()
    for path in (body.url, body.chat_script):
        if path and Path(path).exists() and not Path(path).resolve().is_relative_to(demo_dir):
            raise HTTPException(400, "local files must be in backend/demo/")
    try:
        s = await manager.create(body.source, body.streamer_id, body.url,
                                 demo_alerts=body.demo_alerts, chat_script=body.chat_script)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    return s.summary()


@app.get("/api/sessions")
async def list_sessions():
    return [s.summary() for s in manager.sessions.values()]


@app.post("/api/sessions/{session_id}/chunk", dependencies=[Depends(require_key)])
async def upload_chunk(session_id: str, file: UploadFile = File(...),
                       duration: float = Form(config.CHUNK_SECONDS)):
    s = manager.sessions.get(session_id)
    if not s or not isinstance(s.source, BrowserSource):
        raise HTTPException(404, "browser session not found")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty chunk")
    idx = await s.source.push(data, file.content_type or "video/webm", duration)
    return {"chunk_index": idx, "bytes": len(data)}


@app.get("/api/sessions/{session_id}/media")
async def session_media(session_id: str):
    """The local file a demo session is replaying, so the dashboard can play it."""
    s = manager.sessions.get(session_id)
    if not s or not s.url or not Path(s.url).is_file():
        raise HTTPException(404, "no local media for this session")
    return FileResponse(s.url)


@app.post("/api/sessions/{session_id}/chat", dependencies=[Depends(require_key)])
async def post_chat(session_id: str, body: ChatPost):
    """Inject chat messages (dashboard input, hype bursts, demos)."""
    s = manager.sessions.get(session_id)
    if not s or not s.chat:
        raise HTTPException(404, "session not found")
    msgs = body.messages or ([{"user": body.user, "text": body.text}] if body.text else [])
    for m in msgs[:50]:
        if m.get("text"):
            await s.chat.add(str(m.get("user") or "viewer"), str(m["text"]))
    if "manual" not in s.chat_feeds:
        s.chat_feeds.append("manual")
    return {"added": len(msgs[:50])}


@app.delete("/api/sessions/{session_id}", dependencies=[Depends(require_key)])
async def delete_session(session_id: str):
    await manager.stop(session_id)
    return {"ok": True}


@app.get("/api/events")
async def recent_events():
    return sink.recent


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    await ws.accept()
    sink.sockets.add(ws)
    try:
        for s in manager.sessions.values():
            await ws.send_json({"type": "session", "data": s.summary()})
            for m in list(s.chat.messages)[-40:] if s.chat else []:
                await ws.send_json({"type": "chat", "data": {
                    "session_id": s.id, "user": m.user, "text": m.text, "at": m.wall}})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        sink.sockets.discard(ws)


@app.on_event("shutdown")
async def shutdown():
    for sid in list(manager.sessions):
        await manager.stop(sid)
