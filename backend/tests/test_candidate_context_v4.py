import unittest

from app.services.candidate_context_v4 import candidate_fundamental_targets


class CandidateContextV4Test(unittest.TestCase):
    def test_targets_highest_priority_stale_or_missing_fundamentals(self):
        rows = [
            {"symbol": "WATCH", "attention_stage": "watch", "contextual_priority_score": 90, "formula_score": 95, "candidate_context": {"sections": {"fundamentals": {"fresh": False}}}},
            {"symbol": "ACTION", "attention_stage": "actionable", "contextual_priority_score": 75, "formula_score": 75, "candidate_context": {"sections": {"fundamentals": {"fresh": False}}}},
            {"symbol": "HIGH", "attention_stage": "high_conviction", "contextual_priority_score": 82, "formula_score": 84, "candidate_context": {"sections": {"fundamentals": {"fresh": False}}}},
            {"symbol": "FRESH", "attention_stage": "high_conviction", "contextual_priority_score": 99, "formula_score": 99, "candidate_context": {"sections": {"fundamentals": {"fresh": True}}}},
        ]
        self.assertEqual(candidate_fundamental_targets(rows, limit=3), ["HIGH", "ACTION", "WATCH"])

    def test_target_limit_is_bounded(self):
        rows = [
            {"symbol": f"S{i}", "attention_stage": "developing", "contextual_priority_score": 100-i, "formula_score": 80, "candidate_context": {"sections": {"fundamentals": {"fresh": False}}}}
            for i in range(20)
        ]
        self.assertEqual(len(candidate_fundamental_targets(rows, limit=100)), 12)


if __name__ == "__main__":
    unittest.main()
