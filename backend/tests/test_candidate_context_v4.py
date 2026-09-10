import unittest

from app.services.candidate_context_v4 import candidate_fundamental_targets, candidate_intelligence_targets


class CandidateContextV4Test(unittest.TestCase):
    def test_targets_highest_priority_stale_or_missing_fundamentals(self):
        rows = [
            {"symbol": "WATCH", "attention_stage": "watch", "contextual_priority_score": 90, "formula_score": 95, "candidate_context": {"sections": {"fundamentals": {"fresh": False}}}},
            {"symbol": "ACTION", "attention_stage": "actionable", "contextual_priority_score": 75, "formula_score": 75, "candidate_context": {"sections": {"fundamentals": {"fresh": False}}}},
            {"symbol": "HIGH", "attention_stage": "high_conviction", "contextual_priority_score": 82, "formula_score": 84, "candidate_context": {"sections": {"fundamentals": {"fresh": False}}}},
            {"symbol": "FRESH", "attention_stage": "high_conviction", "contextual_priority_score": 99, "formula_score": 99, "candidate_context": {"sections": {"fundamentals": {"fresh": True}}}},
        ]
        self.assertEqual(candidate_fundamental_targets(rows, limit=3), ["HIGH", "ACTION", "WATCH"])

    def test_fundamental_target_limit_is_bounded(self):
        rows = [
            {"symbol": f"S{i}", "attention_stage": "developing", "contextual_priority_score": 100-i, "formula_score": 80, "candidate_context": {"sections": {"fundamentals": {"fresh": False}}}}
            for i in range(20)
        ]
        self.assertEqual(len(candidate_fundamental_targets(rows, limit=100)), 12)

    def test_intelligence_targets_only_stale_context_and_prioritizes_stage(self):
        fresh_sections = {"news": {"fresh": True}, "flow": {"fresh": True}, "catalysts": {"fresh": True}, "filings": {"fresh": True}}
        stale_sections = {"news": {"fresh": False}, "flow": {"fresh": True}, "catalysts": {"fresh": True}, "filings": {"fresh": True}}
        rows = [
            {"symbol": "WATCH", "attention_stage": "watch", "contextual_priority_score": 99, "formula_score": 99, "candidate_context": {"sections": stale_sections}},
            {"symbol": "ACTION", "attention_stage": "actionable", "contextual_priority_score": 70, "formula_score": 70, "candidate_context": {"sections": stale_sections}},
            {"symbol": "HIGH", "attention_stage": "high_conviction", "contextual_priority_score": 80, "formula_score": 80, "candidate_context": {"sections": stale_sections}},
            {"symbol": "FRESH", "attention_stage": "high_conviction", "contextual_priority_score": 100, "formula_score": 100, "candidate_context": {"sections": fresh_sections}},
        ]
        self.assertEqual(candidate_intelligence_targets(rows, limit=3), ["HIGH", "ACTION", "WATCH"])

    def test_stale_filing_alone_targets_candidate_for_context_refresh(self):
        rows = [{
            "symbol": "FILING",
            "attention_stage": "actionable",
            "contextual_priority_score": 82,
            "formula_score": 79,
            "candidate_context": {"sections": {
                "news": {"fresh": True},
                "flow": {"fresh": True},
                "catalysts": {"fresh": True},
                "filings": {"fresh": False},
            }},
        }]
        self.assertEqual(candidate_intelligence_targets(rows, limit=5), ["FILING"])

    def test_intelligence_refresh_limit_is_hard_capped(self):
        stale = {"news": {"fresh": False}, "flow": {"fresh": False}, "catalysts": {"fresh": False}, "filings": {"fresh": False}}
        rows = [
            {"symbol": f"S{i}", "attention_stage": "developing", "contextual_priority_score": 100-i, "formula_score": 80, "candidate_context": {"sections": stale}}
            for i in range(20)
        ]
        self.assertEqual(len(candidate_intelligence_targets(rows, limit=100)), 5)


if __name__ == "__main__":
    unittest.main()
