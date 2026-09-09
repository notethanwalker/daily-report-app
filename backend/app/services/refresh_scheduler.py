import asyncio
import gc
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func

from ..database import SessionLocal
from ..models import FundamentalCache, HistoricalDailyBar, MarketSnapshot, PortfolioHolding, RefreshQueueItem, SymbolRegistry, UserWatchlistItem, WatchlistItem
from ..multiuser_models import PortfolioPosition
from ..normalized_market_models import MarketPipelineState, NormalizedDailyBar
from ..providers.twelve_data import SOURCE_URL, TwelveDataProvider
from ..providers.yahoo_finance import YahooFinanceProvider
from ..providers.yahoo_ohlcv import YahooOhlcvProvider
from .alert_engine import evaluate_alerts
from .market_data_pipeline import (
    _normalize_twelve,
    _snapshot_from_normalized,
    bulk_refresh_us_market,
    persist_normalized_history,
    prune_market_snapshots,
    prune_normalized_bars,
    refresh_tracked_market_snapshot,
    store_market_snapshot,
    sync_us_symbol_universe,
)
from .provider_orchestrator import FRESHNESS_POLICIES, ProviderOrchestrator, is_stale
from .rotation import SECTORS
from .validation import build_secondary_metrics, cross_check_market_snapshot

_last_universe_sync = None
_last_bulk_attempt = None
_last_cleanup = None
_BROAD_BOOTSTRAP_LOCK = threading.Lock()
QUEUE_RUNNING_TIMEOUT_MINUTES = 30
QUEUE_HISTORY_RETENTION_DAYS = 14
DEPLOYMENT_WARM_SYMBOLS = {x.strip().upper() for x in os.getenv("DEPLOYMENT_WARM_SYMBOLS", "MU,NVDA").split(",") if x.strip()}


def _user_symbols(db):
    out = {r.symbol for r in db.query(WatchlistItem).all()}
    out |= {r.symbol for r in db.query(UserWatchlistItem).all() if r.symbol != "__INITIALIZED__"}
    out |= {r.symbol for r in db.query(PortfolioHolding).all()}
    out |= {r.symbol for r in db.query(PortfolioPosition).all()}
    return sorted(out)


def _enqueue(db, symbol, data_class, priority):
    exists = db.query(RefreshQueueItem).filter(
        RefreshQueueItem.symbol == symbol,
        RefreshQueueItem.data_class == data_class,
        RefreshQueueItem.status.in_(["queued", "running"]),
    ).first()
    if not exists:
        db.add(RefreshQueueItem(symbol=symbol, data_class=data_class, priority=priority, requested_by="scheduler"))


def recover_and_prune_queue(db):
    """Recover jobs orphaned by a worker/process restart and bound queue-history growth.

    A provider job should never legitimately remain in `running` for 30 minutes in the
    current worker. Reclaimed rows retain an explicit diagnostic in `error` and are
    retried through the normal bounded worker rather than executed inline.
    """
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=QUEUE_RUNNING_TIMEOUT_MINUTES)
    old_before = now - timedelta(days=QUEUE_HISTORY_RETENTION_DAYS)
    stale = db.query(RefreshQueueItem).filter(
        RefreshQueueItem.status == "running",
        RefreshQueueItem.updated_at < stale_before,
    ).all()
    for row in stale:
        row.status = "queued"
        row.error = "reclaimed_stale_running_after_worker_timeout"
    deleted = db.query(RefreshQueueItem).filter(
        RefreshQueueItem.status.in_(["complete", "failed"]),
        RefreshQueueItem.updated_at < old_before,
    ).delete(synchronize_session=False)
    if stale or deleted:
        db.commit()
    return {"reclaimed": len(stale), "pruned": int(deleted or 0)}


def seed_historical_from_normalized(db, symbols, keep=260):
    seeded_symbols = inserted = 0
    for symbol in sorted(set(str(x).upper() for x in symbols if x)):
        existing_count = db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol == symbol).count()
        if existing_count >= 120:
            continue
        rows = db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol == symbol).order_by(NormalizedDailyBar.bar_date.desc()).limit(keep).all()
        if len(rows) < 120:
            continue
        existing_dates = {r.bar_date for r in db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol == symbol).all()}
        for row in reversed(rows):
            if row.bar_date in existing_dates or row.close is None:
                continue
            db.add(HistoricalDailyBar(symbol=symbol, bar_date=row.bar_date, close=float(row.close), volume=float(row.volume or 0), provider=str(row.provider or "normalized_daily_bars"), source_url=str(row.source_url or "")))
            inserted += 1
        seeded_symbols += 1
    if inserted:
        db.commit()
    return {"seeded_symbols": seeded_symbols, "inserted_rows": inserted}


