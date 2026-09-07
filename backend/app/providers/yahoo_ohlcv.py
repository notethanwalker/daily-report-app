from __future__ import annotations

from datetime import datetime, timezone

import yfinance as yf

SOURCE_ROOT = "https://finance.yahoo.com/quote"


class YahooOhlcvError(RuntimeError):
    pass


def _number(value):
    try:
        if value is None:
            return None
        n = float(value)
        return None if n != n else n
    except (TypeError, ValueError):
        return None


class YahooOhlcvProvider:
    name = "Yahoo Finance"

    def daily_history(self, symbol: str, period: str = "5y") -> dict:
        s = symbol.strip().upper()
        try:
            frame = yf.Ticker(s).history(period=period, interval="1d", auto_adjust=False, actions=False)
        except Exception as exc:
            raise YahooOhlcvError(f"Yahoo Finance OHLCV request failed for {s}") from exc
        if frame is None or frame.empty:
            raise YahooOhlcvError(f"Yahoo Finance returned no OHLCV history for {s}")
        rows = []
        for idx, row in frame.iterrows():
            close = _number(row.get("Close"))
            if close is None:
                continue
            try:
                dt = idx.to_pydatetime().date().isoformat() if hasattr(idx, "to_pydatetime") else str(idx)[:10]
            except Exception:
                dt = str(idx)[:10]
            rows.append({
                "date": dt,
                "open": _number(row.get("Open")),
                "high": _number(row.get("High")),
                "low": _number(row.get("Low")),
                "close": close,
                "volume": _number(row.get("Volume")) or 0.0,
            })
        if len(rows) < 14:
            raise YahooOhlcvError(f"Yahoo Finance returned insufficient OHLCV history for {s}")
        return {
            "symbol": s,
            "rows": rows,
            "provider": self.name,
            "source_url": f"{SOURCE_ROOT}/{s}/history",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
