"""SessionManager._pay with the payments API stubbed. Run:  python -m unittest discover -s backend/tests -t ."""

import asyncio
import unittest
from unittest import mock

from backend import session_manager as sm
from backend import tip_policy
from backend.models import BeverageEvent, Moment
from backend.payments import PaymentResult
from backend.sources import Chunk


def make_event(**kw) -> BeverageEvent:
    base = dict(session_id="s1", streamer_id="demo-streamer", category="sports_drink_mention", confidence=0.9,
                description="Praises the drink", brand="Gatorade", stream_offset_seconds=12.0,
                suggested_tip_cents=450, status="pending_verification")
    return BeverageEvent(**{**base, **kw})


class PayFlowTest(unittest.TestCase):
    def setUp(self):
        # Python 3.9's asyncio.Queue (inside Session) needs a current loop at creation time.
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.addCleanup(self.loop.close)
        self.published = []
        self.emitted = []

        async def broadcast(msg):
            if msg["type"] == "event":
                self.published.append(msg["data"]["status"])

        async def emit_tip(ev):
            self.emitted.append(ev.event_id)

        for target, value in [
            ("backend.session_manager.save_evidence", mock.AsyncMock(return_value=("/evidence/c.mp4", None))),
            ("backend.session_manager.sink.broadcast", broadcast),
            ("backend.session_manager.sink.emit_tip", emit_tip),
            ("backend.session_manager.payments.max_tip_cents", mock.AsyncMock(return_value=500)),
        ]:
            p = mock.patch(target, value)
            p.start()
            self.addCleanup(p.stop)

        self.manager = sm.SessionManager()
        self.session = sm.Session(id="s1", source_type="url", streamer_id="demo-streamer", url="demo.mp4")
        self.chunk = Chunk(0, 0.0, b"x", "video/mp4")
        m = Moment(category="sports_drink_mention", confidence=0.9, offset_seconds=2.0, description="d",
                   brand="Gatorade", sentiment="positive", subject_type="real_person", looks_staged=False)
        self.reservation = tip_policy.reserve(self.session.tip_state, m, 12.0)

    async def _run(self, result: PaymentResult, event: BeverageEvent):
        with mock.patch("backend.session_manager.payments.pay", mock.AsyncMock(return_value=result)), \
             mock.patch.object(self.manager, "_enrich", mock.AsyncMock()):
            await self.manager._pay(self.session, self.chunk, event, 2.0, self.reservation)
            await asyncio.sleep(0)

    def test_paid_tip(self):
        ev = make_event()
        self.loop.run_until_complete(self._run(PaymentResult(ok=True, status="paid", amount_cents=450, tip_id="t1",
                                            stripe_transfer_id="tr_1"), ev))
        self.assertEqual(ev.status, "tipped")
        self.assertEqual(ev.stripe_transfer_id, "tr_1")
        self.assertEqual(self.session.tips_cents, 450)
        self.assertEqual(self.published[:2], ["paying", "tipped"])
        self.assertEqual(self.emitted, [ev.event_id])
        self.assertEqual(len(self.session.tip_state.recent_tips), 1)

    def test_failed_payment_releases_slot(self):
        ev = make_event()
        self.loop.run_until_complete(self._run(PaymentResult(ok=False, status="failed", amount_cents=0,
                                            error="insufficient_budget"), ev))
        self.assertEqual(ev.status, "payment_failed")
        self.assertEqual(ev.payment_error, "insufficient_budget")
        self.assertEqual(self.session.tips_cents, 0)
        self.assertEqual(self.emitted, [])
        self.assertEqual(len(self.session.tip_state.recent_tips), 0)
        self.assertIsNone(self.session.tip_state.last_tip_offset)

    def test_suggestion_capped_before_paying(self):
        ev = make_event(suggested_tip_cents=900)
        seen = {}

        async def fake_pay(event, url):
            seen["amount"] = event.suggested_tip_cents
            return PaymentResult(ok=True, status="paid", amount_cents=event.suggested_tip_cents)

        async def go():
            with mock.patch("backend.session_manager.payments.pay", fake_pay), \
                 mock.patch.object(self.manager, "_enrich", mock.AsyncMock()):
                await self.manager._pay(self.session, self.chunk, ev, 2.0, self.reservation)

        self.loop.run_until_complete(go())
        self.assertEqual(seen["amount"], 500)
        self.assertEqual((ev.suggested_tip_cents, ev.requested_tip_cents), (500, 900))


if __name__ == "__main__":
    unittest.main()
