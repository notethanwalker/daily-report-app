from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FeatureSnapshot, FundamentalCache, HistoricalDailyBar, MarketSnapshot, SymbolRegistry
from ..providers.twelve_data import TwelveDataProvider
from ..services.calculations import build_market_snapshot
from ..services.refresh_scheduler import _persist_history
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
    # Fundamentals are requested by the Research frontend through the dedicated
    # fundamentals endpoint. Do not duplicate that provider call here.
    o=_opportunity_components(db,s,m);flow=_recent_flow(db,s);reg=db.get(SymbolRegistry,s)
    feature=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==s).order_by(FeatureSnapshot.created_at.desc()).first()
    if not feature:
        try:_refresh_feature(db,s);feature=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==s).order_by(FeatureSnapshot.created_at.desc()).first()
        except Exception:db.rollback()
    return {"symbol":s,"market":m,"opportunity":{k:v for k,v in (o or {}).items() if k!="market"},"flow":flow,"registry":{"name":reg.name,"asset_type":reg.asset_type,"exchange":reg.exchange,"sector":reg.sector,"industry":reg.industry,"themes":reg.themes} if reg else None,"features":feature.payload if feature else None,"hydrated":hydrated,"history_state":history,"data_state":"hydrated_on_demand" if hydrated else "stored"}
