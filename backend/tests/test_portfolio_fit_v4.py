import unittest

from app.services.portfolio_fit_v4 import _correlation, _fit_score, _weighted_portfolio_returns


class PortfolioFitV4Test(unittest.TestCase):
    def test_weighted_portfolio_returns_renormalizes_available_holdings(self):
        returns = {
            "A": {"2026-09-01": 0.10, "2026-09-02": 0.02},
            "B": {"2026-09-01": -0.10},
        }
        result = _weighted_portfolio_returns(returns, {"A": 0.6, "B": 0.4})
        self.assertAlmostEqual(result["2026-09-01"], 0.02)
        self.assertAlmostEqual(result["2026-09-02"], 0.02)

    def test_correlation_requires_minimum_observations(self):
        a = {f"d{i}": float(i) for i in range(19)}
        b = {f"d{i}": float(i) for i in range(19)}
        corr, n = _correlation(a, b)
        self.assertIsNone(corr)
        self.assertEqual(n, 19)

    def test_correlation_detects_high_overlap(self):
        a = {f"d{i}": float(i) for i in range(25)}
        b = {f"d{i}": float(i) * 2 for i in range(25)}
        corr, n = _correlation(a, b)
        self.assertAlmostEqual(corr, 1.0)
        self.assertEqual(n, 25)

    def test_fit_score_omits_missing_components_and_renormalizes(self):
        score, coverage = _fit_score({
            "existing_position": {"score": 100},
            "sector_concentration": {"score": 50},
            "theme_overlap": {"score": None},
            "correlation": {"score": None},
        })
        self.assertAlmostEqual(score, (100 * .25 + 50 * .30) / .55, places=2)
        self.assertEqual(coverage, .55)

    def test_fit_score_is_not_expected_return_probability(self):
        score, _ = _fit_score({
            "existing_position": {"score": 100},
            "sector_concentration": {"score": 100},
            "theme_overlap": {"score": 100},
            "correlation": {"score": 100},
        })
        self.assertEqual(score, 100.0)
        # A score of 100 only means maximum fit under the heuristic inputs.
        self.assertIsInstance(score, float)


if __name__ == "__main__":
    unittest.main()
