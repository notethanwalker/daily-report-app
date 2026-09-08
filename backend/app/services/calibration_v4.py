from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import logging
import threading

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..database import SessionLocal, engine
from ..normalized_market_models import NormalizedDailyBar
from ..v4_models import CandidateObservationV4, CandidateOutcomeV4, RotationSnapshotV4
from .candidate_funnel_v4 import CANDIDATE_MODEL_VERSION, build_candidate_funnel
from .macro_universe import MACRO_CATEGORIES
from .rotation_model_v4 import ROTATION_MODEL_VERSION, build_rotation_model

logger=logging.getLogger(__name__)
CAPTURE_SECONDS=60*60
INITIAL_CAPTURE_DELAY_SECONDS=5*60
OUTCOME_HORIZONS=(5,20,60)
MAX_CANDIDATES_PER_DAY=50
RETENTION_DAYS=1095
MIN_PROBABILITY_SAMPLES=60
MIN_PROBABILITY_DATES=30
MIN_PROBABILITY_SPAN_DAYS=90
_CAPTURE_LOCK_KEY=1146242612
_LOCAL_CAPTURE_LOCK=threading.Lock()
CALIBRATION_BENCHMARKS={"U.S. Market":"SPY","Factors":"SPY","Sectors":"SPY","Technology Themes":"QQQ","Industrial / Infrastructure":"SPY","Consumer / Housing":"SPY","Healthcare Themes":"XLV"}


def _rotation_payload(r:dict)->dict:
    keep=("symbol","name","as_of","delta_1_observation","delta_3_observations","trend_context","relative_volume","observations","history_quality","data_age_hours","stale_input","transition_ready")
    return {k:r.get(k) for k in keep if k in r}

def _candidate_payload(c:dict)->dict:
    keep=("as_of","provider","bucket","technical_score","base_buy_score","base_buy_source","rotation_state","rotation_pressure","rotation_conviction","macro_confidence_factor","rotation_exposures","williams_r_14","price_vs_ma100_percent","average_dollar_volume_20d","enrichment_status","raw_rank_score")
    return {**{k:c.get(k) for k in keep if k in c},"discovery_policy":"first qualifying observation for the underlying market-data date; immutable thereafter","entry_price_policy":"stored scanner price at first capture; forward windows begin on the next trading day"}

@contextmanager
def _single_capture_lock():
    if engine.dialect.name.startswith("postgres"):
        conn=engine.connect();acquired=False
        try:
            acquired=bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"),{"k":_CAPTURE_LOCK_KEY}).scalar())
            yield acquired
        finally:
            if acquired:
                try:conn.execute(text("SELECT pg_advisory_unlock(:k)"),{"k":_CAPTURE_LOCK_KEY})
                except Exception:logger.exception("Failed to release v4 calibration advisory lock")
            conn.close()
    else:
        acquired=_LOCAL_CAPTURE_LOCK.acquire(blocking=False)
        try:yield acquired
        finally:
            if acquired:_LOCAL_CAPTURE_LOCK.release()


def _upsert_rotation(db:Session,rotation:dict)->int:
    changed=0
    for r in rotation.get("rows",[]):
        day=str(r.get("as_of") or date.today().isoformat())[:10];payload=_rotation_payload(r)
        row=db.query(RotationSnapshotV4).filter(RotationSnapshotV4.symbol==r["symbol"],RotationSnapshotV4.observation_date==day,RotationSnapshotV4.model_version==ROTATION_MODEL_VERSION).first()
        if row:
            if row.payload==payload and row.rotation_score==float(r.get("rotation_score") or 0) and row.rotation_pressure==float(r.get("rotation_pressure") or 0):continue
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
        db.add(CandidateObservationV4(symbol=symbol,observation_date=obs_date,model_version=CANDIDATE_MODEL_VERSION,funnel_score=float(c.get("funnel_score") or 0),rank=rank,setup_type=str(c.get("setup_type") or "technical_only"),rotation_proxy=c.get("rotation_proxy"),price=float(c["price"]) if c.get("price") is not None else None,payload=_candidate_payload(c)));changed+=1
    if changed:db.commit()
    return changed


def _base_close(db,symbol,day):
    row=db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol==symbol,NormalizedDailyBar.bar_date<=day).order_by(NormalizedDailyBar.bar_date.desc()).first();return float(row.close) if row else None

def _forward_bars(db,symbol,day,max_horizon):
    return db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol==symbol,NormalizedDailyBar.bar_date>day).order_by(NormalizedDailyBar.bar_date.asc()).limit(max_horizon+8).all()
