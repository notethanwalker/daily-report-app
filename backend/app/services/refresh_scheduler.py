import asyncio
import time
from datetime import datetime, timezone

from ..database import SessionLocal
from ..models import FundamentalCache, HistoricalDailyBar, MarketSnapshot, PortfolioHolding, RefreshQueueItem, UserWatchlistItem, WatchlistItem
from ..providers.twelve_data import SOURCE_URL, TwelveDataProvider
from .alert_engine import evaluate_alerts
from .calculations import build_market_snapshot
from .provider_orchestrator import FRESHNESS_POLICIES, ProviderOrchestrator, is_stale


def _symbols(db):
    out={r.symbol for r in db.query(WatchlistItem).all()}
    out|={r.symbol for r in db.query(UserWatchlistItem).all() if r.symbol!="__INITIALIZED__"}
    out|={r.symbol for r in db.query(PortfolioHolding).all()}
    return sorted(out)


def _enqueue(db,symbol,data_class,priority):
    exists=db.query(RefreshQueueItem).filter(RefreshQueueItem.symbol==symbol,RefreshQueueItem.data_class==data_class,RefreshQueueItem.status.in_(["queued","running"])).first()
    if not exists:db.add(RefreshQueueItem(symbol=symbol,data_class=data_class,priority=priority,requested_by="scheduler"))


def enqueue_stale(db):
    now=datetime.now(timezone.utc)
    for symbol in _symbols(db):
        market=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol).order_by(MarketSnapshot.retrieved_at.desc()).first()
        fundamental=db.get(FundamentalCache,symbol)
        history_count=db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol==symbol).count()
        if not market or is_stale(market.retrieved_at,"market",now):
            _enqueue(db,symbol,"market",FRESHNESS_POLICIES["market"].priority)
        if history_count<120:
            _enqueue(db,symbol,"history",FRESHNESS_POLICIES["history"].priority)
        if not fundamental or is_stale(fundamental.retrieved_at,"fundamentals",now):
            _enqueue(db,symbol,"fundamentals",FRESHNESS_POLICIES["fundamentals"].priority)
    db.commit()


def _market_refresh_allowed(now):
    # Avoid wasting price credits overnight/weekends. History/fundamentals can backfill while markets are closed.
    return now.weekday()<5 and 12<=now.hour<=22


def _persist_history(db,symbol):
    raw=TwelveDataProvider().daily_history(symbol,outputsize=750);values=raw.get("values") or raw.get("data") or []
    existing={r.bar_date:r for r in db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol==symbol).all()}
    inserted=0
    for item in values:
        dt=str(item.get("datetime") or item.get("date") or "")[:10]
        try:close=float(item.get("close"));volume=float(item.get("volume") or 0)
        except (TypeError,ValueError):continue
        if not dt:continue
        row=existing.get(dt)
        if row:row.close=close;row.volume=volume;row.provider="Twelve Data";row.source_url=SOURCE_URL
        else:db.add(HistoricalDailyBar(symbol=symbol,bar_date=dt,close=close,volume=volume,provider="Twelve Data",source_url=SOURCE_URL));inserted+=1
    return inserted


def process_queue(db,limit=4):
    now=datetime.now(timezone.utc);rows=db.query(RefreshQueueItem).filter(RefreshQueueItem.status=="queued").order_by(RefreshQueueItem.priority.desc(),RefreshQueueItem.created_at).limit(limit).all();done=[]
    for idx,row in enumerate(rows):
        if row.data_class=="market" and not _market_refresh_allowed(now):
            continue
        row.status="running";db.commit()
        try:
            if row.data_class=="fundamentals":
                payload,_=ProviderOrchestrator().fundamentals(row.symbol,allow_alpha=False);cached=db.get(FundamentalCache,row.symbol)
                if cached:cached.provider=str(payload.get("provider") or "Yahoo Finance");cached.payload=payload;cached.retrieved_at=datetime.now(timezone.utc)
                else:db.add(FundamentalCache(symbol=row.symbol,provider=str(payload.get("provider") or "Yahoo Finance"),payload=payload,retrieved_at=datetime.now(timezone.utc)))
            elif row.data_class=="history":
                _persist_history(db,row.symbol)
            else:
                snap=build_market_snapshot(TwelveDataProvider().market_snapshot_raw(row.symbol));db.add(MarketSnapshot(symbol=row.symbol,as_of=str(snap.get("as_of") or ""),provider=str(snap.get("provider") or "Twelve Data"),payload=snap))
            row.status="complete";row.error=None;db.commit();done.append({"symbol":row.symbol,"data_class":row.data_class})
        except Exception as exc:
            db.rollback();row=db.get(RefreshQueueItem,row.id);row.status="failed";row.error=str(exc)[:500];db.commit()
        if idx<len(rows)-1:time.sleep(8.2)
    return done


def run_cycle():
    db=SessionLocal()
    try:
        enqueue_stale(db)
        process_queue(db,4)
        # Refresh derived features after source data updates. Local import avoids router/service startup coupling.
        from ..routers.intelligence import _refresh_feature
        for symbol in _symbols(db):
            try:_refresh_feature(db,symbol)
            except Exception:db.rollback()
        evaluate_alerts(db)
    except Exception:
        db.rollback()
    finally:
        db.close()


async def scheduler_loop():
    while True:
        await asyncio.to_thread(run_cycle)
        await asyncio.sleep(15*60)
