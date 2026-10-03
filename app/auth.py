import hmac
from typing import Optional

from fastapi import Header, HTTPException

from app.config import get_settings
from app.db import get_supabase


def require_agent(x_agent_key: Optional[str] = Header(default=None)) -> None:
    """Agents (finder and tipper) authenticate with a shared secret in X-Agent-Key."""
    expected = get_settings().agent_api_key.encode()
    given = (x_agent_key or "").encode()
    if not hmac.compare_digest(given, expected):
        raise HTTPException(status_code=401, detail="invalid_agent_key")


def require_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """Frontend users send their Supabase access token as a Bearer token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    token = authorization[7:].strip()
    try:
        res = get_supabase().auth.get_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid_token")
    if not res or not getattr(res, "user", None):
        raise HTTPException(status_code=401, detail="invalid_token")
    return {"id": str(res.user.id)}
