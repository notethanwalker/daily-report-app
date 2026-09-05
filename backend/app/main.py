import os
import time
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import FlowEvent, MarketSnapshot, ReportSnapshot, SecondaryVerificationCache, WatchlistItem
from .providers.alpha_vantage import AlphaVantageError, AlphaVantageProvider
from .providers.frankfurter import FrankfurterProvider
from .providers.gdelt import GdeltProvider
from .providers.twelve_data import TwelveDataError, TwelveDataProvider
from .services.calculations import build_market_snapshot
from .services.report import build_daily_report
from .services.rotation import SECTORS, build_rotation_snapshot
from .services.validation import build_secondary_metrics, cross_check_market_snapshot

app = FastAPI(title="Daily Report API", version="1.1")
app.add_middleware(CORSMiddleware, allow_origins=["https://daily-report-app-pearl.vercel.app"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
Base.metadata.create_all(bind=engine)
DEFAULT_WATCHLIST=["SPY","QQQ","AAOI","NBIS","SNDK","AXTI","CRBS","IONQ","OKLO","GLD","SMH","EUV","DRAM","BOTZ","VIX"]
MARKET_CACHE_TTL_SECONDS=900; SECONDARY_CACHE_TTL_SECONDS=86400; ALPHA_VANTAGE_DAILY_BUDGET=20; NEWS_CACHE_TTL_SECONDS=600; CURRENCY_CACHE_TTL_SECONDS=3600; SECURITY_SEARCH_CACHE_TTL_SECONDS=3600
_market_cache={}; _shared_cache={}
class TickerRequest(BaseModel): symbol:str

def _cached_shared(key,ttl,loader):
    cached=_shared_cache.get(key)
    if cached and time.time()-cached[0]<ttl:return {**cached[1],"cache":"hit"}
    data=loader();_shared_cache[key]=(time.time(),data);return {**data,"cache":"miss"}

def _alpha_requests_used_today(db):
    start=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    return db.query(SecondaryVerificationCache).filter(SecondaryVerificationCache.provider=="Alpha Vantage",SecondaryVerificationCache.retrieved_at>=start).count()

def _safe_secondary_error(exc):
    text=str(exc).lower()
    return "secondary_quota_unavailable" if any(x in text for x in ["rate limit","requests per day","premium","budget"]) else "secondary_provider_unavailable"

def get_secondary_metrics(symbol,db):
    symbol=symbol.strip().upper();cached=db.get(SecondaryVerificationCache,symbol)
    if cached:
        at=cached.retrieved_at if cached.retrieved_at.tzinfo else cached.retrieved_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc)-at).total_seconds()<SECONDARY_CACHE_TTL_SECONDS:
            if cached.payload.get("error"):raise AlphaVantageError(cached.payload["error"])
            return cached.payload
    if _alpha_requests_used_today(db)>=ALPHA_VANTAGE_DAILY_BUDGET:raise AlphaVantageError("secondary_daily_budget_reached")
    try:payload=build_secondary_metrics(AlphaVantageProvider().daily_history(symbol))
    except Exception as exc:
        payload={"error":_safe_secondary_error(exc)}
        if cached:cached.provider="Alpha Vantage";cached.payload=payload;cached.retrieved_at=datetime.now(timezone.utc)
        else:db.add(SecondaryVerificationCache(symbol=symbol,provider="Alpha Vantage",payload=payload,retrieved_at=datetime.now(timezone.utc)))
        db.commit();raise AlphaVantageError(payload["error"])
    if cached:cached.provider="Alpha Vantage";cached.payload=payload;cached.retrieved_at=datetime.now(timezone.utc)
    else:db.add(SecondaryVerificationCache(symbol=symbol,provider="Alpha Vantage",payload=payload,retrieved_at=datetime.now(timezone.utc)))
    db.commit();return payload

def get_market_snapshot(symbol,db,verify=True):
    symbol=symbol.strip().upper();key=f"{symbol}:{verify}"
    cached=_market_cache.get(key)
    if cached and time.time()-cached[0]<MARKET_CACHE_TTL_SECONDS:return {**cached[1],"cache":"hit"}
    try:snapshot=build_market_snapshot(TwelveDataProvider().market_snapshot_raw(symbol))
    except Exception as exc:raise HTTPException(502,f"Market data unavailable for {symbol}: {exc}") from exc
    if verify and os.getenv("ALPHA_VANTAGE_API_KEY"):
        try:snapshot.update(cross_check_market_snapshot(snapshot,get_secondary_metrics(symbol,db)))
        except Exception as exc:snapshot["verification_status"]="primary_only";snapshot["verification"]={"primary_provider":snapshot.get("provider"),"secondary_provider":"Alpha Vantage","error":_safe_secondary_error(exc)}
    _market_cache[key]=(time.time(),snapshot);return {**snapshot,"cache":"miss"}

