from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
ROT=(ROOT/'backend/app/services/rotation_model_v4.py').read_text()
FUN=(ROOT/'backend/app/services/candidate_funnel_v4.py').read_text()
SCH=(ROOT/'backend/app/services/refresh_scheduler.py').read_text()
class StackQueryEfficiency(unittest.TestCase):
    def test_rotation_bulk_loads_sector_snapshots(self):
        self.assertIn('def _all_daily_snapshots',ROT)
        self.assertIn('all_history=_all_daily_snapshots(db)',ROT)
        self.assertNotIn('history=_daily_snapshots(db,symbol)',ROT)
    def test_candidate_funnel_bulk_loads_market_and_features(self):
        self.assertIn('market_map=_latest_market_map(db,source_symbols)',FUN)
        self.assertIn('feature_map=_latest_feature_map(db,source_symbols)',FUN)
        self.assertNotIn('market=_latest_market(db,symbol);feature=_latest_feature(db,symbol)',FUN)
    def test_macro_refreshes_are_prioritized(self):
        self.assertIn('macro_boost = 40',SCH)
        self.assertIn('FRESHNESS_POLICIES["market"].priority + macro_boost',SCH)
if __name__=='__main__':unittest.main()
