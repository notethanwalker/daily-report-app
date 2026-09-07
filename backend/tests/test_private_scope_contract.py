from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
INTELLIGENCE = (ROOT / "backend/app/routers/intelligence.py").read_text(encoding="utf-8")
START = (ROOT / "backend/app/start.py").read_text(encoding="utf-8")
USER_STATE = (ROOT / "backend/app/routers/user_state.py").read_text(encoding="utf-8")
THESIS_UI = (ROOT / "web/app/intelligence-suite.tsx").read_text(encoding="utf-8")


class PrivateScopeContract(unittest.TestCase):
    def test_session_gate_strips_spoofable_identity_headers(self):
        self.assertIn('b"x-user-email"', START)
        self.assertIn('b"x-user-token"', START)
        self.assertIn('account_from_session', START)
        self.assertIn('_inject_subject(request.scope,account.id)', START)

    def test_portfolio_routes_scope_by_authenticated_subject(self):
        self.assertGreaterEqual(INTELLIGENCE.count("PortfolioHolding.user_email==user"), 3)

    def test_alert_routes_scope_reads_and_deletes(self):
        self.assertIn("AlertRule.user_email==user", INTELLIGENCE)
        self.assertIn("AlertRule.id==alert_id,AlertRule.user_email==user", INTELLIGENCE)

    def test_thesis_routes_scope_reads_and_deletes(self):
        self.assertIn("Thesis.user_email==user", INTELLIGENCE)
        self.assertIn("Thesis.id==thesis_id,Thesis.user_email==user", INTELLIGENCE)

    def test_watchlist_routes_are_user_scoped(self):
        self.assertIn("UserWatchlistItem.user_email==user", USER_STATE)

    def test_thesis_draft_does_not_ship_with_live_example_values(self):
        self.assertNotIn('useState("AI infrastructure buildout")', THESIS_UI)
        self.assertNotIn('useState("AAOI,AXTI,SNDK,MU,NBIS,SMH")', THESIS_UI)
        self.assertIn('[title,setTitle]=useState("")', THESIS_UI)
        self.assertIn('[statement,setStatement]=useState("")', THESIS_UI)


if __name__ == "__main__":
    unittest.main()
