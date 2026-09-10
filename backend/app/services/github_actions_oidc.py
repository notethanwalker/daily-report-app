from __future__ import annotations

import base64
import json
import time
from threading import Lock

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = f"{ISSUER}/.well-known/jwks"
AUDIENCE = "daily-report-opportunity-ingest"
REPOSITORY = "notethanwalker/daily-report-app"
WORKFLOW_PATH = ".github/workflows/opportunity-coverage.yml"
MAINTENANCE_AUDIENCE = "daily-report-maintenance"
MAINTENANCE_WORKFLOW_PATH = ".github/workflows/daily-report-refresh.yml"
SMOKE_AUDIENCE = "daily-report-smoke"
SMOKE_WORKFLOW_PATH = ".github/workflows/smoke-once.yml"
_ALLOWED_EVENTS = {"schedule", "workflow_dispatch", "push"}

_jwks_cache: tuple[float, dict] | None = None
_jwks_lock = Lock()


def _b64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _jwks() -> dict:
    global _jwks_cache
    now = time.time()
    with _jwks_lock:
        if _jwks_cache and now - _jwks_cache[0] < 3600:
            return _jwks_cache[1]
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(JWKS_URL, headers={"User-Agent": "daily-report-app/1.0"})
            response.raise_for_status()
            payload = response.json()
        _jwks_cache = (now, payload)
        return payload


def _verify_github_actions_token(
    token: str,
    *,
    audience: str,
    workflow_path: str,
    allowed_events: set[str] | None = None,
) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed GitHub Actions identity token")
    try:
        header = json.loads(_b64url(parts[0]))
        claims = json.loads(_b64url(parts[1]))
    except Exception as exc:
        raise ValueError("Invalid GitHub Actions identity token encoding") from exc

    if header.get("alg") != "RS256" or not header.get("kid"):
        raise ValueError("Unsupported GitHub Actions identity token")

    keys = _jwks().get("keys") or []
    key = next((item for item in keys if item.get("kid") == header["kid"]), None)
    if not key or key.get("kty") != "RSA":
        raise ValueError("Unknown GitHub Actions signing key")

    try:
        n = int.from_bytes(_b64url(key["n"]), "big")
        e = int.from_bytes(_b64url(key["e"]), "big")
        public_key = rsa.RSAPublicNumbers(e, n).public_key()
        public_key.verify(
            _b64url(parts[2]),
            f"{parts[0]}.{parts[1]}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception as exc:
        raise ValueError("Invalid GitHub Actions identity token signature") from exc

    now = int(time.time())
    if claims.get("iss") != ISSUER:
        raise ValueError("Unexpected GitHub Actions token issuer")
    token_audience = claims.get("aud")
    audiences = token_audience if isinstance(token_audience, list) else [token_audience]
    if audience not in audiences:
        raise ValueError("Unexpected GitHub Actions token audience")
    if int(claims.get("exp") or 0) <= now:
        raise ValueError("Expired GitHub Actions identity token")
    if int(claims.get("nbf") or 0) > now + 30:
        raise ValueError("GitHub Actions identity token is not active")
    if claims.get("repository") != REPOSITORY:
        raise ValueError("GitHub Actions token repository is not authorized")
    if claims.get("ref") != "refs/heads/main":
        raise ValueError("GitHub Actions token branch is not authorized")
    if claims.get("event_name") not in (allowed_events or _ALLOWED_EVENTS):
        raise ValueError("GitHub Actions token event is not authorized")
    workflow_ref = str(claims.get("workflow_ref") or "")
    expected_prefix = f"{REPOSITORY}/{workflow_path}@"
    if not workflow_ref.startswith(expected_prefix):
        raise ValueError("GitHub Actions token workflow is not authorized")
    return claims


def verify_github_actions_token(token: str) -> dict:
    """Verify the Opportunity coverage worker identity token."""
    return _verify_github_actions_token(token,audience=AUDIENCE,workflow_path=WORKFLOW_PATH)


def verify_daily_report_maintenance_token(token: str) -> dict:
    """Verify the scheduled Daily Report refresh identity token."""
    return _verify_github_actions_token(token,audience=MAINTENANCE_AUDIENCE,workflow_path=MAINTENANCE_WORKFLOW_PATH,allowed_events={"schedule", "workflow_dispatch"})


def verify_live_smoke_token(token: str) -> dict:
    """Verify the live API smoke-test identity token."""
    return _verify_github_actions_token(token,audience=SMOKE_AUDIENCE,workflow_path=SMOKE_WORKFLOW_PATH,allowed_events={"push", "workflow_dispatch"})
