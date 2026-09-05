import os,time
from datetime import datetime,timezone
from fastapi import BackgroundTasks,Depends,FastAPI,HTTPException,Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .database import Base,SessionLocal,engine,get_db
from .models import FlowEvent,FundamentalCache,HistoricalDailyBar,MarketSnapshot,ReportSnapshot,SecondaryVerificationCache,WatchlistItem
from .providers.alpha_vantage import AlphaVantageError,AlphaVantageProvider
from .providers.frankfurter import FrankfurterProvider
from .providers.gdelt import GdeltProvider
from .providers.squawkflow import SquawkFlowProvider
from .providers.twelve_data import TwelveDataProvider
from .services.calculations import build_market_snapshot,build_williams_r_series
from .services.macro_history import build_macro_history
from .services.report import build_daily_report
from .services.rotation import SECTORS,build_rotation_snapshot
from .services.validation import build_secondary_metrics,cross_check_market_snapshot

app=FastAPI(title="Daily Report API",version="1.7")
app.add_middleware(CORSMiddleware,allow_origins=["https://daily-report-app-pearl.vercel.app"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
Base.metadata.create_all(bind=engine)
DEFAULT_WATCHLIST=["SPY","QQQ","AAOI","NBIS","SNDK","AXTI","CRBS","IONQ","OKLO","GLD","SMH","EUV","DRAM","BOTZ","VIX"]
MACRO_BACKFILL_PRIORITY=["ITA","PAVE","KRE","XBI","IYT","URA","COPX","XME"]
MARKET_CACHE_TTL_SECONDS=900;SECONDARY_CACHE_TTL_SECONDS=86400;FUNDAMENTAL_CACHE_TTL_SECONDS=604800;ALPHA_VANTAGE_DAILY_BUDGET=20;NEWS_CACHE_TTL_SECONDS=600;CURRENCY_CACHE_TTL_SECONDS=3600;SECURITY_SEARCH_CACHE_TTL_SECONDS=3600;SYMBOL_VALIDATION_CACHE_TTL_SECONDS=86400;FLOW_CACHE_TTL_SECONDS=30;WILLIAMS_CACHE_TTL_SECONDS=3600
WORLD_NEWS_TOPIC_QUERIES={"AI & Semiconductors":'("artificial intelligence" OR AI OR semiconductor OR chips OR memory OR "data center" OR Nvidia)',"Rates & Central Banks":'("Federal Reserve" OR Fed OR "central bank" OR "interest rates" OR yields OR ECB OR BOJ)',"Energy & Commodities":'(oil OR crude OR gas OR energy OR gold OR copper OR commodities)',"Trade & Geopolitics":'(tariffs OR trade OR sanctions OR China OR Russia OR exports OR geopolitics)',"Economy & Inflation":'(inflation OR jobs OR employment OR GDP OR economy OR recession OR consumer)'}
WORLD_NEWS_ALL_QUERY='(economy OR markets OR trade OR tariffs OR sanctions OR semiconductor OR "artificial intelligence" OR energy OR oil OR central bank)'
_market_cache={};_shared_cache={};_symbol_validation_cache={};_macro_backfill_running=False
class TickerRequest(BaseModel):symbol:str

def _cached_shared(key,ttl,loader):
 c=_shared_cache.get(key)
 if c and time.time()-c[0]<ttl:return {**c[1],"cache":"hit"}
 d=loader();_shared_cache[key]=(time.time(),d);return {**d,"cache":"miss"}

def _alpha_requests_used_today(db):
 s=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
 secondary=db.query(SecondaryVerificationCache).filter(SecondaryVerificationCache.provider=="Alpha Vantage",SecondaryVerificationCache.retrieved_at>=s).count()
 fundamentals=db.query(FundamentalCache).filter(FundamentalCache.provider=="Alpha Vantage",FundamentalCache.retrieved_at>=s).count()
 return secondary+fundamentals

def _safe_secondary_error(exc):
 t=str(exc).lower();return "secondary_quota_unavailable" if any(x in t for x in ["rate limit","requests per day","premium","budget","quota"]) else "secondary_provider_unavailable"

def _validate_symbol(symbol,db=None,allow_stored=True):
 s=symbol.strip().upper();cached=_symbol_validation_cache.get(s)
 if cached and time.time()-cached[0]<SYMBOL_VALIDATION_CACHE_TTL_SECONDS:return cached[1]
 if allow_stored and db is not None:
  stored=db.query(MarketSnapshot.id).filter(MarketSnapshot.symbol==s).first()
  if stored:
   result={"symbol":s,"valid":True,"method":"stored_market_snapshot"};_symbol_validation_cache[s]=(time.time(),result);return result
 try:data=TwelveDataProvider().symbol_search(s,outputsize=20)
 except Exception:return {"symbol":s,"valid":None,"method":"provider_unavailable","error":"Ticker validation provider unavailable"}
 matches=[r for r in data.get("results",[]) if str(r.get("symbol") or "").upper()==s]
 result={"symbol":s,"valid":bool(matches),"method":"exact_provider_symbol_search","match":matches[0] if matches else None};_symbol_validation_cache[s]=(time.time(),result);return result

def _cleanup_watchlist(db):
 removed=[];unchecked=[];kept=[]
 for item in db.query(WatchlistItem).order_by(WatchlistItem.created_at).all():
  result=_validate_symbol(item.symbol,db,allow_stored=True)
  if result["valid"] is False:removed.append(item.symbol);db.delete(item)
  elif result["valid"] is None:unchecked.append(item.symbol)
  else:kept.append(item.symbol)
 if removed:db.commit()
 return {"removed":removed,"unchecked":unchecked,"kept":kept}

def _latest_market_payload(db,symbol):
 r=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol.strip().upper()).order_by(MarketSnapshot.retrieved_at.desc()).first()
 return {**r.payload,"retrieved_at":r.retrieved_at.isoformat()} if r else None

def _enrich_fundamental_ratios(payload,market_payload=None):
 p={**(payload or {})};market_payload=market_payload or {}
 price=market_payload.get("price");eps=p.get("eps");market_cap=p.get("market_cap");revenue=p.get("revenue_ttm")
 if p.get("pe_ratio") is None and isinstance(price,(int,float)) and isinstance(eps,(int,float)) and eps>0:
  p["pe_ratio"]=round(price/eps,4);p["pe_ratio_method"]="derived from stored price / Alpha Vantage EPS"
 if p.get("price_to_sales_ratio") is None and isinstance(market_cap,(int,float)) and isinstance(revenue,(int,float)) and revenue>0:
  p["price_to_sales_ratio"]=round(market_cap/revenue,4);p["price_to_sales_method"]="derived from Alpha Vantage market cap / revenue TTM"
 growth=p.get("quarterly_earnings_growth_yoy");pe=p.get("pe_ratio")
 if p.get("peg_ratio") is None and isinstance(pe,(int,float)) and pe>0 and isinstance(growth,(int,float)) and growth>0:
  growth_pct=growth*100 if growth<=5 else growth
  if growth_pct>0:
   p["peg_ratio"]=round(pe/growth_pct,4);p["peg_ratio_method"]="derived from P/E / Alpha Vantage quarterly earnings growth; estimate"
 p["valuation_source"]="Alpha Vantage OVERVIEW with stored-price derivation fallback"
 return p

def get_secondary_metrics(symbol,db):
 symbol=symbol.strip().upper();c=db.get(SecondaryVerificationCache,symbol)
 if c:
  at=c.retrieved_at if c.retrieved_at.tzinfo else c.retrieved_at.replace(tzinfo=timezone.utc)
  if (datetime.now(timezone.utc)-at).total_seconds()<SECONDARY_CACHE_TTL_SECONDS:
   if c.payload.get("error"):raise AlphaVantageError(c.payload["error"])
   return c.payload
 if _alpha_requests_used_today(db)>=ALPHA_VANTAGE_DAILY_BUDGET:raise AlphaVantageError("secondary_daily_budget_reached")
 try:p=build_secondary_metrics(AlphaVantageProvider().daily_history(symbol))
 except Exception as exc:
  p={"error":_safe_secondary_error(exc)}
  if c:c.provider="Alpha Vantage";c.payload=p;c.retrieved_at=datetime.now(timezone.utc)
  else:db.add(SecondaryVerificationCache(symbol=symbol,provider="Alpha Vantage",payload=p,retrieved_at=datetime.now(timezone.utc)))
  db.commit();raise AlphaVantageError(p["error"])
 if c:c.provider="Alpha Vantage";c.payload=p;c.retrieved_at=datetime.now(timezone.utc)
 else:db.add(SecondaryVerificationCache(symbol=symbol,provider="Alpha Vantage",payload=p,retrieved_at=datetime.now(timezone.utc)))
 db.commit();return p

def get_fundamentals(symbol,db):
 symbol=symbol.strip().upper();c=db.get(FundamentalCache,symbol);market_payload=_latest_market_payload(db,symbol)
 if c:
  at=c.retrieved_at if c.retrieved_at.tzinfo else c.retrieved_at.replace(tzinfo=timezone.utc);cached=_enrich_fundamental_ratios(c.payload,market_payload)
  if (datetime.now(timezone.utc)-at).total_seconds()<FUNDAMENTAL_CACHE_TTL_SECONDS:return {**cached,"fundamentals_cache":"fresh"}
 if _alpha_requests_used_today(db)>=ALPHA_VANTAGE_DAILY_BUDGET:
  if c:return {**_enrich_fundamental_ratios(c.payload,market_payload),"fundamentals_cache":"stale"}
  raise HTTPException(429,"Fundamentals daily provider budget reached")
 try:p=_enrich_fundamental_ratios(AlphaVantageProvider().overview(symbol),market_payload)
 except Exception as exc:
  if c:return {**_enrich_fundamental_ratios(c.payload,market_payload),"fundamentals_cache":"stale"}
  raise HTTPException(502,"Fundamentals unavailable") from exc
 if c:c.provider="Alpha Vantage";c.payload=p;c.retrieved_at=datetime.now(timezone.utc)
 else:db.add(FundamentalCache(symbol=symbol,provider="Alpha Vantage",payload=p,retrieved_at=datetime.now(timezone.utc)))
 db.commit();return {**p,"fundamentals_cache":"fresh"}

def get_market_snapshot(symbol,db,verify=True):
 symbol=symbol.strip().upper();k=f"{symbol}:{verify}";c=_market_cache.get(k)
 if c and time.time()-c[0]<MARKET_CACHE_TTL_SECONDS:return {**c[1],"cache":"hit"}
 try:s=build_market_snapshot(TwelveDataProvider().market_snapshot_raw(symbol))
 except Exception as exc:raise HTTPException(502,f"Market data unavailable for {symbol}: {exc}") from exc
 if verify and os.getenv("ALPHA_VANTAGE_API_KEY"):
  try:s.update(cross_check_market_snapshot(s,get_secondary_metrics(symbol,db)))
  except Exception as exc:s["verification_status"]="primary_only";s["verification"]={"primary_provider":s.get("provider"),"secondary_provider":"Alpha Vantage","error":_safe_secondary_error(exc)}
 f=db.get(FundamentalCache,symbol)
 if f:s.update(_enrich_fundamental_ratios(f.payload,s))
 _market_cache[k]=(time.time(),s);return {**s,"cache":"miss"}

def _persist_daily_bar(db,symbol,r):
 dt=str(r.get("as_of") or "")[:10];price=r.get("price")
 if not dt or price is None:return
 row=db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol==symbol,HistoricalDailyBar.bar_date==dt).first()
 if row:row.close=float(price);row.volume=float(r.get("volume") or 0);row.provider=str(r.get("provider") or "Twelve Data");row.source_url=str(r.get("source_url") or "")
 else:db.add(HistoricalDailyBar(symbol=symbol,bar_date=dt,close=float(price),volume=float(r.get("volume") or 0),provider=str(r.get("provider") or "Twelve Data"),source_url=str(r.get("source_url") or "")))

