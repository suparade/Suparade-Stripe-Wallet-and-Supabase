"""Pure helpers of the MCP server on Supabase Compute (supabase/compute/mcp/logic.py)."""

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "supabase" / "compute" / "mcp" / "logic.py"
_spec = importlib.util.spec_from_file_location("suparade_mcp_logic", _PATH)
logic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(logic)

CAMPAIGN = "850978ce-6a21-48d7-950f-fcddc2869d70"


def test_service_key_prefers_the_service_role_key():
    assert logic.service_key({"SUPABASE_SERVICE_ROLE_KEY": "jwt", "SUPABASE_SECRET_KEYS": '{"default": "sb_secret_x"}'}) == "jwt"
    assert logic.service_key({"SUPABASE_SECRET_KEYS": '{"default": "sb_secret_x"}'}) == "sb_secret_x"
    assert logic.service_key({"SUPABASE_SECRET_KEYS": '{"jobs": "sb_secret_y"}'}) == "sb_secret_y"
    assert logic.service_key({"SUPABASE_SECRET_KEYS": "sb_secret_raw"}) == "sb_secret_raw"
    assert logic.service_key({}) == ""


def test_rest_headers_send_new_keys_as_apikey_only():
    assert logic.rest_headers("sb_secret_x") == {"apikey": "sb_secret_x"}
    assert logic.rest_headers("eyJ.jwt") == {"apikey": "eyJ.jwt", "Authorization": "Bearer eyJ.jwt"}


def test_keys_match_needs_two_equal_non_empty_keys():
    assert logic.keys_match("secret", "secret")
    assert not logic.keys_match("secret", "other")
    assert not logic.keys_match("", "")
    assert not logic.keys_match("secret", "")


def test_key_cache_forgets_keys_after_the_ttl():
    now = [100.0]
    cache = logic.KeyCache(ttl_seconds=60, clock=lambda: now[0])
    assert not cache.accepted("k")
    cache.accept("k")
    assert cache.accepted("k")
    assert not cache.accepted("other")
    now[0] = 161.0
    assert not cache.accepted("k")


def test_campaign_uuid_rejects_anything_but_a_uuid():
    assert logic.campaign_uuid(f" {CAMPAIGN.upper()} ") == CAMPAIGN
    with pytest.raises(ValueError, match="campaign UUID"):
        logic.campaign_uuid("eq.x&select=*")


@pytest.mark.parametrize("given, expected", [(10, 10), (0, 1), (500, 50), ("7", 7), ("x", 10), (None, 10)])
def test_clamp_limit(given, expected):
    assert logic.clamp_limit(given) == expected


def test_money():
    assert logic.money(750, "usd") == "7.50 USD"
    assert logic.money(0, None) == "0.00 USD"
    assert logic.money(None) is None


def test_campaign_shapes_budget_and_brand():
    row = {"id": CAMPAIGN, "name": "Sips", "type": "brand_mention", "status": "active", "max_tip_cents": 500,
           "currency": "usd", "brand_context": "Electrolytes", "brands": {"name": "Gatorade"}}
    out = logic.campaign(row, 11943)
    assert out["brand"] == "Gatorade"
    assert out["budget_left"] == "119.43 USD"
    assert out["max_tip"] == "5.00 USD"


def test_sighting_reads_the_tip_and_makes_evidence_links_absolute():
    row = {"id": "d1", "kind": "brand_mention", "brand": "Gatorade", "quote": "this hits", "confidence": 0.92,
           "timestamp_seconds": 41, "created_at": "2026-10-03T22:00:00Z",
           "meta": {"thumbnail_url": "/evidence/s1/t.jpg", "verifier_reason": "real sip"},
           "tips": {"status": "paid", "amount_cents": 750, "currency": "usd"}}
    out = logic.sighting(row, "https://ref.supabase.co/compute/v1/detector")
    assert out["tip"] == {"status": "paid", "amount": "7.50 USD"}
    assert out["details"]["thumbnail_url"] == "https://ref.supabase.co/compute/v1/detector/evidence/s1/t.jpg"
    assert out["details"]["verifier_reason"] == "real sip"


def test_sighting_without_a_tip_or_with_a_tip_list():
    assert logic.sighting({"id": "d1", "tips": None})["tip"] is None
    assert logic.sighting({"id": "d1", "tips": []})["tip"] is None
    assert logic.sighting({"id": "d1", "tips": [{"status": "failed", "amount_cents": 100}]})["tip"]["status"] == "failed"


def test_tip_includes_creator_and_transfer():
    row = {"id": "t1", "status": "paid", "amount_cents": 750, "currency": "usd", "message": "Thanks!",
           "reasoning": "clear sip", "stripe_transfer_id": "tr_1", "creators": {"display_name": "Demo Streamer"}}
    out = logic.tip(row)
    assert out["creator"] == "Demo Streamer"
    assert out["stripe_transfer_id"] == "tr_1"
    assert out["amount"] == "7.50 USD"


def test_scout_status_summarises_sessions():
    health = {"ok": True, "sponsor_brand": "Gatorade", "model": "gemini-flash-latest", "payments_enabled": True}
    sessions = [{"id": "s1", "url": "https://twitch.tv/x", "streamer_id": "demo-streamer", "chunks_analyzed": 4,
                 "events_detected": 1, "sponsor_screen_seconds": 6.5, "source_exited": False}]
    out = logic.scout_status(health, sessions)
    assert out["online"] is True
    assert out["watching"][0]["session_id"] == "s1"
    assert out["watching"][0]["moments_detected"] == 1
