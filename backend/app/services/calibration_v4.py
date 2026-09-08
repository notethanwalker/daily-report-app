from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..normalized_market_models import NormalizedDailyBar
from ..v4_models import CandidateObservationV4, CandidateOutcomeV4, RotationSnapshotV4
from .candidate_funnel_v4 import build_candidate_funnel
from .macro_universe import MACRO_CATEGORIES
from .rotation_model_v4 import build_rotation_model

ROTATION_MODEL_VERSION="rotation-v4.5"
CANDIDATE_MODEL_VERSION="candidate-funnel-v4.4"
CAPTURE_SECONDS=60*60
OUTCOME_HORIZONS=(5,20,60)
MAX_CANDIDATES_PER_DAY=100
CALIBRATION_BENCHMARKS={"U.S. Market":"SPY","Factors":"SPY","Sectors":"SPY","Technology Themes":"QQQ","Industrial / Infrastructure":"SPY","Consumer / Housing":"SPY","Healthcare Themes":"XLV"}


def _upsert_rotation(db:Session,rotation:dict)->int:
    changed=0
    for r in rotation.get("rows",[]):
        day=str(r.get("as_of") or date.today().isoformat())[:10];payload=dict(r)
        row=db.query(RotationSnapshotV4).filter(RotationSnapshotV4.symbol==r["symbol"],RotationSnapshotV4.observation_date==day,RotationSnapshotV4.model_version==ROTATION_MODEL_VERSION).first()
        if row:
            if row.payload==payload:continue
            row.rotation_score=float(r.get("rotation_score") or 0);row.rotation_pressure=float(r.get("rotation_pressure") or 0);row.state=str(r.get("state") or "unknown");row.forward_bias=str(r.get("forward_bias") or "unknown");row.conviction=float(r.get("conviction") or 0);row.payload=payload
        else:db.add(RotationSnapshotV4(symbol=r["symbol"],name=str(r.get("name") or r["symbol"]),observation_date=day,rotation_score=float(r.get("rotation_score") or 0),rotation_pressure=float(r.get("rotation_pressure") or 0),state=str(r.get("state") or "unknown"),forward_bias=str(r.get("forward_bias") or "unknown"),conviction=float(r.get("conviction") or 0),payload=payload,model_version=ROTATION_MODEL_VERSION))
        changed+=1
    if changed:db.commit()
    return changed


def _insert_candidates_once(db:Session,funnel:dict)->int:
    changed=0
    for rank,c in enumerate((funnel.get("candidates") or [])[:MAX_CANDIDATES_PER_DAY],start=1):
        symbol=str(c.get("symbol") or "").upper();obs_date=str(c.get("as_of") or date.today().isoformat())[:10]
        if not symbol:continue
        exists=db.query(CandidateObservationV4).filter(CandidateObservationV4.symbol==symbol,CandidateObservationV4.observation_date==obs_date,CandidateObservationV4.model_version==CANDIDATE_MODEL_VERSION).first()
        if exists:continue
        db.add(CandidateObservationV4(symbol=symbol,observation_date=obs_date,model_version=CANDIDATE_MODEL_VERSION,funnel_score=float(c.get("funnel_score") or 0),rank=rank,setup_type=str(c.get("setup_type") or "technical_only"),rotation_proxy=c.get("rotation_proxy"),price=float(c["price"]) if c.get("price") is not None else None,payload={**dict(c),"discovery_policy":"first qualifying observation for the underlying market-data date; immutable thereafter"}));changed+=1
    if changed:db.commit()
    return changed

def _bars_after(db,symbol,start_date,count):return db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol==symbol,NormalizedDailyBar.bar_date>=start_date).order_by(NormalizedDailyBar.bar_date.asc()).limit(count+8).all()
def _base_close(db,symbol,day):
    row=db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol==symbol,NormalizedDailyBar.bar_date<=day).order_by(NormalizedDailyBar.bar_date.desc()).first();return float(row.close) if row else None
def _forward_window(db,symbol,day,horizon):return [b for b in _bars_after(db,symbol,day,horizon+1) if b.bar_date>day][:horizon]
def _incomplete_candidates(db,limit):
    completed=db.query(CandidateOutcomeV4.candidate_id,func.count(CandidateOutcomeV4.id).label("n")).filter(CandidateOutcomeV4.status=="complete").group_by(CandidateOutcomeV4.candidate_id).having(func.count(CandidateOutcomeV4.id)>=len(OUTCOME_HORIZONS)).subquery()
    return db.query(CandidateObservationV4).outerjoin(completed,CandidateObservationV4.id==completed.c.candidate_id).filter(completed.c.candidate_id.is_(None)).order_by(CandidateObservationV4.observation_date.asc()).limit(limit).all()