def _load_currencies():return _cached_shared("major_currencies",CURRENCY_CACHE_TTL_SECONDS,lambda:FrankfurterProvider().major_currency_snapshot())
def _load_market_news(limit=15):return _cached_shared(f"market_news:{limit}",NEWS_CACHE_TTL_SECONDS,lambda:GdeltProvider().search('(stocks OR "stock market" OR equities OR Nasdaq OR S&P OR Federal Reserve OR earnings OR inflation)',max_records=limit,timespan="24h"))
def _latest_market_by_symbol(db,symbols=None):
    target=symbols or [r.symbol for r in db.query(WatchlistItem).all()];result={}
    for symbol in target:
        row=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol).order_by(MarketSnapshot.retrieved_at.desc()).first()
        if row:result[symbol]={**row.payload,"retrieved_at":row.retrieved_at.isoformat()}
    return result

@app.get("/")
def root():return {"status":"ok","service":"Daily Report API"}
@app.get("/api/v1/health")
def health(db:Session=Depends(get_db)):
    used=_alpha_requests_used_today(db) if os.getenv("ALPHA_VANTAGE_API_KEY") else 0
    return {"status":"ok","version":"1.1","providers":{"twelve_data":{"configured":bool(os.getenv("TWELVE_DATA_API_KEY"))},"alpha_vantage":{"configured":bool(os.getenv("ALPHA_VANTAGE_API_KEY")),"daily_budget":20,"used_today":used,"remaining_today":max(20-used,0)},"gdelt":{"configured":True},"frankfurter":{"configured":True},"flow":{"configured":False}}}
@app.get("/api/v1/watchlist")
def watchlist(db:Session=Depends(get_db)):
    items=db.query(WatchlistItem).order_by(WatchlistItem.created_at).all()
    if not items:
        for s in DEFAULT_WATCHLIST:db.add(WatchlistItem(symbol=s))
        db.commit();items=db.query(WatchlistItem).order_by(WatchlistItem.created_at).all()
    return {"tickers":[i.symbol for i in items]}
@app.post("/api/v1/watchlist")
def add_ticker(request:TickerRequest,db:Session=Depends(get_db)):
    s=request.symbol.strip().upper()
    if not s or len(s)>20 or not all(c.isalnum() or c in ".-^" for c in s):raise HTTPException(400,"Invalid ticker symbol")
    if db.get(WatchlistItem,s):return {"status":"exists","symbol":s}
    db.add(WatchlistItem(symbol=s));db.commit();return {"status":"added","symbol":s}
@app.delete("/api/v1/watchlist/{symbol}")
def remove_ticker(symbol:str,db:Session=Depends(get_db)):
    s=symbol.strip().upper();item=db.get(WatchlistItem,s)
    if not item:raise HTTPException(404,"Ticker not found")
    db.delete(item);db.commit();return {"status":"removed","symbol":s}
@app.get("/api/v1/securities/search")
def search(q:str=Query(min_length=2,max_length=64)):
    try:return _cached_shared(f"search:{q.lower()}",SECURITY_SEARCH_CACHE_TTL_SECONDS,lambda:TwelveDataProvider().symbol_search(q.strip(),outputsize=8))
    except Exception as exc:raise HTTPException(502,f"Security search unavailable: {exc}") from exc
@app.get("/api/v1/markets/latest")
def latest_markets(db:Session=Depends(get_db)):return {"markets":list(_latest_market_by_symbol(db).values())}
@app.get("/api/v1/markets/{symbol}")
def market(symbol:str,verify:bool=True,db:Session=Depends(get_db)):
    result=get_market_snapshot(symbol,db,verify)
    if result.get("cache")=="miss":db.add(MarketSnapshot(symbol=(result.get("symbol") or symbol).upper(),as_of=str(result.get("as_of") or ""),provider=str(result.get("provider") or "unknown"),payload={k:v for k,v in result.items() if k!="cache"}));db.commit()
    return result
