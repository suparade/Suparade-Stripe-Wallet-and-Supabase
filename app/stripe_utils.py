import json

import stripe

from app.config import get_settings

try:  # newer stripe-python exposes errors at the top level
    from stripe import InvalidRequestError, SignatureVerificationError, StripeError  # noqa: F401
except ImportError:  # older versions keep them in stripe.error
    from stripe.error import InvalidRequestError, SignatureVerificationError, StripeError  # noqa: F401


def get_stripe():
    """Return the configured stripe module. Refuses live keys unless explicitly allowed."""
    s = get_settings()
    if s.stripe_secret_key.startswith("sk_live_") and not s.allow_live_mode:
        raise RuntimeError(
            "Live Stripe key detected. Set ALLOW_LIVE_MODE=1 only when you really mean to move real money."
        )
    stripe.api_key = s.stripe_secret_key
    return stripe


def as_dict(obj) -> dict:
    """Convert a StripeObject into a plain dict regardless of stripe-python version.

    Newer stripe-python versions return objects that are not dicts, so .get() and ['key'] can fail.
    """
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:
            pass
    return json.loads(str(obj))
