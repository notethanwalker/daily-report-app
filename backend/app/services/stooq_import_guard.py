from __future__ import annotations

from ..normalized_market_models import MarketPipelineState

_INSTALLED = False


def _canonical_import_active(db) -> bool:
    row = db.get(MarketPipelineState, "stooq_manual_archive")
    payload = dict(row.payload or {}) if row else {}
    return payload.get("status") in {"queued", "importing"} and not bool(payload.get("canonical"))


def install_refresh_guard() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from . import refresh_scheduler as scheduler

    original_yahoo = scheduler.yahoo_broad_bootstrap_batch
    original_bulk = scheduler.bulk_refresh_us_market

    def guarded_yahoo(db, limit=None, chunk_size=None):
        if _canonical_import_active(db):
            return {"status": "paused_for_stooq_canonical_import", "requested": 0}
        return original_yahoo(db, limit=limit, chunk_size=chunk_size)

    def guarded_bulk(db, force_full=False):
        if _canonical_import_active(db):
            return {"status": "skipped", "reason": "Stooq canonical import is active"}
        return original_bulk(db, force_full=force_full)

    scheduler.yahoo_broad_bootstrap_batch = guarded_yahoo
    scheduler.bulk_refresh_us_market = guarded_bulk
    _INSTALLED = True
