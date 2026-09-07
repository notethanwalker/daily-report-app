from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
ROUTER = (ROOT / "backend/app/routers/future_release.py").read_text(encoding="utf-8")
START = (ROOT / "backend/app/start.py").read_text(encoding="utf-8")
AUG = (ROOT / "web/app/intelligence-augmentations.tsx").read_text(encoding="utf-8")
PANELS = (ROOT / "web/app/future-release-panels.tsx").read_text(encoding="utf-8")
ALERT_TEMPLATES = (ROOT / "web/app/future-alert-templates.tsx").read_text(encoding="utf-8")
HOME = (ROOT / "web/app/home-dashboard.tsx").read_text(encoding="utf-8")
CSS = (ROOT / "web/app/future-release.css").read_text(encoding="utf-8")


class FutureReleaseContract(unittest.TestCase):
    def test_future_router_is_wired_and_model_table_loaded(self):
        self.assertIn("future_models as _future_models", START)
        self.assertIn("future_release_router", START)
        self.assertIn("app.include_router(future_release_router)", START)

    def test_portfolio_intelligence_is_user_scoped(self):
        self.assertIn("_portfolio_or_404(db, user, portfolio_id)", ROUTER)
        self.assertIn('"exposures": {"sector":', ROUTER)
        self.assertIn('"scenarios": scenarios', ROUTER)
        self.assertIn('"benchmark": benchmark', ROUTER)
        self.assertIn("PortfolioIntelligenceAutoPanel", AUG)

    def test_opportunity_change_explanation_is_watchlist_scoped(self):
        self.assertIn("UserWatchlistItem.user_email == user", ROUTER)
        self.assertIn('"component_deltas":deltas', ROUTER)
        self.assertIn('"new_flags":sorted(cf-pf)', ROUTER)
        self.assertIn("OpportunityChangeDigest", AUG)

    def test_flow_clustering_does_not_overclaim_participant_identity(self):
        self.assertIn('"participant_behavior_supported":False', ROUTER)
        self.assertIn('"opening_closing_supported":False', ROUTER)
        self.assertIn("FlowClustersPanel", AUG)

    def test_impact_mapping_marks_news_as_association_only(self):
        self.assertIn('"causal_confidence":"association_only"', ROUTER)
        self.assertIn("ImpactMapPanel", AUG)

    def test_regime_has_confidence_and_transition_history(self):
        self.assertIn('"confidence":round(confidence,1)', ROUTER)
        self.assertIn('"transition_history":trans', ROUTER)
        self.assertIn("RegimeConfidencePanel", AUG)

    def test_saved_dashboard_profiles_are_private_preferences(self):
        self.assertIn('settings["dashboard_layouts"]', ROUTER)
        self.assertIn('settings["active_dashboard_layout"]', ROUTER)
        self.assertIn('data-dashboard-card="market_dashboard"', HOME)
        self.assertIn("DashboardLayoutEditorV2", AUG)
        self.assertIn("DashboardLayoutRuntimeV3", AUG)

    def test_snapshot_compare_and_exports_preserve_stored_history(self):
        self.assertIn('@router.get("/reports/compare")', ROUTER)
        self.assertIn('@router.get("/reports/{report_id}/export.json")', ROUTER)
        self.assertIn('@router.get("/reports/{report_id}/export.csv"', ROUTER)
        self.assertIn("does not silently refresh historical data", ROUTER)
        self.assertIn("ReportComparePanel", AUG)

    def test_alert_templates_are_capability_aware(self):
        self.assertIn('KIND_BY_ID', ALERT_TEMPLATES)
        self.assertIn('/api/v1/alerts/v3/preview', ALERT_TEMPLATES)
        self.assertIn('Would trigger now', ALERT_TEMPLATES)
        self.assertIn('MA proximity uses absolute distance', ALERT_TEMPLATES)
        self.assertIn("FutureAlertTemplates", AUG)

    def test_mobile_dense_data_guards(self):
        self.assertIn(".grouped-market-table th:first-child", CSS)
        self.assertIn("min-height:44px", CSS)
        self.assertIn("overscroll-behavior-inline:contain", CSS)


if __name__ == "__main__":
    unittest.main()
