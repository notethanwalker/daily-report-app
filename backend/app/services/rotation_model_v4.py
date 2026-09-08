from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import MarketSnapshot
from ..normalized_market_models import MarketPipelineState
from .rotation import SECTORS

ROTATION_HISTORY_KEY = "v4_rotation_history"
MIN_TRANSITION_OBSERVATIONS = 4
MAX_ROTATION_HISTORY_DAYS = 400
STALE_INPUT_HOURS = 72
ROTATION_CAPTURE_SECONDS = 60 * 60


def _f(value, default=None):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _score(payload: dict) -> float:
    day = _f(payload.get("change_percent"), 0.0)
    week = _f(payload.get("seven_day_percent"), 0.0)
    month = _f(payload.get("thirty_day_percent"), 0.0)
    rv = _f(payload.get("relative_volume"), 1.0)
    score = day * .25 + week * .45 + month * .30
    if rv and rv > 1:
        score *= min(rv, 2.0)
    return score


def _daily_snapshots(db: Session, symbol: str, limit_days: int = 8) -> list[MarketSnapshot]:
    rows = db.query(MarketSnapshot).filter(MarketSnapshot.symbol == symbol).order_by(MarketSnapshot.retrieved_at.desc()).limit(160).all()
    by_day = {}
    for row in rows:
        key = str((row.payload or {}).get("as_of") or row.as_of or row.retrieved_at.date().isoformat())[:10]
        by_day.setdefault(key, row)
    return [by_day[k] for k in sorted(by_day, reverse=True)[:limit_days]][::-1]


def _state(level: float, delta: float, trend: float) -> tuple[str, str]:
    if level >= 1.0 and delta > .35:
        return "leading_accelerating", "inflow_candidate"
    if level >= 1.0 and delta < -.35:
        return "leading_weakening", "rotation_out_risk"
    if level >= 0:
        return "leading_stable", "hold_leadership"
    if level < -1.0 and delta > .35:
        return "lagging_improving", "early_rotation_candidate"
    if level < -1.0 and delta < -.35:
        return "lagging_deteriorating", "avoidance_bias"
    if trend > 0 and delta > 0:
        return "recovering", "watch_for_rotation"
    return "lagging_stable", "neutral_to_weak"


def _history_record(rows: list[dict], day: str) -> dict:
    return {
        "date": day,
        "rows": [
            {"symbol": r["symbol"], "name": r["name"], "rotation_score": r["rotation_score"], "rotation_pressure": r["rotation_pressure"], "state": r["state"], "forward_bias": r["forward_bias"], "conviction": r["conviction"], "stale_input": r["stale_input"]}
            for r in rows
        ],
    }


def _persist_history(db: Session, rows: list[dict], generated_at: str) -> bool:
    day = generated_at[:10]
    state = db.get(MarketPipelineState, ROTATION_HISTORY_KEY)
    payload = dict(state.payload or {}) if state else {}
    history = list(payload.get("daily") or [])
    record = _history_record(rows, day)
    previous_today = next((x for x in history if x.get("date") == day), None)
    if previous_today == record and payload.get("methodology_version") == "rotation-v4.2":
        return False
    history = [x for x in history if x.get("date") != day]
    history.append(record)
    history = sorted(history, key=lambda x: x.get("date", ""))[-MAX_ROTATION_HISTORY_DAYS:]
    payload.update({"daily": history, "latest_date": day, "methodology_version": "rotation-v4.2"})
    if state:
        state.payload = payload
    else:
        db.add(MarketPipelineState(key=ROTATION_HISTORY_KEY, payload=payload))
    db.commit()
    return True


