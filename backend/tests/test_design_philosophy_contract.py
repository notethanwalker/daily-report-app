from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCANNER = (ROOT / "backend/app/services/opportunity_scanner.py").read_text(encoding="utf-8")
PIPELINE = (ROOT / "backend/app/services/market_data_pipeline.py").read_text(encoding="utf-8")
FUNNEL = (ROOT / "backend/app/services/candidate_funnel_v4.py").read_text(encoding="utf-8")
V4 = (ROOT / "web/app/v4/page.tsx").read_text(encoding="utf-8")
V4_CSS = (ROOT / "web/app/v4/v4.css").read_text(encoding="utf-8")
PHILOSOPHY = (ROOT / "docs/DAILY_REPORT_APP_DESIGN_PHILOSOPHY.md").read_text(encoding="utf-8")
STACK = (ROOT / "backend/app/routers/stack_v4.py").read_text(encoding="utf-8")
MAIN = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
GDELT = (ROOT / "backend/app/providers/gdelt.py").read_text(encoding="utf-8")


class DesignPhilosophyContract(unittest.TestCase):
    def test_four_layer_stack_is_documented(self):
        for label in ("General Research", "Macro", "Opportunity", "Deployment Model"):
            self.assertIn(label, PHILOSOPHY)

    def test_scanner_cannot_claim_market_wide_without_measured_coverage(self):
        self.assertIn('"cached_snapshot_coverage_percent"', SCANNER)
        self.assertIn('"technical_coverage_percent"', SCANNER)
        self.assertIn('"market_wide_ready"', SCANNER)
        self.assertIn('Broad archive is not canonical', SCANNER)
        self.assertIn('performs zero provider calls', SCANNER)

    def test_candidate_funnel_propagates_coverage_and_verification(self):
        self.assertIn('"coverage":coverage', FUNNEL)
        self.assertIn('"verification":scan.get("verification")', FUNNEL)
        self.assertIn('"name":"Universe coverage"', FUNNEL)
        self.assertIn('"name":"Technical completeness"', FUNNEL)

    def test_v4_requests_are_bounded_and_retryable(self):
        self.assertIn('REQUEST_TIMEOUT_MS=12000', V4)
        self.assertIn('AbortController', V4)
        self.assertIn('Retry', V4)

    def test_v4_exposes_source_transparency(self):
        self.assertIn('Data state & sources', V4)
        self.assertIn('market?.source_url', V4)
        self.assertIn('verification_status', V4)
        self.assertIn('Scanner coverage', V4)

    def test_cross_layer_rows_drill_into_research(self):
        self.assertGreaterEqual(V4.count('openResearch('), 5)
        self.assertIn('table-row-button', V4)
        self.assertIn('allocation-row-button', V4)

    def test_broad_scanner_uses_tiered_history_retention(self):
        self.assertIn('BROAD_OPPORTUNITY_HISTORY_DAYS', PIPELINE)
        self.assertIn('BROAD_OPPORTUNITY_MIN_BARS = 120', PIPELINE)
        self.assertIn('TRACKED_MIN_BARS = 220', PIPELINE)
        self.assertIn('retain_days = NORMALIZED_HISTORY_DAYS if tracked else BROAD_OPPORTUNITY_HISTORY_DAYS', PIPELINE)
        self.assertIn('tail=BROAD_OPPORTUNITY_HISTORY_DAYS', PIPELINE)

    def test_deployment_fundamental_score_is_informational_only(self):
        self.assertIn('build_fundamental_score', STACK)
        self.assertIn('fundamental_score_policy', STACK)
        self.assertIn('never changes Williams rank, weight, eligibility or suggested dollars', STACK)
        self.assertNotIn('fundamental_score', (ROOT / "backend/app/services/monthly_priority.py").read_text(encoding="utf-8"))

    def test_expandable_detail_controls_are_wired_into_v4(self):
        self.assertIn('DeepLinksV4', V4)
        self.assertIn('OpportunityTableV4', V4)
        self.assertIn('Fundamental score details', V4)

    def test_world_news_window_is_real_backend_input(self):
        self.assertIn('hours:int=Query(default=48,ge=1,le=168)', MAIN)
        self.assertIn('timespan=f"{hours}h"', MAIN)
        self.assertIn('suffix=f" when:{days}d"', GDELT)
        self.assertIn('_google_news_fallback(query, max_records, timespan)', GDELT)

    def test_mobile_progressive_disclosure_is_preserved(self):
        self.assertIn('@media(max-width:560px)', V4_CSS)
        self.assertIn('.v4-pipeline{grid-template-columns:1fr}', V4_CSS)
        self.assertIn('.source-state-grid{grid-template-columns:1fr}', V4_CSS)


if __name__ == "__main__":
    unittest.main()
