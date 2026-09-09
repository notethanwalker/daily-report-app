from __future__ import annotations

import os
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FeatureSnapshot, FundamentalCache, MarketSnapshot, SymbolRegistry, Thesis, UserWatchlistItem
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from ..normalized_market_models import MarketPipelineState
from ..providers.alpaca_market_data import AlpacaMarketDataProvider
from ..services.calibration_v4 import CANDIDATE_MODEL_VERSION, ROTATION_MODEL_VERSION, rotation_calibration_summary
from ..services.candidate_funnel_v4 import build_candidate_funnel, enqueue_deep_enrichment
from ..services.classification_v4 import blend_rotation_context, rotation_exposures
from ..services.feature_model_v4 import presentation_payload
from ..services.fundamental_score import build_fundamental_score
from ..services.monthly_priority import deployment_plan
from ..services.opportunity_model import recent_flow
from ..services.provider_orchestrator import ProviderOrchestrator
from ..services.rotation_model_v4 import ROTATION_HISTORY_KEY, build_rotation_model
from ..services.score_history_v4 import build_score_history
from ..v4_models import CandidateObservationV4, CandidateOutcomeV4, RotationSnapshotV4
from .intelligence import current_user

router=APIRouter(prefix="/api/v1/stack",tags=["decision-stack-v4"])
AI_BUILDOUT_BASKET=["NBIS","MU","AAOI","NVDA","SMH"]

def _user_symbols(db,user):
    symbols={x.symbol for x in db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email==user).all() if x.symbol!="__INITIALIZED__"};pids=[x.id for x in db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email==user).all()]
    if pids:symbols|={x.symbol for x in db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id.in_(pids)).all()}
    return sorted(symbols)
def _latest_feature(db,symbol):
    row=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==symbol).order_by(FeatureSnapshot.as_of.desc(),FeatureSnapshot.created_at.desc()).first();return {**presentation_payload(row.payload or {},row.as_of),"as_of":row.as_of} if row else {}
def _latest_market(db,symbol):
    row=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol).order_by(MarketSnapshot.retrieved_at.desc()).first();return {**(row.payload or {}),"retrieved_at":row.retrieved_at.isoformat()} if row else {}
def _sources():
    return [{"provider":"Twelve Data","role":"shared market snapshots/history","configured":bool(os.getenv("TWELVE_DATA_API_KEY")),"authoritative":"shared snapshot when configured"},{"provider":"Alpaca IEX","role":"independent OHLC/history and Williams research","configured":AlpacaMarketDataProvider.configured(),"authoritative":False,"notes":"Free IEX feed is not consolidated SIP."},{"provider":"Yahoo Finance","role":"quota-free OHLC fallback and valuation coverage","configured":True,"authoritative":False},{"provider":"SEC EDGAR","role":"public fundamental history","configured":True,"authoritative":"fundamental-history source where taxonomy coverage exists"},{"provider":"Alpha Vantage","role":"quota-aware independent check / missing fundamentals","configured":bool(os.getenv("ALPHA_VANTAGE_API_KEY")),"authoritative":False},{"provider":"GDELT + Google News RSS","role":"news intelligence","configured":True,"authoritative":False},{"provider":"Frankfurter / ECB","role":"FX and currency context","configured":True,"authoritative":"FX layer"},{"provider":"Public economic calendars + Nasdaq","role":"macro/company events","configured":True,"authoritative":"event-specific public source"},{"provider":"SquawkFlow observations","role":"unusual options / large-flow observations","configured":True,"authoritative":False}]
def _macro(db,rotation,symbol,market,reg):
    sector=(reg.sector if reg else None) or market.get("sector");industry=(reg.industry if reg else None) or market.get("industry");themes=(reg.themes if reg else None) or market.get("themes");return blend_rotation_context(rotation,symbol,sector,industry,themes)

