import unittest

from app.services.candidate_funnel_formula_v4 import _apply_flow_confirmation_guardrail, _attention_stage, _context_score


class FormulaCandidateFunnelV4Test(unittest.TestCase):
    def test_high_formula_score_alone_is_not_high_conviction(self):
        item = {"formula_score": 92, "convergence": {"state": "extended"}, "feature_context_status": "available", "rotation_state": "leading_accelerating"}
        self.assertEqual(_attention_stage(item), "developing")

    def test_high_conviction_requires_readiness_feature_context_and_rotation_support(self):
        item = {"formula_score": 86, "convergence": {"state": "triggered"}, "feature_context_status": "available", "rotation_state": "leading_stable"}
        self.assertEqual(_attention_stage(item), "high_conviction")

    def test_high_conviction_fails_without_feature_context(self):
        item = {"formula_score": 90, "convergence": {"state": "triggered"}, "feature_context_status": "missing", "rotation_state": "leading_stable"}
        self.assertEqual(_attention_stage(item), "actionable")

    def test_actionable_does_not_require_feature_context(self):
        item = {"formula_score": 75, "convergence": {"state": "approaching"}, "feature_context_status": "missing", "rotation_state": "unknown"}
        self.assertEqual(_attention_stage(item), "actionable")

    def test_medium_bearish_flow_blocks_high_conviction_without_changing_score_or_rank(self):
        item = {
            "attention_stage": "high_conviction",
            "formula_score": 88.0,
            "formula_rank": 4,
            "candidate_context": {"persistent_flow": {"verdict": "contradiction", "direction": "bearish", "confidence": "medium"}},
        }
        _apply_flow_confirmation_guardrail(item)
        self.assertEqual(item["attention_stage"], "actionable")
        self.assertTrue(item["flow_guardrail_applied"])
        self.assertEqual(item["formula_score"], 88.0)
        self.assertEqual(item["formula_rank"], 4)
        self.assertEqual(item["flow_confirmation"]["score_effect"], 0)

    def test_bullish_flow_does_not_promote_stage(self):
        item = {
            "attention_stage": "actionable",
            "formula_score": 78.0,
            "formula_rank": 9,
            "candidate_context": {"persistent_flow": {"verdict": "confirmation", "direction": "bullish", "confidence": "medium"}},
        }
        _apply_flow_confirmation_guardrail(item)
        self.assertEqual(item["attention_stage"], "actionable")
        self.assertIsNone(item["decision_warning"])

    def test_context_score_keeps_formula_dominant(self):
        self.assertEqual(_context_score(80, 10, 100, False), 78.0)
        self.assertEqual(_context_score(80, 10, 100, True), 80.0)

    def test_context_score_is_bounded(self):
        self.assertEqual(_context_score(100, 100, 100, True), 100.0)
        self.assertGreaterEqual(_context_score(0, -100, 0, True), 0.0)


if __name__ == "__main__":
    unittest.main()
