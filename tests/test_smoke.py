import os

os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("AGENT_API_KEY", "secret")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"ok": True}


def test_agent_routes_require_key():
    assert client.post("/agent/tips", json={}).status_code == 401
    assert client.get("/agent/videos").status_code == 401
    assert client.get("/agent/videos", headers={"X-Agent-Key": "wrong"}).status_code == 401


def test_user_routes_require_bearer_token():
    assert client.post("/creators", json={"display_name": "x"}).status_code == 401
    assert client.post(
        "/campaigns/00000000-0000-0000-0000-000000000000/fund", json={"amount_cents": 100}
    ).status_code == 401


def test_tip_validation_rejects_bad_amounts():
    r = client.post(
        "/agent/tips",
        headers={"X-Agent-Key": "secret"},
        json={
            "detection_id": "00000000-0000-0000-0000-000000000000",
            "amount_cents": 0,
            "message": "nice",
        },
    )
    assert r.status_code == 422


def test_webhook_rejects_unsigned_payload():
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    from app.config import get_settings

    get_settings.cache_clear()
    r = client.post("/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "bad"})
    assert r.status_code == 400
