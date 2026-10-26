from pathlib import Path
import ssl
import unittest
from unittest.mock import patch
import urllib.error

import httpx
import requests
from curl_cffi import requests as curl_requests

from app.services.tls_audit import certificate_verification_failed, probe


class TLSAuditTest(unittest.TestCase):
    def test_ssl_verification_error_and_wrappers(self):
        error = ssl.SSLCertVerificationError(1, "certificate verify failed")
        self.assertTrue(certificate_verification_failed(error))
        self.assertTrue(certificate_verification_failed(urllib.error.URLError(error)))
        wrapped = httpx.ConnectError("TLS connection failed")
        wrapped.__cause__ = error
        self.assertTrue(certificate_verification_failed(wrapped))

    def test_library_verification_errors(self):
        self.assertTrue(certificate_verification_failed(curl_requests.errors.RequestsError("peer verification", code=60)))
        self.assertTrue(certificate_verification_failed(requests.exceptions.SSLError("[SSL: CERTIFICATE_VERIFY_FAILED]")))

    def test_other_errors_are_not_certificate_rejection(self):
        for error in (TimeoutError(), OSError(), ssl.SSLError("handshake failure"), requests.exceptions.SSLError("handshake failure"), curl_requests.errors.RequestsError("timeout", code=28)):
            self.assertFalse(certificate_verification_failed(error))

    def test_any_http_status_means_certificate_was_accepted(self):
        with patch("app.services.tls_audit._request", return_value=503):
            self.assertEqual(probe("httpx", "https://test.invalid/")["result"], "accepted")

    def test_transport_failure_is_inconclusive_and_does_not_leak_message(self):
        with patch("app.services.tls_audit._request", side_effect=TimeoutError("private detail")):
            result = probe("httpx", "https://test.invalid/")
        self.assertEqual(result["result"], "inconclusive")
        self.assertNotIn("private detail", str(result))

    def test_dependency_and_image_refresh_are_explicit(self):
        backend = Path(__file__).resolve().parents[1]
        self.assertIn("certifi>=2026.10.19", (backend / "requirements.txt").read_text())
        dockerfile = (backend / "Dockerfile").read_text()
        self.assertIn("apt-get update", dockerfile)
        self.assertIn("ca-certificates", dockerfile)
        self.assertIn("update-ca-certificates", dockerfile)


if __name__ == "__main__":
    unittest.main()
