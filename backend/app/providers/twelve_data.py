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
        with httpx.Client(timeout=20.0) as client:
            response = client.get(f"{BASE_URL}{path}", params=request_params)
            response.raise_for_status()
            data = response.json()

        if data.get("status") == "error" or ("code" in data and "message" in data):
            raise TwelveDataError(data.get("message", "Twelve Data request failed"))

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

    def market_snapshot_raw(self, symbol: str) -> dict:
        return {
            "history": self.daily_history(symbol),
            "provider": self.name,
            "source_url": SOURCE_URL,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