@router.get("/overview")
def overview(db:Session=Depends(get_db),user:str=Depends(current_user)):
    symbols=_user_symbols(db,user);state=db.get(MarketPipelineState,ROTATION_HISTORY_KEY);days=len((state.payload or {}).get("daily",[])) if state else 0
    return {"version":"4.5-dev","pipeline":["research","macro","opportunity","deployment"],"provider_policy":ProviderOrchestrator().describe(),"sources":_sources(),"layers":{"research":{"tracked_symbols":len(symbols),"stored_market_snapshots":db.query(MarketSnapshot).count(),"stored_feature_snapshots":db.query(FeatureSnapshot).count(),"status":"active-v4"},"macro":{"status":"active-v4","rotation_history_days":days,"relational_rotation_snapshots":db.query(RotationSnapshotV4).count()},"opportunity":{"status":"active-v4","tracked_symbols":len(symbols),"candidate_observations":db.query(CandidateObservationV4).count(),"candidate_outcomes":db.query(CandidateOutcomeV4).filter(CandidateOutcomeV4.status=="complete").count()},"deployment":{"status":"phase-1","models":["Williams Priority — new capital only"],"named_baskets":{"AI Buildout Basket":AI_BUILDOUT_BASKET},"manual_quality_gate":True,"rebalancing_default":False}},"overview_policy":"Summary metadata only; detailed layer data is permission-isolated."}

@router.get("/sources")
def sources(user:str=Depends(current_user)):return {"sources":_sources(),"policy":ProviderOrchestrator().describe()}
@router.get("/rotation")
def rotation(db:Session=Depends(get_db),user:str=Depends(current_user)):return build_rotation_model(db)
@router.get("/rotation/history")
def rotation_history(days:int=Query(90,ge=1,le=400),db:Session=Depends(get_db),user:str=Depends(current_user)):
    rows=db.query(RotationSnapshotV4).order_by(RotationSnapshotV4.observation_date.desc(),RotationSnapshotV4.symbol).limit(days*80).all();return {"rows":[{"symbol":x.symbol,"name":x.name,"date":x.observation_date,"score":x.rotation_score,"pressure":x.rotation_pressure,"state":x.state,"forward_bias":x.forward_bias,"conviction":x.conviction,"model_version":x.model_version} for x in rows],"model_version":ROTATION_MODEL_VERSION}
@router.get("/rotation/calibration")
def rotation_calibration(horizon:int=Query(20,ge=5,le=60),db:Session=Depends(get_db),user:str=Depends(current_user)):return rotation_calibration_summary(db,horizon)

@router.get("/candidates")
def candidates(limit:int=Query(50,ge=1,le=200),db:Session=Depends(get_db),user:str=Depends(current_user)):return build_candidate_funnel(db,build_rotation_model(db),limit=limit,enqueue_enrichment=False)
@router.post("/candidates/enrich")
def enrich_candidates(limit:int=Query(50,ge=1,le=200),db:Session=Depends(get_db),user:str=Depends(current_user)):
    f=build_candidate_funnel(db,build_rotation_model(db),limit=limit,enqueue_enrichment=False);symbols=f.get("deep_enrichment_symbols",[]);return {"shortlist":symbols,"jobs_added":enqueue_deep_enrichment(db,symbols),"policy":"Explicit bounded enrichment action."}
@router.get("/candidates/history")
def candidate_history(limit:int=Query(200,ge=1,le=1000),db:Session=Depends(get_db),user:str=Depends(current_user)):
    rows=db.query(CandidateObservationV4).order_by(CandidateObservationV4.observation_date.desc(),CandidateObservationV4.rank).limit(limit).all();return {"model_version":CANDIDATE_MODEL_VERSION,"rows":[{"id":x.id,"symbol":x.symbol,"date":x.observation_date,"score":x.funnel_score,"rank":x.rank,"setup_type":x.setup_type,"rotation_proxy":x.rotation_proxy,"price":x.price} for x in rows]}

@router.get("/scores/{symbol}")
def score_history(symbol:str,limit:int=Query(90,ge=2,le=365),db:Session=Depends(get_db),user:str=Depends(current_user)):return build_score_history(db,symbol,limit=limit)

