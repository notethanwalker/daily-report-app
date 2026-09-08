from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://data.alpaca.markets/v2/stocks"


class AlpacaMarketDataError(RuntimeError):
    pass


class AlpacaMarketDataProvider:
    """Free Alpaca/IEX historical OHLC provider.

    Activation is credential-only: set APCA_API_KEY_ID and APCA_API_SECRET_KEY in the
    backend environment. No credentials are committed to source control.
    """

    name = "Alpaca IEX"

    @staticmethod
    def configured() -> bool:
        return bool(os.getenv("APCA_API_KEY_ID") and os.getenv("APCA_API_SECRET_KEY"))

    def _headers(self) -> dict[str, str]:
        key = os.getenv("APCA_API_KEY_ID")
        secret = os.getenv("APCA_API_SECRET_KEY")
        if not key or not secret:
            raise AlpacaMarketDataError("Alpaca credentials are not configured")
        return {
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "User-Agent": "daily-report-app/1.0",
        }

    def daily_history(self, symbol: str, start: str = "2016-01-01", end: str | None = None) -> dict:
        s = symbol.strip().upper()
        rows: list[dict] = []
        token = None
        while True:
            params = {
                "timeframe": "1Day",
                "start": start,
                "limit": 10000,
                "adjustment": "all",
                "feed": "iex",
                "sort": "asc",
            }
            if end:
                params["end"] = end
            if token:
                params["page_token"] = token
            url = f"{BASE}/{urllib.parse.quote(s)}/bars?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                raise AlpacaMarketDataError(f"Alpaca historical request failed for {s}") from exc
            for b in payload.get("bars") or []:
                rows.append({
                    "date": str(b.get("t") or "")[:10],
                    "open": float(b["o"]),
                    "high": float(b["h"]),
                    "low": float(b["l"]),
                    "close": float(b["c"]),
                    "volume": float(b.get("v") or 0),
                })
            token = payload.get("next_page_token")
            if not token:
                break
        rows = [r for r in rows if r["date"]]
        rows.sort(key=lambda r: r["date"])
        if len(rows) < 14:
            raise AlpacaMarketDataError(f"Alpaca returned insufficient history for {s}")
        return {
            "symbol": s,
            "rows": rows,
            "provider": self.name,
            "source_url": f"https://docs.alpaca.markets/reference/stockbarsingle-1",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
