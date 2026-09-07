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


def _rows_from_frame(frame) -> list[dict]:
    rows = []
    if frame is None or frame.empty:
        return rows
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
    return rows


class YahooOhlcvProvider:
    name = "Yahoo Finance"

    def daily_history(self, symbol: str, period: str = "5y") -> dict:
        s = symbol.strip().upper()
        try:
            frame = yf.Ticker(s).history(period=period, interval="1d", auto_adjust=False, actions=False)
        except Exception as exc:
            raise YahooOhlcvError(f"Yahoo Finance OHLCV request failed for {s}") from exc
        rows = _rows_from_frame(frame)
        if len(rows) < 14:
            raise YahooOhlcvError(f"Yahoo Finance returned insufficient OHLCV history for {s}")
        return {
            "symbol": s,
            "rows": rows,
            "provider": self.name,
            "source_url": f"{SOURCE_ROOT}/{s}/history",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

    def batch_daily_history(self, symbols: list[str], period: str = "2y") -> dict[str, dict]:
        """Fetch many symbols concurrently and return only symbols with usable OHLCV."""
        requested = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
        if not requested:
            return {}
        try:
            frame = yf.download(
                tickers=requested,
                period=period,
                interval="1d",
                auto_adjust=False,
                actions=False,
                group_by="ticker",
                threads=True,
                progress=False,
                timeout=30,
            )
        except Exception as exc:
            raise YahooOhlcvError("Yahoo Finance batch OHLCV request failed") from exc

        retrieved_at = datetime.now(timezone.utc).isoformat()
        out: dict[str, dict] = {}
        if len(requested) == 1:
            symbol = requested[0]
            rows = _rows_from_frame(frame)
            if len(rows) >= 14:
                out[symbol] = {
                    "symbol": symbol,
                    "rows": rows,
                    "provider": self.name,
                    "source_url": f"{SOURCE_ROOT}/{symbol}/history",
                    "retrieved_at": retrieved_at,
                }
            return out

        # yfinance returns a ticker-first MultiIndex when group_by='ticker'.
        for symbol in requested:
            try:
                sub = frame[symbol]
            except Exception:
                continue
            rows = _rows_from_frame(sub)
            if len(rows) < 14:
                continue
            out[symbol] = {
                "symbol": symbol,
                "rows": rows,
                "provider": self.name,
                "source_url": f"{SOURCE_ROOT}/{symbol}/history",
                "retrieved_at": retrieved_at,
            }
        return out
