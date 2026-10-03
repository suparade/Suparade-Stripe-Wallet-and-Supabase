"""Pure helpers for the Suparade MCP server (server.py).

No imports from the mcp package, so the tests in tests/test_compute_mcp.py run without it.
"""

import hashlib
import hmac
import json
import time
from typing import Callable, Mapping, Optional
from uuid import UUID


def service_key(env: Mapping[str, str]) -> str:
    """The key used to read Postgres: the service role key, or the default secret key."""
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if key:
        return key
    raw = env.get("SUPABASE_SECRET_KEYS", "").strip()
    if not raw:
        return ""
    try:
        keys = json.loads(raw)
    except ValueError:
        return raw
    if isinstance(keys, dict) and keys:
        return str(keys.get("default") or next(iter(keys.values())))
    return ""


def rest_headers(key: str) -> dict:
    """PostgREST headers. New sb_ keys go in apikey only; legacy JWT keys also go in Authorization."""
    headers = {"apikey": key}
    if not key.startswith("sb_"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def keys_match(given: str, expected: str) -> bool:
    return bool(given) and bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class KeyCache:
    """Agent keys the payments API accepted recently, so each MCP request doesn't re-check them."""

    def __init__(self, ttl_seconds: float = 300, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._expiry: dict = {}

    def accepted(self, key: str) -> bool:
        expires = self._expiry.get(_digest(key))
        return expires is not None and expires > self._clock()

    def accept(self, key: str) -> None:
        self._expiry[_digest(key)] = self._clock() + self._ttl


def campaign_uuid(value: str) -> str:
    try:
        return str(UUID(str(value).strip()))
    except ValueError:
        raise ValueError("campaign_id must be a campaign UUID; list_campaigns returns them") from None


def clamp_limit(limit, default: int = 10, maximum: int = 50) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, maximum))


def money(cents, currency: Optional[str] = "usd") -> Optional[str]:
    if cents is None:
        return None
    return f"{int(cents) / 100:.2f} {(currency or 'usd').upper()}"


def _one(embedded):
    """PostgREST embeds a one-to-one relation as an object, older versions as a list."""
    if isinstance(embedded, list):
        return embedded[0] if embedded else None
    return embedded or None


def absolute_links(meta: Mapping, detector_url: str) -> dict:
    """Evidence paths the detector stores (/evidence/...) as URLs an agent can open."""
    out = {}
    for name, value in (meta or {}).items():
        if isinstance(value, str) and value.startswith("/evidence/") and detector_url:
            value = f"{detector_url}{value}"
        out[name] = value
    return out


def campaign(row: Mapping, balance_cents: int) -> dict:
    currency = row.get("currency") or "usd"
    return {
        "campaign_id": row.get("id"),
        "name": row.get("name"),
        "brand": (_one(row.get("brands")) or {}).get("name"),
        "status": row.get("status"),
        "type": row.get("type"),
        "budget_left": money(balance_cents, currency),
        "max_tip": money(row.get("max_tip_cents"), currency),
        "brand_context": row.get("brand_context") or "",
    }


def sighting(row: Mapping, detector_url: str = "") -> dict:
    tip = _one(row.get("tips"))
    return {
        "detection_id": row.get("id"),
        "seen_at": row.get("created_at"),
        "kind": row.get("kind"),
        "category": row.get("category"),
        "brand": row.get("brand"),
        "quote": row.get("quote"),
        "description": row.get("description"),
        "confidence": row.get("confidence"),
        "stream_seconds": row.get("timestamp_seconds"),
        "tip": {"status": tip.get("status"), "amount": money(tip.get("amount_cents"), tip.get("currency"))} if tip else None,
        "details": absolute_links(row.get("meta") or {}, detector_url),
    }


def tip(row: Mapping) -> dict:
    return {
        "tip_id": row.get("id"),
        "status": row.get("status"),
        "amount": money(row.get("amount_cents"), row.get("currency")),
        "creator": (_one(row.get("creators")) or {}).get("display_name"),
        "message": row.get("message"),
        "reasoning": row.get("reasoning"),
        "stripe_transfer_id": row.get("stripe_transfer_id"),
        "failure_reason": row.get("failure_reason"),
        "created_at": row.get("created_at"),
        "paid_at": row.get("paid_at"),
    }


def scout_status(health: Mapping, sessions: list) -> dict:
    return {
        "online": bool(health.get("ok")),
        "sponsor_brand": health.get("sponsor_brand"),
        "model": health.get("model"),
        "verify_model": health.get("verify_model"),
        "payments_enabled": health.get("payments_enabled"),
        "watching": [
            {
                "session_id": s.get("id"),
                "url": s.get("url"),
                "streamer_id": s.get("streamer_id"),
                "clips_analyzed": s.get("chunks_analyzed"),
                "moments_detected": s.get("events_detected"),
                "sponsor_screen_seconds": s.get("sponsor_screen_seconds"),
                "ended": s.get("source_exited"),
            }
            for s in sessions
        ],
    }