def _persist_market_result(db,sym,r):
 latest=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==sym).order_by(MarketSnapshot.retrieved_at.desc()).first()
 if not latest or latest.as_of!=str(r.get("as_of") or "") or latest.payload.get("williams_r_14") is None:
  db.add(MarketSnapshot(symbol=sym,as_of=str(r.get("as_of") or ""),provider=str(r.get("provider") or "unknown"),payload={k:v for k,v in r.items() if k!="cache"}))
 _persist_daily_bar(db,sym,r)

def _load_currencies():return _cached_shared("major_currencies",CURRENCY_CACHE_TTL_SECONDS,lambda:FrankfurterProvider().major_currency_snapshot())
def _load_market_news(limit=15):return _cached_shared(f"market_news:{limit}",NEWS_CACHE_TTL_SECONDS,lambda:GdeltProvider().search('(stocks OR "stock market" OR equities OR Nasdaq OR S&P OR Federal Reserve OR earnings OR inflation)',max_records=limit,timespan="24h"))

def _latest_market_by_symbol(db,symbols=None):
 target=symbols or [r.symbol for r in db.query(WatchlistItem).all()];out={}
 for symbol in target:
  r=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol).order_by(MarketSnapshot.retrieved_at.desc()).first()
  if r:
   p={**r.payload,"retrieved_at":r.retrieved_at.isoformat()};f=db.get(FundamentalCache,symbol)
   if f:p.update(_enrich_fundamental_ratios(f.payload,p))
   out[symbol]=p
 return out

