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


def build_market_snapshot(raw: dict) -> dict:
    history = raw["history"]
    meta = history.get("meta", {})
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
        rows.append({"date": row_date,"close": close,"high": _number(item.get("high")),"low": _number(item.get("low")),"volume": _number(item.get("volume"))})
    rows.sort(key=lambda row: row["date"])
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
    ma50 = _mean(closes[-50:]) if len(closes) >= 50 else None
    ma100 = _mean(closes[-100:]) if len(closes) >= 100 else None
    ma200 = _mean(closes[-200:]) if len(closes) >= 200 else None
    year_rows = rows[-252:]
    highs_52 = [row["high"] for row in year_rows if row["high"] is not None]
    lows_52 = [row["low"] for row in year_rows if row["low"] is not None]
    all_highs = [row["high"] for row in rows if row["high"] is not None]
    all_time_high = max(all_highs) if all_highs else max(closes)

    current_volume = rows[-1]["volume"]
    prior_volumes = [row["volume"] for row in rows[-21:-1] if row["volume"] is not None]
    average_volume = _mean(prior_volumes)

    return {
        "symbol": meta.get("symbol"),"name": None,"exchange": meta.get("exchange"),"currency": meta.get("currency"),
        "price": current,"previous_close": previous_close,"change": None if previous_close is None else current - previous_close,
        "change_percent": _pct_change(current, previous_close),"seven_day_percent": _pct_change(current, close_7d),"thirty_day_percent": _pct_change(current, close_30d),"ytd_percent": _pct_change(current, close_ytd),
        "high_52_week": max(highs_52) if highs_52 else None,"low_52_week": min(lows_52) if lows_52 else None,"all_time_high": all_time_high,"price_vs_ath_percent": _pct_change(current, all_time_high),
        "ma50": ma50,"ma100": ma100,"ma200": ma200,"price_vs_ma50_percent": _pct_change(current, ma50),"price_vs_ma100_percent": _pct_change(current, ma100),"price_vs_ma200_percent": _pct_change(current, ma200),
        "volume": current_volume,"average_volume_20d": average_volume,"relative_volume": None if average_volume in (None, 0) or current_volume is None else current_volume / average_volume,
        "market_open": None,"as_of": rows[-1]["date"].isoformat(),"provider": raw["provider"],"source_url": raw["source_url"],"retrieved_at": raw["retrieved_at"],"verification_status": "primary_only",
        "data_note": "Daily time-series data; all-time high is based on provider history returned for the symbol."
    }