def _history_needs_refresh(db, symbol, now):
    count = db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol == symbol).count()
    if count < 120:
        return True
    latest = db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol == symbol).order_by(HistoricalDailyBar.bar_date.desc()).first()
    if not latest:
        return True
    try:
        last = date.fromisoformat(str(latest.bar_date)[:10])
    except ValueError:
        return True
    age = (now.date() - last).days
    return age > 3 if now.weekday() in (0, 1) else age > 2


def _fundamentals_supported(db, symbol):
    row = db.get(SymbolRegistry, str(symbol).upper())
    if not row or not row.asset_type:
        return str(symbol).upper() != "VIX"
    return str(row.asset_type).strip().lower() in {"stock", "equity"}


def enqueue_stale(db):
    now = datetime.now(timezone.utc)
    users = set(_user_symbols(db)) | DEPLOYMENT_WARM_SYMBOLS
    macro = set(SECTORS)
    for symbol in sorted(users):
        market = db.query(MarketSnapshot).filter(MarketSnapshot.symbol == symbol).order_by(MarketSnapshot.retrieved_at.desc()).first()
        fundamental = db.get(FundamentalCache, symbol)
        warm_boost = 50 if symbol in DEPLOYMENT_WARM_SYMBOLS else 0
        if not market or is_stale(market.retrieved_at, "market", now):
            _enqueue(db, symbol, "market", FRESHNESS_POLICIES["market"].priority + warm_boost)
        if _history_needs_refresh(db, symbol, now):
            _enqueue(db, symbol, "history", FRESHNESS_POLICIES["history"].priority + warm_boost)
        if _fundamentals_supported(db, symbol) and (not fundamental or is_stale(fundamental.retrieved_at, "fundamentals", now)):
            _enqueue(db, symbol, "fundamentals", FRESHNESS_POLICIES["fundamentals"].priority + warm_boost)
    macro_boost = 40
    for symbol in sorted(macro - users):
        market = db.query(MarketSnapshot).filter(MarketSnapshot.symbol == symbol).order_by(MarketSnapshot.retrieved_at.desc()).first()
        if not market or is_stale(market.retrieved_at, "market", now):
            _enqueue(db, symbol, "market", FRESHNESS_POLICIES["market"].priority + macro_boost)
        if _history_needs_refresh(db, symbol, now):
            _enqueue(db, symbol, "history", FRESHNESS_POLICIES["history"].priority + macro_boost)
    db.commit()


def _market_refresh_allowed(now):
    return now.weekday() < 5 and 12 <= now.hour <= 22


def _persist_history(db, symbol):
    raw = TwelveDataProvider().daily_history(symbol, outputsize=400)
    values = raw.get("values") or raw.get("data") or []
    existing = {r.bar_date: r for r in db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol == symbol).all()}
    inserted = 0
    for item in values:
        dt = str(item.get("datetime") or item.get("date") or "")[:10]
        try:
            close = float(item.get("close"))
            volume = float(item.get("volume") or 0)
        except (TypeError, ValueError):
            continue
        if not dt:
            continue
        row = existing.get(dt)
        if row:
            row.close = close; row.volume = volume; row.provider = "Twelve Data"; row.source_url = SOURCE_URL
        else:
            db.add(HistoricalDailyBar(symbol=symbol, bar_date=dt, close=close, volume=volume, provider="Twelve Data", source_url=SOURCE_URL))
            inserted += 1
    persist_normalized_history(db, _normalize_twelve(symbol, raw))
    return inserted


def _verified_market_snapshot(db, symbol):
    snap, refresh_meta = refresh_tracked_market_snapshot(db, symbol)
    try:
        secondary = build_secondary_metrics(YahooFinanceProvider().daily_history(symbol))
        snap.update(cross_check_market_snapshot(snap, secondary))
    except Exception as exc:
        snap["verification_status"] = "primary_only"
        snap["verification"] = {"primary_provider": snap.get("provider"), "secondary_provider": "Yahoo Finance", "error": "secondary_provider_unavailable", "detail": str(exc)[:160]}
    snap["tracked_refresh"] = refresh_meta
    latest = db.query(MarketSnapshot).filter(MarketSnapshot.symbol == symbol.upper()).order_by(MarketSnapshot.id.desc()).first()
    if latest:
        latest.payload = snap; latest.provider = str(snap.get("provider") or "Twelve Data"); latest.as_of = str(snap.get("as_of") or latest.as_of); db.commit()
    return snap


