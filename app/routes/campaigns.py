from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_agent, require_user
from app.config import get_settings
from app.db import get_supabase
from app.schemas import DevCreditIn, FundIn
from app.services.funding import create_funding_checkout, credit_campaign

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _owned_campaign(campaign_id: UUID, user: dict) -> dict:
    sb = get_supabase()
    rows = sb.table("campaigns").select("*, brands(owner_id)").eq("id", str(campaign_id)).limit(1).execute().data
    if not rows:
        raise HTTPException(404, "campaign_not_found")
    campaign = rows[0]
    if (campaign.get("brands") or {}).get("owner_id") != user["id"]:
        raise HTTPException(403, "not_your_campaign")
    return campaign


@router.post("/{campaign_id}/fund")
def fund_campaign(campaign_id: UUID, body: FundIn, user: dict = Depends(require_user)):
    """Returns a Stripe Checkout URL. The brand's Link agent pays it; the webhook credits the budget."""
    campaign = _owned_campaign(campaign_id, user)
    return create_funding_checkout(campaign, body.amount_cents)


@router.post("/{campaign_id}/dev-credit", dependencies=[Depends(require_agent)])
def dev_credit(campaign_id: UUID, body: DevCreditIn):
    """Demo fallback: credit a campaign without a payment. Disabled unless ALLOW_DEV_FUNDING=1."""
    if not get_settings().allow_dev_funding:
        raise HTTPException(403, "dev_funding_disabled")
    import uuid

    credited = credit_campaign(str(campaign_id), body.amount_cents, f"dev:{uuid.uuid4()}")
    return {"credited": credited}
