import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/daily-report-v4-tests.db")

from app.services.opportunity_convergence import MODEL_CONFIG, MODEL_CONFIG_HASH, MODEL_VERSION, STATE_ORDER, _price_context, _quality
from app.services.typed_alerts import typed_trigger


class OpportunityConvergenceContractTests(unittest.TestCase):
    def test_saved_priority_thresholds_are_preserved(self):
        self.assertEqual(MODEL_CONFIG["williams_approach"], -70.0)
        self.assertEqual(MODEL_CONFIG["williams_trigger"], -80.0)
        self.assertEqual(MODEL_CONFIG["ma100_approach_range_pct"], [0.0, 7.0])
        self.assertGreater(len(MODEL_CONFIG_HASH), 6)
        self.assertTrue(MODEL_VERSION.startswith("opportunity-convergence-v"))

    def test_state_order_and_trigger_semantics(self):
        self.assertLess(STATE_ORDER["watching"], STATE_ORDER["approaching"])
        self.assertLess(STATE_ORDER["approaching"], STATE_ORDER["triggered"])
        self.assertFalse(typed_trigger("opportunity_convergence", float(STATE_ORDER["approaching"]), ">=", 3))
        self.assertTrue(typed_trigger("opportunity_convergence", float(STATE_ORDER["triggered"]), ">=", 3))

    def test_quality_uses_existing_point_in_time_components(self):
        q=_quality({"buy_score":70,"components":{"valuation":60,"sector":80}})
        self.assertAlmostEqual(q, 69.0)

    def test_stabilization_detects_decelerating_decline(self):
        class Bar:
            def __init__(self,close):self.close=close
        # Prior five-day window falls faster than the most recent five-day window.
        closes=[120,116,112,108,104,100,99,98.5,98,97.5,97]
        ctx=_price_context([Bar(x) for x in closes])
        self.assertTrue(ctx["stabilizing"])
        self.assertLess(ctx["drawdown_60d_pct"],0)

if __name__=="__main__":unittest.main()
