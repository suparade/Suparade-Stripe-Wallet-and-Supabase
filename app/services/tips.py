from datetime import datetime, timezone
from typing import Optional

from postgrest.exceptions import APIError

from app.db import get_supabase
from app.services.connect import refresh_creator_status
from app.stripe_utils import InvalidRequestError, StripeError, get_stripe

# Error codes raised by the reserve_tip SQL function, mapped to HTTP status codes.
RESERVE_ERRORS = {
    "detection_not_found": 404,
    "campaign_not_active": 409,
    "amount_out_of_range": 422,
    "video_has_no_creator": 409,
    "creator_not_payable": 409,
    "insufficient_budget": 409,
}


class TipError(Exception):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _one(data):
    return data[0] if isinstance(data, list) else data


def _refresh_creator_if_needed(detection_id: str) -> None:
    """If the creator finished onboarding but we have not seen it yet, check Stripe before reserving."""
    sb = get_supabase()
    det = sb.table("detections").select("video_id").eq("id", detection_id).limit(1).execute().data
    if not det:
        return
    vid = sb.table("videos").select("creator_id").eq("id", det[0]["video_id"]).limit(1).execute().data
    if not vid or not vid[0]["creator_id"]:
        return
    cr = (
        sb.table("creators")
        .select("id,stripe_account_id,transfers_enabled")
        .eq("id", vid[0]["creator_id"])
        .limit(1)
        .execute()
        .data
    )
    if cr and cr[0]["stripe_account_id"] and not cr[0]["transfers_enabled"]:
        try:
            refresh_creator_status(cr[0]["id"])
        except StripeError:
            pass  # reserve_tip will report creator_not_payable


def reserve_tip(
    detection_id: str,
    amount_cents: int,
    message: str,
    reasoning: str,
    show_at_seconds: Optional[float],
) -> dict:
    """Atomically check the budget and write the tip plus its ledger debit."""
    _refresh_creator_if_needed(detection_id)
    try:
        res = get_supabase().rpc(
            "reserve_tip",
            {
                "p_detection_id": detection_id,
                "p_amount_cents": amount_cents,
                "p_message": message,
                "p_reasoning": reasoning,
                "p_show_at_seconds": show_at_seconds,
            },
        ).execute()
    except APIError as e:
        code = (e.message or "").strip()
        if code in RESERVE_ERRORS:
            raise TipError(code, RESERVE_ERRORS[code])
        raise
    return _one(res.data)


def settle_tip(tip: dict) -> dict:
    """Send the Stripe transfer for a pending tip and flip it to paid.

    Safe to call again for the same tip: the Stripe idempotency key is derived from the tip id,
    so a retry returns the original transfer instead of paying twice.
    """
    if tip["status"] != "pending":
        return tip

    sb, st = get_supabase(), get_stripe()
    creator = sb.table("creators").select("stripe_account_id").eq("id", tip["creator_id"]).single().execute().data

    try:
        transfer = st.Transfer.create(
            amount=tip["amount_cents"],
            currency=tip["currency"],
            destination=creator["stripe_account_id"],
            transfer_group=f"campaign_{tip['campaign_id']}",
            metadata={"tip_id": tip["id"], "detection_id": tip["detection_id"]},
            idempotency_key=f"tip-{tip['id']}",
        )
    except InvalidRequestError as e:
        # Definitive rejection (for example not enough platform balance). Refund the campaign budget.
        res = get_supabase().rpc("fail_tip", {"p_tip_id": tip["id"], "p_reason": str(e)[:500]}).execute()
        return _one(res.data)
    except StripeError:
        # Network or server trouble: the transfer may or may not exist. Leave the tip pending
        # so a retry with the same idempotency key resolves it safely.
        return tip

    updated = (
        sb.table("tips")
        .update(
            {
                "status": "paid",
                "stripe_transfer_id": transfer.id,
                "paid_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", tip["id"])
        .execute()
    )
    return updated.data[0]
