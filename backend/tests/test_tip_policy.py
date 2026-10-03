"""Run:  .venv/bin/python -m unittest discover -s backend/tests -t ."""

import unittest

from backend import config, tip_policy
from backend.gemini_analyzer import is_competitor, is_sponsor
from backend.models import ClipAnalysis, Moment, SafetyFlags


def moment(**kw) -> Moment:
    base = dict(category="sports_drink_mention", confidence=0.9, offset_seconds=1.0,
                description="test", brand="Gatorade", sentiment="positive",
                subject_type="real_person", looks_staged=False)
    return Moment(**{**base, **kw})


def clip(**kw) -> ClipAnalysis:
    safety = dict(alcohol=False, vaping=False, nsfw=False, slurs=False, gambling=False)
    safety.update(kw.pop("safety", {}))
    base = dict(detected=True, moments=[], brand_exposures=[], safety=SafetyFlags(**safety),
                on_screen_subject="real_person", looks_prerecorded_or_looped=False, clip_summary="")
    return ClipAnalysis(**{**base, **kw})


def evaluate(m=None, c=None, offset=100.0, state=None, competitor=False):
    return tip_policy.evaluate(m or moment(), c or clip(), offset, state or tip_policy.TipState(), competitor)


class TipPolicyTest(unittest.TestCase):
    def test_clean_positive_mention_passes(self):
        self.assertEqual(evaluate(), [])

    def test_negative_and_sarcastic_mentions_blocked(self):
        self.assertIn("sentiment:negative", evaluate(moment(sentiment="negative")))
        self.assertIn("sentiment:sarcastic", evaluate(moment(sentiment="sarcastic")))

    def test_neutral_mention_blocked_but_neutral_drinking_allowed(self):
        self.assertIn("sentiment:neutral", evaluate(moment(sentiment="neutral")))
        self.assertEqual(evaluate(moment(category="drinking_water", sentiment="neutral", brand=None)), [])

    def test_competitor_blocked(self):
        self.assertIn("competitor_brand", evaluate(moment(brand="Prime"), competitor=True))

    def test_animated_subject_blocked(self):
        self.assertIn("subject:animated_character", evaluate(moment(subject_type="animated_character")))

    def test_safety_flag_blocks(self):
        self.assertIn("safety:alcohol", evaluate(c=clip(safety={"alcohol": True})))

    def test_staged_and_looped_blocked(self):
        self.assertIn("looks_staged", evaluate(moment(looks_staged=True)))
        self.assertIn("prerecorded_or_looped", evaluate(c=clip(looks_prerecorded_or_looped=True)))

    def test_cooldown(self):
        state = tip_policy.TipState()
        tip_policy.reserve(state, moment(), 100.0)
        self.assertIn("cooldown", evaluate(offset=110.0, state=state))
        self.assertNotIn("cooldown", evaluate(offset=100.0 + config.COOLDOWN_SECONDS, state=state))

    def test_repetition(self):
        state = tip_policy.TipState()
        for i in range(config.REPEAT_LIMIT):
            tip_policy.reserve(state, moment(), 100.0 + i * 60)
        later = 100.0 + config.REPEAT_LIMIT * 60
        self.assertIn("repetitive", evaluate(offset=later, state=state))
        self.assertNotIn("repetitive", evaluate(moment(brand="Water"), offset=later, state=state))

    def test_release_restores_state(self):
        state = tip_policy.TipState()
        r = tip_policy.reserve(state, moment(), 100.0)
        tip_policy.release(state, r)
        self.assertIsNone(state.last_tip_offset)
        self.assertEqual(len(state.recent_tips), 0)

    def test_exposure_blocks(self):
        self.assertEqual(tip_policy.evaluate_exposure(clip()), [])
        self.assertIn("subject:video_playback",
                      tip_policy.evaluate_exposure(clip(on_screen_subject="video_playback")))

    def test_brand_matching(self):
        self.assertTrue(is_sponsor("gatorade zero"))
        self.assertTrue(is_competitor("PRIME Hydration"))
        self.assertFalse(is_competitor("Gatorade"))
        self.assertFalse(is_competitor(None))


if __name__ == "__main__":
    unittest.main()
