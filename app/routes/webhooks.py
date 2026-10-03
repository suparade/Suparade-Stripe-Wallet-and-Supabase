import json
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import get_settings
from app.services.funding import credit_campaign
from app.stripe_utils import SignatureVerificationError, get_stripe

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(default=None)):
    """Handles checkout.session.completed (credits the budget).

    Creator payout status is not handled here: Accounts v2 sends its events through a separate system,
    so we poll Stripe instead (see services/connect.py).

    Every handler is idempotent on its own (ledger refs are unique, account sync is a plain update),
    so Stripe retries are harmless.
    """
    secret = get_settings().stripe_webhook_secret
    if not secret:
        raise HTTPException(500, "stripe_webhook_secret_not_configured")

    payload = await request.body()
    try:
        get_stripe().Webhook.construct_event(payload, stripe_signature or "", secret)
    except (ValueError, SignatureVerificationError):
        raise HTTPException(400, "invalid_signature")

    event = json.loads(payload)  # plain dict after the signature check
    obj = event["data"]["object"]

    if event["type"] == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        if meta.get("purpose") == "campaign_funding" and obj.get("payment_status") == "paid":
            credit_campaign(meta["campaign_id"], int(obj["amount_total"]), f"checkout:{obj['id']}")

    return {"received": True}
