from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FundamentalCache, SymbolRegistry, UserWatchlistItem, WatchlistItem
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from ..providers.nasdaq_company_events import NasdaqCompanyEventsProvider
from ..providers.yahoo_finance import YahooFinanceProvider
from .intelligence import current_user

router=APIRouter(prefix="/api/v1",tags=["events-v4"])


def _tracked_symbols(db:Session,user:str):
    market={r.symbol for r in db.query(WatchlistItem).all() if r.symbol and r.symbol!="__INITIALIZED__"}
    market|={r.symbol for r in db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email==user).all() if r.symbol and r.symbol!="__INITIALIZED__"}
    pids=[p.id for p in db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email==user).all()]
    portfolio={r.symbol for r in db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id.in_(pids)).all()} if pids else set()
    return {"markets":{s.upper() for s in market},"portfolio":{s.upper() for s in portfolio}}


def _event_rows(symbol:str,payload:dict,start:date,end:date,sources:list[str]):
    specs=[("earnings_date","Earnings","Earnings",3),("ex_dividend_date","Ex-dividend","Dividend",2),("dividend_date","Dividend payment","Dividend",1)]
    out=[]
    for field,label,category,impact_score in specs:
        raw=payload.get(field)
        if not raw:continue
        try:d=date.fromisoformat(str(raw)[:10])
        except ValueError:continue
        if not start<=d<=end:continue
        out.append({"event_date":d.isoformat(),"time":None,"title":f"{symbol} {label.lower()}","category":category,"impact":"high" if impact_score==3 else "medium" if impact_score==2 else "low","impact_score":impact_score,"source":payload.get("provider") or "Yahoo Finance","source_url":payload.get("source_url") or f"https://finance.yahoo.com/quote/{symbol}","symbol":symbol,"description":f"Tracked-company {label.lower()} date. Company dates can change; reconfirm near the event.","tracked_via":sources,"date_status":"reported"})
    # Free provider fallback when a confirmed forward date is unavailable. This is
    # intentionally labeled an estimate rather than silently presented as fact.
    if not any(x["category"]=="Earnings" for x in out):
        raw=payload.get("earnings_date_estimate")
        try:d=date.fromisoformat(str(raw)[:10]) if raw else None
        except ValueError:d=None
        if d and start<=d<=end:
            lo=payload.get("earnings_date_estimate_start");hi=payload.get("earnings_date_estimate_end")
            cadence=payload.get("earnings_estimate_cadence_days");last=payload.get("earnings_estimate_last_reported")
            out.append({"event_date":d.isoformat(),"time":None,"title":f"{symbol} earnings window (estimated)","category":"Earnings","impact":"high","impact_score":3,"source":"Nasdaq earnings history","source_url":payload.get("nasdaq_source_url") or f"https://www.nasdaq.com/market-activity/stocks/{symbol.lower()}/earnings","symbol":symbol,"description":f"Estimated next earnings date from recent Nasdaq-reported earnings cadence{f' ({cadence} days)' if cadence else ''}. Window {lo or '—'} to {hi or '—'}; last reported date {last or '—'}. This is a planning estimate, not a confirmed company announcement.","tracked_via":sources,"date_status":"estimated","window_start":lo,"window_end":hi,"estimate_method":payload.get("earnings_date_estimate_method")})
    return out


def _merge_calendar_into_cache(db:Session,symbol:str,calendar_payload:dict,check_key:str):
    checked=datetime.now(timezone.utc).isoformat();row=db.get(FundamentalCache,symbol)
    event_keys=("earnings_date","ex_dividend_date","dividend_date","earnings_date_estimate","earnings_date_estimate_start","earnings_date_estimate_end","earnings_estimate_cadence_days","earnings_estimate_last_reported","earnings_estimate_sample_count","earnings_date_estimate_method")
    if row:
        payload={**(row.payload or {})}
        for key in event_keys:
            if calendar_payload.get(key) is not None:payload[key]=calendar_payload[key]
        if calendar_payload.get("source_url"):
            if check_key.startswith("nasdaq"):payload["nasdaq_source_url"]=calendar_payload["source_url"]
            else:payload.setdefault("source_url",calendar_payload["source_url"])
        payload[check_key]=checked;row.payload=payload;row.retrieved_at=datetime.now(timezone.utc)
    else:
        payload={**calendar_payload,check_key:checked}
        if check_key.startswith("nasdaq") and payload.get("source_url"):payload["nasdaq_source_url"]=payload["source_url"]
        row=FundamentalCache(symbol=symbol,provider=str(calendar_payload.get("provider") or "Event enrichment"),payload=payload,retrieved_at=datetime.now(timezone.utc));db.add(row)
    db.commit();return payload


