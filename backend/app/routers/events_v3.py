from __future__ import annotations

import calendar
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FundamentalCache, UserWatchlistItem
from ..multiuser_models import PortfolioPosition, PortfolioDefinition
from ..providers.event_catalog import _TableParser, _event, catalog
from ..v3_models import UserCustomEvent
from .intelligence import current_user

router = APIRouter(prefix="/api/v1", tags=["events-v3"])

BLS_YEAR = "https://www.bls.gov/schedule/{year}/"
TREASURY_XML = "https://www.treasurydirect.gov/xml/PendingAuctions.xml"
TREASURY_SOURCE = "https://www.treasurydirect.gov/auctions/announcements-data-results/announcement-results-press-releases/"
OPTIONS_SOURCE = "https://www.optionseducation.org/referencelibrary/expiration-calendar"
RUSSELL_SOURCE = "https://www.lseg.com/en/ftse-russell/russell-reconstitution"


class CustomEventIn(BaseModel):
    event_date: str
    event_time: str | None = None
    title: str = Field(min_length=1, max_length=256)
    category: str = Field(default="Custom", max_length=80)
    impact: str = Field(default="medium", pattern="^(low|medium|high)$")
    symbol: str | None = Field(default=None, max_length=20)
    description: str | None = None
    source_url: str | None = None


def _date_from_text(text: str, year: int) -> date | None:
    clean = " ".join((text or "").replace("Sept.", "Sep.").split())
    for fmt in ("%A, %B %d, %Y", "%B %d, %Y", "%b. %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            pass
    m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s*(\d{4})?", clean, re.I)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3) or year}", "%B %d %Y").date()
        except ValueError:
            return None
    return None


def bls_html_events(start: date, end: date) -> list[dict]:
    out: list[dict] = []
    headers = {"User-Agent": "DailyReportApp/2.0 contact: market-dashboard"}
    with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
        for year in range(start.year, end.year + 1):
            r = client.get(BLS_YEAR.format(year=year))
            r.raise_for_status()
            p = _TableParser(); p.feed(r.text)
            for row in p.rows:
                if len(row) < 2:
                    continue
                joined = " | ".join(row)
                d = next((_date_from_text(cell, year) for cell in row if _date_from_text(cell, year)), None)
                if not d or not start <= d <= end:
                    continue
                event_time = next((cell for cell in row if re.fullmatch(r"\d{1,2}:\d{2}\s*[AP]M", cell, re.I)), None)
                title_candidates = [cell for cell in row if cell and cell != event_time and _date_from_text(cell, year) is None and not re.search(r"holiday", cell, re.I)]
                title = max(title_candidates, key=len) if title_candidates else "BLS scheduled release"
                if len(title) < 4:
                    continue
                out.append(_event(d.isoformat(), title, "BLS", BLS_YEAR.format(year=year), event_time=event_time, detail="Official Bureau of Labor Statistics release schedule. Parsed from the public yearly schedule because the ICS endpoint may block hosted servers."))
    return out


def _parse_isoish(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            pass
    return None


def treasury_auction_events(start: date, end: date) -> list[dict]:
    with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "DailyReportApp/2.0"}) as client:
        r = client.get(TREASURY_XML); r.raise_for_status()
    root = ET.fromstring(r.text); out=[]
    for node in root.iter():
        children=list(node)
        if not children:
            continue
        fields={c.tag.split("}")[-1].lower(): (c.text or "").strip() for c in children}
        auction_raw=next((v for k,v in fields.items() if "auctiondate" in k or k=="auction_date"),None)
        d=_parse_isoish(auction_raw)
        if not d or not start<=d<=end:
            continue
        term=next((v for k,v in fields.items() if k in {"securityterm","security_term","term"}),"")
        sec_type=next((v for k,v in fields.items() if k in {"securitytype","security_type","type"}),"Treasury")
        offering=next((v for k,v in fields.items() if "offeringamount" in k),None)
        detail=f"U.S. Treasury {term or sec_type} auction."
        if offering: detail += f" Offering amount: {offering}."
        out.append(_event(d.isoformat(), f"Treasury auction · {term or sec_type}", "U.S. Treasury", TREASURY_SOURCE, event_time="13:00", detail=detail))
    return out


def _third_friday(year: int, month: int) -> date:
    d=date(year,month,1)
    offset=(4-d.weekday())%7
    return d+timedelta(days=offset+14)


