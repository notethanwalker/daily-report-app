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
    if not eligible:
        return None
    return eligible[-1]["close"]


def _mean(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    return sum(values) / len(values)


def build_market_snapshot(raw: dict) -> dict:
    quote = raw["quote"]
    history = raw["history"]
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

        rows.append(
            {
                "date": row_date,
                "close": close,
                "high": _number(item.get("high")),
                "low": _number(item.get("low")),
                "volume": _number(item.get("volume")),
            }
        )

    rows.sort(key=lambda row: row["date"])
    if not rows:
        raise ValueError("No daily history returned")

    current = _number(quote.get("close")) or rows[-1]["close"]
    previous_close = _number(quote.get("previous_close"))
    if previous_close is None and len(rows) >= 2:
        previous_close = rows[-2]["close"]

    today = rows[-1]["date"]
    close_7d = _nearest_close_on_or_before(rows, today - timedelta(days=7))
    close_30d = _nearest_close_on_or_before(rows, today - timedelta(days=30))
    close_ytd = _nearest_close_on_or_before(rows, date(today.year - 1, 12, 31))
    if close_ytd is None:
        year_rows = [row for row in rows if row["date"].year == today.year]
        close_ytd = year_rows[0]["close"] if year_rows else None

    closes = [row["close"] for row in rows]
    ma100 = _mean(closes[-100:]) if len(closes) >= 100 else None
    ma200 = _mean(closes[-200:]) if len(closes) >= 200 else None

    year_rows = rows[-252:]
    highs = [row["high"] for row in year_rows if row["high"] is not None]
    lows = [row["low"] for row in year_rows if row["low"] is not None]

    current_volume = _number(quote.get("volume"))
    if current_volume is None:
        current_volume = rows[-1]["volume"]
    average_volume = _mean([row["volume"] for row in rows[-20:] if row["volume"] is not None])

    return {
        "symbol": quote.get("symbol") or history.get("meta", {}).get("symbol"),
        "name": quote.get("name"),
        "exchange": quote.get("exchange"),
        "currency": quote.get("currency"),
        "price": current,
        "previous_close": previous_close,
        "change": None if previous_close is None else current - previous_close,
        "change_percent": _pct_change(current, previous_close),
        "seven_day_percent": _pct_change(current, close_7d),
        "thirty_day_percent": _pct_change(current, close_30d),
        "ytd_percent": _pct_change(current, close_ytd),
        "high_52_week": max(highs) if highs else None,
        "low_52_week": min(lows) if lows else None,
        "ma100": ma100,
        "ma200": ma200,
        "price_vs_ma100_percent": _pct_change(current, ma100),
        "price_vs_ma200_percent": _pct_change(current, ma200),
        "volume": current_volume,
        "average_volume_20d": average_volume,
        "relative_volume": None if average_volume in (None, 0) or current_volume is None else current_volume / average_volume,
        "market_open": quote.get("is_market_open"),
        "as_of": quote.get("datetime") or rows[-1]["date"].isoformat(),
        "provider": raw["provider"],
        "source_url": raw["source_url"],
        "retrieved_at": raw["retrieved_at"],
        "verification_status": "primary_only",
    }
