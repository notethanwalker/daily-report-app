from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FundamentalCache, UserWatchlistItem, WatchlistItem
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
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
        out.append({"event_date":d.isoformat(),"time":None,"title":f"{symbol} {label.lower()}","category":category,"impact":"high" if impact_score==3 else "medium" if impact_score==2 else "low","impact_score":impact_score,"source":payload.get("provider") or "Yahoo Finance","source_url":payload.get("source_url") or f"https://finance.yahoo.com/quote/{symbol}","symbol":symbol,"description":f"Tracked-company {label.lower()} date. Company dates can change; reconfirm near the event.","tracked_via":sources})
    return out


def _merge_calendar_into_cache(db:Session,symbol:str,calendar_payload:dict):
    row=db.get(FundamentalCache,symbol)
    if row:
        payload={**(row.payload or {})}
        for key in ("earnings_date","ex_dividend_date","dividend_date"):
            if calendar_payload.get(key):payload[key]=calendar_payload[key]
        payload.setdefault("source_url",calendar_payload.get("source_url"))
        row.payload=payload
    else:
        row=FundamentalCache(symbol=symbol,provider="Yahoo Finance",payload=calendar_payload,retrieved_at=datetime.now(timezone.utc));db.add(row)
    db.commit()


@router.get("/events/tracked-companies")
def tracked_company_events(days:int=Query(365,ge=7,le=730),scope:str=Query("all",pattern="^(all|markets|portfolio)$"),refresh_missing:bool=True,user:str=Depends(current_user),db:Session=Depends(get_db)):
    tracked=_tracked_symbols(db,user);markets=tracked["markets"];portfolio=tracked["portfolio"]
    symbols=markets|portfolio if scope=="all" else tracked[scope]
    start=date.today();end=start+timedelta(days=days);events=[];errors=[];refreshed=[];unresolved=[]
    provider=YahooFinanceProvider()
    for symbol in sorted(symbols)[:60]:
        via=[]
        if symbol in markets:via.append("Markets")
        if symbol in portfolio:via.append("Portfolio")
        row=db.get(FundamentalCache,symbol);payload={**(row.payload or {})} if row else {}
        existing=_event_rows(symbol,payload,start,end,via)
        has_future=bool(existing)
        if refresh_missing and not has_future:
            try:
                cal=provider.company_calendar(symbol);_merge_calendar_into_cache(db,symbol,cal);payload={**payload,**{k:v for k,v in cal.items() if v is not None}};refreshed.append(symbol)
            except Exception as exc:
                errors.append(f"{symbol}: {str(exc)[:180]}")
        rows=_event_rows(symbol,payload,start,end,via);events.extend(rows)
        if not rows:unresolved.append(symbol)
    events.sort(key=lambda e:(e["event_date"],-int(e.get("impact_score") or 0),e["symbol"]))
    return {"events":events,"count":len(events),"tracked_symbols":sorted(symbols),"markets_symbols":sorted(markets),"portfolio_symbols":sorted(portfolio),"refreshed_symbols":refreshed,"unresolved_symbols":unresolved,"errors":errors,"window":{"start":start.isoformat(),"end":end.isoformat()},"methodology":"Tracked-company calendar combines symbols visible in Markets with all positions in the user's portfolios. Cached company dates are used first; symbols without a usable upcoming date are queried from Yahoo Finance on demand and merged into the shared fundamentals cache."}
