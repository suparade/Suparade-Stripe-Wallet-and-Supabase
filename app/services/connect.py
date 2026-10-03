"""Streamer (creator) payout accounts, built on Stripe Accounts v2.

Each creator gets a connected account with the Express dashboard and the recipient configuration,
which lets our platform send them transfers. The platform collects fees and carries losses
("application"; Stripe requires this for recipient accounts).
"""
import stripe

from app.config import get_settings
from app.db import get_supabase
from app.stripe_utils import as_dict, get_stripe


def _client() -> "stripe.StripeClient":
    get_stripe()  # enforces the live key guard
    return stripe.StripeClient(get_settings().stripe_secret_key)


def _get_creator(creator_id: str) -> dict:
    res = get_supabase().table("creators").select("*").eq("id", creator_id).limit(1).execute()
    if not res.data:
        raise LookupError("creator_not_found")
    return res.data[0]


def _contact_email(creator: dict) -> str:
    """Stripe requires a contact email. Use the signed up user's email, else a placeholder (fine in test mode)."""
    if creator.get("user_id"):
        try:
            user = get_supabase().auth.admin.get_user_by_id(str(creator["user_id"])).user
            if user and user.email:
                return user.email
        except Exception:
            pass
    return f"streamer+{str(creator['id'])[:8]}@example.com"


def recipient_account_params(display_name: str, creator_id: str, country: str, email: str) -> dict:
    return {
        "display_name": display_name,
        "contact_email": email,
        "dashboard": "express",
        "identity": {"country": country, "entity_type": "individual"},
        "defaults": {"responsibilities": {"fees_collector": "application", "losses_collector": "application"}},
        "configuration": {
            "recipient": {"capabilities": {"stripe_balance": {"stripe_transfers": {"requested": True}}}}
        },
        "metadata": {"creator_id": creator_id},
        "include": ["configuration.recipient"],
    }


def create_onboarding_link(creator_id: str) -> str:
    """Create (once) the creator's connected account and return a Stripe hosted onboarding URL."""
    sb, client, s = get_supabase(), _client(), get_settings()
    creator = _get_creator(creator_id)

    account_id = creator.get("stripe_account_id")
    if not account_id:
        account = client.v2.core.accounts.create(
            params=recipient_account_params(creator["display_name"], creator_id, s.creator_country, _contact_email(creator))
        )
        account_id = account.id
        sb.table("creators").update({"stripe_account_id": account_id}).eq("id", creator_id).execute()

    link = client.v2.core.account_links.create(
        params={
            "account": account_id,
            "use_case": {
                "type": "account_onboarding",
                "account_onboarding": {
                    "refresh_url": f"{s.frontend_url}/creator/onboarding?refresh=1",
                    "return_url": f"{s.frontend_url}/creator/onboarding?done=1",
                },
            },
        }
    )
    return link.url


def transfers_active(account: dict) -> bool:
    """True when the account's stripe_transfers capability is active (the creator can be paid)."""
    recipient = (account.get("configuration") or {}).get("recipient") or {}
    transfers = ((recipient.get("capabilities") or {}).get("stripe_balance") or {}).get("stripe_transfers") or {}
    return transfers.get("status") == "active"


def refresh_creator_status(creator_id: str) -> dict:
    """Pull the account from Stripe and sync transfers_enabled.

    v2 account events are not delivered to classic webhooks, so we check Stripe directly,
    both from the API and automatically right before a tip is reserved.
    """
    sb, client = get_supabase(), _client()
    creator = _get_creator(creator_id)
    account_id = creator.get("stripe_account_id")
    if not account_id:
        return {"creator_id": creator_id, "stripe_account_id": None, "transfers_enabled": False}

    account = as_dict(client.v2.core.accounts.retrieve(account_id, params={"include": ["configuration.recipient"]}))
    enabled = transfers_active(account)
    sb.table("creators").update({"transfers_enabled": enabled}).eq("id", creator_id).execute()
    return {"creator_id": creator_id, "stripe_account_id": account_id, "transfers_enabled": enabled}
