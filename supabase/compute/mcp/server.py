"""Suparade's MCP server, running on Supabase Compute.

Gives any agent what Suparade sells: brand sightings from live streams, the tips paid for them and
the budget left, plus the scout itself (status, watch a stream, stop). Agents send the Suparade
agent key in X-Agent-Key. To start or stop the scout they also send X-Detector-Key, which this
server forwards to the detector.

Deploy: supabase compute deploy mcp --project-ref <ref>
URL:    https://<ref>.supabase.co/compute/v1/mcp/mcp
"""

import contextvars
import logging
import os

import httpx
from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

import logic

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("suparade.mcp")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
DB_KEY = logic.service_key(os.environ)
PAYMENTS_URL = os.environ.get("SUPARADE_API_URL", "https://suparade.vercel.app/api").rstrip("/")
DETECTOR_URL = os.environ.get("DETECTOR_URL", "").rstrip("/") or (
    f"{SUPABASE_URL}/compute/v1/detector" if SUPABASE_URL.startswith("https://") else ""
)
AGENT_KEY = os.environ.get("AGENT_API_KEY", "") or os.environ.get("SUPARADE_AGENT_KEY", "")

_detector_key: contextvars.ContextVar = contextvars.ContextVar("detector_key", default="")
_accepted_keys = logic.KeyCache()

try:  # Compute's gateway sends Host: <ref>.supabase.co, which the localhost-only default would refuse.
    from mcp.server.transport_security import TransportSecuritySettings

    _security = {"transport_security": TransportSecuritySettings(enable_dns_rebinding_protection=False)}
except ImportError:
    _security = {}

mcp = FastMCP("suparade", stateless_http=True, json_response=True, host="0.0.0.0", **_security)


async def _rest(path: str, params: dict) -> list:
    if not SUPABASE_URL or not DB_KEY:
        raise RuntimeError("This service has no database credentials (SUPABASE_URL and a service key).")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{SUPABASE_URL}/rest/v1/{path}", params=params, headers=logic.rest_headers(DB_KEY))
    if r.status_code >= 400:
        raise RuntimeError(f"Database read of {path} failed ({r.status_code}): {r.text[:300]}")
    return r.json()


async def _agent_key_ok(key: str) -> bool:
    if not key:
        return False
    if AGENT_KEY:
        return logic.keys_match(key, AGENT_KEY)
    if _accepted_keys.accepted(key):
        return True
    # No key on this service: the payments API, which issued it, decides.
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{PAYMENTS_URL}/agent/videos", params={"limit": 1}, headers={"X-Agent-Key": key})
    if r.status_code == 200:
        _accepted_keys.accept(key)
        return True
    return False


def _caller_detector_key(ctx: Context) -> str:
    try:
        key = ctx.request_context.request.headers.get("x-detector-key", "")
    except AttributeError:
        key = ""
    return key or _detector_key.get()


async def _detector(method: str, path: str, ctx: Context = None, **kwargs) -> dict:
    if not DETECTOR_URL:
        raise RuntimeError("DETECTOR_URL is not set on this service.")
    headers = {}
    if ctx is not None:
        key = _caller_detector_key(ctx)
        if not key:
            raise ValueError("Starting or stopping the scout needs the X-Detector-Key header on your MCP connection.")
        headers["X-Detector-Key"] = key
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.request(method, f"{DETECTOR_URL}{path}", headers=headers, **kwargs)
    if r.status_code >= 400:
        raise RuntimeError(f"The scout answered {r.status_code}: {r.text[:300]}")
    return r.json()


@mcp.tool()
async def list_campaigns() -> list[dict]:
    """Campaigns you can work for: the brand, status, budget left and the cap on a single tip."""
    rows = await _rest("campaigns", {
        "select": "id,name,type,status,max_tip_cents,currency,brand_context,brands(name)",
        "order": "created_at.desc", "limit": "20",
    })
    balances = {b["campaign_id"]: b["balance_cents"] for b in await _rest("campaign_balances", {"select": "campaign_id,balance_cents"})}
    return [logic.campaign(r, balances.get(r["id"], 0)) for r in rows]


@mcp.tool()
async def brand_sightings(campaign_id: str, limit: int = 10) -> list[dict]:
    """Moments the brand appeared on a watched live stream, newest first: what was seen or said, the
    exact quote, the model's confidence, whether it was tipped, and evidence links when there are any."""
    rows = await _rest("detections", {
        "select": "id,kind,category,brand,quote,description,confidence,timestamp_seconds,meta,created_at,"
                  "tips(status,amount_cents,currency)",
        "campaign_id": f"eq.{logic.campaign_uuid(campaign_id)}",
        "order": "created_at.desc", "limit": str(logic.clamp_limit(limit)),
    })
    return [logic.sighting(r, DETECTOR_URL) for r in rows]


@mcp.tool()
async def tips(campaign_id: str, limit: int = 10) -> list[dict]:
    """Tips for a campaign, newest first: the creator, amount, message, why the agent paid, the
    Stripe transfer id, or the reason a tip failed."""
    rows = await _rest("tips", {
        "select": "id,status,amount_cents,currency,message,reasoning,stripe_transfer_id,failure_reason,"
                  "created_at,paid_at,creators(display_name)",
        "campaign_id": f"eq.{logic.campaign_uuid(campaign_id)}",
        "order": "created_at.desc", "limit": str(logic.clamp_limit(limit)),
    })
    return [logic.tip(r) for r in rows]


@mcp.tool()
async def scout_status() -> dict:
    """What the scout (the Gemini detector, also on Supabase Compute) is watching right now."""
    health = await _detector("GET", "/api/health")
    sessions = await _detector("GET", "/api/sessions")
    return logic.scout_status(health, sessions)


@mcp.tool()
async def watch_stream(url: str, ctx: Context, streamer_id: str = "demo-streamer") -> dict:
    """Send the scout to watch a live stream (a Twitch, YouTube or Kick URL, or the demo recording
    backend/demo/demo_stream.mp4). When the brand appears, it tips the streamer from the campaign
    budget, within the per-tip cap. streamer_id is the creator handle that gets paid."""
    return await _detector("POST", "/api/sessions", ctx, json={"source": "url", "url": url, "streamer_id": streamer_id})


@mcp.tool()
async def stop_watching(session_id: str, ctx: Context) -> dict:
    """Stop a scout session started with watch_stream (session ids are in scout_status)."""
    return await _detector("DELETE", f"/api/sessions/{session_id}", ctx)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({
        "ok": True,
        "database_configured": bool(SUPABASE_URL and DB_KEY),
        "agent_keys_checked_by": "this service" if AGENT_KEY else "payments API",
        "detector_url": DETECTOR_URL or None,
    })


class AgentKeyGate:
    """Every MCP request needs a valid X-Agent-Key; /health stays open."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/health":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        if not await _agent_key_ok(headers.get("x-agent-key", "")):
            response = JSONResponse(
                {"error": "invalid_agent_key", "hint": "Send the Suparade agent key in the X-Agent-Key header."},
                status_code=401,
            )
            return await response(scope, receive, send)
        _detector_key.set(headers.get("x-detector-key", ""))
        await self.app(scope, receive, send)


app = AgentKeyGate(mcp.streamable_http_app())
