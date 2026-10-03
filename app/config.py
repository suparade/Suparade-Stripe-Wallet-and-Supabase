import os
from dataclasses import dataclass
from functools import lru_cache


def _req(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_service_role_key: str
    stripe_secret_key: str
    stripe_webhook_secret: str
    agent_api_key: str
    frontend_url: str
    allow_dev_funding: bool
    allow_live_mode: bool
    creator_country: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        supabase_url=_req("SUPABASE_URL"),
        supabase_service_role_key=_req("SUPABASE_SERVICE_ROLE_KEY"),
        stripe_secret_key=_req("STRIPE_SECRET_KEY"),
        stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
        agent_api_key=_req("AGENT_API_KEY"),
        frontend_url=os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/"),
        allow_dev_funding=_flag("ALLOW_DEV_FUNDING"),
        allow_live_mode=_flag("ALLOW_LIVE_MODE"),
        creator_country=os.environ.get("CREATOR_COUNTRY", "US").upper(),
    )