def process_queue(db, limit=4):
    recover_and_prune_queue(db)
    now = datetime.now(timezone.utc)
    q = db.query(RefreshQueueItem).filter(RefreshQueueItem.status == "queued")
    if not _market_refresh_allowed(now):
        q = q.filter(RefreshQueueItem.data_class != "market")
    rows = q.order_by(RefreshQueueItem.priority.desc(), RefreshQueueItem.created_at).limit(limit).all()
    done = []
    supported = {"market", "history", "fundamentals"}
    for idx, row in enumerate(rows):
        if row.data_class not in supported:
            row.status = "failed"; row.error = f"unsupported_refresh_data_class:{row.data_class}"; db.commit()
            continue
        row.status = "running"; row.error = None; db.commit()
        try:
            if row.data_class == "fundamentals":
                payload, _ = ProviderOrchestrator().fundamentals(row.symbol, allow_alpha=False)
                cached = db.get(FundamentalCache, row.symbol)
                if cached:
                    cached.provider = str(payload.get("provider") or "Composite fundamentals"); cached.payload = payload; cached.retrieved_at = datetime.now(timezone.utc)
                else:
                    db.add(FundamentalCache(symbol=row.symbol, provider=str(payload.get("provider") or "Composite fundamentals"), payload=payload, retrieved_at=datetime.now(timezone.utc)))
            elif row.data_class == "history":
                _persist_history(db, row.symbol)
            else:
                _verified_market_snapshot(db, row.symbol)
            row.status = "complete"; row.error = None; db.commit(); done.append({"symbol": row.symbol, "data_class": row.data_class})
        except Exception as exc:
            db.rollback(); row = db.get(RefreshQueueItem, row.id); row.status = "failed"; row.error = str(exc)[:500]; db.commit()
        if idx < len(rows) - 1:
            time.sleep(8.2)
    return done


def _sync_universe_if_due(db):
    global _last_universe_sync
    now = datetime.now(timezone.utc)
    if _last_universe_sync is None or (now - _last_universe_sync).total_seconds() >= 12 * 60 * 60:
        sync_us_symbol_universe(db); _last_universe_sync = now


def _pipeline_state(db, key):
    row = db.get(MarketPipelineState, key)
    return dict(row.payload or {}) if row else {}


def _save_pipeline_state(db, key, payload):
    row = db.get(MarketPipelineState, key)
    if row:
        row.payload = payload
    else:
        db.add(MarketPipelineState(key=key, payload=payload))
    db.commit()


def _process_rss_mb():
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        return 0.0
    return 0.0


def _broad_bootstrap_memory_limit_mb():
    return float(os.getenv("YAHOO_BOOTSTRAP_MEMORY_LIMIT_MB", "400"))


def _yahoo_safe_symbol(symbol):
    return bool(re.fullmatch(r"[A-Z][A-Z0-9-]{0,9}", str(symbol or "").upper()))


def _broad_stock_eligible(row):
    if str(row.asset_type or "").lower() not in {"stock", "equity"}:
        return False
    if not _yahoo_safe_symbol(row.symbol):
        return False
    name = str(row.name or "").lower()
    blocked = (" warrant", " warrants", " unit", " units", " right", " rights", " preferred", " preference", " notes due", " bond", " fund")
    return not any(term in name for term in blocked)


