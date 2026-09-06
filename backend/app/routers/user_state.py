from collections import defaultdict
from datetime import datetime, timezone
from math import sqrt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FundamentalCache, HistoricalDailyBar, MarketSnapshot, PortfolioHolding, RefreshQueueItem, UserWatchlistItem, WatchlistItem
from ..services.provider_orchestrator import FRESHNESS_POLICIES, is_stale
from .intelligence import current_user

router=APIRouter(prefix="/api/v1",tags=["user-state"])
SENTINEL="__INITIALIZED__"

class SymbolIn(BaseModel):symbol:str


def _ensure_user_watchlist(db,user):
    rows=db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email==user).all()
    if rows:return
    db.add(UserWatchlistItem(user_email=user,symbol=SENTINEL))
    for item in db.query(WatchlistItem).order_by(WatchlistItem.created_at).all():
        db.add(UserWatchlistItem(user_email=user,symbol=item.symbol))
    db.commit()


def _symbols(db,user):
    _ensure_user_watchlist(db,user)
    return [r.symbol for r in db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email==user,UserWatchlistItem.symbol!=SENTINEL).order_by(UserWatchlistItem.created_at).all()]


def _latest(db,symbol):
    row=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol).order_by(MarketSnapshot.retrieved_at.desc()).first()
    if not row:return None,row
    p={**(row.payload or {})};p.setdefault("symbol",symbol);p["retrieved_at"]=row.retrieved_at.isoformat();f=db.get(FundamentalCache,symbol)
    if f:p.update(f.payload or {});p["fundamentals_retrieved_at"]=f.retrieved_at.isoformat()
    return p,row


def _enqueue(db,symbol,data_class,priority,user):
    existing=db.query(RefreshQueueItem).filter(RefreshQueueItem.symbol==symbol,RefreshQueueItem.data_class==data_class,RefreshQueueItem.status.in_(["queued","running"])).first()
    if not existing:db.add(RefreshQueueItem(symbol=symbol,data_class=data_class,priority=priority,requested_by=user))


@router.get("/user/watchlist")
def user_watchlist(user:str=Depends(current_user),db:Session=Depends(get_db)):
    return {"tickers":_symbols(db,user),"scope":"per-user","user":user}

@router.post("/user/watchlist")
def add_user_watchlist(body:SymbolIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _ensure_user_watchlist(db,user);s=body.symbol.strip().upper()
    if not s or len(s)>20 or not all(c.isalnum() or c in ".-^" for c in s):raise HTTPException(400,"Invalid ticker symbol format")
    exists=db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email==user,UserWatchlistItem.symbol==s).first()
    if not exists:db.add(UserWatchlistItem(user_email=user,symbol=s))
    _enqueue(db,s,"market",100,user);_enqueue(db,s,"fundamentals",40,user);db.commit();return {"status":"added","symbol":s,"refresh":"queued"}

@router.delete("/user/watchlist/{symbol}")
def remove_user_watchlist(symbol:str,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _ensure_user_watchlist(db,user);row=db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email==user,UserWatchlistItem.symbol==symbol.upper()).first()
    if not row:raise HTTPException(404,"Ticker not found")
    db.delete(row);db.commit();return {"status":"removed","symbol":symbol.upper()}

@router.get("/user/markets/latest")
def user_markets_latest(user:str=Depends(current_user),db:Session=Depends(get_db)):
    out=[];pending=[];now=datetime.now(timezone.utc)
    for symbol in _symbols(db,user):
        p,row=_latest(db,symbol);f=db.get(FundamentalCache,symbol)
        if p:out.append(p)
        if row is None or is_stale(row.retrieved_at,"market",now):_enqueue(db,symbol,"market",FRESHNESS_POLICIES["market"].priority,user);pending.append({"symbol":symbol,"data_class":"market"})
        if f is None or is_stale(f.retrieved_at,"fundamentals",now):_enqueue(db,symbol,"fundamentals",FRESHNESS_POLICIES["fundamentals"].priority,user);pending.append({"symbol":symbol,"data_class":"fundamentals"})
    db.commit();return {"markets":out,"pending_refresh":pending,"note":"User-specific watchlist references shared symbol-level caches; this route does not make provider calls."}


def _returns(db,symbol,limit=70):
    rows=db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol==symbol).order_by(HistoricalDailyBar.bar_date.desc()).limit(limit).all();rows=list(reversed(rows));return {rows[i].bar_date:(rows[i].close/rows[i-1].close-1) for i in range(1,len(rows)) if rows[i-1].close}


def _corr(a,b):
    dates=sorted(set(a)&set(b))
    if len(dates)<20:return None
    x=[a[d] for d in dates];y=[b[d] for d in dates];mx=sum(x)/len(x);my=sum(y)/len(y);dx=[v-mx for v in x];dy=[v-my for v in y];den=sqrt(sum(v*v for v in dx)*sum(v*v for v in dy))
    return sum(i*j for i,j in zip(dx,dy))/den if den else None

@router.get("/portfolio/risk")
def portfolio_risk(user:str=Depends(current_user),db:Session=Depends(get_db)):
    symbols=[r.symbol for r in db.query(PortfolioHolding).filter(PortfolioHolding.user_email==user).all()];series={s:_returns(db,s) for s in symbols};pairs=[]
    for i,a in enumerate(symbols):
        for b in symbols[i+1:]:
            c=_corr(series[a],series[b])
            if c is not None:pairs.append({"a":a,"b":b,"correlation":round(c,2),"cluster_risk":"high" if c>=.8 else "moderate" if c>=.65 else "low"})
    pairs.sort(key=lambda x:x["correlation"],reverse=True)
    return {"pairs":pairs,"high_correlation_pairs":[p for p in pairs if p["correlation"]>=.8],"methodology":"Pearson correlation of overlapping stored daily returns, requiring at least 20 observations. Correlation is historical and can change."}

@router.get("/security/{symbol}/quality")
def security_quality(symbol:str,db:Session=Depends(get_db)):
    s=symbol.upper();p,row=_latest(db,s);f=db.get(FundamentalCache,s)
    if not p:raise HTTPException(404,"No stored data")
    return {"symbol":s,"fields":{
        "price":{"value":p.get("price"),"source":p.get("provider"),"as_of":p.get("as_of"),"retrieved_at":row.retrieved_at.isoformat() if row else None,"state":"stale" if row and is_stale(row.retrieved_at,"market") else "cached"},
        "pe_ratio":{"value":p.get("pe_ratio"),"source":(f.payload or {}).get("provider") if f else None,"as_of":f.retrieved_at.isoformat() if f else None,"method":p.get("pe_ratio_method") or "provider","state":"unavailable" if p.get("pe_ratio") is None else "derived" if p.get("pe_ratio_method") else "cached"},
        "price_to_sales_ratio":{"value":p.get("price_to_sales_ratio"),"source":(f.payload or {}).get("provider") if f else None,"as_of":f.retrieved_at.isoformat() if f else None,"method":p.get("price_to_sales_method") or "provider","state":"unavailable" if p.get("price_to_sales_ratio") is None else "derived" if p.get("price_to_sales_method") else "cached"},
        "peg_ratio":{"value":p.get("peg_ratio"),"source":(f.payload or {}).get("provider") if f else None,"as_of":f.retrieved_at.isoformat() if f else None,"method":p.get("peg_ratio_method") or "provider","state":"unavailable" if p.get("peg_ratio") is None else "derived" if p.get("peg_ratio_method") else "cached"},
    }}
