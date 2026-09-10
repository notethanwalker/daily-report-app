import unittest
from datetime import date

from app.services.candidate_evidence_v4 import classify_catalysts, classify_flow, classify_news


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


if __name__ == "__main__":
    unittest.main()