@app.get("/api/v1/markets/{symbol}/history")
def history(symbol:str,limit:int=Query(default=20,ge=1,le=100),db:Session=Depends(get_db)):
    rows=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol.strip().upper()).order_by(MarketSnapshot.retrieved_at.desc()).limit(limit).all();return {"symbol":symbol.upper(),"snapshots":[{"id":r.id,"as_of":r.as_of,"provider":r.provider,"retrieved_at":r.retrieved_at.isoformat(),"data":r.payload} for r in rows]}
@app.get("/api/v1/news/world")
def world_news(limit:int=Query(default=25,ge=1,le=50),topic:str|None=None):
    q='(economy OR markets OR trade OR tariffs OR sanctions OR semiconductor OR "artificial intelligence" OR energy OR oil OR central bank)'
    if topic:q=f'({q}) AND "{topic[:40]}"'
    try:return _cached_shared(f"world:{limit}:{topic}",NEWS_CACHE_TTL_SECONDS,lambda:GdeltProvider().search(q,max_records=limit,timespan="48h"))
    except Exception as exc:raise HTTPException(502,f"World news unavailable: {exc}") from exc
@app.get("/api/v1/news/market")
def market_news(limit:int=Query(default=15,ge=1,le=30)):
    try:return _load_market_news(limit)
    except Exception as exc:raise HTTPException(502,f"Market news unavailable: {exc}") from exc
@app.get("/api/v1/macro/currencies")
def currencies():return _load_currencies()
@app.get("/api/v1/macro/rotation")
def rotation(db:Session=Depends(get_db)):
    market=_latest_market_by_symbol(db,list(SECTORS.keys()))
    try:c=_load_currencies()
    except Exception:c={"rates":[]}
    try:n=_load_market_news(20).get("articles",[])
    except Exception:n=[]
    return build_rotation_snapshot(market,c,n)
@app.get("/api/v1/flow/recent")
def flow(limit:int=Query(default=50,ge=1,le=200),symbol:str|None=None,event_type:str|None=None,db:Session=Depends(get_db)):
    q=db.query(FlowEvent)
    if symbol:q=q.filter(FlowEvent.symbol==symbol.strip().upper())
    if event_type:q=q.filter(FlowEvent.event_type==event_type.strip().lower())
    rows=q.order_by(FlowEvent.occurred_at.desc()).limit(limit).all();return {"provider_configured":False,"events":[{"id":r.id,"event_type":r.event_type,"symbol":r.symbol,"provider":r.provider,"outlier_score":r.outlier_score,"source_url":r.source_url,"occurred_at":r.occurred_at.isoformat(),"data":r.payload} for r in rows],"note":"Storage is ready; real-time flow requires licensed data."}
@app.get("/api/v1/report/current")
def current_report(db:Session=Depends(get_db)):
    try:c=_load_currencies()
    except Exception:c={"rates":[],"provider":"unavailable"}
    try:n=_load_market_news(15)
    except Exception:n={"articles":[],"provider":"unavailable"}
    return build_daily_report(db,currencies=c,market_news=n)
@app.post("/api/v1/report/generate")
def generate_report(db:Session=Depends(get_db)):
    report=current_report(db);row=ReportSnapshot(report_date=report["report_date"],payload=report);db.add(row);db.commit();db.refresh(row);return {"id":row.id,**report}
@app.get("/api/v1/report/history")
def report_history(limit:int=Query(default=20,ge=1,le=100),db:Session=Depends(get_db)):
    rows=db.query(ReportSnapshot).order_by(ReportSnapshot.created_at.desc()).limit(limit).all();return {"reports":[{"id":r.id,"report_date":r.report_date,"created_at":r.created_at.isoformat(),"data":r.payload} for r in rows]}
@app.get("/api/v1/report/config")
def config():return {"sections":["vix","markets","currencies","macro_rotation","market_news","world_news","outliers","flow"],"providers":{"primary_market_data":"Twelve Data","secondary_market_data":"Alpha Vantage","world_news":"GDELT","currencies":"Frankfurter","flow":"not configured"},"flow_research":{"free_public":"FINRA OTC transparency is aggregated/delayed.","licensed_options":"Real-time consolidated options flow requires licensed OPRA/Cboe or vendor data."}}
