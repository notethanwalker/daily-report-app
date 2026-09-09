import os
import unittest
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
from app.services import refresh_scheduler as rs

class BootstrapMemoryGuardTests(unittest.TestCase):
    def test_defaults_are_bounded_for_free_render(self):
        self.assertEqual(rs._broad_bootstrap_memory_limit_mb(), 400.0)
        self.assertTrue(rs._yahoo_safe_symbol("AAPL"))
        self.assertTrue(rs._yahoo_safe_symbol("BRK-B"))
        self.assertFalse(rs._yahoo_safe_symbol("BAC$E"))
        self.assertFalse(rs._yahoo_safe_symbol("BF.A"))

    def test_rss_reader_is_nonnegative(self):
        self.assertGreaterEqual(rs._process_rss_mb(), 0.0)
