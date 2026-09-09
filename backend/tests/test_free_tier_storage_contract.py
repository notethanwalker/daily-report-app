from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
START = (ROOT / "backend/app/start.py").read_text(encoding="utf-8")
GUARD = (ROOT / "backend/app/services/storage_guard.py").read_text(encoding="utf-8")
IMPORTER = (ROOT / "backend/app/services/stooq_durable_import.py").read_text(encoding="utf-8")
MODEL = (ROOT / "backend/app/normalized_market_models.py").read_text(encoding="utf-8")


class FreeTierStorageContract(unittest.TestCase):
    def test_broad_background_ingestion_is_opt_in(self):
        self.assertIn("if broad_ingest_enabled()", START)
        self.assertNotIn(
            "asyncio.create_task(scheduler_loop());asyncio.create_task(bulk_market_loop())",
            START,
        )

    def test_database_archive_upload_is_disabled_in_free_tier_mode(self):
        self.assertIn("and not free_tier_mode()", GUARD)
        self.assertIn("require_bulk_capacity(db)", IMPORTER)

    def test_capacity_has_headroom_below_provider_limit(self):
        self.assertIn("400 * 1024 * 1024", GUARD)
        self.assertIn("DEFAULT_STOP_RATIO = 0.90", GUARD)

    def test_disposable_timestamp_index_is_not_recreated(self):
        line = next(line for line in MODEL.splitlines() if "retrieved_at:" in line)
        self.assertNotIn("index=True", line)


if __name__ == "__main__":
    unittest.main()