def _load_world_news(topic,limit):
 q=WORLD_NEWS_TOPIC_QUERIES.get(topic,WORLD_NEWS_ALL_QUERY);d=GdeltProvider().search(q,max_records=limit,timespan="48h")
 if topic in WORLD_NEWS_TOPIC_QUERIES:d["articles"]=[a for a in d.get("articles",[]) if topic in (a.get("topics") or [])]
 d["selected_topic"]=topic or "All";return d

def _stored_flow(db,limit,symbol=None,event_type=None):
 q=db.query(FlowEvent)
 if symbol:q=q.filter(FlowEvent.symbol==symbol.strip().upper())
 if event_type:q=q.filter(FlowEvent.event_type==event_type.strip().lower())
 rs=q.order_by(FlowEvent.occurred_at.desc()).limit(limit).all()
 return [{"id":r.id,"event_type":r.event_type,"symbol":r.symbol,"provider":r.provider,"outlier_score":r.outlier_score,"source_url":r.source_url,"occurred_at":r.occurred_at.isoformat(),"data":r.payload} for r in rs]

def _dedupe_flow_events(events):
 out={};order=[]
 for e in events or []:
  d=e.get("data") or {};side=d.get("side");strike=d.get("strike");expiry=d.get("expiration")
  key=(e.get("symbol"),side,strike,expiry) if strike is not None and expiry else (e.get("event_id") or e.get("id"),e.get("symbol"),side,d.get("premium"))
  if key not in out:order.append(key)
  old=out.get(key);old_p=(old or {}).get("data",{}).get("premium") or 0;new_p=d.get("premium") or 0
  if old is None or new_p>=old_p:out[key]=e
 return [out[k] for k in order]

