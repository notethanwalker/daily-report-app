import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.flow_confirmation_v4 import analyze_flow_rows


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def row(side="call", aggression="buy", expiration="2026-10-16", occurred="2026-09-10T10:00:00+00:00", premium=100000, provider="SquawkFlow", strike=100):
    return SimpleNamespace(
        event_type="options",
        symbol="TEST",
        provider=provider,
        occurred_at=datetime.fromisoformat(occurred),
        source_url="https://example.test",
        outlier_score=50.0,
        payload={
            "side": side,
            "aggression": aggression,
            "expiration": expiration,
            "strike": strike,
            "premium": premium,
            "contracts": 500,
            "volume": 1000,
            "open_interest": 500,
        },
    )


class FlowConfirmationV4Test(unittest.TestCase):
    def test_expired_contracts_are_excluded(self):
        result = analyze_flow_rows([
            row(expiration="2026-09-09"),
            row(expiration="2026-10-16"),
        ], now=NOW)
        self.assertEqual(result["expired_filtered_count"], 1)
        self.assertEqual(result["active_event_count"], 1)

    def test_repeated_bullish_contract_can_confirm_with_medium_confidence(self):
        rows = [
            row(occurred="2026-09-10T08:00:00+00:00"),
            row(occurred="2026-09-10T09:00:00+00:00"),
            row(occurred="2026-09-10T10:00:00+00:00"),
        ]
        result = analyze_flow_rows(rows, now=NOW)
        self.assertEqual(result["verdict"], "confirmation")
        self.assertEqual(result["direction"], "bullish")
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(result["repeated_contract_count"], 1)
        self.assertGreaterEqual(result["largest_time_burst"], 2)
        self.assertEqual(result["score_effect"], 0)

    def test_consistent_bearish_activity_is_contradiction_for_long_setup(self):
        rows = [
            row(side="put", aggression="buy", strike=90),
            row(side="put", aggression="buy", strike=95, occurred="2026-09-10T11:00:00+00:00"),
        ]
        result = analyze_flow_rows(rows, now=NOW)
        self.assertEqual(result["verdict"], "contradiction")
        self.assertEqual(result["direction"], "bearish")

    def test_conflicting_activity_stays_mixed(self):
        rows = [
            row(side="call", aggression="buy", strike=100),
            row(side="put", aggression="buy", strike=90, occurred="2026-09-10T11:00:00+00:00"),
        ]
        result = analyze_flow_rows(rows, now=NOW)
        self.assertEqual(result["verdict"], "mixed")
        self.assertEqual(result["confidence"], "low")

    def test_large_premium_without_direction_does_not_create_confirmation(self):
        result = analyze_flow_rows([
            row(side="call", aggression="mid", premium=100000000),
        ], now=NOW)
        self.assertEqual(result["verdict"], "insufficient")
        self.assertEqual(result["direction"], "unknown")
        self.assertEqual(result["score_effect"], 0)


if __name__ == "__main__":
    unittest.main()
