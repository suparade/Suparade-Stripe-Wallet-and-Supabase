"""Pin the payments API settings so no test runs on a developer's real .env.

Collecting backend/tests imports backend/config.py, which loads backend/.env and the root .env
into os.environ before tests/ is collected. get_settings() and get_supabase() are cached, so
every test starts from the values below with both caches cleared.
"""
from dataclasses import fields

import pytest

from app.config import Settings, get_settings
from app.db import get_supabase

# Every Settings field is read from the env var of the same name in upper case. The required ones
# get dummies (tests send X-Agent-Key: secret); the rest are unset so the app's defaults apply.
REQUIRED_ENV = {
    "SUPABASE_URL": "http://localhost:54321",
    "SUPABASE_SERVICE_ROLE_KEY": "test",
    "STRIPE_SECRET_KEY": "sk_test_dummy",
    "AGENT_API_KEY": "secret",
}


@pytest.fixture(autouse=True)
def pinned_settings(monkeypatch):
    for field in fields(Settings):
        monkeypatch.delenv(field.name.upper(), raising=False)
    for name, value in REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    get_supabase.cache_clear()
    yield
    get_settings.cache_clear()
    get_supabase.cache_clear()
