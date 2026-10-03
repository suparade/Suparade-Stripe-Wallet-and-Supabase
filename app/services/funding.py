from app.config import get_settings
from app.db import get_supabase
from app.stripe_utils import get_stripe


def create_funding_checkout(campaign: dict, amount_cents: int) -> dict:
    """Create a Stripe Checkout Session that tops up a campaign budget.

    Link Agent Wallet pays this checkout: the brand's agent opens a spend request, the brand approves
    it in Link, and the agent completes this hosted checkout with the Link pay token. When Stripe
    reports the payment, the webhook credits the campaign ledger.
    """
    st, s = get_stripe(), get_settings()
    campaign_id = campaign["id"]
    session = st.checkout.Session.create(
        mode="payment",
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": campaign["currency"],
                    "unit_amount": amount_cents,
                    "product_data": {"name": f"Suparade campaign budget: {campaign['name']}"},
                },
            }
        ],
        success_url=f"{s.frontend_url}/campaigns/{campaign_id}?funded=1",
        cancel_url=f"{s.frontend_url}/campaigns/{campaign_id}?funded=0",
        metadata={"purpose": "campaign_funding", "campaign_id": campaign_id},
        payment_intent_data={"transfer_group": f"campaign_{campaign_id}"},
    )
    return {"checkout_url": session.url, "session_id": session.id}


def credit_campaign(campaign_id: str, amount_cents: int, ref: str) -> bool:
    res = get_supabase().rpc(
        "credit_campaign",
        {"p_campaign_id": campaign_id, "p_amount_cents": amount_cents, "p_ref": ref},
    ).execute()
    return bool(res.data)
