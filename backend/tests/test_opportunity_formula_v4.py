import unittest

from app.services.opportunity_formula_v4 import (
    DEFAULT_FORMULA,
    formula_metadata,
    formula_score,
    normalized_weights,
    validate_formula,
)


class OpportunityFormulaV4Test(unittest.TestCase):
    def test_default_formula_preserves_60_30_5_5(self):
        self.assertEqual(DEFAULT_FORMULA, {
            "williams": 60.0,
            "ma100_proximity": 30.0,
            "ma100_slope": 5.0,
            "approach_velocity": 5.0,
        })
        self.assertEqual(normalized_weights(DEFAULT_FORMULA), DEFAULT_FORMULA)

    def test_weights_are_scale_invariant(self):
        components = {
            "williams": 90.0,
            "ma100_proximity": 80.0,
            "ma100_slope": 70.0,
            "approach_velocity": 60.0,
        }
        score_a = formula_score(components, DEFAULT_FORMULA)
        score_b = formula_score(components, {
            "williams": 6,
            "ma100_proximity": 3,
            "ma100_slope": .5,
            "approach_velocity": .5,
        })
        self.assertEqual(score_a, 84.5)
        self.assertEqual(score_a, score_b)

    def test_formula_can_remove_a_criterion(self):
        components = {"williams": 100.0, "ma100_proximity": 0.0}
        self.assertEqual(formula_score(components, {"williams": 1}), 100.0)

    def test_unknown_or_nonpositive_weight_rejected(self):
        with self.assertRaises(ValueError):
            validate_formula({"made_up_factor": 1})
        with self.assertRaises(ValueError):
            validate_formula({"williams": 0})

    def test_score_is_explicitly_not_probability(self):
        meta = formula_metadata(DEFAULT_FORMULA)
        self.assertIn("not an expected-return or probability estimate", meta["score_semantics"])
        self.assertEqual(meta["schema_version"], "opportunity-formula-v1")


if __name__ == "__main__":
    unittest.main()
