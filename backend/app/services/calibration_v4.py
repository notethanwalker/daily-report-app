from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..normalized_market_models import NormalizedDailyBar
from ..v4_models import CandidateObservationV4, CandidateOutcomeV4, RotationSnapshotV4
from .candidate_funnel_v4 import build_candidate_funnel
from .rotation_model_v4 import build_rotation_model

ROTATION_MODEL_VERSION="rotation-v4.3"
CANDIDATE_MODEL_VERSION="candidate-funnel-v4.3"
CAPTURE_SECONDS=60*60
OUTCOME_HORIZONS=(5,20,60)
MAX_CANDIDATES_PER_DAY=100


def _upsert_rotation(db:Session,rotation:dict)->int:
    changed=0
    for r in rotation.get("rows",[]):
        day=str(r.get("as_of") or date.today().isoformat())[:10]
        row=db.query(RotationSnapshotV4).filter(RotationSnapshotV4.symbol==r["symbol"],RotationSnapshotV4.observation_date==day,RotationSnapshotV4.model_version==ROTATION_MODEL_VERSION).first()
        payload=dict(r)
        if row:
            if row.payload==payload:continue
            row.rotation_score=float(r.get("rotation_score") or 0);row.rotation_pressure=float(r.get("rotation_pressure") or 0);row.state=str(r.get("state") or "unknown");row.forward_bias=str(r.get("forward_bias") or "unknown");row.conviction=float(r.get("conviction") or 0);row.payload=payload
        else:
            db.add(RotationSnapshotV4(symbol=r["symbol"],name=str(r.get("name") or r["symbol"]),observation_date=day,rotation_score=float(r.get("rotation_score") or 0),rotation_pressure=float(r.get("rotation_pressure") or 0),state=str(r.get("state") or "unknown"),forward_bias=str(r.get("forward_bias") or "unknown"),conviction=float(r.get("conviction") or 0),payload=payload,model_version=ROTATION_MODEL_VERSION))
        changed+=1
    if changed:db.commit()
    return changed


def _upsert_candidates(db:Session,funnel:dict)->int:
    changed=0;today=date.today().isoformat()
    for rank,c in enumerate((funnel.get("candidates") or [])[:MAX_CANDIDATES_PER_DAY],start=1):
        symbol=str(c.get("symbol") or "").upper()
        if not symbol:continue
        row=db.query(CandidateObservationV4).filter(CandidateObservationV4.symbol==symbol,CandidateObservationV4.observation_date==today,CandidateObservationV4.model_version==CANDIDATE_MODEL_VERSION).first()
        payload=dict(c)
        values={"funnel_score":float(c.get("funnel_score") or 0),"rank":rank,"setup_type":str(c.get("setup_type") or "technical_only"),"rotation_proxy":c.get("rotation_proxy"),"price":float(c["price"]) if c.get("price") is not None else None,"payload":payload}
        if row:
            for k,v in values.items():setattr(row,k,v)
        else:db.add(CandidateObservationV4(symbol=symbol,observation_date=today,model_version=CANDIDATE_MODEL_VERSION,**values))
        changed+=1
    if changed:db.commit()
    return changed


def _bars_after(db:Session,symbol:str,start_date:str,horizon:int):
    return db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol==symbol,NormalizedDailyBar.bar_date>=start_date).order_by(NormalizedDailyBar.bar_date.asc()).limit(horizon+5).all()


def update_candidate_outcomes(db:Session,limit:int=250)->dict:
    pending=db.query(CandidateObservationV4).order_by(CandidateObservationV4.observation_date.asc()).limit(limit).all()
    completed=0;waiting=0
    for c in pending:
        if c.price is None or c.price<=0:continue
        for horizon in OUTCOME_HORIZONS:
            existing=db.query(CandidateOutcomeV4).filter(CandidateOutcomeV4.candidate_id==c.id,CandidateOutcomeV4.horizon_days==horizon).first()
            if existing and existing.status=="complete":continue
            bars=_bars_after(db,c.symbol,c.observation_date,horizon+1)
            forward=[b for b in bars if b.bar_date>c.observation_date]
            if len(forward)<horizon:
                waiting+=1
                if not existing:db.add(CandidateOutcomeV4(candidate_id=c.id,symbol=c.symbol,horizon_days=horizon,status="pending"))
                continue
            window=forward[:horizon];last=window[-1];prices=[float(b.close) for b in window]
            ret=(float(last.close)/c.price-1)*100;mfe=(max(prices)/c.price-1)*100;mae=(min(prices)/c.price-1)*100
            if existing:
                existing.return_pct=ret;existing.max_favorable_excursion_pct=mfe;existing.max_adverse_excursion_pct=mae;existing.end_date=last.bar_date;existing.status="complete";existing.computed_at=datetime.now(timezone.utc)
            else:db.add(CandidateOutcomeV4(candidate_id=c.id,symbol=c.symbol,horizon_days=horizon,return_pct=ret,max_favorable_excursion_pct=mfe,max_adverse_excursion_pct=mae,end_date=last.bar_date,status="complete"))
            completed+=1
    db.commit();return {"completed":completed,"waiting":waiting}


def rotation_calibration_summary(db:Session,horizon_days:int=20)->dict:
    rows=db.query(RotationSnapshotV4).order_by(RotationSnapshotV4.observation_date.asc()).all()
    groups={}
    for r in rows:
        bars=_bars_after(db,r.symbol,r.observation_date,horizon_days+1);forward=[b for b in bars if b.bar_date>r.observation_date]
        if len(forward)<horizon_days:continue
        start=float((r.payload or {}).get("price") or 0)
        if not start:
            base=db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol==r.symbol,NormalizedDailyBar.bar_date<=r.observation_date).order_by(NormalizedDailyBar.bar_date.desc()).first();start=float(base.close) if base else 0
        if not start:continue
        ret=(float(forward[horizon_days-1].close)/start-1)*100
        g=groups.setdefault(r.state,[]);g.append(ret)
    return {"horizon_days":horizon_days,"states":{k:{"samples":len(v),"mean_return_pct":round(sum(v)/len(v),3),"positive_rate":round(sum(1 for x in v if x>0)/len(v),3)} for k,v in groups.items() if v},"note":"Descriptive calibration only; relative-to-benchmark calibration will replace raw returns once sufficient history accumulates."}


def capture_once()->dict:
    db=SessionLocal()
    try:
        rotation=build_rotation_model(db,persist=False);rw=_upsert_rotation(db,rotation)
        funnel=build_candidate_funnel(db,rotation,limit=MAX_CANDIDATES_PER_DAY,enqueue_enrichment=False);cw=_upsert_candidates(db,funnel)
        outcomes=update_candidate_outcomes(db)
        return {"rotation_rows":rw,"candidate_rows":cw,"outcomes":outcomes}
    except Exception:
        db.rollback();raise
    finally:db.close()


async def calibration_loop():
    while True:
        try:await asyncio.to_thread(capture_once)
        except Exception:pass
        await asyncio.sleep(CAPTURE_SECONDS)