def update_candidate_outcomes(db:Session,limit:int=500)->dict:
    candidates=_incomplete_candidates(db,limit);completed=waiting=0
    for c in candidates:
        if c.price is None or c.price<=0:continue
        for horizon in OUTCOME_HORIZONS:
            existing=db.query(CandidateOutcomeV4).filter(CandidateOutcomeV4.candidate_id==c.id,CandidateOutcomeV4.horizon_days==horizon).first()
            if existing and existing.status=="complete":continue
            window=_forward_window(db,c.symbol,c.observation_date,horizon)
            if len(window)<horizon:
                waiting+=1
                if not existing:db.add(CandidateOutcomeV4(candidate_id=c.id,symbol=c.symbol,horizon_days=horizon,status="pending"))
                continue
            last=window[-1];highs=[float(b.high if b.high is not None else b.close) for b in window];lows=[float(b.low if b.low is not None else b.close) for b in window];ret=(float(last.close)/c.price-1)*100;mfe=(max(highs)/c.price-1)*100;mae=(min(lows)/c.price-1)*100
            if existing:existing.return_pct=ret;existing.max_favorable_excursion_pct=mfe;existing.max_adverse_excursion_pct=mae;existing.end_date=last.bar_date;existing.status="complete";existing.computed_at=datetime.now(timezone.utc)
            else:db.add(CandidateOutcomeV4(candidate_id=c.id,symbol=c.symbol,horizon_days=horizon,return_pct=ret,max_favorable_excursion_pct=mfe,max_adverse_excursion_pct=mae,end_date=last.bar_date,status="complete"))
            completed+=1
    db.commit();return {"completed":completed,"waiting":waiting,"candidates_examined":len(candidates)}


def _benchmark_for(symbol:str)->str|None:return CALIBRATION_BENCHMARKS.get(MACRO_CATEGORIES.get(symbol,""))
def rotation_calibration_summary(db:Session,horizon_days:int=20)->dict:
    rows=db.query(RotationSnapshotV4).filter(RotationSnapshotV4.model_version==ROTATION_MODEL_VERSION).order_by(RotationSnapshotV4.observation_date.asc()).all();groups={};skipped=0
    for r in rows:
        benchmark=_benchmark_for(r.symbol)
        if not benchmark:skipped+=1;continue
        ss=_base_close(db,r.symbol,r.observation_date);bs=_base_close(db,benchmark,r.observation_date);sf=_forward_window(db,r.symbol,r.observation_date,horizon_days);bf=_forward_window(db,benchmark,r.observation_date,horizon_days)
        if not ss or not bs or len(sf)<horizon_days or len(bf)<horizon_days:continue
        rel=(float(sf[-1].close)/ss-1)*100-(float(bf[-1].close)/bs-1)*100;groups.setdefault(r.state,[]).append(rel)
    return {"horizon_days":horizon_days,"benchmark_policy":CALIBRATION_BENCHMARKS,"states":{k:{"samples":len(v),"mean_relative_return_pct":round(sum(v)/len(v),3),"outperformance_rate":round(sum(1 for x in v if x>0)/len(v),3),"probability_label_eligible":len(v)>=30} for k,v in groups.items() if v},"skipped_non_equity_or_unmapped_rows":skipped,"model_version":ROTATION_MODEL_VERSION,"interpretation":"Equity sectors/themes are calibrated relative to category-appropriate equity benchmarks. Cross-asset groups are excluded until dedicated benchmark models exist. Probability language requires at least 30 observations per state."}

def capture_once()->dict:
    db=SessionLocal()
    try:
        rotation=build_rotation_model(db,persist=False);rw=_upsert_rotation(db,rotation);funnel=build_candidate_funnel(db,rotation,limit=MAX_CANDIDATES_PER_DAY,enqueue_enrichment=False);cw=_insert_candidates_once(db,funnel);outcomes=update_candidate_outcomes(db);return {"rotation_rows":rw,"candidate_rows":cw,"outcomes":outcomes}
    except Exception:db.rollback();raise
    finally:db.close()
async def calibration_loop():
    while True:
        try:await asyncio.to_thread(capture_once)
        except Exception:pass
        await asyncio.sleep(CAPTURE_SECONDS)