def yahoo_broad_bootstrap_batch(db, limit=None, chunk_size=None):
    limit = int(limit or os.getenv("YAHOO_BOOTSTRAP_SYMBOLS_PER_CYCLE", "60"))
    chunk_size = int(chunk_size or os.getenv("YAHOO_BOOTSTRAP_CHUNK_SIZE", "10"))
    min_bars = int(os.getenv("MARKET_MIN_TECHNICAL_BARS", "120"))
    memory_limit_mb = _broad_bootstrap_memory_limit_mb()
    if not _BROAD_BOOTSTRAP_LOCK.acquire(blocking=False):
        return {"status": "skipped", "reason": "broad bootstrap already running"}
    try:
        covered = set(r[0] for r in db.query(NormalizedDailyBar.symbol).group_by(NormalizedDailyBar.symbol).having(func.count(NormalizedDailyBar.id) >= min_bars).all())
        registry_rows = db.query(SymbolRegistry.symbol, SymbolRegistry.name, SymbolRegistry.asset_type, SymbolRegistry.provider_ids).order_by(SymbolRegistry.symbol).all()
        rows = [r for r in registry_rows if (r.provider_ids or {}).get("universe_source") == "Nasdaq Trader" and _broad_stock_eligible(r)]
        del registry_rows
        gc.collect()
        if not rows:
            return {"status": "waiting_for_universe", "requested": 0}

        state = _pipeline_state(db, "yahoo_bootstrap")
        cursor = str(state.get("cursor") or "")
        candidates = [r.symbol.upper() for r in rows if r.symbol.upper() not in covered and r.symbol.upper() > cursor]
        wrapped = False
        if not candidates:
            candidates = [r.symbol.upper() for r in rows if r.symbol.upper() not in covered]
            cursor = ""; wrapped = True
        selected = candidates[:limit]
        if not selected:
            result = {"status": "complete", "eligible_stocks": len(rows), "covered_stocks": len(covered), "requested": 0, "completed_at": datetime.now(timezone.utc).isoformat()}
            _save_pipeline_state(db, "yahoo_bootstrap", result)
            return result

        succeeded = failed = snapshots = bars = 0
        failed_examples = []
        paused_for_memory = False
        processed = 0
        for i in range(0, len(selected), max(1, chunk_size)):
            rss_before = _process_rss_mb()
            if rss_before and rss_before >= memory_limit_mb:
                paused_for_memory = True
                break
            chunk = selected[i:i + max(1, chunk_size)]
            provider = YahooOhlcvProvider()
            batch = {}
            try:
                batch = provider.batch_daily_history(chunk, period="2y")
            except Exception as exc:
                failed += len(chunk)
                processed += len(chunk)
                if len(failed_examples) < 10:
                    failed_examples.append({"symbols": chunk[:5], "error": str(exc)[:180]})
            else:
                for symbol in chunk:
                    data = batch.get(symbol)
                    processed += 1
                    if not data or len(data.get("rows") or []) < min_bars:
                        failed += 1
                        if len(failed_examples) < 10:
                            failed_examples.append({"symbol": symbol, "error": "insufficient Yahoo history"})
                        continue
                    try:
                        bars += persist_normalized_history(db, data)
                        snap = _snapshot_from_normalized(db, symbol)
                        if snap:
                            store_market_snapshot(db, symbol, snap, "Yahoo Finance")
                            snapshots += 1
                        succeeded += 1
                    except Exception as exc:
                        db.rollback(); failed += 1
                        if len(failed_examples) < 10:
                            failed_examples.append({"symbol": symbol, "error": str(exc)[:180]})
            batch.clear()
            del batch, provider
            gc.collect()

        status = "paused_memory_guard" if paused_for_memory else "running"
        result = {
            "status": status,
            "source": "Yahoo Finance batch OHLCV",
            "eligible_stocks": len(rows),
            "covered_before": len(covered),
            "requested": len(selected),
            "processed": processed,
            "succeeded": succeeded,
            "failed": failed,
            "snapshots_written": snapshots,
            "bars_touched": bars,
            "cursor": selected[processed - 1] if processed else cursor,
            "wrapped": wrapped,
            "memory_limit_mb": memory_limit_mb,
            "rss_mb_after": round(_process_rss_mb(), 1),
            "failed_examples": failed_examples,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_pipeline_state(db, "yahoo_bootstrap", result)
        return result
    finally:
        gc.collect()
        _BROAD_BOOTSTRAP_LOCK.release()


def bootstrap_macro_cache(db, limit=80):
    """Batch-warm the macro universe from Yahoo OHLCV instead of serial queue jobs.

    This is cache-first infrastructure: only symbols lacking the minimum technical
    history are requested, and successful results are materialized into the same
    normalized/snapshot/history layers used everywhere else.
    """
    min_bars=int(os.getenv("MARKET_MIN_TECHNICAL_BARS","120"))
    symbols=sorted(set(SECTORS))
    covered={r[0] for r in db.query(NormalizedDailyBar.symbol).filter(NormalizedDailyBar.symbol.in_(symbols)).group_by(NormalizedDailyBar.symbol).having(func.count(NormalizedDailyBar.id)>=min_bars).all()}
    missing=[s for s in symbols if s not in covered][:max(1,int(limit))]
    if not missing:return {"status":"complete","requested":0,"covered":len(covered),"total":len(symbols)}
    provider=YahooOhlcvProvider();succeeded=[];failed=[];snapshots=0
    try:batch=provider.batch_daily_history(missing,period="2y")
    except Exception as exc:return {"status":"failed","requested":len(missing),"error":str(exc)[:180]}
    for symbol in missing:
        data=batch.get(symbol)
        if not data or len(data.get("rows") or [])<min_bars:
            failed.append(symbol);continue
        try:
            persist_normalized_history(db,data)
            snap=_snapshot_from_normalized(db,symbol)
            if snap:store_market_snapshot(db,symbol,snap,"Yahoo Finance");snapshots+=1
            succeeded.append(symbol)
        except Exception:
            db.rollback();failed.append(symbol)
    if succeeded:
        seed_historical_from_normalized(db,succeeded)
        db.query(RefreshQueueItem).filter(RefreshQueueItem.symbol.in_(succeeded),RefreshQueueItem.data_class.in_(["market","history"]),RefreshQueueItem.status=="queued").update({RefreshQueueItem.status:"complete",RefreshQueueItem.error:"satisfied_by_macro_batch_bootstrap",RefreshQueueItem.updated_at:datetime.now(timezone.utc)},synchronize_session=False)
        db.commit()
    return {"status":"running" if failed else "complete","requested":len(missing),"succeeded":len(succeeded),"failed":len(failed),"snapshots":snapshots,"failed_symbols":failed[:20]}


def run_cycle():
    global _last_cleanup
    db = SessionLocal()
    try:
        try:
            bootstrap_macro_cache(db)
        except Exception:
            db.rollback()
        seed_historical_from_normalized(db, set(_user_symbols(db)) | set(SECTORS) | DEPLOYMENT_WARM_SYMBOLS)
        enqueue_stale(db); process_queue(db, 4)
        try:
            _sync_universe_if_due(db)
        except Exception:
            db.rollback()
        now = datetime.now(timezone.utc)
        if _last_cleanup is None or (now - _last_cleanup).total_seconds() >= 6 * 60 * 60:
            try:
                prune_market_snapshots(db); prune_normalized_bars(db); _last_cleanup = now
            except Exception:
                db.rollback()
        from ..routers.intelligence import _refresh_feature
        for symbol in _user_symbols(db):
            try:
                _refresh_feature(db, symbol)
            except Exception:
                db.rollback()
        evaluate_alerts(db)
    except Exception:
        db.rollback()
    finally:
        db.close()


def run_bulk_market_cycle():
    global _last_bulk_attempt
    now = datetime.now(timezone.utc)
    if _last_bulk_attempt is not None and (now - _last_bulk_attempt).total_seconds() < 18 * 60 * 60:
        return {"status": "skipped", "reason": "bulk refresh attempted within 18 hours"}
    _last_bulk_attempt = now
    db = SessionLocal()
    try:
        try:
            _sync_universe_if_due(db)
        except Exception:
            db.rollback()
        result = bulk_refresh_us_market(db)
        if result.get("status") in {"degraded", "failed"}:
            result["yahoo_bootstrap"] = yahoo_broad_bootstrap_batch(db)
        return result
    except Exception as exc:
        db.rollback()
        try:
            return {"status": "degraded", "error": str(exc)[:500], "yahoo_bootstrap": yahoo_broad_bootstrap_batch(db)}
        except Exception as fallback_exc:
            return {"status": "failed", "error": str(exc)[:500], "fallback_error": str(fallback_exc)[:500]}
    finally:
        db.close()


def run_yahoo_bootstrap_cycle():
    db = SessionLocal()
    try:
        try:
            _sync_universe_if_due(db)
        except Exception:
            db.rollback()
        return yahoo_broad_bootstrap_batch(db)
    except Exception as exc:
        db.rollback()
        return {"status": "failed", "error": str(exc)[:500]}
    finally:
        db.close()


async def scheduler_loop():
    while True:
        await asyncio.to_thread(run_cycle)
        await asyncio.sleep(15 * 60)


async def bulk_market_loop():
    await asyncio.sleep(60)
    while True:
        await asyncio.to_thread(run_bulk_market_cycle)
        await asyncio.sleep(6 * 60 * 60)


async def yahoo_bootstrap_loop():
    await asyncio.sleep(90)
    while True:
        await asyncio.to_thread(run_yahoo_bootstrap_cycle)
        await asyncio.sleep(10 * 60)