@router.get("/research/{symbol}")
def research_workspace(symbol:str,db:Session=Depends(get_db),user:str=Depends(current_user)):
    s=symbol.strip().upper()
    if not s:raise HTTPException(400,"Symbol is required")
    market=_latest_market(db,s);feature=_latest_feature(db,s);fund=db.get(FundamentalCache,s);reg=db.get(SymbolRegistry,s);rotation=build_rotation_model(db);macro=_macro(db,rotation,s,market,reg);theses=[]
    for t in db.query(Thesis).filter(Thesis.user_email==user,Thesis.enabled.is_(True)).all():
        syms=t.symbols if isinstance(t.symbols,list) else (t.symbols or {}).get("symbols",[]) if isinstance(t.symbols,dict) else []
        if s in [str(x).upper() for x in syms]:theses.append({"id":t.id,"title":t.title,"statement":t.statement})
    hist=build_score_history(db,s,90)
    return {"symbol":s,"registry":{"name":reg.name,"asset_type":reg.asset_type,"exchange":reg.exchange,"sector":reg.sector,"industry":reg.industry,"themes":reg.themes} if reg else None,"market":market,"fundamentals":{**(fund.payload or {}),"retrieved_at":fund.retrieved_at.isoformat()} if fund else None,"latest_features":feature,"score_history":hist,"flow_72h":recent_flow(db,s),"rotation_context":macro,"theses":theses,"data_state":{"market":bool(market),"fundamentals":bool(fund),"feature_history_points":len(hist.get("history",[])),"registry":bool(reg)},"methodology":"Entity-centric, cache-first workspace with weighted theme/sector rotation context."}

@router.get("/research/theme/{name}")
def theme_workspace(name:str,db:Session=Depends(get_db),user:str=Depends(current_user)):
    target=name.strip().lower();rotation=build_rotation_model(db);rrow=next((x for x in rotation.get("rows",[]) if str(x.get("name") or "").lower()==target),None);const=[]
    for reg in db.query(SymbolRegistry).all():
        ex,basis=rotation_exposures(reg.symbol,reg.sector,reg.industry,reg.themes)
        match=next((w for k,w in ex.items() if k.lower()==target),None)
        if match is None:continue
        m=_latest_market(db,reg.symbol);f=_latest_feature(db,reg.symbol);const.append({"symbol":reg.symbol,"name":reg.name,"exposure_weight":match,"basis":basis,"price":m.get("price"),"return_7d":m.get("seven_day_percent"),"return_30d":m.get("thirty_day_percent"),"buy_score":f.get("buy_score"),"williams_r":f.get("williams_r"),"ma100_distance":f.get("ma100_distance")})
    const.sort(key=lambda x:(x.get("exposure_weight") or 0,x.get("buy_score") or 0),reverse=True)
    return {"theme":name,"rotation":rrow,"constituents":const[:100],"constituent_count":len(const),"methodology":"Weighted exposure workspace joins current rotation state to mapped securities and their stored opportunity context."}

@router.get("/deployment")
def deployment(capital:float=Query(1000,ge=0,le=100000000),basket:str=Query("watchlist"),symbols:str|None=Query(None),db:Session=Depends(get_db),user:str=Depends(current_user)):
    if symbols:selected=[x.strip().upper() for x in symbols.split(",") if x.strip()];name="Custom Basket"
    elif basket.lower() in {"ai","ai-buildout","ai_buildout","ai buildout basket"}:selected=AI_BUILDOUT_BASKET;name="AI Buildout Basket"
    else:selected=_user_symbols(db,user);name="Watchlist + Portfolio"
    plan=deployment_plan(selected,capital)
    for row in plan.get("eligible",[]):
        fund=db.get(FundamentalCache,row["symbol"])
        row["fundamental_score"]=build_fundamental_score(fund.payload if fund else None)
        row["fundamental_source"]={"provider":fund.provider,"retrieved_at":fund.retrieved_at.isoformat()} if fund else None
    return {"model":"Williams Priority v1 + informational fundamentals","basket":name,"symbols":selected,"capital":capital,"new_capital_only":True,"existing_holdings_rebalanced":False,"quality_gate":"informational_only","fundamental_score_policy":"Display-only context. Fundamental score never changes Williams rank, weight, eligibility or suggested dollars.",**plan}
