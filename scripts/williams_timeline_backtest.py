#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import urllib.parse
import urllib.request
from pathlib import Path


def fetch_stooq(symbol: str) -> list[dict]:
    s = symbol.strip().lower()
    if "." not in s:
        s += ".us"
    url = "https://stooq.com/q/d/l/?" + urllib.parse.urlencode({"s": s, "i": "d"})
    req = urllib.request.Request(url, headers={"User-Agent": "daily-report-app-backtest/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        text = response.read().decode("utf-8")
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            rows.append({
                "date": row["Date"][:10],
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row.get("Volume") or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r["date"])
    if len(rows) < 14:
        raise RuntimeError(f"Insufficient Stooq history for {symbol}: {len(rows)} rows")
    return rows


def fetch_yahoo(symbol: str) -> list[dict]:
    import yfinance as yf

    frame = yf.download(
        symbol.strip().upper(),
        start="1990-01-01",
        interval="1d",
        auto_adjust=True,
        actions=False,
        progress=False,
        threads=False,
    )
    if frame is None or frame.empty:
        raise RuntimeError(f"Yahoo returned no history for {symbol}")
    rows = []
    for dt, item in frame.iterrows():
        def value(name):
            v = item[name]
            if hasattr(v, "iloc"):
                v = v.iloc[0]
            return float(v)
        rows.append({
            "date": dt.date().isoformat(),
            "open": value("Open"),
            "high": value("High"),
            "low": value("Low"),
            "close": value("Close"),
            "volume": value("Volume"),
        })
    rows.sort(key=lambda r: r["date"])
    if len(rows) < 14:
        raise RuntimeError(f"Insufficient Yahoo history for {symbol}: {len(rows)} rows")
    return rows


def fetch_history(symbol: str) -> tuple[list[dict], str]:
    errors = []
    for name, loader in (("Yahoo Finance adjusted daily OHLC", fetch_yahoo), ("Stooq daily OHLC", fetch_stooq)):
        try:
            return loader(symbol), name
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("All history providers failed: " + " | ".join(errors))


def williams(rows: list[dict], window: int) -> list[dict]:
    out = []
    for i, row in enumerate(rows):
        wr = None
        if i >= window - 1:
            lookback = rows[i-window+1:i+1]
            hh = max(x["high"] for x in lookback)
            ll = min(x["low"] for x in lookback)
            if hh != ll:
                wr = -100.0 * (hh - row["close"]) / (hh - ll)
        out.append({**row, "williams_r": wr})
    return out


def summary(contributions, invested, cash, shares, price):
    market_value = shares * price
    total_value = market_value + cash
    profit = total_value - contributions
    return {
        "total_contributions": round(contributions, 2),
        "total_invested": round(invested, 2),
        "remaining_cash": round(cash, 2),
        "shares": round(shares, 8),
        "effective_cost_basis": round(invested / shares, 6) if shares else None,
        "stock_market_value": round(market_value, 2),
        "total_portfolio_value": round(total_value, 2),
        "profit": round(profit, 2),
        "return_pct": round(100 * profit / contributions, 4) if contributions else None,
    }


def run(symbol: str, start: str, end: str | None, contribution: float, threshold: float, window: int):
    raw, source = fetch_history(symbol)
    end = end or raw[-1]["date"]
    series = williams(raw, window)
    eligible = [r for r in series if start <= r["date"] <= end]
    if not eligible:
        raise RuntimeError("No trading days in requested range")

    first_by_month = {}
    for row in eligible:
        first_by_month.setdefault(row["date"][:7], row)
    contribution_dates = {r["date"] for r in first_by_month.values()}

    dca_shares = dca_invested = 0.0
    dca_transactions = []
    for row in first_by_month.values():
        shares = contribution / row["close"]
        dca_shares += shares
        dca_invested += contribution
        dca_transactions.append({"date": row["date"], "amount": contribution, "close": row["close"], "shares_bought": shares})

    cash = wr_shares = wr_invested = 0.0
    contributions_ledger = []
    triggers = []
    previous = None
    for row in series:
        if row["date"] > end:
            break
        if row["date"] < start:
            previous = row
            continue
        if row["date"] in contribution_dates:
            cash += contribution
            contributions_ledger.append({"date": row["date"], "amount": contribution, "cash_after_contribution": cash})
        cur = row["williams_r"]
        prev = previous["williams_r"] if previous else None
        if cur is not None and prev is not None and cur <= threshold and prev > threshold and cash > 0:
            amount = cash
            shares = amount / row["close"]
            wr_shares += shares
            wr_invested += amount
            cash = 0.0
            triggers.append({"date": row["date"], "prior_williams_r": prev, "williams_r": cur, "close": row["close"], "amount_invested": amount, "shares_bought": shares})
        previous = row

    total_contributions = len(first_by_month) * contribution
    price = eligible[-1]["close"]
    result = {
        "test": "Williams Timeline Test",
        "symbol": symbol.upper(),
        "source": source,
        "parameters": {"start": eligible[0]["date"], "end": eligible[-1]["date"], "monthly_contribution": contribution, "threshold": threshold, "window": window},
        "valuation": {"date": eligible[-1]["date"], "close": price},
        "strategy_1_monthly_dca": {**summary(total_contributions, dca_invested, 0.0, dca_shares, price), "transactions": dca_transactions},
        "strategy_2_williams_timeline": {**summary(total_contributions, wr_invested, cash, wr_shares, price), "contributions": contributions_ledger, "triggers": triggers},
    }
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end")
    p.add_argument("--contribution", type=float, default=1000.0)
    p.add_argument("--threshold", type=float, default=-80.0)
    p.add_argument("--window", type=int, default=14)
    p.add_argument("--output", default="williams_backtest.json")
    args = p.parse_args()
    result = run(args.symbol, args.start, args.end, args.contribution, args.threshold, args.window)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
