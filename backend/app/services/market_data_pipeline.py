from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import func, or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import MarketSnapshot, SymbolRegistry
from ..normalized_market_models import MarketPipelineState, NormalizedDailyBar
from ..providers.nasdaq_trader import NasdaqTraderProvider
from ..providers.stooq import StooqError, StooqInsufficientDiskError, StooqProvider, symbol_key
from ..providers.twelve_data import TwelveDataProvider
from ..providers.yahoo_ohlcv import YahooOhlcvProvider
from .calculations import build_market_snapshot


FREE_SOURCE_POLICY = {
    "universe": "Nasdaq Trader",
    "broad_history_primary": "Stooq bulk US daily archive",
    "tracked_refresh": "Twelve Data small daily-bar update",
    "repair_verification": "Stooq per-symbol -> Yahoo Finance; Twelve Data only for tracked symbols",
    "canonical_technicals": "normalized_daily_bars",
}
BULK_LOCK_ID = 88421173
NORMALIZED_HISTORY_DAYS = int(os.getenv("NORMALIZED_HISTORY_DAYS", "260"))
MARKET_SNAPSHOT_KEEP_PER_SYMBOL = int(os.getenv("MARKET_SNAPSHOT_KEEP_PER_SYMBOL", "4"))


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _set_state(db: Session, key: str, payload: dict) -> None:
    row = db.get(MarketPipelineState, key)
    if row:
        row.payload = payload
    else:
        db.add(MarketPipelineState(key=key, payload=payload))
    db.commit()


def _get_state(db: Session, key: str) -> dict:
    row = db.get(MarketPipelineState, key)
    return dict(row.payload or {}) if row else {}


def sync_us_symbol_universe(db: Session) -> dict:
    payload = NasdaqTraderProvider().us_equity_universe()
    created = updated = 0
    for item in payload["symbols"]:
        symbol = item["symbol"].upper()
        row = db.get(SymbolRegistry, symbol)
        if not row:
            row = SymbolRegistry(symbol=symbol, themes={}, provider_ids={})
            db.add(row)
            created += 1
        else:
            updated += 1
        row.name = item.get("name") or row.name
        row.exchange = item.get("exchange") or row.exchange
        row.asset_type = item.get("asset_type") or row.asset_type
        ids = dict(row.provider_ids or {})
        ids["universe_source"] = "Nasdaq Trader"
        row.provider_ids = ids
    db.commit()
    result = {
        "symbols": len(payload["symbols"]),
        "created": created,
        "updated": updated,
        "provider": payload["provider"],
        "retrieved_at": payload["retrieved_at"],
    }
    _set_state(db, "universe", result)
    return result


def _normalize_twelve(symbol: str, raw: dict) -> dict:
    rows = []
    for item in raw.get("values") or raw.get("data") or []:
        dt = str(item.get("datetime") or item.get("date") or "")[:10]
        close = _number(item.get("close"))
        if not dt or close is None:
            continue
        rows.append({
            "date": dt,
            "open": _number(item.get("open")),
            "high": _number(item.get("high")),
            "low": _number(item.get("low")),
            "close": close,
            "volume": _number(item.get("volume")) or 0.0,
        })
    rows.sort(key=lambda x: x["date"])
    return {
        "symbol": symbol.upper(),
        "rows": rows,
        "provider": "Twelve Data",
        "source_url": "https://twelvedata.com/docs",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def _history_from_sources(symbol: str, prefer: str = "stooq") -> tuple[dict, list[str]]:
    s = symbol.strip().upper()
    errors = []
    # Broad repair avoids consuming Twelve Data quota. Tracked refresh may use Twelve first.
    order = ["stooq", "yahoo"] if prefer == "stooq" else ["twelve", "stooq", "yahoo"]
    for source in order:
        try:
            if source == "stooq":
                data = StooqProvider().daily_history(s)
            elif source == "twelve":
                data = _normalize_twelve(s, TwelveDataProvider().daily_history(s, outputsize=NORMALIZED_HISTORY_DAYS))
            else:
                data = YahooOhlcvProvider().daily_history(s, period="2y")
            rows = data.get("rows") or []
            full_bars = sum(1 for r in rows if r.get("high") is not None and r.get("low") is not None)
            if len(rows) >= 220 and full_bars >= 220:
                data["rows"] = rows[-NORMALIZED_HISTORY_DAYS:]
                return data, errors
            errors.append(f"{source}: insufficient full OHLCV history")
        except Exception as exc:
            errors.append(f"{source}: {str(exc)[:180]}")
    raise RuntimeError("; ".join(errors) or f"No free history source available for {s}")


def _upsert_bar_payloads(db: Session, payloads: list[dict]):
    if not payloads:
        return
    stmt = pg_insert(NormalizedDailyBar).values(payloads)
    stmt = stmt.on_conflict_do_update(
        index_elements=[NormalizedDailyBar.symbol, NormalizedDailyBar.bar_date],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
            "provider": stmt.excluded.provider,
            "source_url": stmt.excluded.source_url,
            "retrieved_at": func.now(),
        },
    )
    db.execute(stmt)


