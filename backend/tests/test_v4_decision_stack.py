import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/daily-report-v4-tests.db")

from app.services.rotation_model_v4 import _state
from app.services.opportunity_scanner import _bucket


class RotationStateTests(unittest.TestCase):
    def test_leading_accelerating(self):
        self.assertEqual(_state(2.0, 0.8, 4.0), ("leading_accelerating", "inflow_candidate"))

    def test_leading_weakening(self):
        self.assertEqual(_state(2.0, -0.8, 4.0), ("leading_weakening", "rotation_out_risk"))

    def test_lagging_improving(self):
        self.assertEqual(_state(-2.0, 0.8, -3.0), ("lagging_improving", "early_rotation_candidate"))


class CandidateSetupTests(unittest.TestCase):
    def test_strong_williams_and_100ma_setup(self):
        self.assertEqual(_bucket(-85.0, 2.0), "strong")

    def test_below_100ma_is_not_entry_setup(self):
        self.assertIsNone(_bucket(-90.0, -1.0))


if __name__ == "__main__":
    unittest.main()