def _enrich_flow_events(db,events):
 events=_dedupe_flow_events(events);symbols=sorted({str(e.get("symbol") or "").upper() for e in events if e.get("symbol")});markets=_latest_market_by_symbol(db,symbols)
 enriched=[]
 for e in events:
  row={**e};d={**(e.get("data") or {})};m=markets.get(str(e.get("symbol") or "").upper(),{})
  if d.get("market_cap") in (None,0) and m.get("market_cap") not in (None,0):d["market_cap"]=m.get("market_cap");d["market_cap_source"]="cached market fundamentals"
  d["underlying_price"]=m.get("price");d["sector"]=m.get("sector");row["data"]=d;enriched.append(row)
 return enriched

def _macro_backfill_worker(symbols):
 global _macro_backfill_running
 if _macro_backfill_running:return
 _macro_backfill_running=True;db=SessionLocal()
 try:
  for i,symbol in enumerate(symbols):
   try:
    if _latest_market_payload(db,symbol):continue
    r=get_market_snapshot(symbol,db,verify=False);_persist_market_result(db,symbol,r);db.commit()
   except Exception:
    db.rollback()
   if i<len(symbols)-1:time.sleep(8.2)
 finally:
  db.close();_macro_backfill_running=False

@app.get("/")
def root():return {"status":"ok","service":"Daily Report API"}
@app.get("/api/v1/health")
def health(db:Session=Depends(get_db)):
 u=_alpha_requests_used_today(db) if os.getenv("ALPHA_VANTAGE_API_KEY") else 0;return {"status":"ok","version":"1.7","providers":{"twelve_data":{"configured":bool(os.getenv("TWELVE_DATA_API_KEY"))},"alpha_vantage":{"configured":bool(os.getenv("ALPHA_VANTAGE_API_KEY")),"daily_budget":20,"used_today":u,"remaining_today":max(20-u,0)},"gdelt":{"configured":True},"frankfurter":{"configured":True},"macroradar":{"configured":True},"ticker_validation":{"configured":bool(os.getenv("TWELVE_DATA_API_KEY"))},"flow":{"configured":True,"provider":"SquawkFlow public unusual-options API","anonymous_limit":"60 requests/hour/IP"}}}
