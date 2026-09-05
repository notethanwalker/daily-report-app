from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

BASE_URL = "https://api.squawkflow.com"
SOURCE_URL = "https://squawkflow.com/docs/endpoints/unusual-options-flow"


class SquawkFlowError(RuntimeError):
    pass


class SquawkFlowProvider:
    name = "SquawkFlow"

    def unusual_options(self, limit: int = 50) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                response = client.get(
                    f"{BASE_URL}/api/v1/options/flow/unusual",
                    params={"limit": max(1, min(limit, 100))},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise SquawkFlowError("SquawkFlow unusual-options request failed") from exc

        if not payload.get("success", True):
            error = payload.get("error") or {}
            raise SquawkFlowError(str(error.get("message") or "SquawkFlow unavailable"))

        raw_data = payload.get("data") or []
        if isinstance(raw_data, dict):
            rows = raw_data.get("items") or raw_data.get("results") or raw_data.get("flow") or []
        else:
            rows = raw_data
        if not isinstance(rows, list):
            rows = []

        normalized = [self._normalize(row) for row in rows if isinstance(row, dict)]
        normalized = [row for row in normalized if row.get("symbol")]
        normalized = self._dedupe(normalized)

        return {
            "provider": self.name,
            "provider_configured": True,
            "source_url": SOURCE_URL,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "meta": payload.get("meta") or {},
            "usage": payload.get("usage") or {},
            "events": normalized,
            "note": "Public unusual-options observations. Repeated observations of the same contract print are deduplicated. Significance and direction are separate; calls are not automatically bullish and puts are not automatically bearish.",
        }

    @staticmethod
    def _first(row: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def _time_value(value: Any) -> float:
        if not value:
            return float("inf")
        try:
            text = str(value).replace("Z", "+00:00")
            return datetime.fromisoformat(text).timestamp()
        except Exception:
            return float("inf")

    def _dedupe(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        order: list[tuple[Any, ...]] = []
        for event in events:
            data = event.get("data") or {}
            event_id = event.get("event_id")
            if event_id not in (None, ""):
                key = ("id", str(event_id))
            else:
                # SquawkFlow can surface the same underlying observation more than once
                # with different observation timestamps. Exclude timestamp from the
                # identity but keep fields that distinguish the actual option print.
                key = (
                    "print",
                    event.get("symbol"),
                    data.get("side"),
                    data.get("strike"),
                    data.get("expiration"),
                    data.get("premium"),
                    data.get("contracts"),
                    data.get("volume"),
                    data.get("open_interest"),
                    data.get("aggression"),
                    data.get("direction"),
                )
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = event
                order.append(key)
                continue
            # Purchase time should represent the earliest source timestamp for the
            # repeated observation rather than a later cache/observation timestamp.
            if self._time_value(event.get("occurred_at")) < self._time_value(existing.get("occurred_at")):
                by_key[key] = event
        return [by_key[key] for key in order]

    def _normalize(self, row: dict[str, Any]) -> dict[str, Any]:
        symbol = self._first(row, "symbol", "ticker", "underlying", "underlying_symbol")
        side = self._first(row, "side", "option_type", "type", "call_put", "right")
        if isinstance(side, str):
            s = side.strip().lower()
            side = "call" if s in {"c", "call", "calls"} else "put" if s in {"p", "put", "puts"} else s

        occurred = self._first(row, "occurred_at", "trade_time", "trade_timestamp", "timestamp", "time", "observed_at", "as_of", "datetime")
        score = self._first(row, "outlier_score", "unusual_score", "score", "rank_score")
        aggression = self._first(row, "aggression", "execution", "execution_side", "trade_side")
        premium = self._first(row, "premium", "total_premium", "estimated_premium", "notional")
        contracts = self._first(row, "contracts", "size", "contract_volume")
        volume = self._first(row, "volume", "option_volume")
        oi = self._first(row, "open_interest", "oi")
        vol_oi = self._first(row, "volume_oi_ratio", "vol_oi", "volume_to_oi", "vol_oi_ratio")
        direction = self._first(row, "direction", "sentiment", "bias")
        event_id = self._first(row, "id", "event_id", "trade_id", "flow_id", "uuid")

        return {
            "event_id": event_id,
            "event_type": "options",
            "symbol": str(symbol or "").upper(),
            "provider": self.name,
            "outlier_score": self._number(score),
            "occurred_at": occurred,
            "source_url": self._first(row, "source_url", "url") or SOURCE_URL,
            "data": {
                "side": side,
                "strike": self._number(self._first(row, "strike", "strike_price")),
                "expiration": self._first(row, "expiration", "expiry", "expiration_date"),
                "premium": self._number(premium),
                "contracts": self._number(contracts),
                "volume": self._number(volume),
                "open_interest": self._number(oi),
                "volume_oi_ratio": self._number(vol_oi),
                "aggression": aggression,
                "direction": direction,
                "raw": row,
            },
        }

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return None if value in (None, "") else float(value)
        except (TypeError, ValueError):
            return None
