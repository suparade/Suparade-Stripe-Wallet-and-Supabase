"""conftest.py wins over .env values that are already in the process when a test starts."""
import pytest

from app.config import Settings, get_settings


@pytest.fixture(scope="module")
def developer_env():
    # Module scope sets this up before conftest's per-test fixture, like collecting backend/tests
    # (backend/config.py loads the real .env) or a shell that exports real keys. Importing app.main
    # then caches settings built from them.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SUPABASE_URL", "https://real-project.supabase.co")
        mp.setenv("SUPABASE_SERVICE_ROLE_KEY", "real-service-role-key")
        mp.setenv("STRIPE_SECRET_KEY", "sk_live_from_the_shell")
        mp.setenv("STRIPE_WEBHOOK_SECRET", "whsec_real")
        mp.setenv("AGENT_API_KEY", "real-agent-key")
        mp.setenv("ALLOW_DEV_FUNDING", "1")
        mp.setenv("ALLOW_LIVE_MODE", "1")
        get_settings.cache_clear()
        get_settings()
        yield
    get_settings.cache_clear()


def test_settings_ignore_the_developer_env(developer_env):
    assert get_settings() == Settings(
        supabase_url="http://localhost:54321",
        supabase_service_role_key="test",
        stripe_secret_key="sk_test_dummy",
        stripe_webhook_secret="",
        agent_api_key="secret",
        frontend_url="http://localhost:3000",
        allow_dev_funding=False,
        allow_live_mode=False,
        creator_country="US",
    )
