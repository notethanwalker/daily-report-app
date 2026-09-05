from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import MarketSnapshot, WatchlistItem


def _latest_market_rows(db: Session) -> dict[str, MarketSnapshot]:
    rows = (
        db.query(MarketSnapshot)
        .order_by(MarketSnapshot.symbol.asc(), MarketSnapshot.retrieved_at.desc())
        .all()
    )
    latest: dict[str, MarketSnapshot] = {}
    for row in rows:
        if row.symbol not in latest:
            latest[row.symbol] = row
    return latest


def _market_outlier_score(data: dict[str, Any]) -> float:
    daily = abs(float(data.get("change_percent") or 0.0))
    seven = abs(float(data.get("seven_day_percent") or 0.0))
    rel_vol = float(data.get("relative_volume") or 1.0)
    ma_gap = max(
        abs(float(data.get("price_vs_ma100_percent") or 0.0)),
        abs(float(data.get("price_vs_ma200_percent") or 0.0)),
    )
    return round((daily * 4.0) + (seven * 1.5) + (max(rel_vol - 1.0, 0.0) * 8.0) + (ma_gap * 0.35), 2)


def _outlier_reason(data: dict[str, Any]) -> str:
    reasons: list[str] = []
    daily = data.get("change_percent")
    seven = data.get("seven_day_percent")
    rel_vol = data.get("relative_volume")
    vs_100 = data.get("price_vs_ma100_percent")
    vs_200 = data.get("price_vs_ma200_percent")

    if daily is not None and abs(float(daily)) >= 3:
        reasons.append(f"{float(daily):+.1f}% daily move")
    if seven is not None and abs(float(seven)) >= 6:
        reasons.append(f"{float(seven):+.1f}% over 7 days")
    if rel_vol is not None and float(rel_vol) >= 1.5:
        reasons.append(f"{float(rel_vol):.1f}x relative volume")
    if vs_100 is not None and abs(float(vs_100)) >= 10:
        reasons.append(f"{float(vs_100):+.1f}% vs 100MA")
    if vs_200 is not None and abs(float(vs_200)) >= 15:
        reasons.append(f"{float(vs_200):+.1f}% vs 200MA")

    return "; ".join(reasons) if reasons else "largest combined move/volume trend deviation"


def build_daily_report(
    db: Session,
    currencies: dict[str, Any] | None = None,
    market_news: dict[str, Any] | None = None,
) -> dict[str, Any]:
    watchlist = [row.symbol for row in db.query(WatchlistItem).order_by(WatchlistItem.created_at).all()]
    latest = _latest_market_rows(db)

    markets: list[dict[str, Any]] = []
    missing_symbols: list[str] = []

    for symbol in watchlist:
        row = latest.get(symbol)
        if not row:
            missing_symbols.append(symbol)
            continue
        payload = dict(row.payload or {})
        payload["stored_retrieved_at"] = row.retrieved_at.isoformat()
        markets.append(payload)

    outliers = sorted(
        [
            {
                "symbol": item.get("symbol"),
                "score": _market_outlier_score(item),
                "reason": _outlier_reason(item),
                "change_percent": item.get("change_percent"),
                "seven_day_percent": item.get("seven_day_percent"),
                "relative_volume": item.get("relative_volume"),
            }
            for item in markets
        ],
        key=lambda item: item["score"],
        reverse=True,
    )[:5]

    vix = next((item for item in markets if str(item.get("symbol", "")).upper() in {"VIX", "^VIX"}), None)
    top_news = list((market_news or {}).get("articles") or [])[:3]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_date": datetime.now(timezone.utc).date().isoformat(),
        "watchlist_count": len(watchlist),
        "market_data_count": len(markets),
        "missing_market_symbols": missing_symbols,
        "vix": vix,
        "markets": markets,
        "currencies": currencies or {"rates": []},
        "top_market_news": top_news,
        "outliers": outliers,
        "verification_summary": {
            "verified": sum(1 for item in markets if item.get("verification_status") == "verified"),
            "primary_only": sum(1 for item in markets if item.get("verification_status") != "verified"),
        },
        "notes": [
            "Report uses the latest persisted market snapshot for each watchlist symbol.",
            "Market values are never synthesized by AI; unavailable symbols remain explicitly missing.",
        ],
    }
