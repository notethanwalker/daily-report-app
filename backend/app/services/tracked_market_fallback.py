from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..normalized_market_models import NormalizedDailyBar
from ..providers.yahoo_ohlcv import YahooOhlcvProvider
from .market_data_pipeline import (
    NORMALIZED_HISTORY_DAYS,
    _snapshot_from_normalized,
    persist_normalized_history,
    refresh_tracked_market_snapshot as _primary_refresh,
    store_market_snapshot,
)


def refresh_tracked_market_snapshot_with_fallback(db: Session, symbol: str) -> tuple[dict, dict]:
    """Use the normal tracked source first, then seed/repair from Yahoo OHLCV."""
    s = symbol.strip().upper()
    try:
        return _primary_refresh(db, s)
    except Exception as primary_exc:
        db.rollback()
        data = YahooOhlcvProvider().daily_history(s, period="2y")
        persist_normalized_history(db, data)
        snapshot = _snapshot_from_normalized(db, s)
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
            "primary_error": str(primary_exc)[:180],
            "history_days_retained": NORMALIZED_HISTORY_DAYS,
        }