@app.get("/api/v1/watchlist")
def watchlist(db:Session=Depends(get_db)):
 items=db.query(WatchlistItem).order_by(WatchlistItem.created_at).all()
 if not items:[db.add(WatchlistItem(symbol=s)) for s in DEFAULT_WATCHLIST];db.commit()
 validation=_cleanup_watchlist(db);items=db.query(WatchlistItem).order_by(WatchlistItem.created_at).all();return {"tickers":[i.symbol for i in items],"validation":validation}
@app.post("/api/v1/watchlist")
def add_ticker(request:TickerRequest,db:Session=Depends(get_db)):
 s=request.symbol.strip().upper()
 if not s or len(s)>20 or not all(c.isalnum() or c in ".-^" for c in s):raise HTTPException(400,"Invalid ticker symbol format")
 if db.get(WatchlistItem,s):return {"status":"exists","symbol":s}
 result=_validate_symbol(s,db,allow_stored=False)
 if result["valid"] is None:raise HTTPException(503,"Ticker validation is temporarily unavailable. The ticker was not added; retry when the provider is reachable.")
 if result["valid"] is False:raise HTTPException(400,f"Ticker {s} was not found in the market-data provider and was not added.")
 db.add(WatchlistItem(symbol=s));db.commit();return {"status":"added","symbol":s,"validation":result}
@app.delete("/api/v1/watchlist/{symbol}")
def remove_ticker(symbol:str,db:Session=Depends(get_db)):
 s=symbol.strip().upper();i=db.get(WatchlistItem,s)
 if not i:raise HTTPException(404,"Ticker not found")
 db.delete(i);db.commit();return {"status":"removed","symbol":s}
@app.get("/api/v1/securities/search")
def search(q:str=Query(min_length=2,max_length=64)):
 try:return _cached_shared(f"search:{q.lower()}",SECURITY_SEARCH_CACHE_TTL_SECONDS,lambda:TwelveDataProvider().symbol_search(q.strip(),outputsize=8))
 except Exception as exc:raise HTTPException(502,f"Security search unavailable: {exc}") from exc
@app.get("/api/v1/markets/latest")
def latest_markets(db:Session=Depends(get_db)):return {"markets":list(_latest_market_by_symbol(db).values()),"note":"Includes cached fundamentals and current Williams %R when present in the stored market snapshot; no provider calls are made by this route."}
@app.get("/api/v1/markets/{symbol}/fundamentals")
def fundamentals(symbol:str,db:Session=Depends(get_db)):return get_fundamentals(symbol,db)
@app.get("/api/v1/markets/{symbol}/williams-r")
def williams_r(symbol:str,period:int=Query(default=14,ge=2,le=100)):
 s=symbol.strip().upper()
 try:return _cached_shared(f"williams:{s}:{period}",WILLIAMS_CACHE_TTL_SECONDS,lambda:{"symbol":s,"provider":"Twelve Data","source_url":"https://twelvedata.com/docs",**build_williams_r_series(TwelveDataProvider().daily_history(s,outputsize=5000),period=period)})
 except Exception as exc:raise HTTPException(502,f"Williams %R unavailable for {s}") from exc
@app.get("/api/v1/markets/{symbol}")
def market(symbol:str,verify:bool=True,db:Session=Depends(get_db)):
 r=get_market_snapshot(symbol,db,verify);sym=(r.get("symbol") or symbol).upper();_persist_market_result(db,sym,r);db.commit();return r
@app.get("/api/v1/markets/{symbol}/history")
def history(symbol:str,limit:int=Query(default=20,ge=1,le=100),db:Session=Depends(get_db)):
 rs=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol.strip().upper()).order_by(MarketSnapshot.retrieved_at.desc()).limit(limit).all();return {"symbol":symbol.upper(),"snapshots":[{"id":r.id,"as_of":r.as_of,"provider":r.provider,"retrieved_at":r.retrieved_at.isoformat(),"data":r.payload} for r in rs]}
@app.get("/api/v1/news/world")
def world_news(limit:int=Query(default=25,ge=1,le=50),topic:str|None=None):
 selected=topic if topic in WORLD_NEWS_TOPIC_QUERIES else None
 try:return _cached_shared(f"world:{limit}:{selected or 'all'}",NEWS_CACHE_TTL_SECONDS,lambda:_load_world_news(selected,limit))
 except Exception as exc:raise HTTPException(502,f"World news unavailable: {exc}") from exc
