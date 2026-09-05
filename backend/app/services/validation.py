from datetime import datetime, timedelta


def _pct_change(current, previous):
    if current is None or previous in (None, 0):
        return None
    return ((current / previous) - 1.0) * 100.0


def _mean(values):
    values = [value for value in values if value is not None]
    return None if not values else sum(values) / len(values)


def _nearest_close_on_or_before(rows, target_date):
    eligible = [row for row in rows if row["date"] <= target_date]
    return None if not eligible else eligible[-1]["close"]


def build_secondary_metrics(alpha_raw: dict) -> dict:
    rows = []
    for row in alpha_raw["rows"]:
        try:
            rows.append(
                {
                    **row,
                    "date": datetime.fromisoformat(row["date"]).date(),
                }
            )
        except (TypeError, ValueError):
            continue

    rows.sort(key=lambda row: row["date"])
    if not rows:
        raise ValueError("No usable secondary rows")

    latest = rows[-1]
    previous = rows[-2] if len(rows) >= 2 else None
    close_7d = _nearest_close_on_or_before(rows, latest["date"] - timedelta(days=7))
    close_30d = _nearest_close_on_or_before(rows, latest["date"] - timedelta(days=30))
    closes = [row["close"] for row in rows]

    return {
        "as_of": latest["date"].isoformat(),
        "price": latest["close"],
        "previous_close": None if previous is None else previous["close"],
        "change_percent": None if previous is None else _pct_change(latest["close"], previous["close"]),
        "seven_day_percent": _pct_change(latest["close"], close_7d),
        "thirty_day_percent": _pct_change(latest["close"], close_30d),
        "ma100": _mean(closes[-100:]) if len(closes) >= 100 else None,
        "provider": alpha_raw["provider"],
        "source_url": alpha_raw["source_url"],
        "retrieved_at": alpha_raw["retrieved_at"],
    }


def _within_tolerance(primary, secondary, absolute=0.02, relative=0.0025):
    if primary is None or secondary is None:
        return None
    allowed = max(absolute, abs(primary) * relative)
    return abs(primary - secondary) <= allowed


def cross_check_market_snapshot(primary: dict, secondary: dict) -> dict:
    fields = [
        "price",
        "previous_close",
        "change_percent",
        "seven_day_percent",
        "thirty_day_percent",
        "ma100",
    ]

    checks = {}
    verified = []
    discrepancies = []
    unavailable = []

    same_as_of = primary.get("as_of") == secondary.get("as_of")

    for field in fields:
        p = primary.get(field)
        s = secondary.get(field)
        if p is None or s is None:
            status = "unavailable"
            unavailable.append(field)
        elif field.endswith("percent"):
            ok = _within_tolerance(p, s, absolute=0.15, relative=0.02)
            status = "verified" if ok else "discrepancy"
        else:
            ok = _within_tolerance(p, s)
            status = "verified" if ok else "discrepancy"

        if status == "verified":
            verified.append(field)
        elif status == "discrepancy":
            discrepancies.append(field)

        checks[field] = {
            "primary": p,
            "secondary": s,
            "status": status,
        }

    if discrepancies:
        overall = "discrepancy"
    elif verified and same_as_of:
        overall = "partially_verified"
    elif verified:
        overall = "verified_different_as_of"
    else:
        overall = "primary_only"

    return {
        "verification_status": overall,
        "verification": {
            "primary_provider": primary.get("provider"),
            "secondary_provider": secondary.get("provider"),
            "same_as_of": same_as_of,
            "primary_as_of": primary.get("as_of"),
            "secondary_as_of": secondary.get("as_of"),
            "verified_fields": verified,
            "discrepancy_fields": discrepancies,
            "unavailable_fields": unavailable,
            "checks": checks,
            "secondary_source_url": secondary.get("source_url"),
            "secondary_retrieved_at": secondary.get("retrieved_at"),
        },
    }
