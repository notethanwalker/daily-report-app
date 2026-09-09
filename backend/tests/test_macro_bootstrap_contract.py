from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
S=(ROOT/'backend/app/services/refresh_scheduler.py').read_text()
class MacroBootstrapContract(unittest.TestCase):
    def test_macro_uses_batch_warm_path(self):
        self.assertIn('def bootstrap_macro_cache',S)
        self.assertIn('provider.batch_daily_history(missing,period="2y")',S)
        self.assertIn('bootstrap_macro_cache(db)',S)
        self.assertIn('satisfied_by_macro_batch_bootstrap',S)
    def test_bootstrap_is_bounded_and_cache_first(self):
        self.assertIn('MARKET_MIN_TECHNICAL_BARS',S)
        self.assertIn('missing=[s for s in symbols if s not in covered]',S)
if __name__=='__main__':unittest.main()
