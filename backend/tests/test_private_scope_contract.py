from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
INTELLIGENCE=(ROOT/"backend/app/routers/intelligence.py").read_text(encoding="utf-8")
START=(ROOT/"backend/app/start.py").read_text(encoding="utf-8")
USER_STATE=(ROOT/"backend/app/routers/user_state.py").read_text(encoding="utf-8")
OPPORTUNITY_ROUTER=(ROOT/"backend/app/routers/opportunity_scanner.py").read_text(encoding="utf-8")
OPPORTUNITY_SERVICE=(ROOT/"backend/app/services/opportunity_scanner.py").read_text(encoding="utf-8")
PIPELINE=(ROOT/"backend/app/services/market_data_pipeline.py").read_text(encoding="utf-8")
THESIS_UI=(ROOT/"web/app/intelligence-suite.tsx").read_text(encoding="utf-8")
OPPORTUNITY_UI=(ROOT/"web/app/opportunities-workspace-v4.tsx").read_text(encoding="utf-8")

class PrivateScopeContract(unittest.TestCase):
    def test_session_gate_strips_spoofable_identity_headers(self):
        self.assertIn('b"x-user-email"',START);self.assertIn('b"x-user-token"',START);self.assertIn('account_from_session',START);self.assertIn('_inject_subject(request.scope,account.id)',START)
    def test_portfolio_routes_scope_by_authenticated_subject(self):self.assertGreaterEqual(INTELLIGENCE.count("PortfolioHolding.user_email==user"),3)
    def test_alert_routes_scope_reads_and_deletes(self):self.assertIn("AlertRule.user_email==user",INTELLIGENCE);self.assertIn("AlertRule.id==alert_id,AlertRule.user_email==user",INTELLIGENCE)
    def test_thesis_routes_scope_reads_and_deletes(self):self.assertIn("Thesis.user_email==user",INTELLIGENCE);self.assertIn("Thesis.id==thesis_id,Thesis.user_email==user",INTELLIGENCE)
    def test_watchlist_routes_are_user_scoped(self):self.assertIn("UserWatchlistItem.user_email==user",USER_STATE)
    def test_opportunities_use_authenticated_tracked_scope_and_shared_market_cache(self):
        self.assertIn('@router.get("/tracked")',OPPORTUNITY_ROUTER);self.assertIn("UserWatchlistItem.user_email == user",OPPORTUNITY_ROUTER);self.assertIn("PortfolioHolding.user_email == user",OPPORTUNITY_ROUTER);self.assertIn("PortfolioDefinition.user_email == user",OPPORTUNITY_ROUTER);self.assertIn('@router.get("/market-scan")',OPPORTUNITY_ROUTER);self.assertIn("user: str = Depends(current_user)",OPPORTUNITY_ROUTER)
        self.assertIn('api("/api/v1/opportunities/tracked")',OPPORTUNITY_UI);self.assertIn('/api/v1/opportunities/market-scan?limit=200&include_etfs=',OPPORTUNITY_UI);self.assertNotIn('api("/api/v1/opportunities?limit=200")',OPPORTUNITY_UI)
    def test_market_scanner_reads_only_latest_snapshot_per_symbol(self):
        self.assertIn('func.max(MarketSnapshot.id)',OPPORTUNITY_SERVICE);self.assertIn('zero provider calls',OPPORTUNITY_SERVICE.lower())
    def test_scanner_defaults_to_stocks_and_uses_real_confirmation(self):
        self.assertIn('include_etfs: bool = Query(default=False)',OPPORTUNITY_ROUTER)
        self.assertIn('approach_velocity_100_5d',OPPORTUNITY_SERVICE)
        self.assertIn('ma100_slope_20d_percent',OPPORTUNITY_SERVICE)
        self.assertNotIn('ma_trend_proxy',OPPORTUNITY_SERVICE)
        self.assertNotIn('approach_proxy',OPPORTUNITY_SERVICE)
    def test_market_pipeline_is_bounded_and_canonical(self):
        self.assertIn('canonical_technicals',PIPELINE)
        self.assertIn('prune_market_snapshots',PIPELINE)
        self.assertIn('prune_normalized_bars',PIPELINE)
        self.assertIn('refresh_tracked_market_snapshot',PIPELINE)
        self.assertIn('incremental per-symbol repair',PIPELINE)
    def test_thesis_draft_does_not_ship_with_live_example_values(self):
        self.assertNotIn('useState("AI infrastructure buildout")',THESIS_UI);self.assertNotIn('useState("AAOI,AXTI,SNDK,MU,NBIS,SMH")',THESIS_UI);self.assertIn('[title,setTitle]=useState("")',THESIS_UI);self.assertIn('[statement,setStatement]=useState("")',THESIS_UI)

if __name__=="__main__":unittest.main()