@app.get("/api/v1/news/market")
def market_news(limit:int=Query(default=15,ge=1,le=30)):
 try:return _load_market_news(limit)
 except Exception as exc:raise HTTPException(502,f"Market news unavailable: {exc}") from exc
@app.get("/api/v1/macro/currencies")
def currencies():return _load_currencies()
@app.get("/api/v1/macro/rotation")
def rotation(background_tasks:BackgroundTasks,db:Session=Depends(get_db)):
 m=_latest_market_by_symbol(db,list(SECTORS.keys()));missing=[s for s in MACRO_BACKFILL_PRIORITY if s not in m]
 if missing and not _macro_backfill_running:background_tasks.add_task(_macro_backfill_worker,missing)
 try:c=_load_currencies()
 except Exception:c={"rates":[]}
 try:n=_load_market_news(20).get("articles",[])
 except Exception:n=[]
 result=build_rotation_snapshot(m,c,n);result["tracking_status"]={"tracked":len(m),"requested":len(SECTORS),"pending_backfill":missing,"backfill_uses_latest_completed_market_session":True};return result
@app.get("/api/v1/macro/history")
def macro_history(year:int=2026,db:Session=Depends(get_db)):return build_macro_history(db,year)
@app.get("/api/v1/flow/recent")
def flow(limit:int=Query(default=50,ge=1,le=100),symbol:str|None=None,event_type:str|None=None,db:Session=Depends(get_db)):
 try:
  live=_cached_shared(f"flow:unusual:{limit}",FLOW_CACHE_TTL_SECONDS,lambda:SquawkFlowProvider().unusual_options(limit));events=_enrich_flow_events(db,live.get("events",[]))
  if symbol:events=[e for e in events if str(e.get("symbol") or "").upper()==symbol.strip().upper()]
  if event_type:events=[e for e in events if str(e.get("event_type") or "").lower()==event_type.strip().lower()]
  return {**live,"events":events,"stored_events":_enrich_flow_events(db,_stored_flow(db,min(limit,20),symbol,event_type)),"enrichment":"market cap/price/sector are reused from cached market fundamentals when the flow source omits them"}
 except Exception as exc:
  stored=_enrich_flow_events(db,_stored_flow(db,limit,symbol,event_type));return {"provider":"SquawkFlow","provider_configured":True,"events":stored,"stored_events":stored,"live_error":"Live unusual-options feed temporarily unavailable","note":"Showing stored flow observations when available. No synthetic flow is generated.","error_detail":str(exc)}
@app.get("/api/v1/report/current")
def current_report(db:Session=Depends(get_db)):
 try:c=_load_currencies()
 except Exception:c={"rates":[],"provider":"unavailable"}
 try:n=_load_market_news(15)
 except Exception:n={"articles":[],"provider":"unavailable"}
 return build_daily_report(db,currencies=c,market_news=n)
@app.post("/api/v1/report/generate")
def generate_report(db:Session=Depends(get_db)):
 r=current_report(db);row=ReportSnapshot(report_date=r["report_date"],payload=r);db.add(row);db.commit();db.refresh(row);return {"id":row.id,**r}
@app.get("/api/v1/report/history")
def report_history(limit:int=Query(default=20,ge=1,le=100),db:Session=Depends(get_db)):
 rs=db.query(ReportSnapshot).order_by(ReportSnapshot.created_at.desc()).limit(limit).all();return {"reports":[{"id":r.id,"report_date":r.report_date,"created_at":r.created_at.isoformat(),"data":r.payload} for r in rs]}
@app.get("/api/v1/report/config")
def config():return {"sections":["vix","markets","currencies","macro_rotation","macro_history","market_news","world_news","outliers","flow"],"providers":{"primary_market_data":"Twelve Data","secondary_market_data":"Alpha Vantage","fundamentals":"Alpha Vantage OVERVIEW cached for 7 days, with derived P/E/P/S/PEG fallback and stale-cache fallback","world_news":"GDELT + Google News RSS fallback","currencies":"Frankfurter","macro_calendar":"MacroRadar","ticker_validation":"Twelve Data exact symbol search + stored market history","flow":"SquawkFlow public unusual-options API enriched from cached market fundamentals"}}
