"""
Payments: hands each confirmed tip to the Suparade payments API (app/ in this
repo), which logs the moment in Supabase, checks the brand's campaign budget,
and sends a real Stripe transfer to the streamer's connected account.

    POST {SUPARADE_API_URL}/agent/stream-events   (header X-Agent-Key)

The call is idempotent on event_id, so retrying after a timeout never pays
twice. The streamer is matched by `streamer_id` = creators.handle in Supabase
(the seeded demo streamer is "demo-streamer").

With SUPARADE_API_URL unset, tips are simulated exactly like before the merge.

CLI check (sends one $0.50 test tip for the given streamer, no Gemini needed):
    python -m backend.payments demo-streamer
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional
from uuid import uuid4

import httpx

from . import config
from .models import BeverageEvent

log = logging.getLogger("payments")


@dataclass
class PaymentResult:
    ok: bool
    status: str  # paid | pending | failed | simulated
    amount_cents: int
    capped: bool = False
    error: Optional[str] = None
    tip_id: Optional[str] = None
    stripe_transfer_id: Optional[str] = None
    detection_id: Optional[str] = None


_http: Optional[httpx.AsyncClient] = None
_campaign_cache: dict[str, Any] = {"at": 0.0, "data": None}


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(
            base_url=config.SUPARADE_API_URL,
            headers={"X-Agent-Key": config.SUPARADE_AGENT_KEY},
            timeout=config.PAYMENTS_TIMEOUT_SECONDS,
        )
    return _http


def _detail(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail")
    except Exception:
        d = None
    if isinstance(d, list):  # FastAPI validation errors
        return "invalid_request: " + "; ".join(str(e.get("msg")) for e in d[:3])
    return str(d or f"http_{r.status_code}")


async def pay(event: BeverageEvent, source_url: Optional[str]) -> PaymentResult:
    """Pay one tip. Never raises: failures come back as ok=False with an error code."""
    if not config.PAYMENTS_ENABLED:
        return PaymentResult(ok=True, status="simulated", amount_cents=event.suggested_tip_cents)

    body = event.model_dump(mode="json")
    body.update(campaign_id=config.SUPARADE_CAMPAIGN_ID, source_url=source_url,
                message=(event.alert_message or "")[:200] or None)
    last_error = "payments_unreachable"
    for attempt in range(1, config.PAYMENTS_MAX_ATTEMPTS + 1):
        try:
            r = await _client().post("/agent/stream-events", json=body)
        except httpx.HTTPError as exc:
            last_error = f"payments_unreachable: {type(exc).__name__}"
            log.warning("payments call failed (attempt %d): %s", attempt, exc)
        else:
            if r.status_code >= 500:
                last_error = _detail(r)
                log.warning("payments API %s (attempt %d): %s", r.status_code, attempt, last_error)
            elif r.status_code >= 400:
                # Definitive answer (no budget, unknown streamer, not payable...). Do not retry.
                err = _detail(r)
                log.info("tip for %s refused: %s", event.event_id, err)
                return PaymentResult(ok=False, status="failed", amount_cents=0, error=err)
            else:
                data = r.json()
                tip = data.get("tip") or {}
                status = data.get("status") or tip.get("status") or "failed"
                result = PaymentResult(
                    ok=status in ("paid", "pending"),
                    status=status if status in ("paid", "pending") else "failed",
                    amount_cents=int(data.get("amount_cents") or 0),
                    capped=bool(data.get("capped")),
                    error=tip.get("failure_reason") or (None if status in ("paid", "pending") else status),
                    tip_id=tip.get("id"),
                    stripe_transfer_id=tip.get("stripe_transfer_id"),
                    detection_id=data.get("detection_id"),
                )
                if status != "pending" or attempt == config.PAYMENTS_MAX_ATTEMPTS:
                    _campaign_cache["at"] = 0.0  # budget changed
                    log.info("tip %s for %s: %s %s", result.tip_id, event.event_id, result.status,
                             result.stripe_transfer_id or result.error or "")
                    return result
                last_error = "stripe_pending"  # Stripe hiccup: the same call retries the transfer safely
        await asyncio.sleep(2 * attempt)
    return PaymentResult(ok=False, status="failed", amount_cents=0, error=last_error)


def apply(event: BeverageEvent, result: PaymentResult) -> None:
    """Copy a payment result onto the event shown in the dashboard and sent to the webhook."""
    event.payment_status = result.status
    event.payment_error = result.error
    event.stripe_transfer_id = result.stripe_transfer_id
    event.tip_id = result.tip_id
    event.detection_id = result.detection_id
    if result.ok and result.amount_cents != event.suggested_tip_cents:
        event.requested_tip_cents = event.suggested_tip_cents
        event.suggested_tip_cents = result.amount_cents


async def campaign_status(max_age_seconds: float = 10) -> dict[str, Any]:
    """Budget left, brand and max tip for the dashboard (cached briefly)."""
    if not config.PAYMENTS_ENABLED:
        return {"enabled": False}
    now = time.monotonic()
    if _campaign_cache["data"] and now - _campaign_cache["at"] < max_age_seconds:
        return _campaign_cache["data"]
    try:
        r = await _client().get(f"/agent/campaigns/{config.SUPARADE_CAMPAIGN_ID}/context")
        if r.status_code != 200:
            return {"enabled": True, "ok": False, "error": _detail(r), "api_url": config.SUPARADE_API_URL}
        c = r.json()
    except httpx.HTTPError as exc:
        return {"enabled": True, "ok": False, "error": f"payments_unreachable: {type(exc).__name__}",
                "api_url": config.SUPARADE_API_URL}
    data = {
        "enabled": True,
        "ok": True,
        "api_url": config.SUPARADE_API_URL,
        "campaign_id": c.get("campaign_id"),
        "brand_name": c.get("brand_name"),
        "status": c.get("status"),
        "balance_cents": c.get("balance_cents"),
        "max_tip_cents": c.get("max_tip_cents"),
        "currency": c.get("currency"),
    }
    _campaign_cache.update(at=now, data=data)
    return data


async def max_tip_cents() -> Optional[int]:
    status = await campaign_status(max_age_seconds=60)
    return status.get("max_tip_cents") if status.get("ok") else None


async def _cli(streamer_id: str) -> None:
    if not config.PAYMENTS_ENABLED:
        sys.exit("Set SUPARADE_API_URL, SUPARADE_CAMPAIGN_ID and AGENT_API_KEY (or SUPARADE_AGENT_KEY) first.")
    print("campaign:", await campaign_status(0))
    event = BeverageEvent(
        session_id=f"cli-{uuid4().hex[:6]}", streamer_id=streamer_id, category="sports_drink_mention",
        confidence=0.99, description="Payments check from the command line", brand=config.SPONSOR_BRAND,
        stream_offset_seconds=0, suggested_tip_cents=50, status="paying",
    )
    result = await pay(event, None)
    print("payment:", result)
    print("campaign:", await campaign_status(0))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_cli(sys.argv[1] if len(sys.argv) > 1 else "demo-streamer"))
