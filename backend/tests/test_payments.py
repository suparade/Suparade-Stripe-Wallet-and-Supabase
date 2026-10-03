"""Run:  .venv/bin/python -m unittest discover -s backend/tests -t ."""

import asyncio
import json
import unittest
from unittest import mock

import httpx

from backend import config, payments
from backend.models import BeverageEvent


def event(**kw) -> BeverageEvent:
    base = dict(session_id="s1", streamer_id="demo-streamer", category="sports_drink_mention",
                confidence=0.9, description="Praises the drink", brand="Gatorade",
                stream_offset_seconds=12.0, suggested_tip_cents=300)
    return BeverageEvent(**{**base, **kw})


def run(coro):
    return asyncio.run(coro)


class PaymentsTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.responses = []
        patches = [
            mock.patch.object(config, "PAYMENTS_ENABLED", True),
            mock.patch.object(config, "SUPARADE_API_URL", "http://pay.test"),
            mock.patch.object(config, "SUPARADE_AGENT_KEY", "k"),
            mock.patch.object(config, "SUPARADE_CAMPAIGN_ID", "camp-1"),
            mock.patch.object(payments.asyncio, "sleep", mock.AsyncMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            status, body = self.responses.pop(0)
            return httpx.Response(status, json=body)

        payments._http = httpx.AsyncClient(base_url="http://pay.test", headers={"X-Agent-Key": "k"},
                                           transport=httpx.MockTransport(handler))
        self.addCleanup(setattr, payments, "_http", None)

    def test_paid(self):
        self.responses = [(200, {"status": "paid", "amount_cents": 300, "capped": False, "detection_id": "d1",
                                 "tip": {"id": "t1", "status": "paid", "stripe_transfer_id": "tr_1"}})]
        e = event(alert_message="Gatorade just tipped $3!")
        r = run(payments.pay(e, "backend/demo/demo_stream.mp4"))
        self.assertTrue(r.ok)
        self.assertEqual((r.status, r.stripe_transfer_id, r.tip_id), ("paid", "tr_1", "t1"))
        sent = json.loads(self.calls[0].content)
        self.assertEqual(sent["campaign_id"], "camp-1")
        self.assertEqual(sent["source_url"], "backend/demo/demo_stream.mp4")
        self.assertEqual(sent["message"], "Gatorade just tipped $3!")
        self.assertEqual(self.calls[0].headers["X-Agent-Key"], "k")
        self.assertTrue(self.calls[0].url.path.endswith("/agent/stream-events"))

    def test_refusal_is_not_retried(self):
        self.responses = [(409, {"detail": "insufficient_budget"})]
        r = run(payments.pay(event(), None))
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "insufficient_budget")
        self.assertEqual(len(self.calls), 1)

    def test_server_error_then_success_is_retried(self):
        self.responses = [(502, {"detail": "bad gateway"}),
                          (200, {"status": "paid", "amount_cents": 300,
                                 "tip": {"id": "t1", "status": "paid", "stripe_transfer_id": "tr_1"}})]
        r = run(payments.pay(event(), None))
        self.assertTrue(r.ok)
        self.assertEqual(len(self.calls), 2)

    def test_stripe_pending_is_retried_with_same_event(self):
        pending = (200, {"status": "pending", "amount_cents": 300, "tip": {"id": "t1", "status": "pending"}})
        paid = (200, {"status": "paid", "amount_cents": 300,
                      "tip": {"id": "t1", "status": "paid", "stripe_transfer_id": "tr_1"}})
        self.responses = [pending, paid]
        r = run(payments.pay(event(), None))
        self.assertEqual(r.status, "paid")
        ids = {json.loads(c.content)["event_id"] for c in self.calls}
        self.assertEqual(len(ids), 1)

    def test_failed_transfer(self):
        self.responses = [(200, {"status": "failed", "amount_cents": 300,
                                 "tip": {"id": "t1", "status": "failed", "failure_reason": "balance_insufficient"}})]
        r = run(payments.pay(event(), None))
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "balance_insufficient")

    def test_apply_records_cap(self):
        e = event(suggested_tip_cents=900)
        payments.apply(e, payments.PaymentResult(ok=True, status="paid", amount_cents=500, capped=True,
                                                 tip_id="t1", stripe_transfer_id="tr_1"))
        self.assertEqual((e.suggested_tip_cents, e.requested_tip_cents), (500, 900))
        self.assertEqual((e.payment_status, e.stripe_transfer_id), ("paid", "tr_1"))


class SimulatedTest(unittest.TestCase):
    def test_simulated_when_not_configured(self):
        with mock.patch.object(config, "PAYMENTS_ENABLED", False):
            r = run(payments.pay(event(), None))
            self.assertEqual((r.ok, r.status, r.amount_cents), (True, "simulated", 300))
            self.assertEqual(run(payments.campaign_status()), {"enabled": False})


if __name__ == "__main__":
    unittest.main()
