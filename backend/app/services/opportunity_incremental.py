from __future__ import annotations

import asyncio
import gc
import os
import re
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import SymbolRegistry
from ..normalized_market_models import MarketPipelineState, NormalizedDailyBar
from ..providers.stooq import StooqProvider
from ..providers.yahoo_ohlcv import YahooOhlcvProvider
from .market_data_pipeline import (
    BROAD_OPPORTUNITY_HISTORY_DAYS,
    BROAD_OPPORTUNITY_MIN_BARS,
    _snapshot_from_normalized,
    persist_normalized_history,
    store_market_snapshot,
)

STATE_KEY = "opportunity_incremental"
COVERAGE_KEY = "opportunity_coverage_bootstrap"
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


def _safe_symbol(symbol: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,11}", str(symbol or "").upper()))


def _eligible_stock(row: SymbolRegistry) -> bool:
    if str(row.asset_type or "").lower() not in {"stock", "equity"}:
        return False
    if (row.provider_ids or {}).get("universe_source") != "Nasdaq Trader":
        return False
    if not _safe_symbol(row.symbol):
        return False
    name = str(row.name or "").lower()
    blocked = (
        " warrant", " warrants", " unit", " units", " right", " rights",
        " preferred", " preference", " notes due", " bond", " fund",
    )
    return not any(term in name for term in blocked)


def _eligible_symbols(db: Session) -> list[str]:
    rows = db.query(SymbolRegistry).order_by(SymbolRegistry.symbol).all()
    return [r.symbol.upper() for r in rows if _eligible_stock(r)]


def _covered_symbols(db: Session) -> set[str]:
    return {
        symbol
        for (symbol,) in db.query(NormalizedDailyBar.symbol)
        .group_by(NormalizedDailyBar.symbol)
        .having(func.count(NormalizedDailyBar.id) >= BROAD_OPPORTUNITY_MIN_BARS)
        .all()
    }


def bootstrap_stooq_coverage_batch(db: Session, limit: int | None = None) -> dict:
    """Fill broad Opportunity history one symbol at a time with bounded memory.

    This is intentionally independent of the old durable archive state. The scanner
    only needs enough normalized OHLCV to calculate Williams %R, 100MA proximity,
    liquidity and confirmation inputs. One Stooq symbol is held in memory at a time,
    then only the technical tail is persisted.
    """
    limit = int(limit or os.getenv("OPPORTUNITY_STOOQ_SYMBOLS_PER_CYCLE", "120"))
    symbols = _eligible_symbols(db)
    if not symbols:
        return {"status": "waiting_for_universe", "requested": 0}

    covered = _covered_symbols(db)
    missing = [s for s in symbols if s not in covered]
    state = _pipeline_state(db, COVERAGE_KEY)
    cursor = str(state.get("cursor") or "")
    candidates = [s for s in missing if s > cursor]
    wrapped = False
    if not candidates and missing:
        candidates = missing
        cursor = ""
        wrapped = True
    selected = candidates[:max(1, limit)]

    if not selected:
        result = {
            "status": "complete",
            "source": "Stooq per-symbol OHLCV",
            "eligible_stocks": len(symbols),
            "covered_stocks": len(covered),
            "coverage_percent": round(len(covered) / len(symbols) * 100.0, 1) if symbols else 0.0,
            "requested": 0,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_state(db, COVERAGE_KEY, result)
        return result

    provider = StooqProvider()
    succeeded = failed = snapshots = bars = processed = 0
    failed_examples: list[dict] = []
    newest_bar = None

    for symbol in selected:
        processed += 1
        try:
            data = provider.daily_history(symbol)
            rows_data = list(data.get("rows") or [])
            full_bars = sum(1 for r in rows_data if r.get("high") is not None and r.get("low") is not None and r.get("close") is not None)
            if full_bars < BROAD_OPPORTUNITY_MIN_BARS:
                raise RuntimeError("insufficient Stooq OHLCV history")
            data["rows"] = rows_data[-BROAD_OPPORTUNITY_HISTORY_DAYS:]
            bars += persist_normalized_history(db, data, keep_days=BROAD_OPPORTUNITY_HISTORY_DAYS)
            snap = _snapshot_from_normalized(
                db,
                symbol,
                min_bars=BROAD_OPPORTUNITY_MIN_BARS,
                tail_days=BROAD_OPPORTUNITY_HISTORY_DAYS,
            )
            if not snap:
                raise RuntimeError("normalized history did not produce Opportunity technicals")
            snap["canonical_history_source"] = "Stooq per-symbol OHLCV"
            snap["latest_bar_source"] = "Stooq"
            snap["coverage_bootstrap"] = True
            store_market_snapshot(db, symbol, snap, "Stooq")
            snapshots += 1
            succeeded += 1
            latest = rows_data[-1].get("date") if rows_data else None
            if latest:
                newest_bar = max(newest_bar or latest, latest)
        except Exception as exc:
            db.rollback()
            failed += 1
            if len(failed_examples) < 12:
                failed_examples.append({"symbol": symbol, "error": str(exc)[:180]})
        finally:
            if processed % 12 == 0:
                gc.collect()

    covered_after = len(covered) + succeeded
    result = {
        "status": "running",
        "role": "low-memory broad Opportunity coverage bootstrap",
        "source": "Stooq per-symbol OHLCV",
        "eligible_stocks": len(symbols),
        "covered_before": len(covered),
        "covered_after_estimate": covered_after,
        "coverage_percent_estimate": round(covered_after / len(symbols) * 100.0, 1) if symbols else 0.0,
        "requested": len(selected),
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed,
        "snapshots_written": snapshots,
        "bars_touched": bars,
        "newest_bar_date": newest_bar,
        "cursor": selected[-1] if selected else cursor,
        "wrapped": wrapped,
        "failed_examples": failed_examples,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_state(db, COVERAGE_KEY, result)
    return result


def refresh_incremental_batch(db: Session, limit: int | None = None, chunk_size: int | None = None) -> dict:
    canonical = _pipeline_state(db, CANONICAL_KEY)
    if canonical.get("status") != "ready" or not canonical.get("canonical"):
        return bootstrap_stooq_coverage_batch(db, limit=limit)

    limit = int(limit or os.getenv("OPPORTUNITY_INCREMENTAL_SYMBOLS_PER_CYCLE", "300"))
    chunk_size = int(chunk_size or os.getenv("OPPORTUNITY_INCREMENTAL_CHUNK_SIZE", "50"))
    symbols = _eligible_symbols(db)
    if not symbols:
        return {"status": "waiting_for_universe", "requested": 0}

    state = _pipeline_state(db, STATE_KEY)
    cursor = str(state.get("cursor") or "")
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
            _save_state(db, COVERAGE_KEY, result)
        except Exception:
            db.rollback()
        return result
    finally:
        db.close()


async def opportunity_incremental_loop():
    await asyncio.sleep(150)
    while True:
        await asyncio.to_thread(run_opportunity_incremental_cycle)
        await asyncio.sleep(10 * 60)