def _incomplete_candidates(db,limit):
    terminal=db.query(CandidateOutcomeV4.candidate_id,func.count(CandidateOutcomeV4.id).label("n")).filter(CandidateOutcomeV4.status.in_(["complete","unavailable"])).group_by(CandidateOutcomeV4.candidate_id).having(func.count(CandidateOutcomeV4.id)>=len(OUTCOME_HORIZONS)).subquery()
    return db.query(CandidateObservationV4).outerjoin(terminal,CandidateObservationV4.id==terminal.c.candidate_id).filter(terminal.c.candidate_id.is_(None)).order_by(CandidateObservationV4.observation_date.asc()).limit(limit).all()


def update_candidate_outcomes(db:Session,limit:int=500)->dict:
    candidates=_incomplete_candidates(db,limit);completed=waiting=unavailable=0
    today=date.today()
    for c in candidates:
        if c.price is None or c.price<=0:continue
        bars=_forward_bars(db,c.symbol,c.observation_date,max(OUTCOME_HORIZONS));existing_rows=db.query(CandidateOutcomeV4).filter(CandidateOutcomeV4.candidate_id==c.id).all();existing_by_h={x.horizon_days:x for x in existing_rows}
        try:elapsed=(today-date.fromisoformat(c.observation_date[:10])).days
        except ValueError:elapsed=0
        for horizon in OUTCOME_HORIZONS:
            existing=existing_by_h.get(horizon)
            if existing and existing.status in {"complete","unavailable"}:continue
            window=bars[:horizon]
            if len(window)<horizon:
                if elapsed>max(45,horizon*3):
                    if existing:existing.status="unavailable";existing.computed_at=datetime.now(timezone.utc)
                    else:db.add(CandidateOutcomeV4(candidate_id=c.id,symbol=c.symbol,horizon_days=horizon,status="unavailable"))
                    unavailable+=1
                else:
                    waiting+=1
                    if not existing:db.add(CandidateOutcomeV4(candidate_id=c.id,symbol=c.symbol,horizon_days=horizon,status="pending"))
                continue
            last=window[-1];highs=[float(b.high if b.high is not None else b.close) for b in window];lows=[float(b.low if b.low is not None else b.close) for b in window];ret=(float(last.close)/c.price-1)*100;mfe=(max(highs)/c.price-1)*100;mae=(min(lows)/c.price-1)*100
            if existing:existing.return_pct=ret;existing.max_favorable_excursion_pct=mfe;existing.max_adverse_excursion_pct=mae;existing.end_date=last.bar_date;existing.status="complete";existing.computed_at=datetime.now(timezone.utc)
            else:db.add(CandidateOutcomeV4(candidate_id=c.id,symbol=c.symbol,horizon_days=horizon,return_pct=ret,max_favorable_excursion_pct=mfe,max_adverse_excursion_pct=mae,end_date=last.bar_date,status="complete"))
            completed+=1
    db.commit();return {"completed":completed,"waiting":waiting,"unavailable":unavailable,"candidates_examined":len(candidates)}


def prune_calibration_history(db:Session)->dict:
    cutoff=(date.today()-timedelta(days=RETENTION_DAYS)).isoformat();old_ids=select(CandidateObservationV4.id).where(CandidateObservationV4.observation_date<cutoff)
    outcomes=db.query(CandidateOutcomeV4).filter(CandidateOutcomeV4.candidate_id.in_(old_ids)).delete(synchronize_session=False)
    candidates=db.query(CandidateObservationV4).filter(CandidateObservationV4.observation_date<cutoff).delete(synchronize_session=False)
    rotation=db.query(RotationSnapshotV4).filter(RotationSnapshotV4.observation_date<cutoff).delete(synchronize_session=False)
    if outcomes or candidates or rotation:db.commit()
    return {"cutoff":cutoff,"candidate_outcomes":outcomes,"candidate_observations":candidates,"rotation_snapshots":rotation}


def _benchmark_for(symbol:str)->str|None:return CALIBRATION_BENCHMARKS.get(MACRO_CATEGORIES.get(symbol,""))
def _eligibility(dates:list[str],samples:int)->dict:
    unique=sorted(set(dates));span=0
    if len(unique)>=2:span=(date.fromisoformat(unique[-1])-date.fromisoformat(unique[0])).days
    eligible=samples>=MIN_PROBABILITY_SAMPLES and len(unique)>=MIN_PROBABILITY_DATES and span>=MIN_PROBABILITY_SPAN_DAYS
    return {"distinct_observation_dates":len(unique),"observation_span_days":span,"probability_label_eligible":eligible}
