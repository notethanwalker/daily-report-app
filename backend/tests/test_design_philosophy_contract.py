from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCANNER = (ROOT / "backend/app/services/opportunity_scanner.py").read_text(encoding="utf-8")
PIPELINE = (ROOT / "backend/app/services/market_data_pipeline.py").read_text(encoding="utf-8")
FUNNEL = (ROOT / "backend/app/services/candidate_funnel_v4.py").read_text(encoding="utf-8")
V4 = (ROOT / "web/app/v4/page.tsx").read_text(encoding="utf-8")
V4_CSS = (ROOT / "web/app/v4/v4.css").read_text(encoding="utf-8")
DEEP_CSS = (ROOT / "web/app/v4/deep-interaction.css").read_text(encoding="utf-8")
OPPORTUNITY_TABLE = (ROOT / "web/app/v4/opportunity-table-v4.tsx").read_text(encoding="utf-8")
MACRO_TABLE = (ROOT / "web/app/v4/macro-rotation-table-v4.tsx").read_text(encoding="utf-8")
RESEARCH_METRICS = (ROOT / "web/app/v4/research-metric-strip-v4.tsx").read_text(encoding="utf-8")
PHILOSOPHY = (ROOT / "docs/DAILY_REPORT_APP_DESIGN_PHILOSOPHY.md").read_text(encoding="utf-8")
STACK = (ROOT / "backend/app/routers/stack_v4.py").read_text(encoding="utf-8")
MAIN = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
GDELT = (ROOT / "backend/app/providers/gdelt.py").read_text(encoding="utf-8")
SCHEDULER = (ROOT / "backend/app/services/refresh_scheduler.py").read_text(encoding="utf-8")


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
        delegated = V4.count('openResearch(') + OPPORTUNITY_TABLE.count('onOpen(') + MACRO_TABLE.count('onOpen(')
        self.assertGreaterEqual(delegated, 6)
        self.assertIn('table-row-button', OPPORTUNITY_TABLE)
        self.assertIn('table-row-button', MACRO_TABLE)
        self.assertIn('allocation-row-button', V4)
        self.assertIn('title={`Open ${x.symbol} research`}', OPPORTUNITY_TABLE)
        self.assertIn('title={`Open ${x.symbol} research`}', MACRO_TABLE)

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
        self.assertIn('MacroRotationTableV4', V4)
        self.assertIn('ResearchMetricStripV4', V4)
        self.assertIn('Fundamental score details', V4)

    def test_sorting_is_clickable_and_dropdown_accessible(self):
        self.assertIn('metric-sort-bar', OPPORTUNITY_TABLE)
        self.assertIn('aria-pressed', OPPORTUNITY_TABLE)
        self.assertIn('<select', OPPORTUNITY_TABLE)
        self.assertIn('function selectSort', OPPORTUNITY_TABLE)
        self.assertIn('onChange={e=>selectSort(', OPPORTUNITY_TABLE)
        self.assertIn('metric-sort-bar', MACRO_TABLE)
        self.assertIn('aria-pressed', MACRO_TABLE)
        self.assertIn('Rank metric', MACRO_TABLE)
        self.assertIn('function selectMetric', MACRO_TABLE)
        self.assertIn('onChange={e=>selectMetric(', MACRO_TABLE)

    def test_research_statistics_are_clickable_and_explained(self):
        self.assertIn('Research statistics; select one for details', RESEARCH_METRICS)
        self.assertIn('aria-pressed', RESEARCH_METRICS)
        self.assertIn('100-day moving average', RESEARCH_METRICS)
        self.assertIn('Williams %R timing signal', RESEARCH_METRICS)
        self.assertIn('provider', RESEARCH_METRICS)

    def test_layer_switch_clears_stale_error_context(self):
        self.assertIn('onClick={()=>{setError("");setActive(key)}}', V4)

    def test_world_news_window_is_real_backend_input(self):
        self.assertIn('hours:int=Query(default=48,ge=1,le=168)', MAIN)
        self.assertIn('timespan=f"{hours}h"', MAIN)
        self.assertIn('suffix=f" when:{days}d"', GDELT)
        self.assertIn('_google_news_fallback(query, max_records, timespan)', GDELT)

    def test_cold_start_reuses_normalized_history_and_warms_deployment_symbols(self):
        self.assertIn('DEPLOYMENT_WARM_SYMBOLS', SCHEDULER)
        self.assertIn('"MU,NVDA"', SCHEDULER)
        self.assertIn('seed_historical_from_normalized', SCHEDULER)
        self.assertIn('users = set(_user_symbols(db)) | DEPLOYMENT_WARM_SYMBOLS', SCHEDULER)

    def test_mobile_progressive_disclosure_is_preserved(self):
        self.assertIn('@media(max-width:560px)', V4_CSS)
        self.assertIn('.v4-pipeline{grid-template-columns:1fr}', V4_CSS)
        self.assertIn('.source-state-grid{grid-template-columns:1fr}', V4_CSS)
        self.assertIn('.metric-sort-bar{display:none}', V4_CSS)
        self.assertIn('.table-controls label,.table-controls select,.table-controls button{width:100%}', V4_CSS)
        self.assertIn('@media(max-width:430px)', DEEP_CSS)
        self.assertIn('.deep-v4-shell .subtab-bar', DEEP_CSS)
        self.assertIn('grid-template-columns:1fr!important', DEEP_CSS)


if __name__ == "__main__":
    unittest.main()
