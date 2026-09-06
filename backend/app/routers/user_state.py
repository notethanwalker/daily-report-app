from datetime import datetime, timezone
from math import sqrt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FundamentalCache, HistoricalDailyBar, MarketSnapshot, PortfolioHolding, RefreshQueueItem, ReportSnapshot, UserWatchlistItem, WatchlistItem
from ..services.provider_orchestrator import FRESHNESS_POLICIES, is_stale
from .intelligence import _opportunity_components, current_user

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


def _catalyst_score(db,symbol):
    report=db.query(ReportSnapshot).order_by(ReportSnapshot.created_at.desc()).first();hits=[]
    if report:
        payload=report.payload or {};articles=payload.get("top_market_news") or payload.get("market_news") or []
        for a in articles:
            text=f"{a.get('title','')} {a.get('why_it_matters','')}".upper()
            if symbol.upper() in text:hits.append({"title":a.get("title"),"url":a.get("url"),"domain":a.get("domain")})
    score=min(100,50+len(hits)*12)
    return score,hits[:4]

@router.get("/opportunities/enhanced")
def enhanced_opportunities(user:str=Depends(current_user),db:Session=Depends(get_db)):
    rows=[]
    for symbol in _symbols(db,user):
        o=_opportunity_components(db,symbol)
        if not o:continue
        catalyst,hits=_catalyst_score(db,symbol);base=o["components"];components={"technical":base.get("technical",50),"valuation":base.get("valuation",50),"sector":base.get("sector",50),"flow":base.get("flow",50),"relative_strength":base.get("momentum",50),"catalyst":catalyst,"risk":base.get("risk",50)}
        buy=components["technical"]*.22+components["valuation"]*.18+components["sector"]*.14+components["flow"]*.14+components["relative_strength"]*.14+components["catalyst"]*.10+components["risk"]*.08
        rows.append({"symbol":symbol,"buy_score":round(buy,1),"sell_score":round(100-buy,1),"components":components,"flow":o["flow"],"sector_score":o.get("sector_score"),"catalysts":hits})
    rows.sort(key=lambda x:x["buy_score"],reverse=True)
    return {"opportunities":rows,"methodology":"Buy score = technical 22%, valuation 18%, sector 14%, flow 14%, relative strength 14%, catalyst match 10%, risk 8%. Catalyst score uses the latest stored market-news report and therefore adds no provider pull. The score is an auditable screener, not a recommendation."}

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