def _age_hours(dt: datetime, now: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def _observation_age_hours(row: MarketSnapshot, payload: dict, now: datetime) -> float:
    """Use the older of retrieval freshness and provider observation freshness.
    This prevents re-fetching an old bar from making stale market state look fresh."""
    ages = [_age_hours(row.retrieved_at, now)]
    raw = str(payload.get("as_of") or row.as_of or "").strip()
    if raw:
        try:
            text = raw.replace("Z", "+00:00")
            if len(text) == 10:
                observed = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
            else:
                observed = datetime.fromisoformat(text)
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                else:
                    observed = observed.astimezone(timezone.utc)
            ages.append(_age_hours(observed, now))
        except ValueError:
            pass
    return max(ages)


def build_rotation_model(db: Session, persist: bool = False) -> dict:
    rows = []
    now = datetime.now(timezone.utc)
    for symbol, name in SECTORS.items():
        history = _daily_snapshots(db, symbol)
        if not history:
            continue
        scores = [_score(r.payload or {}) for r in history]
        latest_row = history[-1]
        p = latest_row.payload or {}
        level = scores[-1]
        prev = scores[-2] if len(scores) >= 2 else level
        old = scores[-4] if len(scores) >= 4 else scores[0]
        delta_1 = level - prev
        delta_3 = level - old
        trend = ((_f(p.get("price_vs_ma100_percent"), 0.0) or 0.0) + (_f(p.get("price_vs_ma200_percent"), 0.0) or 0.0)) / 2
        state, forward_bias = _state(level, delta_3, trend)
        diffs = [b-a for a,b in zip(scores, scores[1:])]
        direction_consistency = 0.0
        if diffs:
            sign = 1 if delta_3 >= 0 else -1
            direction_consistency = sum(1 for x in diffs[-3:] if (x >= 0 and sign > 0) or (x <= 0 and sign < 0)) / min(3, len(diffs))
        trend_agrees = 1.0 if (level >= 0 and trend >= 0) or (level < 0 and trend < 0) else .5
        raw_conviction = min(100.0, 25 + min(abs(level) * 8, 30) + min(abs(delta_3) * 12, 25) + direction_consistency * 10 + trend_agrees * 5)
        history_quality = min(1.0, len(scores) / 8.0)
        conviction = raw_conviction * (0.45 + 0.55 * history_quality)
        transition_ready = len(scores) >= MIN_TRANSITION_OBSERVATIONS
        data_age_hours = _observation_age_hours(latest_row, p, now)
        stale_input = data_age_hours > STALE_INPUT_HOURS
        if not transition_ready:
            conviction = min(conviction, 45.0)
            if forward_bias not in {"hold_leadership", "neutral_to_weak"}:
                forward_bias = "insufficient_history"
        if stale_input:
            conviction = min(conviction, 35.0)
            forward_bias = "stale_input"
        pressure = level + delta_3 * 1.25
        rows.append({
            "symbol": symbol,
            "name": name,
            "rotation_score": round(level, 3),
            "delta_1_observation": round(delta_1, 3),
            "delta_3_observations": round(delta_3, 3),
            "rotation_pressure": round(pressure, 3),
            "state": state,
            "forward_bias": forward_bias,
            "conviction": round(conviction, 1),
            "transition_ready": transition_ready,
            "history_quality": round(history_quality, 2),
            "data_age_hours": round(data_age_hours, 1),
            "stale_input": stale_input,
            "trend_context": round(trend, 2),
            "relative_volume": _f(p.get("relative_volume")),
            "observations": len(scores),
            "as_of": p.get("as_of") or latest_row.as_of,
        })
    rows.sort(key=lambda x: (x["rotation_pressure"], x["conviction"]), reverse=True)
    states = defaultdict(int)
    for row in rows:
        states[row["state"]] += 1
    generated_at = now.isoformat()
    persisted = _persist_history(db, rows, generated_at) if persist and rows else False
    return {
        "rows": rows,
        "leaders": rows[:8],
        "outflow_risk": sorted([x for x in rows if x["forward_bias"] in {"rotation_out_risk", "avoidance_bias"}], key=lambda x: x["rotation_pressure"])[:8],
        "early_rotation": sorted([x for x in rows if x["forward_bias"] in {"early_rotation_candidate", "watch_for_rotation"}], key=lambda x: x["conviction"], reverse=True)[:8],
        "state_counts": dict(states),
        "history_persisted_this_call": persisted,
        "history_policy": {"minimum_transition_observations": MIN_TRANSITION_OBSERVATIONS, "canonical_daily_history_key": ROTATION_HISTORY_KEY, "max_days": MAX_ROTATION_HISTORY_DAYS, "stale_input_hours": STALE_INPUT_HOURS, "capture_seconds": ROTATION_CAPTURE_SECONDS, "write_policy": "background upsert only when today's computed record changes"},
        "methodology": "V4 rotation pressure extends the existing 1D/7D/30D + relative-volume score with stored-observation change and 100/200MA trend context. Sparse or stale histories are confidence-capped and cannot emit actionable transition labels. Freshness uses both provider observation time and retrieval time. Canonical daily state records are persisted by a background capture loop rather than by UI reads.",
        "generated_at": generated_at,
    }


async def rotation_snapshot_loop():
    """Hourly, bounded, idempotent capture for future rotation calibration."""
    while True:
        db = SessionLocal()
        try:
            build_rotation_model(db, persist=True)
        except Exception:
            db.rollback()
        finally:
            db.close()
        await asyncio.sleep(ROTATION_CAPTURE_SECONDS)