def persist_normalized_history(db: Session, data: dict, commit: bool = True) -> int:
    symbol = data["symbol"].upper()
    provider = str(data.get("provider") or "Unknown")
    source_url = str(data.get("source_url") or "")
    payloads = []
    for item in (data.get("rows") or [])[-NORMALIZED_HISTORY_DAYS:]:
        dt = str(item.get("date") or "")[:10]
        close = _number(item.get("close"))
        if not dt or close is None:
            continue
        payloads.append({
            "symbol": symbol,
            "bar_date": dt,
            "open": _number(item.get("open")),
            "high": _number(item.get("high")),
            "low": _number(item.get("low")),
            "close": close,
            "volume": _number(item.get("volume")) or 0.0,
            "provider": provider,
            "source_url": source_url,
        })
    _upsert_bar_payloads(db, payloads)
    if commit:
        db.commit()
    return len(payloads)


def _snapshot_from_rows(data: dict) -> dict | None:
    rows = [r for r in data.get("rows") or [] if r.get("high") is not None and r.get("low") is not None]
    if len(rows) < 220:
        return None
    rows = rows[-NORMALIZED_HISTORY_DAYS:]
    raw = {
        "history": {
            "values": [{
                "datetime": r["date"],
                "open": r.get("open"),
                "high": r.get("high"),
                "low": r.get("low"),
                "close": r.get("close"),
                "volume": r.get("volume"),
            } for r in rows],
            "meta": {"symbol": data["symbol"].upper()},
        },
        "provider": data.get("provider") or "Normalized cache",
        "source_url": data.get("source_url") or "",
        "retrieved_at": data.get("retrieved_at") or datetime.now(timezone.utc).isoformat(),
        "normalized": True,
    }
    return build_market_snapshot(raw)


def _snapshot_from_normalized(db: Session, symbol: str) -> dict | None:
    rows = db.query(NormalizedDailyBar).filter(
        NormalizedDailyBar.symbol == symbol.upper(),
        NormalizedDailyBar.high.is_not(None),
        NormalizedDailyBar.low.is_not(None),
    ).order_by(NormalizedDailyBar.bar_date.desc()).limit(NORMALIZED_HISTORY_DAYS).all()
    rows = list(reversed(rows))
    if len(rows) < 220:
        return None
    return _snapshot_from_rows({
        "symbol": symbol.upper(),
        "rows": [{
            "date": r.bar_date,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
        } for r in rows],
        "provider": rows[-1].provider,
        "source_url": rows[-1].source_url,
    })


def store_market_snapshot(db: Session, symbol: str, snapshot: dict, provider: str | None = None, commit: bool = True):
    payload = dict(snapshot)
    payload["technical_source"] = "normalized_daily_bars"
    payload["is_materialized_cache"] = True
    db.add(MarketSnapshot(
        symbol=symbol.upper(),
        as_of=str(payload.get("as_of") or ""),
        provider=str(provider or payload.get("provider") or "Normalized cache"),
        payload=payload,
    ))
    if commit:
        db.commit()


