from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone

import yfinance as yf

from ..providers.alpaca_market_data import AlpacaMarketDataProvider

_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
CACHE_TTL_SECONDS = 6 * 60 * 60


def _yahoo_ohlc(symbol: str, period: str = "2y") -> dict:
    s = symbol.strip().upper()
    frame = yf.Ticker(s).history(period=period, interval="1d", auto_adjust=False, actions=False)
    if frame is None or frame.empty:
        raise RuntimeError(f"No OHLC history for {s}")
    rows = []
    for idx, row in frame.iterrows():
        try:
            rows.append({
                "date": str(idx.date()),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row.get("Volume") or 0),
            })
        except Exception:
            continue
    if len(rows) < 14:
        raise RuntimeError(f"Insufficient OHLC history for {s}")
    return {
        "symbol": s,
        "rows": rows,
        "provider": "Yahoo Finance",
        "source_url": f"https://finance.yahoo.com/quote/{s}/history",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def history(symbol: str) -> dict:
    s = symbol.strip().upper()
    provider_key = "alpaca" if AlpacaMarketDataProvider.configured() else "yahoo"
    key = (s, provider_key)
    cached = _CACHE.get(key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return {**cached[1], "cache": "hit"}
    if AlpacaMarketDataProvider.configured():
        try:
            data = AlpacaMarketDataProvider().daily_history(s, start="2024-01-01")
        except Exception:
            data = _yahoo_ohlc(s)
    else:
        data = _yahoo_ohlc(s)
    _CACHE[key] = (time.time(), data)
    return {**data, "cache": "miss"}


def aggregate_monthly(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[str(r["date"])[:7]].append(r)
    out = []
    for month in sorted(grouped):
        rs = sorted(grouped[month], key=lambda x: x["date"])
        out.append({
            "month": month,
            "date": rs[-1]["date"],
            "open": rs[0]["open"],
            "high": max(x["high"] for x in rs),
            "low": min(x["low"] for x in rs),
            "close": rs[-1]["close"],
        })
    return out


def completed_months(rows: list[dict], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    current = now.strftime("%Y-%m")
    return [r for r in aggregate_monthly(rows) if r["month"] < current]


def williams_14_month(rows: list[dict]) -> dict | None:
    monthly = completed_months(rows)
    if len(monthly) < 14:
        return None
    window = monthly[-14:]
    hh = max(x["high"] for x in window)
    ll = min(x["low"] for x in window)
    close = window[-1]["close"]
    value = 0.0 if hh == ll else -100.0 * (hh - close) / (hh - ll)
    return {
        "williams_r": round(value, 4),
        "signal_month": window[-1]["month"],
        "close": close,
        "highest_high": hh,
        "lowest_low": ll,
        "window_months": 14,
    }


def rank_basket(symbols: list[str]) -> dict:
    symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    rows = []
    unavailable = []
    for s in symbols:
        try:
            h = history(s)
            wr = williams_14_month(h["rows"])
            if wr is None:
                unavailable.append({"symbol": s, "reason": "insufficient_completed_months", "provider": h.get("provider")})
                continue
            rows.append({"symbol": s, **wr, "provider": h.get("provider"), "source_url": h.get("source_url"), "cache": h.get("cache")})
        except Exception as exc:
            unavailable.append({"symbol": s, "reason": str(exc)[:180]})
    ranked = sorted(rows, key=lambda x: x["williams_r"])
    n = len(ranked)
    denom = n * (n + 1) / 2 if n else 1
    for idx, row in enumerate(ranked):
        # Most oversold receives highest priority rank and largest linear weight.
        priority_rank = n - idx
        row["priority_rank"] = priority_rank
        row["priority_weight"] = round(priority_rank / denom, 6)
    return {
        "eligible": ranked,
        "unavailable": unavailable,
        "methodology": "Prior completed 14-month Williams %R. More-negative values receive higher cross-sectional priority. Linear rank weights sum to 1 across eligible symbols. Existing holdings are not rebalanced.",
    }


def deployment_plan(symbols: list[str], capital: float) -> dict:
    ranked = rank_basket(symbols)
    eligible = ranked["eligible"]
    for row in eligible:
        row["suggested_dollars"] = round(max(0.0, capital) * row["priority_weight"], 2)
    ranked["capital"] = round(max(0.0, capital), 2)
    ranked["allocated"] = round(sum(x["suggested_dollars"] for x in eligible), 2)
    return ranked
