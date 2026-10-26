"""Read-only, bounded startup evidence for Render's eMudhra advisory.

No credentials, response bodies or exception messages are logged. A transport
failure is inconclusive, not proof of certificate rejection. This is diagnostic
only: temporary unavailability of the public test service must not stop the API.
"""

from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
import json
import ssl
import subprocess
import urllib.error
import urllib.request

import httpx
import requests
from curl_cffi import requests as curl_requests

CONTROL = "https://render.com/"
TEST_URLS = (
    "https://dv-g3b-emudhra.we-have-a-problem.com/",
    "https://dv-g3b-aaa-emudhra.we-have-a-problem.com/",
)
TIMEOUT = 10


def certificate_verification_failed(exc):
    """Follow wrappers, without confusing timeouts/other TLS errors with rejection."""
    pending, seen = [exc], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        # libcurl's peer-certificate verification failure (CURLE_PEER_FAILED_VERIFICATION).
        if isinstance(current, curl_requests.errors.RequestsError) and current.code == 60:
            return True
        # Requests/urllib3 may stringify the underlying OpenSSL exception.
        if isinstance(current, requests.exceptions.SSLError) and "CERTIFICATE_VERIFY_FAILED" in str(current):
            return True
        pending.extend(value for value in (
            current.__cause__, current.__context__, getattr(current, "reason", None),
            *current.args,
        ) if isinstance(value, BaseException))
    return False


def _request(client, url):
    if client == "httpx":
        with httpx.Client(timeout=TIMEOUT) as session:
            return session.head(url).status_code
    if client == "urllib":
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=TIMEOUT) as response:
                return response.status
        except urllib.error.HTTPError as response:
            response.close()
            return response.code
    if client == "requests":
        with requests.head(url, timeout=TIMEOUT, allow_redirects=False) as response:
            return response.status_code
    with curl_requests.Session(impersonate="chrome") as session:
        return session.head(url, timeout=TIMEOUT, allow_redirects=False).status_code


def probe(client, url):
    try:
        return {"client": client, "url": url, "result": "accepted", "status": _request(client, url)}
    except Exception as exc:
        result = "certificate_rejected" if certificate_verification_failed(exc) else "inconclusive"
        return {"client": client, "url": url, "result": result, "error_type": type(exc).__name__}


def log_tls_audit():
    try:
        packages = {name: version(name) for name in ("certifi", "httpx", "requests", "curl_cffi", "yfinance")}
        system_ca = subprocess.check_output(
            ["dpkg-query", "-W", "-f=${Version}", "ca-certificates"], text=True, timeout=5,
        ).strip()
        clients = ("httpx", "urllib", "requests", "curl_cffi")
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(probe, client, url) for client in clients for url in (CONTROL, *TEST_URLS)]
            results = [future.result() for future in futures]
        verified = all(row["result"] == ("accepted" if row["url"] == CONTROL else "certificate_rejected") for row in results)
        print("TLS_CERTIFICATE_AUDIT " + json.dumps({
            "verified": verified, "packages": packages, "system_ca": system_ca,
            "openssl": ssl.OPENSSL_VERSION, "results": results,
        }, sort_keys=True), flush=True)
    except Exception as exc:
        print("TLS_CERTIFICATE_AUDIT " + json.dumps({"verified": False, "result": "inconclusive", "error_type": type(exc).__name__}), flush=True)
