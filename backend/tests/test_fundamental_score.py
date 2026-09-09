import unittest

from app.services.fundamental_score import build_fundamental_score


class FundamentalScoreTests(unittest.TestCase):
    def test_score_is_explicitly_informational(self):
        result = build_fundamental_score({
            "quarterly_revenue_growth_yoy": 0.25,
            "profit_margin": 0.15,
            "pe_ratio": 22,
            "debt_to_equity": 0.4,
            "free_cash_flow": 1000000,
        })
        self.assertIsNotNone(result["score"])
        self.assertTrue(result["informational_only"])
        self.assertFalse(result["affects_allocation"])
        self.assertGreaterEqual(result["coverage"], 0.8)

    def test_missing_fundamentals_are_not_invented(self):
        result = build_fundamental_score({})
        self.assertIsNone(result["score"])
        self.assertEqual(result["grade"], "insufficient data")
        self.assertEqual(result["coverage"], 0.0)


if __name__ == "__main__":
    unittest.main()
