from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FundamentalCache
from ..providers.event_catalog import _event, catalog

router = APIRouter(prefix="/api/v1", tags=["events-v2"])


def _earnings_events(db: Session, start: date, end: date) -> list[dict]:
    out=[]
    for row in db.query(FundamentalCache).all():
        payload=row.payload or {};raw=payload.get("earnings_date")
        if not raw:continue
        d=str(raw)[:10]
        try:parsed=date.fromisoformat(d)
        except ValueError:continue
        if start<=parsed<=end:
            out.append(_event(d,f"{row.symbol} earnings","Earnings cache",payload.get("source_url") or f"https://finance.yahoo.com/quote/{row.symbol}",symbol=row.symbol,detail=f"Cached earnings date from {row.provider}. Reconfirm near the event because companies can reschedule earnings."))
    return out


def _sort(events:list[dict], sort:str, order:str):
    reverse=order.lower()=="desc"
    if sort=="impact":key=lambda x:(int(x.get("impact_score") or 0),str(x.get("event_date") or ""),str(x.get("time") or ""))
    elif sort=="category":key=lambda x:(str(x.get("category") or ""),str(x.get("event_date") or ""))
    elif sort=="source":key=lambda x:(str(x.get("source") or ""),str(x.get("event_date") or ""))
    else:key=lambda x:(str(x.get("event_date") or ""),str(x.get("time") or ""),-int(x.get("impact_score") or 0))
    return sorted(events,key=key,reverse=reverse)


@router.get("/events")
def events(
    days:int=Query(default=180,ge=7,le=365),
    sort:str=Query(default="date",pattern="^(date|impact|category|source)$"),
    order:str=Query(default="asc",pattern="^(asc|desc)$"),
    impact:str|None=Query(default=None),
    category:str|None=Query(default=None),
    limit:int=Query(default=500,ge=1,le=1000),
    db:Session=Depends(get_db),
):
    start=date.today();end=start+timedelta(days=days);base=catalog(start,end);rows=list(base.get("events") or [])+_earnings_events(db,start,end)
    dedup={}
    for e in rows:
        k=(e.get("event_date"),str(e.get("title") or "").lower(),e.get("symbol"));old=dedup.get(k)
        if old is None or int(e.get("impact_score") or 0)>int(old.get("impact_score") or 0):dedup[k]=e
    rows=list(dedup.values())
    if impact:rows=[e for e in rows if str(e.get("impact") or "").lower()==impact.lower()]
    if category:rows=[e for e in rows if str(e.get("category") or "").lower()==category.lower()]
    rows=_sort(rows,sort,order)[:limit]
    categories=sorted({str(e.get("category") or "Other") for e in rows})
    return {
        "events":rows,
        "count":len(rows),
        "providers":base.get("providers",[])+[{"provider":"Earnings cache","count":sum(1 for e in rows if e.get("source")=="Earnings cache"),"status":"ok"}],
        "errors":base.get("errors",[]),
        "categories":categories,
        "sort":{"field":sort,"order":order},
        "window":{"start":start.isoformat(),"end":end.isoformat()},
        "methodology":"Economic events are merged from official BLS, BEA and Federal Reserve schedules, MacroRadar when available, plus cached company earnings dates. Duplicate events are collapsed by date/title/symbol and tagged with an impact tier for sorting.",
        "retrieved_at":base.get("retrieved_at"),
    }
