from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..normalized_market_models import NormalizedDailyBar
from ..providers.yahoo_ohlcv import YahooOhlcvProvider
from .calculations import build_market_snapshot
from .market_data_pipeline import (
    NORMALIZED_HISTORY_DAYS,
    _snapshot_from_normalized,
    persist_normalized_history,
    refresh_tracked_market_snapshot as _primary_refresh,
    store_market_snapshot,
)


def _partial_snapshot_from_normalized(db: Session, symbol: str) -> dict | None:
    rows = db.query(NormalizedDailyBar).filter(
        NormalizedDailyBar.symbol == symbol.upper(),
        NormalizedDailyBar.high.is_not(None),
        NormalizedDailyBar.low.is_not(None),
    ).order_by(NormalizedDailyBar.bar_date.desc()).limit(NORMALIZED_HISTORY_DAYS).all()
    rows = list(reversed(rows))
    if len(rows) < 14:
        return None
    raw = {
        "history": {
            "values": [{
                "datetime": r.bar_date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            } for r in rows],
            "meta": {"symbol": symbol.upper()},
        },
        "provider": rows[-1].provider,
        "source_url": rows[-1].source_url,
        "retrieved_at": None,
        "normalized": True,
    }
    snapshot = build_market_snapshot(raw)
    snapshot["history_bars_available"] = len(rows)
    snapshot["partial_history"] = len(rows) < 220
    snapshot["technical_availability_note"] = (
        "Long moving averages remain null until enough trading sessions exist."
        if len(rows) < 220 else None
    )
    return snapshot


def refresh_tracked_market_snapshot_with_fallback(db: Session, symbol: str) -> tuple[dict, dict]:
    """Use the normal tracked source first, then repair from Yahoo OHLCV.

    Newly listed tracked symbols are allowed to publish partial technical snapshots:
    Williams %R after 14 sessions, 100MA after 100 sessions, and 200MA after 200.
    """
    s = symbol.strip().upper()
    try:
        return _primary_refresh(db, s)
    except Exception as primary_exc:
        db.rollback()
        data = YahooOhlcvProvider().daily_history(s, period="2y")
        persist_normalized_history(db, data)
        snapshot = _snapshot_from_normalized(db, s) or _partial_snapshot_from_normalized(db, s)
        if snapshot is None:
            count = db.query(func.count(NormalizedDailyBar.id)).filter(
                NormalizedDailyBar.symbol == s
            ).scalar() or 0
            raise RuntimeError(
                f"Insufficient normalized history to build {s} market snapshot after Yahoo fallback "
                f"({count} bars); primary error: {str(primary_exc)[:160]}"
            ) from primary_exc
        store_market_snapshot(db, s, snapshot, data.get("provider") or "Yahoo Finance")
        return snapshot, {
            "mode": "yahoo_history_fallback",
            "bars_received": len(data.get("rows") or []),
            "partial_history": bool(snapshot.get("partial_history")),
            "primary_error": str(primary_exc)[:180],
            "history_days_retained": NORMALIZED_HISTORY_DAYS,
        }
