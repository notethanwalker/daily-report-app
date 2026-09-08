from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime, timezone

import yfinance as yf

from ..providers.alpaca_market_data import AlpacaMarketDataProvider

_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
CACHE_TTL_SECONDS = 6 * 60 * 60
MODEL_VERSION = "williams-priority-v1.2"
MODEL_CONFIG = {
    "indicator": "Williams %R",
    "lookback_months": 14,
    "signal_period": "prior_completed_month",
    "ranking": "more_negative_is_higher_priority",
    "allocation": "linear_cross_sectional_rank",
    "new_capital_only": True,
    "rebalance_existing_holdings": False,
    "strict_universe": True,
    "require_common_signal_month": True,
}
MODEL_CONFIG_HASH = hashlib.sha256(json.dumps(MODEL_CONFIG, sort_keys=True).encode()).hexdigest()[:12]


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
    data = {
        **data,
        "retrieved_at": data.get("retrieved_at") or datetime.now(timezone.utc).isoformat(),
        "data_start": (data.get("rows") or [{}])[0].get("date") if data.get("rows") else None,
        "data_end": (data.get("rows") or [{}])[-1].get("date") if data.get("rows") else None,
    }
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
        "signal_date": window[-1]["date"],
        "window_start_month": window[0]["month"],
        "window_end_month": window[-1]["month"],
        "close": close,
        "highest_high": hh,
        "lowest_low": ll,
        "window_months": 14,
    }


def _fingerprint(rows: list[dict]) -> str:
    stable=[{
        "symbol":x.get("symbol"),"signal_month":x.get("signal_month"),"williams_r":x.get("williams_r"),
        "priority_rank":x.get("priority_rank"),"priority_weight":x.get("priority_weight"),"provider":x.get("provider"),
        "data_end":x.get("data_end"),"model_version":MODEL_VERSION,"config_hash":MODEL_CONFIG_HASH,
    } for x in rows]
    return hashlib.sha256(json.dumps(stable,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:20]


def rank_basket(symbols: list[str]) -> dict:
    requested = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    rows = []
    unavailable = []
    for s in requested:
        try:
            h = history(s)
            wr = williams_14_month(h["rows"])
            if wr is None:
                unavailable.append({"symbol": s, "reason": "insufficient_completed_months", "provider": h.get("provider"),"data_start":h.get("data_start"),"data_end":h.get("data_end")})
                continue
            rows.append({
                "symbol": s, **wr, "provider": h.get("provider"), "source_url": h.get("source_url"), "cache": h.get("cache"),
                "retrieved_at":h.get("retrieved_at"),"data_start":h.get("data_start"),"data_end":h.get("data_end"),
            })
        except Exception as exc:
            unavailable.append({"symbol": s, "reason": str(exc)[:180]})
    ranked = sorted(rows, key=lambda x: x["williams_r"])
    n = len(ranked)
    denom = n * (n + 1) / 2 if n else 1
    for idx, row in enumerate(ranked):
        priority_rank = n - idx
        row["priority_rank"] = priority_rank
        row["priority_weight"] = round(priority_rank / denom, 6)
    signal_months = sorted({str(x.get("signal_month") or "") for x in ranked if x.get("signal_month")})
    complete_universe = len(ranked) == len(requested) and not unavailable and bool(requested)
    aligned_signal_month = len(signal_months) == 1
    if not requested:
        status = "blocked_empty_universe"
    elif not complete_universe:
        status = "blocked_incomplete_universe"
    elif not aligned_signal_month:
        status = "blocked_signal_misalignment"
    else:
        status = "ready"
    return {
        "requested_symbols": requested,
        "eligible": ranked,
        "unavailable": unavailable,
        "coverage_ratio": round(len(ranked) / len(requested), 4) if requested else 0.0,
        "signal_months": signal_months,
        "common_signal_month": signal_months[0] if aligned_signal_month and signal_months else None,
        "allocation_status": status,
        "model_version":MODEL_VERSION,
        "model_config_hash":MODEL_CONFIG_HASH,
        "model_config":MODEL_CONFIG,
        "input_fingerprint":_fingerprint(ranked),
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "methodology": "Prior completed 14-month Williams %R. More-negative values receive higher cross-sectional priority. Linear rank weights sum to 1 across the complete requested universe. Allocation fails closed if any constituent is unavailable or if constituents do not share the same completed signal month. Existing holdings are not rebalanced.",
    }


def deployment_plan(symbols: list[str], capital: float) -> dict:
    ranked = rank_basket(symbols)
    eligible = ranked["eligible"]
    requested_capital = round(max(0.0, capital), 2)
    if ranked["allocation_status"] != "ready":
        for row in eligible:
            row["suggested_dollars"] = 0.0
        ranked["capital"] = requested_capital
        ranked["allocated"] = 0.0
        ranked["unallocated"] = requested_capital
    else:
        allocations=[]
        for row in eligible:
            allocations.append(round(requested_capital * row["priority_weight"], 2))
        # Keep the plan cash-exact after cent rounding by assigning any residual
        # to the highest-priority constituent.
        residual=round(requested_capital-sum(allocations),2)
        if allocations:
            allocations[0]=round(allocations[0]+residual,2)
        for row,dollars in zip(eligible,allocations):
            row["suggested_dollars"] = dollars
        ranked["capital"] = requested_capital
        ranked["allocated"] = round(sum(allocations),2)
        ranked["unallocated"] = round(requested_capital-ranked["allocated"],2)
    ranked["lineage"]={
        "model_version":MODEL_VERSION,
        "model_config_hash":MODEL_CONFIG_HASH,
        "input_fingerprint":ranked["input_fingerprint"],
        "allocation_status":ranked["allocation_status"],
        "coverage_ratio":ranked["coverage_ratio"],
        "common_signal_month":ranked["common_signal_month"],
        "signal_policy":"prior completed month only; complete and time-aligned universe required",
        "provider_preference":"Alpaca IEX when configured, Yahoo Finance fallback",
        "constituent_inputs":[{"symbol":x["symbol"],"provider":x.get("provider"),"retrieved_at":x.get("retrieved_at"),"data_start":x.get("data_start"),"data_end":x.get("data_end"),"signal_date":x.get("signal_date"),"signal_month":x.get("signal_month"),"source_url":x.get("source_url")} for x in eligible],
    }
    return ranked
