"""POST /agent/stream-events with an in-memory Supabase and a fake Stripe settle step."""
import os
import re
import uuid

os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("AGENT_API_KEY", "secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import stream_events  # noqa: E402
from app.services.tips import TipError  # noqa: E402


class _Res:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.op, self.payload, self.opts = db, table, [], "select", None, {}
        self._single = False

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: str(r.get(col)) == str(val))
        return self

    def ilike(self, col, pattern):
        literal = re.sub(r"\\(.)", r"\1", pattern)
        self.filters.append(lambda r: (r.get(col) or "").lower() == literal.lower())
        return self

    def limit(self, _):
        return self

    def single(self):
        self._single = True
        return self

    def upsert(self, row, on_conflict, ignore_duplicates=False):
        self.op, self.payload, self.opts = "upsert", row, {"key": on_conflict, "ignore": ignore_duplicates}
        return self

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        if self.op == "upsert":
            key = self.opts["key"]
            existing = next((r for r in rows if r.get(key) == self.payload[key]), None)
            if existing and self.opts["ignore"]:
                return _Res([])
            if existing:
                existing.update(self.payload)
                return _Res([existing])
            row = {"id": str(uuid.uuid4()), **self.payload}
            rows.append(row)
            return _Res([row])
        found = [r for r in rows if all(f(r) for f in self.filters)]
        return _Res(found[0] if self._single else found)


class FakeSupabase:
    def __init__(self):
        self.db = {}

    def table(self, name):
        return _Query(self.db, name)


CAMPAIGN = "850978ce-6a21-48d7-950f-fcddc2869d70"
CREATOR = "2d77942e-f6a4-44d6-b554-347d45c211a9"


@pytest.fixture
def env(monkeypatch):
    sb = FakeSupabase()
    sb.db["campaigns"] = [{"id": CAMPAIGN, "type": "brand_mention", "status": "active", "max_tip_cents": 500}]
    sb.db["creators"] = [{"id": CREATOR, "display_name": "Demo Streamer", "handle": "demo-streamer",
                          "stripe_account_id": "acct_x", "transfers_enabled": True}]
    tips = {}

    def fake_reserve(detection_id, amount, message, reasoning, show_at):
        if amount > 400:
            raise TipError("insufficient_budget", 409)
        return tips.setdefault(detection_id, {"id": str(uuid.uuid4()), "detection_id": detection_id,
                                              "amount_cents": amount, "message": message,
                                              "reasoning": reasoning, "status": "pending"})

    def fake_settle(tip):
        tip.update(status="paid", stripe_transfer_id="tr_test")
        return tip

    monkeypatch.setattr(stream_events, "get_supabase", lambda: sb)
    monkeypatch.setattr(stream_events, "reserve_tip", fake_reserve)
    monkeypatch.setattr(stream_events, "settle_tip", fake_settle)
    return sb, tips


client = TestClient(app)
H = {"X-Agent-Key": "secret"}


def event(**kw):
    base = {
        "campaign_id": CAMPAIGN, "event_id": "evt-1", "session_id": "abc123", "streamer_id": "Demo-Streamer",
        "category": "sports_drink_mention", "confidence": 0.95, "description": "Streamer praises the drink.",
        "quote": "this hits", "brand": "Gatorade", "stream_offset_seconds": 13.3, "suggested_tip_cents": 300,
        "source_url": "backend/demo/demo_stream.mp4", "verification_reason": "clearly drinks it",
        "audience_reaction": "high",
    }
    return {**base, **kw}


def test_requires_agent_key():
    assert client.post("/agent/stream-events", json=event()).status_code == 401


def test_pays_and_is_idempotent(env):
    sb, tips = env
    r = client.post("/agent/stream-events", json=event(), headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "paid" and body["tip"]["stripe_transfer_id"] == "tr_test"
    assert body["amount_cents"] == 300 and not body["capped"]
    assert "Gatorade tipped $3.00" in body["tip"]["message"]
    assert "clearly drinks it" in body["tip"]["reasoning"]

    det = sb.db["detections"][0]
    assert det["kind"] == "brand_mention" and det["category"] == "sports_drink_mention"
    assert det["meta"]["audience_reaction"] == "high" and "campaign_id" not in det["meta"]
    assert sb.db["videos"][0]["url"] == "local://demo_stream.mp4"
    assert sb.db["videos"][0]["creator_id"] == CREATOR

    again = client.post("/agent/stream-events", json=event(), headers=H).json()
    assert again["detection_id"] == body["detection_id"] and again["tip"]["id"] == body["tip"]["id"]
    assert len(sb.db["detections"]) == 1 and len(tips) == 1


def test_caps_amount_and_uses_custom_message(env):
    r = client.post("/agent/stream-events", headers=H,
                    json=event(event_id="evt-2", suggested_tip_cents=900, message="Hydration hero!"))
    # capped to 500, then the fake budget (400) rejects it
    assert r.status_code == 409 and r.json()["detail"] == "insufficient_budget"
    r = client.post("/agent/stream-events", headers=H,
                    json=event(event_id="evt-3", suggested_tip_cents=350, message="Hydration hero!"))
    assert r.json()["tip"]["message"] == "Hydration hero!"


def test_unknown_streamer_and_campaign(env):
    r = client.post("/agent/stream-events", headers=H, json=event(streamer_id="someone-else"))
    assert r.status_code == 409 and r.json()["detail"] == "unknown_streamer"
    r = client.post("/agent/stream-events", headers=H, json=event(campaign_id=str(uuid.uuid4())))
    assert r.status_code == 404


def test_streamer_by_uuid_and_webcam_video(env):
    sb, _ = env
    r = client.post("/agent/stream-events", headers=H,
                    json=event(event_id="evt-4", streamer_id=CREATOR, source_url=None))
    assert r.status_code == 200
    assert sb.db["videos"][0]["url"] == "browser://abc123" and sb.db["videos"][0]["platform"] == "browser"


def test_zero_amount_is_logged_not_paid(env):
    r = client.post("/agent/stream-events", headers=H, json=event(event_id="evt-5", suggested_tip_cents=0))
    assert r.json()["status"] == "skipped_zero_amount" and r.json()["tip"] is None