def systematic_market_events(start: date, end: date) -> list[dict]:
    out=[]; y,m=start.year,start.month
    while (y,m) <= (end.year,end.month):
        expiry=_third_friday(y,m)
        if start<=expiry<=end:
            quarterly=m in {3,6,9,12}
            title="Quarterly derivatives expiration / index rebalance window" if quarterly else "Monthly equity & index options expiration"
            e=_event(expiry.isoformat(),title,"Market calendar",OPTIONS_SOURCE,event_time="16:00",detail="Rule-based market calendar marker. Monthly listed equity/index options generally expire around the third Friday; quarterly months can also concentrate index and derivatives rebalancing activity. Confirm product-specific expirations before trading.")
            if quarterly:e["impact"]="high";e["impact_score"]=3;e["category"]="Market structure"
            else:e["impact"]="medium";e["impact_score"]=2;e["category"]="Market structure"
            out.append(e)
        if m==6:
            last=date(y,6,calendar.monthrange(y,6)[1])
            russell=last-timedelta(days=(last.weekday()-4)%7)
            if start<=russell<=end:
                e=_event(russell.isoformat(),"Russell annual reconstitution effective window","FTSE Russell",RUSSELL_SOURCE,event_time="16:00",detail="Rule-based annual Russell reconstitution window. Final implementation details should be confirmed with FTSE Russell for the current year.")
                e["impact"]="high";e["impact_score"]=3;e["category"]="Index rebalance";out.append(e)
        if m==12:
            third=_third_friday(y,12)
            if start<=third<=end:
                e=_event(third.isoformat(),"Nasdaq-100 annual reconstitution / rebalance window","Market calendar","https://indexes.nasdaqomx.com/Index/Overview/NDX",event_time="16:00",detail="Annual Nasdaq-100 reconstitution is typically implemented in December. This is a planning marker; confirm Nasdaq's published effective date and constituent changes.")
                e["impact"]="medium";e["impact_score"]=2;e["category"]="Index rebalance";out.append(e)
        if m==12:y+=1;m=1
        else:m+=1
    return out


def cached_company_events(db: Session, start: date, end: date) -> list[dict]:
    out=[]
    for row in db.query(FundamentalCache).all():
        payload=row.payload or {}
        specs=[("earnings_date","Earnings","earnings"),("ex_dividend_date","Dividend","ex-dividend"),("dividend_date","Dividend","dividend payment")]
        for field,category,label in specs:
            raw=payload.get(field)
            d=_parse_isoish(str(raw)[:10]) if raw else None
            if not d or not start<=d<=end:continue
            e=_event(d.isoformat(),f"{row.symbol} {label}",row.provider,payload.get("source_url") or f"https://finance.yahoo.com/quote/{row.symbol}",symbol=row.symbol,detail=f"Cached {label} date from {row.provider}. Company dates can change; reconfirm near the event.")
            e["category"]=category;e["impact"]="high" if category=="Earnings" else "medium";e["impact_score"]=3 if category=="Earnings" else 2;out.append(e)
    return out


def custom_events(db: Session, user: str, start: date, end: date) -> list[dict]:
    rows=db.query(UserCustomEvent).filter(UserCustomEvent.user_email==user,UserCustomEvent.event_date>=start.isoformat(),UserCustomEvent.event_date<=end.isoformat()).all();out=[]
    for r in rows:
        out.append({"event_date":r.event_date,"time":r.event_time,"title":r.title,"category":r.category,"impact":r.impact,"impact_score":{"low":1,"medium":2,"high":3}.get(r.impact,2),"source":"User event","source_url":r.source_url,"symbol":r.symbol,"description":r.description,"custom_event_id":r.id})
    return out


def _user_symbols(db: Session, user: str) -> tuple[set[str],set[str]]:
    watch={x.symbol for x in db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email==user).all()}
    pids=[x.id for x in db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email==user).all()]
    portfolio={x.symbol for x in db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id.in_(pids)).all()} if pids else set()
    return watch,portfolio


