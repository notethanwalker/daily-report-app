import os
from datetime import datetime, timezone

import httpx

BASE_URL = "https://api.twelvedata.com"
SOURCE_URL = "https://twelvedata.com/docs"


class TwelveDataError(RuntimeError):
    pass


class TwelveDataProvider:
    name = "Twelve Data"

    def __init__(self):
        self.api_key = os.getenv("TWELVE_DATA_API_KEY")
        if not self.api_key:
            raise TwelveDataError("TWELVE_DATA_API_KEY is not configured")

    def _get(self, path: str, params: dict) -> dict:
        request_params = {**params, "apikey": self.api_key}
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.get(f"{BASE_URL}{path}", params=request_params)
                if response.status_code >= 400:
                    raise TwelveDataError(f"Twelve Data HTTP {response.status_code}")
                data = response.json()
        except TwelveDataError:
            raise
        except httpx.HTTPError as exc:
            raise TwelveDataError("Twelve Data network error") from exc
        except ValueError as exc:
            raise TwelveDataError("Twelve Data returned invalid JSON") from exc

        if data.get("status") == "error" or ("code" in data and "message" in data):
            message = str(data.get("message") or "Twelve Data request failed")
            lowered = message.lower()
            if "rate limit" in lowered or "credits" in lowered:
                raise TwelveDataError("Twelve Data rate limit reached")
            if "not found" in lowered or "symbol" in lowered:
                raise TwelveDataError("Twelve Data symbol unavailable")
            raise TwelveDataError("Twelve Data request failed")

        return data

    def daily_history(self, symbol: str, outputsize: int = 260) -> dict:
        return self._get(
            "/time_series",
            {
                "symbol": symbol,
                "interval": "1day",
                "outputsize": outputsize,
                "order": "asc",
            },
        )

    def symbol_search(self, query: str, outputsize: int = 8) -> dict:
        data = self._get(
            "/symbol_search",
            {
                "symbol": query,
                "outputsize": outputsize,
            },
        )
        rows = data.get("data") or []
        return {
            "query": query,
            "provider": self.name,
            "source_url": SOURCE_URL,
            "results": [
                {
                    "symbol": row.get("symbol"),
                    "name": row.get("instrument_name") or row.get("name"),
                    "exchange": row.get("exchange"),
                    "country": row.get("country"),
                    "currency": row.get("currency"),
                    "type": row.get("instrument_type") or row.get("type"),
                }
                for row in rows
                if row.get("symbol")
            ],
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

    def market_snapshot_raw(self, symbol: str) -> dict:
        return {
            "history": self.daily_history(symbol),
            "provider": self.name,
            "source_url": SOURCE_URL,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
