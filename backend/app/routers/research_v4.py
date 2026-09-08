from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FeatureSnapshot, FundamentalCache, HistoricalDailyBar, MarketSnapshot, SymbolRegistry
from ..providers.twelve_data import TwelveDataProvider
from ..services.calculations import build_market_snapshot
from ..services.provider_orchestrator import is_stale
from ..services.refresh_scheduler import _persist_history
from ..services.score_history_v4 import build_score_history
from .intelligence import _latest_market, _opportunity_components, _recent_flow, _refresh_feature, _upsert_registry

router=APIRouter(prefix="/api/v1",tags=["research-v4"])


def _store_market(db:Session,symbol:str)->dict:
    snap=build_market_snapshot(TwelveDataProvider().market_snapshot_raw(symbol))
    if snap.get("price") is None:
        raise HTTPException(404,f"No market data available for {symbol}")
    db.add(MarketSnapshot(symbol=symbol,as_of=str(snap.get("as_of") or ""),provider=str(snap.get("provider") or "Twelve Data"),payload=snap,retrieved_at=datetime.now(timezone.utc)))
    _upsert_registry(db,symbol,snap)
    db.commit()
    return snap


def _ensure_history(db:Session,symbol:str):
    count=db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol==symbol).count()
    if count>=120:return {"status":"stored","bars":count}
    try:
        inserted=_persist_history(db,symbol);db.commit()
        count=db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol==symbol).count()
        return {"status":"hydrated","bars":count,"inserted":inserted}
    except Exception as exc:
        db.rollback();return {"status":"deferred","bars":count,"error":str(exc)[:240]}


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
    if history.get("status")=="deferred":hist="enrichment_deferred"
    return {"market":state(market,"market"),"fundamentals":state(fundamental,"fundamentals"),"features":"stored" if feature else "unavailable","history":hist}


@router.get("/security/{symbol}/workspace")
def security_workspace_v4(symbol:str,db:Session=Depends(get_db)):
    s=symbol.strip().upper()
    if not s:raise HTTPException(400,"Symbol is required")
    hydrated=[]
    m=_latest_market(db,s)
    if not m:
        _store_market(db,s);hydrated.append("market");m=_latest_market(db,s)
    history=_ensure_history(db,s)
    if history.get("status")=="hydrated":hydrated.append("history")
    # Fundamentals are handled by the shared enrichment pipeline; workspace reads
    # whatever is currently stored rather than multiplying provider calls.
    o=_opportunity_components(db,s,m);flow=_recent_flow(db,s);reg=db.get(SymbolRegistry,s)
    feature=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==s).order_by(FeatureSnapshot.created_at.desc()).first()
    if not feature:
        try:_refresh_feature(db,s);feature=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==s).order_by(FeatureSnapshot.created_at.desc()).first()
        except Exception:db.rollback()
    fundamental=db.get(FundamentalCache,s)
    score_history=build_score_history(db,s,limit=90)
    return {
        "symbol":s,
        "market":m,
        "fundamentals":fundamental.payload if fundamental else None,
        "opportunity":{k:v for k,v in (o or {}).items() if k!="market"},
        "flow":flow,
        "registry":{"name":reg.name,"asset_type":reg.asset_type,"exchange":reg.exchange,"sector":reg.sector,"industry":reg.industry,"themes":reg.themes} if reg else None,
        "features":feature.payload if feature else None,
        "score_history":score_history,
        "hydrated":hydrated,
        "history_state":history,
        "data_states":_data_states(db,s,history),
        "data_state":"hydrated_on_demand" if hydrated else "stored",
        "workspace_policy":"Entity-centric research view. Stored data is reused across layers; missing expensive datasets are surfaced explicitly instead of hidden behind blocking refreshes.",
    }
