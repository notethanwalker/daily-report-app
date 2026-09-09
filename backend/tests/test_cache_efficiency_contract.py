from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCHEDULER = (ROOT / "backend/app/services/refresh_scheduler.py").read_text(encoding="utf-8")


class CacheEfficiencyContract(unittest.TestCase):
    def test_fundamentals_are_reserved_for_company_equities(self):
        self.assertIn("def _fundamentals_supported", SCHEDULER)
        self.assertIn('{"stock", "equity"}', SCHEDULER)
        self.assertIn('_fundamentals_supported(db, symbol)', SCHEDULER)
        self.assertIn('!= "VIX"', SCHEDULER)


if __name__ == "__main__":
    unittest.main()
