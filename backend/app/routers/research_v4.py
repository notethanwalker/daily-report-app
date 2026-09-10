from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FeatureSnapshot, FundamentalCache, HistoricalDailyBar, MarketSnapshot, RefreshQueueItem, SymbolRegistry
from ..services.provider_orchestrator import FRESHNESS_POLICIES, is_stale
from ..services.score_history_v4 import build_score_history
from ..services.strategy_lab_v4 import run_formula_history, run_williams_timeline
from .intelligence import _latest_market, _opportunity_components, _recent_flow

router=APIRouter(prefix="/api/v1",tags=["research-v4"])
RESEARCH_ENRICH_CLASSES=("market","history","fundamentals")


class WilliamsTimelineRequest(BaseModel):
    start: str
    end: str|None=None
    contribution: float=Field(default=1000.0,gt=0,le=1_000_000)
    threshold: float=Field(default=-80.0,ge=-100,le=0)
    window: int=Field(default=14,ge=2,le=100)


class FormulaHistoryRequest(BaseModel):
    criteria: dict[str,float]
    filters: list[dict]=Field(default_factory=list)
    score_threshold: float=Field(default=70.0,ge=0,le=100)
    start: str|None=None
    end: str|None=None


def _history_state(db:Session,symbol:str)->dict:
    count=db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol==symbol).count()
    return {"status":"stored" if count>=120 else "partial" if count>0 else "unavailable","bars":count}


def _data_states(db: Session, symbol: str, history: dict) -> dict:
    now=datetime.now(timezone.utc)
    market=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol).order_by(MarketSnapshot.retrieved_at.desc()).first()
    fundamental=db.get(FundamentalCache,symbol)
    feature=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==symbol).order_by(FeatureSnapshot.created_at.desc()).first()
    def state(row, kind):
        if not row:return "unavailable"
        retrieved=getattr(row,"retrieved_at",None) or getattr(row,"created_at",None)
        if retrieved and is_stale(retrieved,kind,now):return "stored_stale"
        return "stored_current"
    hist="current" if (history.get("bars") or 0)>=120 else "partial" if (history.get("bars") or 0)>0 else "unavailable"
    return {"market":state(market,"market"),"fundamentals":state(fundamental,"fundamentals"),"features":"stored" if feature else "unavailable","history":hist}


def _queue_state(db:Session,symbol:str)->list[dict]:
    rows=db.query(RefreshQueueItem).filter(RefreshQueueItem.symbol==symbol,RefreshQueueItem.requested_by=="v4_research").order_by(RefreshQueueItem.created_at.desc()).limit(12).all()
    return [{"data_class":x.data_class,"status":x.status,"error":x.error,"created_at":x.created_at.isoformat() if x.created_at else None,"updated_at":x.updated_at.isoformat() if x.updated_at else None} for x in rows]


def _enqueue_research(db:Session,symbol:str)->list[str]:
    added=[]
    priorities={"market":max(80,FRESHNESS_POLICIES["market"].priority),"history":max(75,FRESHNESS_POLICIES["history"].priority),"fundamentals":max(70,FRESHNESS_POLICIES["fundamentals"].priority)}
    for data_class in RESEARCH_ENRICH_CLASSES:
        exists=db.query(RefreshQueueItem).filter(RefreshQueueItem.symbol==symbol,RefreshQueueItem.data_class==data_class,RefreshQueueItem.status.in_(["queued","running"])).first()
        if exists:continue
        db.add(RefreshQueueItem(symbol=symbol,data_class=data_class,priority=priorities[data_class],requested_by="v4_research"));added.append(data_class)
    if added:db.commit()
    return added


@router.get("/security/{symbol}/workspace")
def security_workspace_v4(symbol:str,db:Session=Depends(get_db)):
    s=symbol.strip().upper()
    if not s:raise HTTPException(400,"Symbol is required")
    m=_latest_market(db,s);history=_history_state(db,s);o=_opportunity_components(db,s,m) if m else {};flow=_recent_flow(db,s);reg=db.get(SymbolRegistry,s)
    feature=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==s).order_by(FeatureSnapshot.created_at.desc()).first();fundamental=db.get(FundamentalCache,s);score_history=build_score_history(db,s,limit=90)
    return {"symbol":s,"market":m,"fundamentals":fundamental.payload if fundamental else None,"opportunity":{k:v for k,v in (o or {}).items() if k!="market"},"flow":flow,"registry":{"name":reg.name,"asset_type":reg.asset_type,"exchange":reg.exchange,"sector":reg.sector,"industry":reg.industry,"themes":reg.themes} if reg else None,"features":feature.payload if feature else None,"score_history":score_history,"history_state":history,"data_states":_data_states(db,s,history),"data_state":"stored" if any((m,feature,fundamental,reg)) else "unavailable","enrichment_queue":_queue_state(db,s),"workspace_policy":"Read-only, cache-first entity view. Missing or stale data is surfaced explicitly; enrichment is queued and processed by the shared bounded background worker."}


@router.post("/security/{symbol}/enrich")
def enrich_security_workspace_v4(symbol:str,db:Session=Depends(get_db)):
    s=symbol.strip().upper()
    if not s:raise HTTPException(400,"Symbol is required")
    added=_enqueue_research(db,s)
    return {"symbol":s,"jobs_added":added,"queue":_queue_state(db,s),"status":"queued" if added else "already_queued_or_running","feature_policy":"Feature generation is downstream of refreshed shared datasets; arbitrary research requests do not bypass the bounded queue.","policy":"Asynchronous bounded research enrichment. Provider work is never performed in the HTTP request path."}


@router.post("/security/{symbol}/strategy-lab/williams")
def strategy_lab_williams(symbol:str,payload:WilliamsTimelineRequest,db:Session=Depends(get_db)):
    s=symbol.strip().upper()
    try:return run_williams_timeline(db,s,payload.start,payload.end,payload.contribution,payload.threshold,payload.window)
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc


@router.post("/security/{symbol}/strategy-lab/formula")
def strategy_lab_formula(symbol:str,payload:FormulaHistoryRequest,db:Session=Depends(get_db)):
    s=symbol.strip().upper()
    try:return run_formula_history(db,s,payload.criteria,payload.filters,payload.score_threshold,payload.start,payload.end)
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc
