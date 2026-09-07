from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import func, or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import MarketSnapshot, SymbolRegistry
from ..normalized_market_models import NormalizedDailyBar
from ..providers.nasdaq_trader import NasdaqTraderProvider
from ..providers.stooq import StooqProvider
from ..providers.twelve_data import TwelveDataProvider
from ..providers.yahoo_ohlcv import YahooOhlcvProvider
from .calculations import build_market_snapshot


FREE_SOURCE_POLICY = {
    "universe": "Nasdaq Trader",
    "broad_history_primary": "Stooq bulk US daily archive",
    "tracked_refresh": "Twelve Data",
    "repair_verification": "Yahoo Finance",
}
BULK_LOCK_ID = 88421173


def _number(value):
    try:return float(value) if value is not None else None
    except (TypeError,ValueError):return None


def sync_us_symbol_universe(db:Session)->dict:
    payload=NasdaqTraderProvider().us_equity_universe();created=updated=0
    for item in payload["symbols"]:
        symbol=item["symbol"];row=db.get(SymbolRegistry,symbol)
        if not row:row=SymbolRegistry(symbol=symbol,themes={},provider_ids={});db.add(row);created+=1
        else:updated+=1
        row.name=item.get("name") or row.name;row.exchange=item.get("exchange") or row.exchange;row.asset_type=item.get("asset_type") or row.asset_type
        ids=dict(row.provider_ids or {});ids["universe_source"]="Nasdaq Trader";row.provider_ids=ids
    db.commit();return {"symbols":len(payload["symbols"]),"created":created,"updated":updated,"provider":payload["provider"],"retrieved_at":payload["retrieved_at"]}


def _normalize_twelve(symbol:str,raw:dict)->dict:
    rows=[]
    for item in raw.get("values") or raw.get("data") or []:
        dt=str(item.get("datetime") or item.get("date") or "")[:10];close=_number(item.get("close"))
        if not dt or close is None:continue
        rows.append({"date":dt,"open":_number(item.get("open")),"high":_number(item.get("high")),"low":_number(item.get("low")),"close":close,"volume":_number(item.get("volume")) or 0.0})
    rows.sort(key=lambda x:x["date"]);return {"symbol":symbol,"rows":rows,"provider":"Twelve Data","source_url":"https://twelvedata.com/docs","retrieved_at":datetime.now(timezone.utc).isoformat()}


def _history_from_sources(symbol:str,prefer:str="stooq")->tuple[dict,list[str]]:
    s=symbol.strip().upper();errors=[];order=["stooq","twelve","yahoo"] if prefer=="stooq" else ["twelve","stooq","yahoo"]
    for source in order:
        try:
            if source=="stooq":data=StooqProvider().daily_history(s)
            elif source=="twelve":data=_normalize_twelve(s,TwelveDataProvider().daily_history(s,outputsize=750))
            else:data=YahooOhlcvProvider().daily_history(s,period="5y")
            rows=data.get("rows") or [];full_bars=sum(1 for r in rows if r.get("high") is not None and r.get("low") is not None)
            if len(rows)>=14 and full_bars>=14:return data,errors
            errors.append(f"{source}: insufficient full OHLCV history")
        except Exception as exc:errors.append(f"{source}: {str(exc)[:180]}")
    raise RuntimeError("; ".join(errors) or f"No free history source available for {s}")


def _upsert_bar_payloads(db:Session,payloads:list[dict]):
    if not payloads:return
    stmt=pg_insert(NormalizedDailyBar).values(payloads)
    stmt=stmt.on_conflict_do_update(index_elements=[NormalizedDailyBar.symbol,NormalizedDailyBar.bar_date],set_={"open":stmt.excluded.open,"high":stmt.excluded.high,"low":stmt.excluded.low,"close":stmt.excluded.close,"volume":stmt.excluded.volume,"provider":stmt.excluded.provider,"source_url":stmt.excluded.source_url,"retrieved_at":func.now()})
    db.execute(stmt)


def persist_normalized_history(db:Session,data:dict)->int:
    symbol=data["symbol"].upper();provider=str(data.get("provider") or "Unknown");source_url=str(data.get("source_url") or "");payloads=[]
    for item in data.get("rows") or []:
        dt=str(item.get("date") or "")[:10];close=_number(item.get("close"))
        if not dt or close is None:continue
        payloads.append({"symbol":symbol,"bar_date":dt,"open":_number(item.get("open")),"high":_number(item.get("high")),"low":_number(item.get("low")),"close":close,"volume":_number(item.get("volume")) or 0.0,"provider":provider,"source_url":source_url})
    _upsert_bar_payloads(db,payloads);db.commit();return len(payloads)


def _snapshot_from_rows(data:dict)->dict|None:
    rows=[r for r in data.get("rows") or [] if r.get("high") is not None and r.get("low") is not None]
    if len(rows)<200:return None
    raw={"history":{"values":[{"datetime":r["date"],"open":r.get("open"),"high":r.get("high"),"low":r.get("low"),"close":r.get("close"),"volume":r.get("volume")} for r in rows],"meta":{"symbol":data["symbol"].upper()}},"provider":data.get("provider") or "Normalized cache","source_url":data.get("source_url") or "","retrieved_at":data.get("retrieved_at") or datetime.now(timezone.utc).isoformat()};return build_market_snapshot(raw)


def _snapshot_from_normalized(db:Session,symbol:str)->dict|None:
    rows=db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol==symbol.upper(),NormalizedDailyBar.high.is_not(None),NormalizedDailyBar.low.is_not(None)).order_by(NormalizedDailyBar.bar_date.desc()).limit(260).all();rows=list(reversed(rows))
    if len(rows)<200:return None
    return _snapshot_from_rows({"symbol":symbol.upper(),"rows":[{"date":r.bar_date,"open":r.open,"high":r.high,"low":r.low,"close":r.close,"volume":r.volume} for r in rows],"provider":rows[-1].provider,"source_url":rows[-1].source_url})


def refresh_symbol(db:Session,symbol:str,tracked:bool=False)->dict:
    data,errors=_history_from_sources(symbol,prefer="twelve" if tracked else "stooq");touched=persist_normalized_history(db,data);snapshot=_snapshot_from_normalized(db,symbol)
    if snapshot:db.add(MarketSnapshot(symbol=symbol.upper(),as_of=str(snapshot.get("as_of") or ""),provider=str(snapshot.get("provider") or data.get("provider") or "Normalized cache"),payload=snapshot));db.commit()
    return {"symbol":symbol.upper(),"provider":data.get("provider"),"bars_touched":touched,"snapshot_ready":snapshot is not None,"fallback_errors":errors}


def _nasdaq_universe_symbols(db:Session)->set[str]:
    rows=db.query(SymbolRegistry).filter(or_(SymbolRegistry.asset_type.in_(["Stock","ETF","Equity"]),SymbolRegistry.asset_type.is_(None))).all();return {r.symbol.upper() for r in rows if (r.provider_ids or {}).get("universe_source")=="Nasdaq Trader"}


def _coverage(db:Session)->tuple[int,int]:
    universe=len(_nasdaq_universe_symbols(db));covered=db.query(NormalizedDailyBar.symbol).group_by(NormalizedDailyBar.symbol).having(func.count(NormalizedDailyBar.id)>=200).count();return universe,covered


def bulk_refresh_us_market(db:Session,force_full:bool=False)->dict:
    if not db.execute(text("SELECT pg_try_advisory_lock(:lock_id)"),{"lock_id":BULK_LOCK_ID}).scalar():return {"status":"skipped","reason":"bulk refresh already running"}
    archive=None
    try:
        universe,covered=_coverage(db)
        if universe==0:sync_us_symbol_universe(db);universe,covered=_coverage(db)
        full=force_full or covered<max(100,int(universe*.60));persist_tail=260 if full else 5;symbols=_nasdaq_universe_symbols(db);provider=StooqProvider();archive=provider.download_us_bulk_archive();archive_bytes=os.path.getsize(archive)
        bar_buffer=[];snapshot_buffer=[];seen=eligible=0
        for data in provider.iter_us_bulk_history(archive,tail=260):
            seen+=1;symbol=data["symbol"].upper()
            if symbol not in symbols:continue
            snapshot=_snapshot_from_rows(data)
            if snapshot is None:continue
            eligible+=1
            for item in (data.get("rows") or [])[-persist_tail:]:bar_buffer.append({"symbol":symbol,"bar_date":item["date"],"open":_number(item.get("open")),"high":_number(item.get("high")),"low":_number(item.get("low")),"close":_number(item.get("close")),"volume":_number(item.get("volume")) or 0.0,"provider":"Stooq","source_url":data.get("source_url") or ""})
            snapshot_buffer.append(MarketSnapshot(symbol=symbol,as_of=str(snapshot.get("as_of") or ""),provider="Stooq",payload=snapshot))
            if len(bar_buffer)>=10000:_upsert_bar_payloads(db,bar_buffer);bar_buffer=[]
            if len(snapshot_buffer)>=500:db.add_all(snapshot_buffer);snapshot_buffer=[];db.commit()
        _upsert_bar_payloads(db,bar_buffer);db.add_all(snapshot_buffer);db.commit()
        return {"status":"complete","mode":"full_bootstrap" if full else "daily_incremental","archive_bytes":archive_bytes,"archive_symbols_seen":seen,"universe_symbols":universe,"eligible_symbols":eligible,"persisted_days_per_symbol":persist_tail,"provider":"Stooq bulk US daily archive","completed_at":datetime.now(timezone.utc).isoformat()}
    finally:
        if archive:
            try:os.remove(archive)
            except OSError:pass
        try:db.execute(text("SELECT pg_advisory_unlock(:lock_id)"),{"lock_id":BULK_LOCK_ID});db.commit()
        except Exception:db.rollback()


def bootstrap_needed_symbols(db:Session,limit:int=8)->list[str]:
    counts=dict(db.query(NormalizedDailyBar.symbol,func.count(NormalizedDailyBar.id)).group_by(NormalizedDailyBar.symbol).all());rows=db.query(SymbolRegistry).filter(or_(SymbolRegistry.asset_type.in_(["Stock","ETF","Equity"]),SymbolRegistry.asset_type.is_(None))).order_by(SymbolRegistry.symbol).all();return [r.symbol for r in rows if counts.get(r.symbol,0)<200][:limit]


def bootstrap_market_batch(db:Session,limit:int=8)->dict:
    symbols=bootstrap_needed_symbols(db,limit=limit);results=[]
    for symbol in symbols:
        try:results.append(refresh_symbol(db,symbol,tracked=False))
        except Exception as exc:db.rollback();results.append({"symbol":symbol,"error":str(exc)[:240]})
    return {"requested":len(symbols),"results":results,"policy":FREE_SOURCE_POLICY}


def pipeline_status(db:Session)->dict:
    universe,covered=_coverage(db);bars=db.query(NormalizedDailyBar).count();latest=db.query(NormalizedDailyBar).order_by(NormalizedDailyBar.bar_date.desc()).first()
    return {"policy":FREE_SOURCE_POLICY,"universe_symbols":universe,"symbols_with_200_plus_bars":covered,"coverage_percent":round(covered/universe*100,1) if universe else 0.0,"normalized_bar_count":bars,"latest_bar_date":latest.bar_date if latest else None,"broad_scan_ready":covered>=max(100,int(universe*.60)) if universe else False}
