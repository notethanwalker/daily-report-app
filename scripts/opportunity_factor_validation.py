#!/usr/bin/env python3
"""Cross-sample validation for V4 Opportunity criteria.

This runner intentionally does not mutate production criterion status. It produces
research evidence for review. Features are computed point-in-time from daily OHLCV;
forward returns begin after the observation date.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

MODEL_VERSION = "opportunity-formula-v1"
DEFAULT_SYMBOLS = [
    "NVDA", "MU", "AMD", "AVGO", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "QCOM",
    "AMZN", "META", "GOOGL", "MSFT", "TSLA", "NFLX", "SPY", "QQQ", "SMH", "IWM", "XLK",
]
HORIZONS = (5, 20, 60)
FACTORS = (
    "williams", "ma100_proximity", "ma50_proximity", "ma100_slope",
    "approach_velocity", "relative_volume",
)


def clip(value: pd.Series, low: float = 0.0, high: float = 100.0) -> pd.Series:
    return value.clip(lower=low, upper=high)


def ma_proximity_score(distance: pd.Series) -> pd.Series:
    out = pd.Series(0.0, index=distance.index)
    out[(distance >= 0) & (distance <= 1)] = 100
    out[(distance > 1) & (distance <= 2)] = 90
    out[(distance > 2) & (distance <= 3)] = 80
    out[(distance > 3) & (distance <= 5)] = 60
    out[(distance > 5) & (distance <= 8)] = 30
    out[(distance > 8) & (distance <= 10)] = 15
    return out


def feature_frame(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        if symbol in df.columns.get_level_values(-1):
            df = df.xs(symbol, axis=1, level=-1)
        elif symbol in df.columns.get_level_values(0):
            df = df.xs(symbol, axis=1, level=0)
    df.columns = [str(c).title() for c in df.columns]
    required = {"High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        return pd.DataFrame()
    df = df.dropna(subset=["High", "Low", "Close"]).copy()
    if df.empty:
        return df

    close = df["Close"].astype(float)
    high14 = df["High"].rolling(14).max()
    low14 = df["Low"].rolling(14).min()
    spread = (high14 - low14).replace(0, pd.NA)
    williams = -100.0 * (high14 - close) / spread

    ma50 = close.rolling(50).mean()
    ma100 = close.rolling(100).mean()
    d50 = (close / ma50 - 1.0) * 100.0
    d100 = (close / ma100 - 1.0) * 100.0
    slope100 = (ma100 / ma100.shift(20) - 1.0) * 100.0
    approach100 = d100.shift(5) - d100
    prior_avg_volume = df["Volume"].astype(float).shift(1).rolling(20).mean()
    rel_volume = df["Volume"].astype(float) / prior_avg_volume.replace(0, pd.NA)

    result = pd.DataFrame(index=df.index)
    result["symbol"] = symbol
    result["williams"] = clip((-50.0 - williams) * 2.0)
    result["ma100_proximity"] = ma_proximity_score(d100)
    result["ma50_proximity"] = ma_proximity_score(d50)
    result["ma100_slope"] = clip(50.0 + slope100 * 20.0)
    result["approach_velocity"] = clip(50.0 + approach100 * 10.0)
    result["relative_volume"] = clip(((rel_volume - 0.5) / 1.5) * 100.0)
    for horizon in HORIZONS:
        result[f"fwd_{horizon}d"] = (close.shift(-horizon) / close - 1.0) * 100.0
    result["raw_williams"] = williams
    result["raw_ma100_distance"] = d100
    result["raw_ma50_distance"] = d50
    result["raw_ma100_slope"] = slope100
    result["raw_approach_velocity"] = approach100
    result["raw_relative_volume"] = rel_volume
    result.index = pd.to_datetime(result.index).tz_localize(None)
    result.index.name = "date"
    return result.reset_index()


def download_symbol(symbol: str, start: str, end: str | None) -> pd.DataFrame:
    kwargs = {"tickers": symbol, "start": start, "auto_adjust": True, "progress": False, "actions": False}
    if end:
        kwargs["end"] = end
    return yf.download(**kwargs)


def weekly_sample(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    work = frame.copy()
    work["week"] = work["date"].dt.to_period("W-FRI")
    return work.sort_values("date").groupby(["symbol", "week"], as_index=False).tail(1).drop(columns=["week"])


def rank_ic(values: pd.DataFrame, factor: str, target: str) -> float | None:
    clean = values[[factor, target]].dropna()
    if len(clean) < 5 or clean[factor].nunique() < 2 or clean[target].nunique() < 2:
        return None
    return float(clean[factor].rank().corr(clean[target].rank()))


def summarize_split(values: pd.DataFrame, factor: str, horizon: int) -> dict:
    target = f"fwd_{horizon}d"
    clean = values[["date", "symbol", factor, target]].dropna().copy()
    if clean.empty:
        return {"samples": 0}
    threshold = clean[factor].quantile(0.75)
    top = clean[clean[factor] >= threshold]
    base_mean = float(clean[target].mean())
    top_mean = float(top[target].mean()) if not top.empty else None
    per_symbol = top.groupby("symbol")[target].mean() if not top.empty else pd.Series(dtype=float)
    return {
        "samples": int(len(clean)),
        "distinct_dates": int(clean["date"].nunique()),
        "symbols": int(clean["symbol"].nunique()),
        "rank_ic": None if (ic := rank_ic(clean, factor, target)) is None else round(ic, 4),
        "top_quartile_threshold": round(float(threshold), 3),
        "all_mean_return_pct": round(base_mean, 3),
        "top_quartile_mean_return_pct": None if top_mean is None else round(top_mean, 3),
        "top_quartile_excess_pct": None if top_mean is None else round(top_mean - base_mean, 3),
        "top_quartile_positive_rate": None if top.empty else round(float((top[target] > 0).mean()), 4),
        "top_quartile_symbol_hit_rate": None if per_symbol.empty else round(float((per_symbol > base_mean).mean()), 4),
    }


def factor_report(frame: pd.DataFrame, factor: str, split_date: pd.Timestamp) -> dict:
    discovery = frame[frame["date"] <= split_date]
    validation = frame[frame["date"] > split_date]
    horizons = {}
    for horizon in HORIZONS:
        horizons[str(horizon)] = {
            "discovery": summarize_split(discovery, factor, horizon),
            "validation": summarize_split(validation, factor, horizon),
        }
    # Deliberately conservative: this is a research flag, not an automatic promotion.
    v20 = horizons["20"]["validation"]
    d20 = horizons["20"]["discovery"]
    review_candidate = bool(
        d20.get("samples", 0) >= 100
        and v20.get("samples", 0) >= 60
        and (d20.get("rank_ic") or 0) > 0
        and (v20.get("rank_ic") or 0) > 0
        and (d20.get("top_quartile_excess_pct") or 0) > 0
        and (v20.get("top_quartile_excess_pct") or 0) > 0
    )
    return {"horizons": horizons, "review_candidate": review_candidate}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    p.add_argument("--start", default="2010-01-01")
    p.add_argument("--end", default="")
    p.add_argument("--split", type=float, default=0.70)
    p.add_argument("--output", default="opportunity_factor_validation.json")
    args = p.parse_args()
    if not 0.5 <= args.split <= 0.9:
        raise SystemExit("--split must be between 0.5 and 0.9")

    symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    frames, failures = [], {}
    for symbol in symbols:
        try:
            raw = download_symbol(symbol, args.start, args.end or None)
            built = feature_frame(raw, symbol)
            if built.empty:
                failures[symbol] = "no usable OHLCV"
            else:
                frames.append(built)
        except Exception as exc:
            failures[symbol] = str(exc)[:240]
    if not frames:
        raise SystemExit("No symbols produced usable data")

    pooled = weekly_sample(pd.concat(frames, ignore_index=True)).sort_values("date")
    dates = sorted(pooled["date"].dropna().unique())
    split_index = min(len(dates) - 2, max(1, int(len(dates) * args.split) - 1))
    split_date = pd.Timestamp(dates[split_index])
    factors = {factor: factor_report(pooled, factor, split_date) for factor in FACTORS}

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": MODEL_VERSION,
        "source": "Yahoo Finance via yfinance; adjusted daily OHLCV",
        "symbols_requested": symbols,
        "symbols_loaded": sorted(pooled["symbol"].unique().tolist()),
        "failures": failures,
        "start": str(pooled["date"].min().date()),
        "end": str(pooled["date"].max().date()),
        "split_date": str(split_date.date()),
        "sampling": "last trading session of each W-FRI week per symbol",
        "forward_return_policy": "Close-to-close forward return; horizon starts after observation date. No future values enter feature computation.",
        "anti_overfit_policy": "Chronological discovery/validation split. review_candidate is advisory only and never mutates production status.",
        "limitations": [
            "Current-symbol basket is not a point-in-time market universe and therefore does not eliminate survivorship bias.",
            "Forward windows overlap, especially at 20D/60D; sample count overstates independent observations.",
            "Yahoo adjusted history is suitable for exploratory research but production promotion should be cross-checked against an independent source/sample.",
        ],
        "factors": factors,
    }
    Path(args.output).write_text(json.dumps(output, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "split_date": output["split_date"], "symbols_loaded": len(output["symbols_loaded"]), "review_candidates": [k for k, v in factors.items() if v["review_candidate"]]}, indent=2))


if __name__ == "__main__":
    main()
