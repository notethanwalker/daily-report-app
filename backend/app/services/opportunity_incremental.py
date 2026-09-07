from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import SymbolRegistry
from ..normalized_market_models import MarketPipelineState
from ..providers.yahoo_ohlcv import YahooOhlcvProvider
from .market_data_pipeline import (
    _snapshot_from_normalized,
    persist_normalized_history,
    store_market_snapshot,
)

STATE_KEY = "opportunity_incremental"
CANONICAL_KEY = "stooq_manual_archive"


def _pipeline_state(db: Session, key: str) -> dict:
    row = db.get(MarketPipelineState, key)
    return dict(row.payload or {}) if row else {}


def _save_state(db: Session, key: str, payload: dict) -> None:
    row = db.get(MarketPipelineState, key)
    if row:
        row.payload = payload
    else:
        db.add(MarketPipelineState(key=key, payload=payload))
    db.commit()


def _eligible_stock(row: SymbolRegistry) -> bool:
    if str(row.asset_type or "").lower() not in {"stock", "equity"}:
        return False
    if (row.provider_ids or {}).get("universe_source") != "Nasdaq Trader":
        return False
    name = str(row.name or "").lower()
    blocked = (
        " warrant", " warrants", " unit", " units", " right", " rights",
        " preferred", " preference", " notes due", " bond", " fund",
    )
    return not any(term in name for term in blocked)


def refresh_incremental_batch(db: Session, limit: int | None = None, chunk_size: int | None = None) -> dict:
    canonical = _pipeline_state(db, CANONICAL_KEY)
    if canonical.get("status") != "ready" or not canonical.get("canonical"):
        return {"status": "waiting_for_stooq_archive", "source": "Yahoo Finance incremental OHLCV"}

    limit = int(limit or os.getenv("OPPORTUNITY_INCREMENTAL_SYMBOLS_PER_CYCLE", "300"))
    chunk_size = int(chunk_size or os.getenv("OPPORTUNITY_INCREMENTAL_CHUNK_SIZE", "50"))
    rows = [r for r in db.query(SymbolRegistry).order_by(SymbolRegistry.symbol).all() if _eligible_stock(r)]
    if not rows:
        return {"status": "waiting_for_universe", "requested": 0}

    state = _pipeline_state(db, STATE_KEY)
    cursor = str(state.get("cursor") or "")
    symbols = [r.symbol.upper() for r in rows]
    candidates = [s for s in symbols if s > cursor]
    wrapped = False
    if not candidates:
        candidates = symbols
        wrapped = True
    selected = candidates[:limit]

    provider = YahooOhlcvProvider()
    succeeded = failed = snapshots = bars = 0
    failed_examples = []
    newest_bar = None

    for i in range(0, len(selected), max(1, chunk_size)):
        chunk = selected[i:i + max(1, chunk_size)]
        try:
            batch = provider.batch_daily_history(chunk, period="1mo")
        except Exception as exc:
            failed += len(chunk)
            if len(failed_examples) < 10:
                failed_examples.append({"symbols": chunk[:5], "error": str(exc)[:180]})
            continue
        for symbol in chunk:
            data = batch.get(symbol)
            rows_data = list(data.get("rows") or []) if data else []
            if len(rows_data) < 2:
                failed += 1
                if len(failed_examples) < 10:
                    failed_examples.append({"symbol": symbol, "error": "insufficient incremental Yahoo OHLCV"})
                continue
            try:
                bars += persist_normalized_history(db, data)
                snap = _snapshot_from_normalized(db, symbol)
                if snap:
                    snap["canonical_history_source"] = "Stooq manual archive"
                    snap["latest_bar_source"] = "Yahoo Finance"
                    snap["canonical_archive_latest_bar_date"] = canonical.get("archive_latest_bar_date")
                    snap["canonical_archive_imported_at"] = canonical.get("imported_at")
                    store_market_snapshot(db, symbol, snap, "Yahoo Finance")
                    snapshots += 1
                newest_bar = max(newest_bar or rows_data[-1]["date"], rows_data[-1]["date"])
                succeeded += 1
            except Exception as exc:
                db.rollback()
                failed += 1
                if len(failed_examples) < 10:
                    failed_examples.append({"symbol": symbol, "error": str(exc)[:180]})

    result = {
        "status": "running",
        "role": "freshness layer over canonical Stooq history",
        "source": "Yahoo Finance incremental OHLCV",
        "eligible_stocks": len(symbols),
        "requested": len(selected),
        "succeeded": succeeded,
        "failed": failed,
        "snapshots_written": snapshots,
        "bars_touched": bars,
        "newest_bar_date": newest_bar,
        "cursor": selected[-1] if selected else cursor,
        "wrapped": wrapped,
        "failed_examples": failed_examples,
        "canonical_archive_sha256": canonical.get("archive_sha256"),
        "canonical_archive_latest_bar_date": canonical.get("archive_latest_bar_date"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_state(db, STATE_KEY, result)
    return result


def run_opportunity_incremental_cycle() -> dict:
    db = SessionLocal()
    try:
        return refresh_incremental_batch(db)
    except Exception as exc:
        db.rollback()
        result = {
            "status": "failed",
            "error": str(exc)[:500],
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            _save_state(db, STATE_KEY, result)
        except Exception:
            db.rollback()
        return result
    finally:
        db.close()


async def opportunity_incremental_loop():
    # Stooq remains the historical authority. This loop only extends the normalized
    # series with fresher daily bars between manual Stooq archive replacements.
    await asyncio.sleep(150)
    while True:
        await asyncio.to_thread(run_opportunity_incremental_cycle)
        await asyncio.sleep(10 * 60)
