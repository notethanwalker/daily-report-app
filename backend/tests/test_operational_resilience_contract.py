from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
START = (ROOT / "backend/app/start.py").read_text(encoding="utf-8")
OIDC = (ROOT / "backend/app/services/github_actions_oidc.py").read_text(encoding="utf-8")
DAILY = (ROOT / ".github/workflows/daily-report-refresh.yml").read_text(encoding="utf-8")
KEEPALIVE = (ROOT / ".github/workflows/render-keepalive.yml").read_text(encoding="utf-8")
PROXY = (ROOT / "web/app/backend/[...path]/route.ts").read_text(encoding="utf-8")
NEXT = (ROOT / "web/next.config.ts").read_text(encoding="utf-8")


class OperationalResilienceContract(unittest.TestCase):
    def test_scheduled_refresh_uses_narrow_github_oidc_identity(self):
        self.assertIn("verify_daily_report_maintenance_token", START)
        self.assertIn('MAINTENANCE_AUDIENCE = "daily-report-maintenance"', OIDC)
        self.assertIn('MAINTENANCE_WORKFLOW_PATH = ".github/workflows/daily-report-refresh.yml"', OIDC)
        self.assertIn('allowed_events={"schedule", "workflow_dispatch"}', OIDC)
        self.assertIn("id-token: write", DAILY)
        self.assertIn("audience=daily-report-maintenance", DAILY)
        self.assertIn('Authorization: Bearer ${OIDC}', DAILY)

    def test_maintenance_identity_is_limited_to_refresh_routes(self):
        self.assertIn('method=="GET" and path=="/api/v1/watchlist"', START)
        self.assertIn('method=="GET" and path.startswith("/api/v1/markets/")', START)
        self.assertIn('method=="GET" and path=="/api/v1/flow/recent"', START)
        self.assertIn('method=="POST" and path=="/api/v1/report/generate"', START)
        self.assertNotIn('path.startswith("/api/v1/portfolios")', START[START.index("def _maintenance_request_authorized"):START.index('@app.middleware("http")')])

    def test_keepalive_jobs_are_short_and_non_overlapping(self):
        self.assertIn("group: render-keepalive", KEEPALIVE)
        self.assertIn("cancel-in-progress: true", KEEPALIVE)
        self.assertIn("timeout-minutes: 3", KEEPALIVE)
        self.assertNotIn("seq 1 70", KEEPALIVE)
        self.assertNotIn("sleep 300", KEEPALIVE)

    def test_frontend_proxy_has_bounded_upstream_time(self):
        self.assertIn("UPSTREAM_TIMEOUT_MS=60000", PROXY)
        self.assertIn("new AbortController()", PROXY)
        self.assertIn("request.signal", PROXY)
        self.assertIn("status:504", PROXY)

    def test_baseline_browser_security_headers_are_enabled(self):
        for header in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Permissions-Policy"):
            self.assertIn(header, NEXT)


if __name__ == "__main__":
    unittest.main()
