from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SERVICE = (ROOT / "backend/app/services/opportunity_bulk_ingest.py").read_text()
ROUTER = (ROOT / "backend/app/routers/opportunity_scanner.py").read_text()
WORKER = (ROOT / "scripts/opportunity_bulk_worker.py").read_text()


class OpportunityCoverageDiagnosticsContract(unittest.TestCase):
    def test_only_insufficient_history_is_removed_from_denominator(self):
        self.assertIn("eligible_stocks - min(insufficient, eligible_stocks)", SERVICE)
        self.assertIn("Provider-unavailable symbols remain gaps", SERVICE)

    def test_diagnostics_are_persisted_and_exposed(self):
        self.assertIn("DIAGNOSTICS_STATE_KEY", SERVICE)
        self.assertIn("save_coverage_diagnostics", ROUTER)
        self.assertIn('bulk-coverage-diagnostics', ROUTER)
        self.assertIn('coverage_diagnostics', ROUTER)

    def test_worker_only_persists_complete_residual_scan(self):
        self.assertIn("complete_residual_scan", WORKER)
        self.assertIn("and not hard_failures and effective_coverage", WORKER)
        self.assertIn("provider_unavailable_or_invalid", WORKER)


if __name__ == "__main__":
    unittest.main()
