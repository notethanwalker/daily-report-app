from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
ROTATION=(ROOT/"backend/app/services/rotation_model_v4.py").read_text(encoding="utf-8")


class RotationQueryBoundsContract(unittest.TestCase):
    def test_primary_rotation_query_has_rolling_bound(self):
        self.assertIn("ROTATION_QUERY_LOOKBACK_DAYS",ROTATION)
        self.assertIn("MarketSnapshot.retrieved_at>=cutoff",ROTATION)

    def test_sparse_history_fallback_is_symbol_scoped_and_bounded(self):
        self.assertIn("for symbol in missing",ROTATION)
        self.assertIn("MarketSnapshot.symbol==symbol",ROTATION)
        self.assertIn(".limit(limit_days*8)",ROTATION)


if __name__=="__main__":
    unittest.main()