def prune_market_snapshots(db: Session, keep_per_symbol: int = MARKET_SNAPSHOT_KEEP_PER_SYMBOL) -> int:
    """MarketSnapshot is a materialized read cache; FeatureSnapshot/bars own history."""
    result = db.execute(text("""
        DELETE FROM market_snapshots
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY symbol ORDER BY retrieved_at DESC, id DESC
                ) AS rn
                FROM market_snapshots
            ) ranked
            WHERE rn > :keep
        )
    """), {"keep": max(1, keep_per_symbol)})
    db.commit()
    return int(result.rowcount or 0)


def prune_normalized_bars(db: Session, keep_per_symbol: int = NORMALIZED_HISTORY_DAYS) -> int:
    result = db.execute(text("""
        DELETE FROM normalized_daily_bars
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY symbol ORDER BY bar_date DESC, id DESC
                ) AS rn
                FROM normalized_daily_bars
            ) ranked
            WHERE rn > :keep
        )
    """), {"keep": max(220, keep_per_symbol)})
    db.commit()
    return int(result.rowcount or 0)


def refresh_symbol(db: Session, symbol: str, tracked: bool = False) -> dict:
    data, errors = _history_from_sources(symbol, prefer="twelve" if tracked else "stooq")
    touched = persist_normalized_history(db, data)
    snapshot = _snapshot_from_normalized(db, symbol)
    if snapshot:
        store_market_snapshot(db, symbol, snapshot, data.get("provider"))
    return {
        "symbol": symbol.upper(),
        "provider": data.get("provider"),
        "bars_touched": touched,
        "snapshot_ready": snapshot is not None,
        "fallback_errors": errors,
    }


def refresh_tracked_market_snapshot(db: Session, symbol: str) -> tuple[dict, dict]:
    """Refresh only the newest bars when local history is already sufficient."""
    s = symbol.upper()
    count = db.query(func.count(NormalizedDailyBar.id)).filter(NormalizedDailyBar.symbol == s).scalar() or 0
    provider = TwelveDataProvider()
    if count >= 220:
        raw = provider.latest_daily_bars(s, outputsize=3)
        mode = "latest_3_bars"
    else:
        raw = provider.daily_history(s, outputsize=NORMALIZED_HISTORY_DAYS)
        mode = "history_seed"
    data = _normalize_twelve(s, raw)
    persist_normalized_history(db, data)
    snapshot = _snapshot_from_normalized(db, s)
    if snapshot is None:
        raise RuntimeError(f"Insufficient normalized history to build {s} market snapshot")
    store_market_snapshot(db, s, snapshot, "Twelve Data")
    return snapshot, {"mode": mode, "bars_received": len(data.get("rows") or [])}


def _nasdaq_registry(db: Session) -> list[SymbolRegistry]:
    rows = db.query(SymbolRegistry).filter(
        or_(SymbolRegistry.asset_type.in_(["Stock", "ETF", "Equity"]), SymbolRegistry.asset_type.is_(None))
    ).all()
    return [r for r in rows if (r.provider_ids or {}).get("universe_source") == "Nasdaq Trader"]


def _nasdaq_universe_symbols(db: Session) -> set[str]:
    return {r.symbol.upper() for r in _nasdaq_registry(db)}


def _coverage(db: Session) -> tuple[int, int]:
    universe = len(_nasdaq_universe_symbols(db))
    covered = db.query(NormalizedDailyBar.symbol).group_by(NormalizedDailyBar.symbol).having(
        func.count(NormalizedDailyBar.id) >= 220
    ).count()
    return universe, covered


def _alias_maps(rows: list[SymbolRegistry]) -> tuple[set[str], dict[str, str]]:
    symbols = {r.symbol.upper() for r in rows}
    grouped: dict[str, list[str]] = {}
    for symbol in symbols:
        grouped.setdefault(symbol_key(symbol), []).append(symbol)
    unique_keys = {key: values[0] for key, values in grouped.items() if len(values) == 1}
    return symbols, unique_keys


