from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
START = (ROOT / "backend/app/start.py").read_text(encoding="utf-8")
OIDC = (ROOT / "backend/app/services/github_actions_oidc.py").read_text(encoding="utf-8")
AUTH = (ROOT / "backend/app/routers/auth.py").read_text(encoding="utf-8")
AUTH_MODELS = (ROOT / "backend/app/auth_models.py").read_text(encoding="utf-8")
DAILY = (ROOT / ".github/workflows/daily-report-refresh.yml").read_text(encoding="utf-8")
KEEPALIVE = (ROOT / ".github/workflows/render-keepalive.yml").read_text(encoding="utf-8")
OPPORTUNITY = (ROOT / ".github/workflows/opportunity-coverage.yml").read_text(encoding="utf-8")
SMOKE = (ROOT / ".github/workflows/smoke-once.yml").read_text(encoding="utf-8")
CI = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
PROXY = (ROOT / "web/app/backend/[...path]/route.ts").read_text(encoding="utf-8")
NEXT = (ROOT / "web/next.config.ts").read_text(encoding="utf-8")
PACKAGE = (ROOT / "web/package.json").read_text(encoding="utf-8")
TSCONFIG = (ROOT / "web/tsconfig.json").read_text(encoding="utf-8")
PLAYWRIGHT = (ROOT / "web/playwright.config.ts").read_text(encoding="utf-8")


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
        section = START[START.index("def _maintenance_request_authorized"):START.index("def _smoke_request_authorized")]
        self.assertNotIn('path.startswith("/api/v1/portfolios")', section)

    def test_smoke_identity_is_narrow_and_deployment_aware(self):
        self.assertIn('SMOKE_AUDIENCE = "daily-report-smoke"', OIDC)
        self.assertIn('SMOKE_WORKFLOW_PATH = ".github/workflows/smoke-once.yml"', OIDC)
        self.assertIn("verify_live_smoke_token", START)
        self.assertIn("audience=daily-report-smoke", SMOKE)
        self.assertIn("Wait for matching backend deployment", SMOKE)
        self.assertIn("attempt ${attempt}/36", SMOKE)
        self.assertNotIn('length) == 9', SMOKE)
        self.assertNotIn('Joint Fidelity', SMOKE)

    def test_auth_rate_limits_are_shared_and_not_proxy_ip_keyed(self):
        self.assertIn("class AuthRateLimit", AUTH_MODELS)
        self.assertIn("with_for_update()", AUTH)
        self.assertIn('rate_key=f"login:{lookup}"', AUTH)
        self.assertIn('f"register:{lookup}"', AUTH)
        self.assertNotIn("request.client.host", AUTH)
        self.assertNotIn("defaultdict", AUTH)
        self.assertNotIn("deque", AUTH)

    def test_keepalive_jobs_are_short_and_non_overlapping(self):
        self.assertIn("group: render-keepalive", KEEPALIVE)
        self.assertIn("cancel-in-progress: true", KEEPALIVE)
        self.assertIn("timeout-minutes: 3", KEEPALIVE)
        self.assertNotIn("seq 1 70", KEEPALIVE)
        self.assertNotIn("sleep 300", KEEPALIVE)

    def test_opportunity_worker_is_bounded_and_avoids_push_race(self):
        self.assertIn("cancel-in-progress: true", OPPORTUNITY)
        self.assertIn("--download-chunk 40 --upload-batch 50", OPPORTUNITY)
        self.assertNotIn("\n  push:", OPPORTUNITY)

    def test_frontend_proxy_has_bounded_upstream_time(self):
        self.assertIn("UPSTREAM_TIMEOUT_MS=60000", PROXY)
        self.assertIn("new AbortController()", PROXY)
        self.assertIn("request.signal", PROXY)
        self.assertIn("status:504", PROXY)

    def test_frontend_has_security_and_test_gates(self):
        for header in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Permissions-Policy"):
            self.assertIn(header, NEXT)
        self.assertIn('"strict": true', TSCONFIG)
        self.assertIn('"typecheck": "tsc --noEmit"', PACKAGE)
        self.assertIn('"test:e2e": "playwright test"', PACKAGE)
        self.assertIn("iPhone 15", PLAYWRIGHT)
        self.assertIn("npm audit --audit-level=high", CI)
        self.assertIn("npm run typecheck", CI)
        self.assertIn("npm run test:e2e", CI)


if __name__ == "__main__":
    unittest.main()
