import unittest

from app.services.opportunity_formula_v4 import (
    DEFAULT_FORMULA,
    formula_metadata,
    formula_score,
    normalized_weights,
    passes_filters,
    sort_index_rows,
    validate_filters,
    validate_formula,
    validate_sort,
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

    def test_hard_filters_screen_before_ranking(self):
        filters = validate_filters([
            {"field": "williams_r_14", "operator": "<=", "value": -80},
            {"field": "price_vs_ma100_percent", "operator": ">=", "value": 0},
        ])
        self.assertTrue(passes_filters({"williams_r_14": -85, "price_vs_ma100_percent": 2}, filters))
        self.assertFalse(passes_filters({"williams_r_14": -75, "price_vs_ma100_percent": 2}, filters))
        self.assertFalse(passes_filters({"williams_r_14": -85, "price_vs_ma100_percent": -1}, filters))

    def test_unknown_filter_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_filters([{"field": "future_leak", "operator": ">=", "value": 1}])

    def test_full_universe_sort_preserves_formula_rank(self):
        rows = [
            {"symbol": "AAA", "score": 90, "formula_rank": 1, "raw_criteria": {"williams": -60}},
            {"symbol": "BBB", "score": 80, "formula_rank": 2, "raw_criteria": {"williams": -90}},
            {"symbol": "CCC", "score": 70, "formula_rank": 3, "raw_criteria": {"williams": -75}},
        ]
        ordered, by, direction = sort_index_rows(rows, "williams", "asc")
        self.assertEqual([x["symbol"] for x in ordered], ["BBB", "CCC", "AAA"])
        self.assertEqual([x["formula_rank"] for x in ordered], [2, 3, 1])
        self.assertEqual([x["display_position"] for x in ordered], [1, 2, 3])
        self.assertEqual((by, direction), ("williams", "asc"))

    def test_invalid_sort_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_sort("future_return", "desc")
        with self.assertRaises(ValueError):
            validate_sort("score", "sideways")

    def test_score_is_explicitly_not_probability(self):
        meta = formula_metadata(DEFAULT_FORMULA)
        self.assertIn("not an expected-return or probability estimate", meta["score_semantics"])
        self.assertIn("never contribute points", meta["filter_semantics"])
        self.assertEqual(meta["schema_version"], "opportunity-formula-v1")


if __name__ == "__main__":
    unittest.main()
