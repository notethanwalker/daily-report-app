import unittest

from app.services.candidate_funnel_formula_v4 import _attention_stage, _context_score


class FormulaCandidateFunnelV4Test(unittest.TestCase):
    def test_high_formula_score_alone_is_not_high_conviction(self):
        item = {
            "formula_score": 92,
            "convergence": {"state": "extended"},
            "enrichment_status": "full",
            "rotation_state": "leading_accelerating",
        }
        self.assertEqual(_attention_stage(item), "developing")

    def test_high_conviction_requires_readiness_enrichment_and_rotation_support(self):
        item = {
            "formula_score": 86,
            "convergence": {"state": "triggered"},
            "enrichment_status": "full",
            "rotation_state": "leading_stable",
        }
        self.assertEqual(_attention_stage(item), "high_conviction")

    def test_actionable_does_not_require_full_enrichment(self):
        item = {
            "formula_score": 75,
            "convergence": {"state": "approaching"},
            "enrichment_status": "scanner_only",
            "rotation_state": "unknown",
        }
        self.assertEqual(_attention_stage(item), "actionable")

    def test_context_score_keeps_formula_dominant(self):
        score_without_feature = _context_score(80, 10, 100, False)
        score_with_feature = _context_score(80, 10, 100, True)
        self.assertEqual(score_without_feature, 78.0)
        self.assertEqual(score_with_feature, 80.0)

    def test_context_score_is_bounded(self):
        self.assertEqual(_context_score(100, 100, 100, True), 100.0)
        self.assertGreaterEqual(_context_score(0, -100, 0, True), 0.0)


if __name__ == "__main__":
    unittest.main()