def _recent_check(payload:dict,key:str,hours:int=24)->bool:
    raw=payload.get(key)
    if not raw:return False
    try:
        dt=datetime.fromisoformat(str(raw).replace("Z","+00:00"));dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc)-dt<timedelta(hours=hours)
    except Exception:return False


def _is_company_symbol(db:Session,symbol:str)->bool:
    # Hard skip common fund/index proxies even when registry metadata has not been hydrated yet.
    obvious_funds={"SPY","QQQ","GLD","SMH","SCHD","BOTZ","DRAM","EUV","VIX","IWM","TLT","SHY","HYG","UUP","USO","CPER","IBIT"}
    if symbol in obvious_funds:return False
    reg=db.get(SymbolRegistry,symbol);kind=str(getattr(reg,"asset_type","") or "").lower()
    return not any(x in kind for x in ("etf","fund","index","mutual"))


@router.get("/events/tracked-companies")
def tracked_company_events(days:int=Query(365,ge=7,le=730),scope:str=Query("all",pattern="^(all|markets|portfolio)$"),refresh_missing:bool=True,max_refresh:int=Query(20,ge=0,le=60),user:str=Depends(current_user),db:Session=Depends(get_db)):
    tracked=_tracked_symbols(db,user);markets=tracked["markets"];portfolio=tracked["portfolio"]
    symbols=markets|portfolio if scope=="all" else tracked[scope]
    start=date.today();end=start+timedelta(days=days);events=[];errors=[];refreshed=[];unresolved=[];deferred=[];refresh_count=0
    yahoo=YahooFinanceProvider();nasdaq=NasdaqCompanyEventsProvider()
    # Portfolio names first: these are highest-value company catalysts for the user.
    ordered=sorted(symbols,key=lambda s:(0 if s in portfolio else 1,s))[:80]
    for symbol in ordered:
        via=[]
        if symbol in markets:via.append("Markets")
        if symbol in portfolio:via.append("Portfolio")
        row=db.get(FundamentalCache,symbol);payload={**(row.payload or {})} if row else {};company=_is_company_symbol(db,symbol)
        existing=_event_rows(symbol,payload,start,end,via);has_future=bool(existing)
        needs_any=refresh_missing and not has_future and company and (not _recent_check(payload,"company_calendar_retrieved_at") or not _recent_check(payload,"nasdaq_calendar_retrieved_at"))
        if needs_any and refresh_count>=max_refresh:deferred.append(symbol)
        elif needs_any:
            refresh_count+=1;did=[]
            if not _recent_check(payload,"company_calendar_retrieved_at"):
                try:
                    cal=yahoo.company_calendar(symbol);payload=_merge_calendar_into_cache(db,symbol,cal,"company_calendar_retrieved_at");did.append("Yahoo")
                except Exception as exc:errors.append(f"{symbol} Yahoo: {str(exc)[:160]}")
            if not _event_rows(symbol,payload,start,end,via) and not _recent_check(payload,"nasdaq_calendar_retrieved_at"):
                try:
                    est=nasdaq.earnings_estimate(symbol);payload=_merge_calendar_into_cache(db,symbol,est,"nasdaq_calendar_retrieved_at");did.append("Nasdaq")
                except Exception as exc:errors.append(f"{symbol} Nasdaq: {str(exc)[:160]}")
            if did:refreshed.append({"symbol":symbol,"providers":did})
        rows=_event_rows(symbol,payload,start,end,via);events.extend(rows)
        if not rows:unresolved.append(symbol)
    events.sort(key=lambda e:(e["event_date"],-int(e.get("impact_score") or 0),e["symbol"]))
    return {"events":events,"count":len(events),"tracked_symbols":sorted(symbols),"markets_symbols":sorted(markets),"portfolio_symbols":sorted(portfolio),"refreshed_symbols":refreshed,"deferred_symbols":deferred,"unresolved_symbols":unresolved,"errors":errors,"window":{"start":start.isoformat(),"end":end.isoformat()},"methodology":"Tracked-company calendar combines Markets and all user portfolio positions. Confirmed cached dates are preferred. Missing company calendars use Yahoo first; when no forward earnings date is available, a free Nasdaq history fallback estimates the next earnings window from recent report cadence and labels it explicitly as estimated. Empty source checks are cached for 24 hours and refresh work is bounded per request."}