def rotation_calibration_summary(db:Session,horizon_days:int=20)->dict:
    rows=db.query(RotationSnapshotV4).filter(RotationSnapshotV4.model_version==ROTATION_MODEL_VERSION).order_by(RotationSnapshotV4.observation_date.asc()).all();groups={};skipped=0
    for r in rows:
        benchmark=_benchmark_for(r.symbol)
        if not benchmark:skipped+=1;continue
        ss=_base_close(db,r.symbol,r.observation_date);bs=_base_close(db,benchmark,r.observation_date);sf=_forward_bars(db,r.symbol,r.observation_date,horizon_days)[:horizon_days]
        if not ss or not bs or len(sf)<horizon_days:continue
        end_day=sf[-1].bar_date;be=_base_close(db,benchmark,end_day)
        if not be:continue
        rel=(float(sf[-1].close)/ss-1)*100-(be/bs-1)*100;groups.setdefault(r.state,[]).append((rel,r.observation_date))
    states={}
    for k,v in groups.items():
        vals=[x[0] for x in v];dates=[x[1] for x in v];states[k]={"samples":len(vals),"mean_relative_return_pct":round(sum(vals)/len(vals),3),"outperformance_rate":round(sum(1 for x in vals if x>0)/len(vals),3),**_eligibility(dates,len(vals))}
    return {"horizon_days":horizon_days,"benchmark_policy":CALIBRATION_BENCHMARKS,"states":states,"skipped_non_equity_or_unmapped_rows":skipped,"model_version":ROTATION_MODEL_VERSION,"probability_policy":{"minimum_samples":MIN_PROBABILITY_SAMPLES,"minimum_distinct_dates":MIN_PROBABILITY_DATES,"minimum_span_days":MIN_PROBABILITY_SPAN_DAYS},"interpretation":"Equity sectors/themes are calibrated to the same forward end date against category-appropriate equity benchmarks. Cross-asset groups are excluded until dedicated benchmark models exist. Daily cross-sectional rows and overlapping horizons are correlated, so probability language requires both sample count and calendar depth."}


def _score_band(score:float)->str:
    if score>=85:return "85-100"
    if score>=75:return "75-84.9"
    if score>=65:return "65-74.9"
    if score>=55:return "55-64.9"
    return "<55"
def _summary(values:list[tuple[float,float,float,str]])->dict:
    rets=[x[0] for x in values];mfes=[x[1] for x in values];maes=[x[2] for x in values];dates=[x[3] for x in values]
    return {"samples":len(values),"mean_return_pct":round(sum(rets)/len(rets),3),"positive_rate":round(sum(1 for x in rets if x>0)/len(rets),3),"mean_mfe_pct":round(sum(mfes)/len(mfes),3),"mean_mae_pct":round(sum(maes)/len(maes),3),**_eligibility(dates,len(values))}
def candidate_calibration_summary(db:Session,horizon_days:int=20)->dict:
    rows=db.query(CandidateObservationV4,CandidateOutcomeV4).join(CandidateOutcomeV4,CandidateObservationV4.id==CandidateOutcomeV4.candidate_id).filter(CandidateObservationV4.model_version==CANDIDATE_MODEL_VERSION,CandidateOutcomeV4.horizon_days==horizon_days,CandidateOutcomeV4.status=="complete").all();by_band={};by_setup={}
    for c,o in rows:
        tup=(float(o.return_pct or 0),float(o.max_favorable_excursion_pct or 0),float(o.max_adverse_excursion_pct or 0),c.observation_date);by_band.setdefault(_score_band(c.funnel_score),[]).append(tup);by_setup.setdefault(c.setup_type,[]).append(tup)
    return {"horizon_days":horizon_days,"model_version":CANDIDATE_MODEL_VERSION,"by_score_band":{k:_summary(v) for k,v in by_band.items()},"by_setup_type":{k:_summary(v) for k,v in by_setup.items()},"probability_policy":{"minimum_samples":MIN_PROBABILITY_SAMPLES,"minimum_distinct_dates":MIN_PROBABILITY_DATES,"minimum_span_days":MIN_PROBABILITY_SPAN_DAYS},"interpretation":"Prospective self-evaluation of frozen first-discovery candidate observations. Same-day candidates and overlapping forward windows are correlated; probability language requires sufficient distinct dates and calendar span in addition to raw sample count."}

def capture_once()->dict:
    with _single_capture_lock() as acquired:
        if not acquired:return {"status":"skipped_lock_held"}
        db=SessionLocal()
        try:
            rotation=build_rotation_model(db,persist=False);rw=_upsert_rotation(db,rotation);funnel=build_candidate_funnel(db,rotation,limit=MAX_CANDIDATES_PER_DAY,enqueue_enrichment=False);cw=_insert_candidates_once(db,funnel);outcomes=update_candidate_outcomes(db);pruned=prune_calibration_history(db);return {"status":"ok","rotation_rows":rw,"candidate_rows":cw,"outcomes":outcomes,"pruned":pruned}
        except Exception:db.rollback();raise
        finally:db.close()
async def calibration_loop():
    await asyncio.sleep(INITIAL_CAPTURE_DELAY_SECONDS)
    while True:
        try:await asyncio.to_thread(capture_once)
        except Exception:logger.exception("V4 calibration maintenance failed")
        await asyncio.sleep(CAPTURE_SECONDS)
