import unittest
from datetime import date

from app.services.candidate_evidence_v4 import classify_catalysts, classify_filings, classify_flow, classify_news, synthesize_context_verdict


class CandidateEvidenceV4Test(unittest.TestCase):
    def test_news_stays_neutral_without_explicit_directional_language(self):
        bundle = {"sections": {"news": {"available": True, "fresh": True}}, "news": {"top": [{"title": "Company schedules investor presentation"}]}}
        result = classify_news(bundle)
        self.assertEqual(result["label"], "neutral")
        self.assertEqual(result["confidence"], "low")

    def test_news_detects_explicit_negative_event_language(self):
        bundle = {"sections": {"news": {"available": True, "fresh": True}}, "news": {"top": [{"title": "Company cuts guidance after weak quarter"}]}}
        result = classify_news(bundle)
        self.assertEqual(result["label"], "potentially_negative")
        self.assertEqual(result["direction"], "bearish")

    def test_near_high_impact_catalyst_is_high_urgency(self):
        bundle = {"sections": {"catalysts": {"available": True, "fresh": True}}, "catalysts": {"upcoming": [{"date": "2026-09-15", "impact": "high", "title": "Earnings"}]}}
        result = classify_catalysts(bundle, today=date(2026, 9, 10))
        self.assertEqual(result["urgency"], "high")
        self.assertEqual(result["days_until"], 5)

    def test_recent_8k_is_event_information_not_directional(self):
        bundle = {"sections": {"filings": {"available": True, "fresh": True}}, "filings": {"top": [{"form": "8-K", "filed_at": "2026-09-08"}]}}
        result = classify_filings(bundle, today=date(2026, 9, 10))
        self.assertEqual(result["label"], "recent_event_disclosure")
        self.assertEqual(result["direction"], "unknown")
        self.assertEqual(result["urgency"], "medium")

    def test_flow_requires_consistent_corroboration(self):
        event = {"data": {"side": "call", "aggression": "buy"}}
        bundle = {"sections": {"flow": {"available": True, "fresh": True}}, "flow": {"top": [event, event]}}
        result = classify_flow(bundle)
        self.assertEqual(result["label"], "confirmation")
        self.assertEqual(result["direction"], "bullish")

    def test_single_directional_flow_is_only_weak_context(self):
        bundle = {"sections": {"flow": {"available": True, "fresh": True}}, "flow": {"top": [{"data": {"side": "put", "aggression": "buy"}}]}}
        result = classify_flow(bundle)
        self.assertEqual(result["label"], "mixed")
        self.assertEqual(result["confidence"], "low")

    def test_positive_news_is_supportive_but_score_effect_stays_zero(self):
        result = synthesize_context_verdict(
            {"label": "potentially_positive"},
            {"label": "none_known", "urgency": "low"},
        )
        self.assertEqual(result["label"], "supportive")
        self.assertEqual(result["score_effect"], 0)

    def test_urgent_catalyst_is_event_risk_not_directional_confirmation(self):
        result = synthesize_context_verdict(
            {"label": "neutral"},
            {"label": "upcoming", "urgency": "high"},
        )
        self.assertEqual(result["label"], "neutral")
        self.assertTrue(result["event_risk"])
        self.assertEqual(result["score_effect"], 0)

    def test_recent_filing_can_raise_event_risk_without_direction(self):
        result = synthesize_context_verdict(
            {"label": "neutral"},
            {"label": "none_known", "urgency": "low"},
            {"label": "recent_event_disclosure", "urgency": "medium"},
        )
        self.assertEqual(result["label"], "neutral")
        self.assertTrue(result["event_risk"])
        self.assertEqual(result["score_effect"], 0)

    def test_missing_news_catalyst_and_filings_are_insufficient(self):
        result = synthesize_context_verdict(
            {"label": "missing"},
            {"label": "missing", "urgency": "unknown"},
            {"label": "missing", "urgency": "unknown"},
        )
        self.assertEqual(result["label"], "insufficient")


if __name__ == "__main__":
    unittest.main()
