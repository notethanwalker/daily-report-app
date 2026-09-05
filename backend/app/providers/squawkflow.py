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
            rows = raw_data.get("items") or raw_data.get("results") or raw_data.get("flow") or raw_data.get("data") or []
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
            "note": "Public unusual-options observations. SquawkFlow describes these rows as aggregated contract activity rather than guaranteed single-trade prints, so repeated rows for the same contract are collapsed. Buy/sell execution is inferred from source execution fields and is separate from call/put type.",
        }

    @staticmethod
    def _first(row: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def _candidate_dicts(row: dict[str, Any]) -> list[dict[str, Any]]:
        out = [row]
        for key in ("contract", "option", "details", "activity", "trade", "underlying", "data"):
            value = row.get(key)
            if isinstance(value, dict):
                out.append(value)
        return out

    @classmethod
    def _nested_first(cls, row: dict[str, Any], *keys: str) -> Any:
        for candidate in cls._candidate_dicts(row):
            value = cls._first(candidate, *keys)
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def _time_value(value: Any) -> float:
        if not value:
            return float("-inf")
        try:
            text = str(value).replace("Z", "+00:00")
            return datetime.fromisoformat(text).timestamp()
        except Exception:
            return float("-inf")

    @staticmethod
    def _option_type(value: Any) -> str | None:
        if value in (None, ""):
            return None
        s = str(value).strip().lower()
        if s in {"c", "call", "calls", "call_option"}:
            return "call"
        if s in {"p", "put", "puts", "put_option"}:
            return "put"
        return None

    @staticmethod
    def _execution(value: Any) -> str | None:
        if value in (None, ""):
            return None
        s = str(value).strip().lower()
        if any(token in s for token in ("buy", "ask", "lift", "bought")):
            return "buy"
        if any(token in s for token in ("sell", "bid", "hit", "sold")):
            return "sell"
        return s

    def _dedupe(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse duplicate snapshots of the same option contract.

        SquawkFlow's public unusual endpoint represents aggregated contract activity.
        Premium/volume and observation timestamps can change between repeated rows, so
        they are not part of the fallback identity. The most recently observed row is
        retained because it contains the fullest aggregate statistics.
        """
        by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        order: list[tuple[Any, ...]] = []
        for event in events:
            data = event.get("data") or {}
            event_id = event.get("event_id")
            contract_key = (
                "contract",
                event.get("symbol"),
                data.get("side"),
                data.get("strike"),
                data.get("expiration"),
            )
            # Prefer contract identity because provider IDs can represent observations
            # of the same aggregate rather than a permanent contract-level identity.
            key = contract_key if all(x not in (None, "") for x in contract_key[1:]) else ("id", str(event_id)) if event_id not in (None, "") else (
                "fallback", event.get("symbol"), data.get("side"), data.get("strike"), data.get("expiration"), data.get("contracts")
            )
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = event
                order.append(key)
                continue
            if self._time_value(event.get("occurred_at")) >= self._time_value(existing.get("occurred_at")):
                by_key[key] = event
        return [by_key[key] for key in order]

    def _normalize(self, row: dict[str, Any]) -> dict[str, Any]:
        symbol = self._nested_first(row, "symbol", "ticker", "underlying_symbol", "underlyingTicker", "underlying")
        if isinstance(symbol, dict):
            symbol = self._first(symbol, "symbol", "ticker")

        # Option type must not treat a generic `side=buy/sell` field as call/put.
        side = None
        for key in ("option_type", "put_call", "call_put", "right", "contract_type", "optionType", "type"):
            side = self._option_type(self._nested_first(row, key))
            if side:
                break
        if not side:
            generic_side = self._nested_first(row, "side")
            side = self._option_type(generic_side)

        occurred = self._nested_first(row, "occurred_at", "trade_time", "trade_timestamp", "last_trade_time", "timestamp", "time", "observed_at", "updated_at", "as_of", "datetime")
        score = self._nested_first(row, "outlier_score", "unusual_score", "score", "rank_score")
        aggression_raw = self._nested_first(row, "aggression", "execution", "execution_side", "trade_side", "order_side", "transaction_side")
        if aggression_raw in (None, ""):
            generic_side = self._nested_first(row, "side")
            if self._option_type(generic_side) is None:
                aggression_raw = generic_side
        aggression = self._execution(aggression_raw)
        premium = self._nested_first(row, "premium", "total_premium", "estimated_premium", "notional", "premium_total")
        contracts = self._nested_first(row, "contracts", "size", "contract_volume", "trade_size")
        volume = self._nested_first(row, "volume", "option_volume", "day_volume")
        oi = self._nested_first(row, "open_interest", "oi", "openInterest")
        vol_oi = self._nested_first(row, "volume_oi_ratio", "vol_oi", "volume_to_oi", "vol_oi_ratio")
        direction = self._nested_first(row, "direction", "sentiment", "bias")
        event_id = self._nested_first(row, "id", "event_id", "trade_id", "flow_id", "uuid")
        market_cap = self._nested_first(row, "market_cap", "marketCap", "underlying_market_cap", "underlyingMarketCap")

        return {
            "event_id": event_id,
            "event_type": "options",
            "symbol": str(symbol or "").upper(),
            "provider": self.name,
            "outlier_score": self._number(score),
            "occurred_at": occurred,
            "source_url": self._nested_first(row, "source_url", "url") or SOURCE_URL,
            "data": {
                "side": side,
                "strike": self._number(self._nested_first(row, "strike", "strike_price", "strikePrice")),
                "expiration": self._nested_first(row, "expiration", "expiry", "expiration_date", "expirationDate"),
                "premium": self._number(premium),
                "contracts": self._number(contracts),
                "volume": self._number(volume),
                "open_interest": self._number(oi),
                "volume_oi_ratio": self._number(vol_oi),
                "aggression": aggression,
                "direction": direction,
                "market_cap": self._number(market_cap),
                "raw": row,
            },
        }

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return None if value in (None, "") else float(value)
        except (TypeError, ValueError):
            return None
