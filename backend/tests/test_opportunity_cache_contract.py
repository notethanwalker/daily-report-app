from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
FUN=(ROOT/'backend/app/services/candidate_funnel_v4.py').read_text()
ROUTE=(ROOT/'backend/app/routers/stack_v4.py').read_text()
START=(ROOT/'backend/app/start.py').read_text()
class OpportunityCacheContract(unittest.TestCase):
    def test_shortlist_bars_are_limited_in_sql(self):
        self.assertIn('row_number().over',FUN)
        self.assertIn('ranked.c.rn<=per_symbol',FUN)
    def test_ui_endpoint_prefers_persisted_snapshot(self):
        self.assertIn('get_candidate_funnel_cache(db,limit)',ROUTE)
        self.assertIn('served_from_cache',FUN)
    def test_background_candidate_snapshot_runs(self):
        self.assertIn('async def candidate_snapshot_loop',FUN)
        self.assertIn('candidate_snapshot_loop()',START)
if __name__=='__main__':unittest.main()
