import unittest

from app.services.fundamental_assessment_v4 import assess_fundamentals


class FundamentalAssessmentV4Test(unittest.TestCase):
    def test_negative_earnings_never_treats_pe_as_cheapness(self):
        result=assess_fundamentals({"eps":-2.0,"pe_ratio":4.0,"price_to_sales_ratio":2.0})
        self.assertFalse(result["valuation_applicability"]["pe_meaningful"])
        self.assertTrue(any(x["code"]=="pe_not_meaningful" for x in result["flags"]))

    def test_cheap_deteriorating_business_is_value_trap_risk(self):
        result=assess_fundamentals({
            "eps":4.0,
            "pe_ratio":8.0,
            "price_to_sales_ratio":1.0,
            "quarterly_revenue_growth_yoy":-0.20,
            "quarterly_earnings_growth_yoy":-0.35,
            "profit_margin":-0.04,
            "free_cash_flow":-1000000,
            "debt_to_equity":250,
        })
        self.assertEqual(result["anomaly"],"value_trap_risk")
        self.assertLess(result["quality_score"],45)
        self.assertGreaterEqual(result["valuation_score"],70)

    def test_margin_compression_is_explicit_deterioration(self):
        result=assess_fundamentals({
            "eps":3.0,
            "pe_ratio":10.0,
            "price_to_sales_ratio":1.5,
            "quarterly_revenue_growth_yoy":0.02,
            "quarterly_earnings_growth_yoy":-0.08,
            "profit_margin":0.10,
            "profit_margin_change_yoy_points":-5.0,
            "free_cash_flow":500000,
            "debt_to_equity":80,
        })
        self.assertTrue(any(x["code"]=="margin_compression" for x in result["flags"]))
        self.assertLess(result["scores"]["profitability"],70)
        self.assertEqual(result["anomaly"],"value_trap_risk")

    def test_quality_at_reasonable_value_is_separate_from_raw_cheapness(self):
        result=assess_fundamentals({
            "eps":5.0,
            "pe_ratio":18.0,
            "price_to_sales_ratio":3.0,
            "peg_ratio":1.1,
            "quarterly_revenue_growth_yoy":0.22,
            "quarterly_earnings_growth_yoy":0.25,
            "profit_margin":0.18,
            "return_on_equity":0.22,
            "free_cash_flow":2500000,
            "operating_cash_flow":3000000,
            "debt_to_equity":40,
            "current_ratio":2.0,
        })
        self.assertEqual(result["anomaly"],"quality_at_reasonable_value")
        self.assertGreaterEqual(result["quality_score"],65)
        self.assertGreaterEqual(result["valuation_score"],60)


if __name__=="__main__":
    unittest.main()