def build_event_payload(db: Session, user: str, days: int=180, scope: str="all", symbol: str|None=None) -> dict:
    start=date.today();end=start+timedelta(days=days);providers=[];errors=[];rows=[]
    base=catalog(start,end);rows.extend(base.get("events") or []);providers.extend(base.get("providers") or []);errors.extend(base.get("errors") or [])
    # If the ICS BLS feed was blocked, parse the public yearly HTML schedule instead.
    if not any(p.get("provider")=="BLS" and p.get("count",0)>0 for p in providers):
        try:
            b=bls_html_events(start,end);rows.extend(b);providers.append({"provider":"BLS HTML fallback","count":len(b),"status":"ok"})
        except Exception as exc:errors.append(f"BLS HTML fallback: {exc}");providers.append({"provider":"BLS HTML fallback","count":0,"status":"unavailable"})
    for name,loader in [("U.S. Treasury",lambda:treasury_auction_events(start,end)),("Systematic market calendar",lambda:systematic_market_events(start,end))]:
        try:
            x=loader();rows.extend(x);providers.append({"provider":name,"count":len(x),"status":"ok"})
        except Exception as exc:errors.append(f"{name}: {exc}");providers.append({"provider":name,"count":0,"status":"unavailable"})
    company=cached_company_events(db,start,end);rows.extend(company);providers.append({"provider":"Company event cache","count":len(company),"status":"ok"})
    custom=custom_events(db,user,start,end);rows.extend(custom);providers.append({"provider":"User events","count":len(custom),"status":"ok"})
    dedup={}
    for e in rows:
        k=(e.get("event_date"),str(e.get("title") or "").lower(),e.get("symbol"));old=dedup.get(k)
        if old is None or int(e.get("impact_score") or 0)>int(old.get("impact_score") or 0):dedup[k]=e
    rows=list(dedup.values());watch,portfolio=_user_symbols(db,user)
    if scope=="watchlist":rows=[e for e in rows if not e.get("symbol") or e.get("symbol") in watch]
    elif scope=="portfolio":rows=[e for e in rows if not e.get("symbol") or e.get("symbol") in portfolio]
    elif scope=="company":rows=[e for e in rows if e.get("symbol")]
    elif scope=="macro":rows=[e for e in rows if not e.get("symbol")]
    if symbol:rows=[e for e in rows if str(e.get("symbol") or "").upper()==symbol.upper()]
    return {"events":rows,"providers":providers,"errors":errors,"window":{"start":start.isoformat(),"end":end.isoformat()},"retrieved_at":datetime.now(timezone.utc).isoformat(),"scope":scope}


def _sort(rows:list[dict],field:str,order:str):
    rev=order=="desc"
    if field=="impact":key=lambda e:(int(e.get("impact_score") or 0),str(e.get("event_date") or ""))
    elif field=="category":key=lambda e:(str(e.get("category") or ""),str(e.get("event_date") or ""))
    elif field=="source":key=lambda e:(str(e.get("source") or ""),str(e.get("event_date") or ""))
    else:key=lambda e:(str(e.get("event_date") or ""),str(e.get("time") or ""),-int(e.get("impact_score") or 0))
    return sorted(rows,key=key,reverse=rev)


@router.get("/events")
def events(days:int=Query(180,ge=7,le=365),sort:str=Query("date",pattern="^(date|impact|category|source)$"),order:str=Query("asc",pattern="^(asc|desc)$"),impact:str|None=None,category:str|None=None,scope:str=Query("all",pattern="^(all|watchlist|portfolio|company|macro)$"),symbol:str|None=None,limit:int=Query(700,ge=1,le=1200),user:str=Depends(current_user),db:Session=Depends(get_db)):
    d=build_event_payload(db,user,days,scope,symbol);rows=d["events"]
    if impact:rows=[e for e in rows if str(e.get("impact") or "").lower()==impact.lower()]
    if category:rows=[e for e in rows if str(e.get("category") or "").lower()==category.lower()]
    rows=_sort(rows,sort,order)[:limit];categories=sorted({str(e.get("category") or "Other") for e in rows})
    return {**d,"events":rows,"count":len(rows),"categories":categories,"sort":{"field":sort,"order":order},"methodology":"Merged official/public BLS, BEA, Federal Reserve and Treasury schedules with rule-based options/index calendar markers, globally cached company dates and private user events. Provider failures are isolated and shown explicitly; generated schedule conventions are labeled rather than presented as company announcements."}


@router.post("/events/custom")
def add_custom_event(body:CustomEventIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    try:date.fromisoformat(body.event_date[:10])
    except ValueError:raise HTTPException(400,"event_date must be YYYY-MM-DD")
    row=UserCustomEvent(user_email=user,event_date=body.event_date[:10],event_time=body.event_time,title=body.title,category=body.category,impact=body.impact,symbol=body.symbol.strip().upper() if body.symbol else None,description=body.description,source_url=body.source_url);db.add(row);db.commit();db.refresh(row);return {"status":"created","id":row.id}


@router.delete("/events/custom/{event_id}")
def delete_custom_event(event_id:int,user:str=Depends(current_user),db:Session=Depends(get_db)):
    row=db.query(UserCustomEvent).filter(UserCustomEvent.id==event_id,UserCustomEvent.user_email==user).first()
    if not row:raise HTTPException(404,"Event not found")
    db.delete(row);db.commit();return {"status":"deleted"}
