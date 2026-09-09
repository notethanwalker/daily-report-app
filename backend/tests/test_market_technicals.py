from datetime import date, timedelta
import unittest

from app.services.calculations import build_market_snapshot


class MarketTechnicalCalculations(unittest.TestCase):
    def _raw(self):
        start = date(2025, 1, 1)
        closes = [100.0] * 254 + [110.0, 108.0, 106.0, 104.0, 102.0, 101.0]
        values = []
        for i, close in enumerate(closes):
            values.append({
                "datetime": (start + timedelta(days=i)).isoformat(),
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000 + i,
            })
        return {
            "history": {"values": values, "meta": {"symbol": "TEST"}},
            "provider": "unit-test",
            "source_url": "test://ohlcv",
            "retrieved_at": "2026-09-07T00:00:00+00:00",
            "normalized": True,
        }

    def _broad_raw(self, bars=130):
        start = date(2026, 1, 1)
        values = []
        for i in range(bars):
            close = 100.0 + i * 0.08
            values.append({
                "datetime": (start + timedelta(days=i)).isoformat(),
                "open": close - 0.2,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 2_000_000 + i * 1000,
            })
        return {
            "history": {"values": values, "meta": {"symbol": "BROAD"}},
            "provider": "unit-test",
            "source_url": "test://broad-ohlcv",
            "retrieved_at": "2026-09-09T00:00:00+00:00",
            "normalized": True,
        }

    def test_real_ma100_approach_velocity_is_positive_when_distance_contracts(self):
        snapshot = build_market_snapshot(self._raw())
        self.assertIsNotNone(snapshot["ma100_distance_5d_ago"])
        self.assertIsNotNone(snapshot["approach_velocity_100_5d"])
        self.assertGreater(snapshot["approach_velocity_100_5d"], 0)

    def test_real_ma100_slope_is_derived_from_historical_ma100(self):
        snapshot = build_market_snapshot(self._raw())
        self.assertIsNotNone(snapshot["ma100_20d_ago"])
        self.assertIsNotNone(snapshot["ma100_slope_20d_percent"])
        self.assertGreater(snapshot["ma100_slope_20d_percent"], 0)

    def test_normalized_snapshot_is_labeled_as_materialized_cache(self):
        snapshot = build_market_snapshot(self._raw())
        self.assertEqual(snapshot["technical_source"], "normalized_daily_bars")
        self.assertTrue(snapshot["is_materialized_cache"])

    def test_broad_130_bar_snapshot_has_opportunity_inputs_without_fake_200ma(self):
        snapshot = build_market_snapshot(self._broad_raw())
        self.assertIsNotNone(snapshot["williams_r_14"])
        self.assertIsNotNone(snapshot["ma100"])
        self.assertIsNotNone(snapshot["price_vs_ma100_percent"])
        self.assertIsNotNone(snapshot["ma100_slope_20d_percent"])
        self.assertIsNotNone(snapshot["approach_velocity_100_5d"])
        self.assertIsNotNone(snapshot["average_dollar_volume_20d"])
        self.assertIsNone(snapshot["ma200"])
        self.assertIsNone(snapshot["price_vs_ma200_percent"])


if __name__ == "__main__":
    unittest.main()