def _record_alias(db: Session, canonical: str, stooq_symbol: str) -> None:
    if canonical == stooq_symbol:
        return
    row = db.get(SymbolRegistry, canonical)
    if not row:
        return
    ids = dict(row.provider_ids or {})
    if ids.get("stooq_symbol") != stooq_symbol:
        ids["stooq_symbol"] = stooq_symbol
        row.provider_ids = ids


def bulk_refresh_us_market(db: Session, force_full: bool = False) -> dict:
    if not db.execute(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": BULK_LOCK_ID}).scalar():
        return {"status": "skipped", "reason": "bulk refresh already running"}
    archive = None
    provider = StooqProvider()
    started = datetime.now(timezone.utc)
    try:
        universe, covered = _coverage(db)
        if universe == 0:
            sync_us_symbol_universe(db)
            universe, covered = _coverage(db)
        full = force_full or covered < max(100, int(universe * .60))
        persist_tail = NORMALIZED_HISTORY_DAYS if full else 5
        registry_rows = _nasdaq_registry(db)
        symbols, unique_keys = _alias_maps(registry_rows)

        try:
            archive = provider.download_us_bulk_archive()
        except (StooqInsufficientDiskError, StooqError) as exc:
            degraded = bootstrap_market_batch(db, limit=8)
            result = {
                "status": "degraded",
                "reason": str(exc)[:300],
                "fallback": "incremental per-symbol repair",
                "fallback_result": degraded,
                "bulk_metadata": provider.last_bulk_metadata,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            _set_state(db, "bulk_refresh", result)
            return result

        archive_bytes = os.path.getsize(archive)
        bar_buffer: list[dict] = []
        snapshot_buffer: list[MarketSnapshot] = []
        seen = eligible = exact_matches = alias_matches = 0
        matched: set[str] = set()
        unmatched_archive = []
        bar_batch = int(os.getenv("MARKET_BAR_UPSERT_BATCH", "10000"))
        snapshot_batch = int(os.getenv("MARKET_SNAPSHOT_INSERT_BATCH", "500"))

        for data in provider.iter_us_bulk_history(archive, tail=NORMALIZED_HISTORY_DAYS):
            seen += 1
            provider_symbol = data["symbol"].upper()
            canonical = provider_symbol if provider_symbol in symbols else unique_keys.get(symbol_key(provider_symbol))
            if canonical is None:
                if len(unmatched_archive) < 50:
                    unmatched_archive.append(provider_symbol)
                continue
            if canonical == provider_symbol:
                exact_matches += 1
            else:
                alias_matches += 1
                _record_alias(db, canonical, provider_symbol)
            matched.add(canonical)
            data["symbol"] = canonical
            snapshot = _snapshot_from_rows(data)
            if snapshot is None:
                continue
            eligible += 1
            for item in (data.get("rows") or [])[-persist_tail:]:
                close = _number(item.get("close"))
                if close is None:
                    continue
                bar_buffer.append({
                    "symbol": canonical,
                    "bar_date": item["date"],
                    "open": _number(item.get("open")),
                    "high": _number(item.get("high")),
                    "low": _number(item.get("low")),
                    "close": close,
                    "volume": _number(item.get("volume")) or 0.0,
                    "provider": "Stooq",
                    "source_url": data.get("source_url") or "",
                })
            snapshot["technical_source"] = "normalized_daily_bars"
            snapshot["is_materialized_cache"] = True
            snapshot_buffer.append(MarketSnapshot(
                symbol=canonical,
                as_of=str(snapshot.get("as_of") or ""),
                provider="Stooq",
                payload=snapshot,
            ))
            if len(bar_buffer) >= bar_batch:
                _upsert_bar_payloads(db, bar_buffer)
                bar_buffer = []
            if len(snapshot_buffer) >= snapshot_batch:
                db.add_all(snapshot_buffer)
                snapshot_buffer = []
                db.commit()

        _upsert_bar_payloads(db, bar_buffer)
        db.add_all(snapshot_buffer)
        db.commit()
        bars_pruned = prune_normalized_bars(db)
        snapshots_pruned = prune_market_snapshots(db)
        missing = sorted(symbols - matched)
        result = {
            "status": "complete",
            "mode": "full_bootstrap" if full else "daily_incremental",
            "archive_bytes": archive_bytes,
            "archive_symbols_seen": seen,
            "universe_symbols": universe,
            "eligible_symbols": eligible,
            "coverage_this_archive_percent": round(len(matched) / universe * 100, 1) if universe else 0.0,
            "exact_symbol_matches": exact_matches,
            "alias_symbol_matches": alias_matches,
            "universe_missing_from_archive": len(missing),
            "missing_examples": missing[:50],
            "unmatched_archive_examples": unmatched_archive,
            "persisted_days_per_symbol": persist_tail,
            "normalized_rows_pruned": bars_pruned,
            "market_snapshots_pruned": snapshots_pruned,
            "provider": "Stooq bulk US daily archive",
            "bulk_metadata": provider.last_bulk_metadata,
            "started_at": started.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        _set_state(db, "bulk_refresh", result)
        return result
    except Exception as exc:
        db.rollback()
        result = {
            "status": "failed",
            "error": str(exc)[:500],
            "bulk_metadata": provider.last_bulk_metadata,
            "started_at": started.isoformat(),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            _set_state(db, "bulk_refresh", result)
        except Exception:
            db.rollback()
        return result
    finally:
        if archive:
            try:
                os.remove(archive)
            except OSError:
                pass
        try:
            db.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": BULK_LOCK_ID})
            db.commit()
        except Exception:
            db.rollback()


def bootstrap_needed_symbols(db: Session, limit: int = 8) -> list[str]:
    covered = {
        symbol for symbol, count in db.query(NormalizedDailyBar.symbol, func.count(NormalizedDailyBar.id))
        .group_by(NormalizedDailyBar.symbol).all() if count >= 220
    }
    return [r.symbol for r in sorted(_nasdaq_registry(db), key=lambda x: x.symbol) if r.symbol not in covered][:limit]


def bootstrap_market_batch(db: Session, limit: int = 8) -> dict:
    symbols = bootstrap_needed_symbols(db, limit=limit)
    results = []
    for symbol in symbols:
        try:
            results.append(refresh_symbol(db, symbol, tracked=False))
        except Exception as exc:
            db.rollback()
            results.append({"symbol": symbol, "error": str(exc)[:240]})
    return {"requested": len(symbols), "results": results, "policy": FREE_SOURCE_POLICY}


def pipeline_status(db: Session) -> dict:
    universe, covered = _coverage(db)
    bars = db.query(func.count(NormalizedDailyBar.id)).scalar() or 0
    latest = db.query(NormalizedDailyBar).order_by(NormalizedDailyBar.bar_date.desc()).first()
    stocks = db.query(func.count(SymbolRegistry.symbol)).filter(
        SymbolRegistry.asset_type.in_(["Stock", "Equity"])
    ).scalar() or 0
    etfs = db.query(func.count(SymbolRegistry.symbol)).filter(SymbolRegistry.asset_type == "ETF").scalar() or 0
    relation_bytes = None
    try:
        relation_bytes = db.execute(text("SELECT pg_total_relation_size('normalized_daily_bars')")).scalar()
    except Exception:
        db.rollback()
    return {
        "policy": FREE_SOURCE_POLICY,
        "universe_symbols": universe,
        "stock_symbols": stocks,
        "etf_symbols": etfs,
        "symbols_with_220_plus_bars": covered,
        "coverage_percent": round(covered / universe * 100, 1) if universe else 0.0,
        "normalized_bar_count": bars,
        "normalized_table_bytes": relation_bytes,
        "history_days_retained_per_symbol": NORMALIZED_HISTORY_DAYS,
        "market_snapshots_retained_per_symbol": MARKET_SNAPSHOT_KEEP_PER_SYMBOL,
        "latest_bar_date": latest.bar_date if latest else None,
        "broad_scan_ready": covered >= max(100, int(universe * .60)) if universe else False,
        "last_bulk_refresh": _get_state(db, "bulk_refresh"),
        "last_universe_sync": _get_state(db, "universe"),
    }
