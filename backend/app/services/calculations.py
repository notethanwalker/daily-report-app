from datetime import date, datetime, timedelta


def _number(value):
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_change(current, previous):
    if current is None or previous in (None, 0):
        return None
    return ((current / previous) - 1.0) * 100.0


def _nearest_close_on_or_before(rows, target: date):
    eligible = [row for row in rows if row["date"] <= target]
    return eligible[-1]["close"] if eligible else None


def _mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _ma_at_offset(closes: list[float], period: int, offset: int = 0) -> float | None:
    end = len(closes) - max(0, offset)
    start = end - period
    if start < 0 or end <= 0:
        return None
    return _mean(closes[start:end])


def parse_daily_rows(history: dict) -> list[dict]:
    values = history.get("values") or []
    rows = []
    for item in values:
        try:
            row_date = datetime.fromisoformat(item["datetime"]).date()
        except (KeyError, TypeError, ValueError):
            continue
        close = _number(item.get("close"))
        if close is None:
            continue
        rows.append({
            "date": row_date,
            "open": _number(item.get("open")),
            "close": close,
            "high": _number(item.get("high")),
            "low": _number(item.get("low")),
            "volume": _number(item.get("volume")),
        })
    rows.sort(key=lambda row: row["date"])
    return rows


def _williams_from_rows(rows: list[dict], period: int = 14) -> float | None:
    if len(rows) < period:
        return None
    window = rows[-period:]
    highs = [r["high"] for r in window if r["high"] is not None]
    lows = [r["low"] for r in window if r["low"] is not None]
    if not highs or not lows:
        return None
    high = max(highs)
    low = min(lows)
    close = rows[-1]["close"]
    value = 0.0 if high == low else -100.0 * ((high - close) / (high - low))
    return round(value, 2)


def build_williams_r_series(history: dict, period: int = 14, max_points: int = 320) -> dict:
    rows = parse_daily_rows(history)
    series = []
    for i in range(max(period - 1, 0), len(rows)):
        window = rows[i - period + 1:i + 1]
        highs = [r["high"] for r in window if r["high"] is not None]
        lows = [r["low"] for r in window if r["low"] is not None]
        close = rows[i]["close"]
        if not highs or not lows:
            continue
        high = max(highs)
        low = min(lows)
        value = 0.0 if high == low else -100.0 * ((high - close) / (high - low))
        series.append({"date": rows[i]["date"].isoformat(), "value": round(value, 2)})
    if len(series) > max_points:
        step = max(1, len(series) // max_points)
        sampled = series[::step]
        if sampled[-1] != series[-1]:
            sampled.append(series[-1])
        series = sampled[-max_points:]
    return {
        "period": period,
        "timeframe": "provider_history",
        "points": series,
        "latest": series[-1]["value"] if series else None,
        "overbought_level": -20,
        "oversold_level": -80,
    }


def build_market_snapshot(raw: dict) -> dict:
    history = raw["history"]
    meta = history.get("meta", {})
    rows = parse_daily_rows(history)
    if not rows:
        raise ValueError("No daily history returned")

    current = rows[-1]["close"]
    previous_close = rows[-2]["close"] if len(rows) >= 2 else None
    today = rows[-1]["date"]
    close_7d = _nearest_close_on_or_before(rows, today - timedelta(days=7))
    close_30d = _nearest_close_on_or_before(rows, today - timedelta(days=30))
    close_ytd = _nearest_close_on_or_before(rows, date(today.year - 1, 12, 31))
    if close_ytd is None:
        year_rows = [row for row in rows if row["date"].year == today.year]
        close_ytd = year_rows[0]["close"] if year_rows else None

    closes = [row["close"] for row in rows]
    ma50 = _ma_at_offset(closes, 50)
    ma100 = _ma_at_offset(closes, 100)
    ma200 = _ma_at_offset(closes, 200)

    ma100_5d_ago = _ma_at_offset(closes, 100, 5)
    ma100_20d_ago = _ma_at_offset(closes, 100, 20)
    close_5d_ago = rows[-6]["close"] if len(rows) >= 106 else None
    ma100_distance_now = _pct_change(current, ma100)
    ma100_distance_5d_ago = _pct_change(close_5d_ago, ma100_5d_ago)
    approach_velocity_100_5d = None
    if ma100_distance_now is not None and ma100_distance_5d_ago is not None:
        # Positive means the stock moved closer to the 100MA from where it was 5 sessions ago.
        approach_velocity_100_5d = ma100_distance_5d_ago - ma100_distance_now
    ma100_slope_20d_percent = _pct_change(ma100, ma100_20d_ago)

    year_rows = rows[-252:]
    highs_52 = [row["high"] for row in year_rows if row["high"] is not None]
    lows_52 = [row["low"] for row in year_rows if row["low"] is not None]
    supplied_highs = [row["high"] for row in rows if row["high"] is not None]
    supplied_history_high = max(supplied_highs) if supplied_highs else max(closes)

    current_volume = rows[-1]["volume"]
    prior_volumes = [row["volume"] for row in rows[-21:-1] if row["volume"] is not None]
    average_volume = _mean(prior_volumes)

    return {
        "symbol": meta.get("symbol"),
        "name": None,
        "exchange": meta.get("exchange"),
        "currency": meta.get("currency"),
        "price": current,
        "previous_close": previous_close,
        "change": None if previous_close is None else current - previous_close,
        "change_percent": _pct_change(current, previous_close),
        "seven_day_percent": _pct_change(current, close_7d),
        "thirty_day_percent": _pct_change(current, close_30d),
        "ytd_percent": _pct_change(current, close_ytd),
        "high_52_week": max(highs_52) if highs_52 else None,
        "low_52_week": min(lows_52) if lows_52 else None,
        "all_time_high": supplied_history_high,
        "price_vs_ath_percent": _pct_change(current, supplied_history_high),
        "ma50": ma50,
        "ma100": ma100,
        "ma200": ma200,
        "price_vs_ma50_percent": _pct_change(current, ma50),
        "price_vs_ma100_percent": ma100_distance_now,
        "price_vs_ma200_percent": _pct_change(current, ma200),
        "ma100_5d_ago": ma100_5d_ago,
        "ma100_20d_ago": ma100_20d_ago,
        "ma100_distance_5d_ago": ma100_distance_5d_ago,
        "approach_velocity_100_5d": approach_velocity_100_5d,
        "ma100_slope_20d_percent": ma100_slope_20d_percent,
        "williams_r_14": _williams_from_rows(rows, 14),
        "volume": current_volume,
        "average_volume_20d": average_volume,
        "relative_volume": None if average_volume in (None, 0) or current_volume is None else current_volume / average_volume,
        "market_open": None,
        "as_of": rows[-1]["date"].isoformat(),
        "provider": raw["provider"],
        "source_url": raw["source_url"],
        "retrieved_at": raw["retrieved_at"],
        "verification_status": "primary_only",
        "technical_source": "normalized_daily_bars" if raw.get("normalized") else "provider_history",
        "is_materialized_cache": bool(raw.get("normalized")),
        "data_note": "Williams %R, moving averages, true 5-session 100MA approach velocity and true 20-session 100MA slope are derived from the same OHLCV history window.",
    }
