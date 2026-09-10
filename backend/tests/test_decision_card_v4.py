import unittest

from app.services.decision_card_v4 import build_decision_card


class DecisionCardV4Test(unittest.TestCase):
    def base_candidate(self):
        return {
            "symbol": "TEST",
            "formula_score": 86.0,
            "formula_rank": 3,
            "williams_r_14": -84.0,
            "price_vs_ma100_percent": 2.0,
            "raw_criteria": {"ma100_slope": 1.2, "approach_velocity": 0.8},
            "convergence": {"state": "triggered"},
            "rotation_state": "leading_stable",
            "verification_status": "verified",
            "feature_context_status": "available",
            "attention_stage": "high_conviction",
            "candidate_context": {
                "sections": {
                    "fundamentals": {"available": True, "fresh": True},
                    "news": {"available": True, "fresh": True},
                    "catalysts": {"available": True, "fresh": True},
                    "filings": {"available": True, "fresh": True},
                    "flow": {"available": True, "fresh": True},
                },
                "evidence": {"context_verdict": {"label": "supportive", "event_risk": False, "score_effect": 0}},
                "persistent_flow": {"verdict": "confirmation", "direction": "bullish", "confidence": "medium"},
            },
            "portfolio_fit": {"available": True, "score": 72.0, "confidence": "high", "status": "experimental"},
            "portfolio_adjusted_rank": 2,
            "flow_confirmation": {"verdict": "confirmation", "direction": "bullish", "confidence": "medium", "score_effect": 0},
        }

    def test_card_has_no_master_score(self):
        card = build_decision_card(self.base_candidate())
        self.assertNotIn("score", card)
        self.assertIn("asset_opportunity", card)
        self.assertIn("portfolio_fit", card)
        self.assertNotEqual(card["asset_opportunity"]["score"], card["portfolio_fit"]["score"])

    def test_supportive_setup_builds_bull_case(self):
        card = build_decision_card(self.base_candidate())
        joined = " ".join(card["bull_case"]).lower()
        self.assertIn("williams", joined)
        self.assertIn("100-day", joined)
        self.assertIn("flow", joined)

    def test_bearish_flow_is_blocker_but_does_not_change_asset_score(self):
        candidate = self.base_candidate()
        candidate["candidate_context"]["persistent_flow"] = {"verdict": "contradiction", "direction": "bearish", "confidence": "medium"}
        candidate["flow_confirmation"] = {"verdict": "contradiction", "direction": "bearish", "confidence": "medium", "score_effect": 0}
        candidate["decision_warning"] = "Medium-confidence persistent bearish flow contradicts the long setup. Formula score and rank are unchanged."
        card = build_decision_card(candidate)
        self.assertEqual(card["asset_opportunity"]["score"], 86.0)
        self.assertTrue(any("bearish" in x.lower() for x in card["blockers"]))

    def test_event_risk_is_not_bullish_confirmation(self):
        candidate = self.base_candidate()
        candidate["candidate_context"]["evidence"]["context_verdict"] = {"label": "neutral", "event_risk": True, "score_effect": 0}
        card = build_decision_card(candidate)
        self.assertTrue(any("event risk" in x.lower() for x in card["bear_case"]))

    def test_limited_data_creates_confidence_blocker(self):
        candidate = self.base_candidate()
        candidate["feature_context_status"] = "missing"
        for state in candidate["candidate_context"]["sections"].values():
            state["available"] = False
            state["fresh"] = False
        card = build_decision_card(candidate)
        self.assertEqual(card["data_quality"]["label"], "limited")
        self.assertTrue(any("data quality" in x.lower() for x in card["blockers"]))


if __name__ == "__main__":
    unittest.main()
