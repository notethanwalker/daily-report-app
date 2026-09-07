from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
ALERTS=(ROOT/"backend/app/routers/alerts_v2.py").read_text(encoding="utf-8")
ENGINE=(ROOT/"backend/app/services/alert_engine.py").read_text(encoding="utf-8")
TYPED=(ROOT/"backend/app/services/typed_alerts.py").read_text(encoding="utf-8")
NEXT=(ROOT/"backend/app/routers/next_intelligence.py").read_text(encoding="utf-8")
START=(ROOT/"backend/app/start.py").read_text(encoding="utf-8")
AUG=(ROOT/"web/app/intelligence-augmentations.tsx").read_text(encoding="utf-8")
TEMPLATES=(ROOT/"web/app/future-alert-templates.tsx").read_text(encoding="utf-8")
RUNTIME=(ROOT/"web/app/dashboard-layout-runtime-v3.tsx").read_text(encoding="utf-8")
EDITOR=(ROOT/"web/app/dashboard-layout-editor-v2.tsx").read_text(encoding="utf-8")
PANELS=(ROOT/"web/app/next-intelligence-panels.tsx").read_text(encoding="utf-8")


class NextIntelligenceContract(unittest.TestCase):
    def test_typed_alerts_support_real_semantics(self):
        for kind in ("ma100_proximity","ma200_proximity","catalyst_days","persistent_flow","portfolio_position_weight","regime_transition"):
            self.assertIn(kind,TYPED)
            self.assertIn(kind,ALERTS)
        self.assertIn("abs(float(raw))",TYPED)
        self.assertIn("event_key",TYPED)
        self.assertIn("event_key",ENGINE)
        self.assertIn('/alerts/v3/preview',ALERTS)
        self.assertIn('/alerts/v3',ALERTS)

    def test_alert_template_ui_previews_same_backend_evaluator(self):
        self.assertIn('/api/v1/alerts/v3/preview',TEMPLATES)
        self.assertIn('/api/v1/alerts/v3',TEMPLATES)
        self.assertIn('portfolio_id',TEMPLATES)
        self.assertIn('Would trigger now',TEMPLATES)

    def test_factor_proxy_endpoint_is_descriptive_not_overclaimed(self):
        self.assertIn('/portfolio/{portfolio_id}/factor-proxies',NEXT)
        self.assertIn('correlation',NEXT)
        self.assertIn('beta',NEXT)
        self.assertIn('not institutional multi-factor-model loadings',NEXT)
        self.assertIn('custom_benchmark',NEXT)
        self.assertIn('FactorProxyPanel',AUG)

    def test_multidimensional_regime_exposes_uncertainty(self):
        self.assertIn('/regime/dimensions',NEXT)
        for dimension in ('risk_appetite','growth','inflation_pressure','liquidity','rates_dollar_pressure'):
            self.assertIn(dimension,NEXT)
        self.assertIn('state="uncertain"',NEXT)
        self.assertIn('RegimeDimensionsPanel',AUG)

    def test_next_router_is_wired(self):
        self.assertIn('next_intelligence_router',START)
        self.assertIn('app.include_router(next_intelligence_router)',START)

    def test_full_report_layout_is_customizable_but_warnings_are_not_hideable(self):
        for key in ('market_dashboard','sentiment','themes','report_controls','trust_summary','currencies','outliers','top_news'):
            self.assertIn(key,EDITOR)
        self.assertIn('report-layout-zone',RUNTIME)
        self.assertNotIn('verification_warning',EDITOR)
        self.assertIn('DashboardLayoutEditorV2',AUG)
        self.assertIn('DashboardLayoutRuntimeV3',AUG)


if __name__=="__main__":
    unittest.main()
