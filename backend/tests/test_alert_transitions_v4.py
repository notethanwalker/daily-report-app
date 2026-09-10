import unittest

from app.services.alert_transition_logic_v4 import combined_technical_state, ma100_approach_state, transition_entered, williams_state


class AlertTransitionsV4Test(unittest.TestCase):
    def test_first_observation_does_not_emit_williams_entry(self):
        self.assertFalse(transition_entered("williams_oversold_entry", None, "oversold", {}))
        self.assertTrue(transition_entered("williams_oversold_entry", "recovered", "oversold", {}))

    def test_williams_recovery_requires_prior_oversold(self):
        self.assertFalse(transition_entered("williams_oversold_recovery", None, "recovered", {}))
        self.assertFalse(transition_entered("williams_oversold_recovery", "recovered", "recovered", {}))
        self.assertTrue(transition_entered("williams_oversold_recovery", "oversold", "recovered", {}))

    def test_ma100_approach_requires_extended_above_prior_state(self):
        self.assertTrue(transition_entered("ma100_approach_from_above", "extended", "approaching", {}))
        self.assertFalse(transition_entered("ma100_approach_from_above", "below", "approaching", {}))
        self.assertFalse(transition_entered("ma100_approach_from_above", None, "approaching", {}))

    def test_combined_trigger_is_edge_triggered_after_state_established(self):
        self.assertFalse(transition_entered("williams_ma100_trigger", None, "triggered", {}))
        self.assertTrue(transition_entered("williams_ma100_trigger", "watching", "triggered", {}))
        self.assertFalse(transition_entered("williams_ma100_trigger", "triggered", "triggered", {}))

    def test_invalidation_is_edge_triggered(self):
        self.assertFalse(transition_entered("opportunity_invalidated", None, "invalidated", {}))
        self.assertTrue(transition_entered("opportunity_invalidated", "triggered", "invalidated", {}))

    def test_convergence_still_requires_alert_ready(self):
        self.assertFalse(transition_entered("opportunity_convergence", "approaching", "triggered", {"alert_ready": False}))
        self.assertTrue(transition_entered("opportunity_convergence", "approaching", "triggered", {"alert_ready": True}))

    def test_saved_formula_score_alert_is_crossing_only(self):
        self.assertFalse(transition_entered("opportunity_formula_score", None, "at_or_above", {}))
        self.assertTrue(transition_entered("opportunity_formula_score", "below", "at_or_above", {}))
        self.assertFalse(transition_entered("opportunity_formula_score", "at_or_above", "at_or_above", {}))

    def test_saved_formula_rank_alert_is_top_n_entry_only(self):
        self.assertFalse(transition_entered("opportunity_formula_rank", None, "inside", {}))
        self.assertTrue(transition_entered("opportunity_formula_rank", "outside", "inside", {}))
        self.assertFalse(transition_entered("opportunity_formula_rank", "inside", "inside", {}))

    def test_candidate_context_change_ignores_initial_and_unavailable_states(self):
        self.assertFalse(transition_entered("candidate_context_changed", None, "supportive|event_risk:0", {}))
        self.assertTrue(transition_entered("candidate_context_changed", "neutral|event_risk:0", "contradictory|event_risk:0", {}))
        self.assertFalse(transition_entered("candidate_context_changed", "supportive|event_risk:0", "unavailable", {}))
        self.assertTrue(transition_entered("candidate_context_changed", "supportive|event_risk:0", "supportive|event_risk:1", {}))

    def test_candidate_flow_change_requires_semantic_flow_state(self):
        self.assertFalse(transition_entered("candidate_flow_changed", None, "confirmation", {}))
        self.assertTrue(transition_entered("candidate_flow_changed", "mixed", "confirmation", {}))
        self.assertTrue(transition_entered("candidate_flow_changed", "confirmation", "contradiction", {}))
        self.assertFalse(transition_entered("candidate_flow_changed", "confirmation", "unavailable", {}))

    def test_portfolio_concentration_breach_is_entry_only(self):
        self.assertFalse(transition_entered("portfolio_concentration_breach", None, "breached", {}))
        self.assertTrue(transition_entered("portfolio_concentration_breach", "within_limit", "breached", {}))
        self.assertFalse(transition_entered("portfolio_concentration_breach", "breached", "breached", {}))

    def test_market_state_classifiers(self):
        _, oversold = williams_state({"williams_r_14": -82, "as_of": "2026-09-10"})
        _, recovered = williams_state({"williams_r_14": -79, "as_of": "2026-09-10"})
        self.assertEqual(oversold["state"], "oversold")
        self.assertEqual(recovered["state"], "recovered")

        _, approaching = ma100_approach_state({"price_vs_ma100_percent": 3.0, "as_of": "2026-09-10"})
        _, below = ma100_approach_state({"price_vs_ma100_percent": -1.0, "as_of": "2026-09-10"})
        self.assertEqual(approaching["state"], "approaching")
        self.assertEqual(below["state"], "below")

        value, combined = combined_technical_state({"williams_r_14": -85, "price_vs_ma100_percent": 2.0, "as_of": "2026-09-10"})
        self.assertEqual(value, 1.0)
        self.assertEqual(combined["state"], "triggered")


if __name__ == "__main__":
    unittest.main()