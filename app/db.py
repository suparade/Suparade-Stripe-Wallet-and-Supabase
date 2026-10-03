from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Service role client. Bypasses RLS, so it must never be exposed to the browser."""
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_role_key)
