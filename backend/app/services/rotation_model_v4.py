from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import MarketSnapshot
from .rotation import SECTORS


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


def build_rotation_model(db: Session) -> dict:
    rows = []
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
        direction_consistency = 0
        diffs = [b-a for a,b in zip(scores, scores[1:])]
        if diffs:
            sign = 1 if delta_3 >= 0 else -1
            direction_consistency = sum(1 for x in diffs[-3:] if (x >= 0 and sign > 0) or (x <= 0 and sign < 0)) / min(3, len(diffs))
        depth = min(1.0, len(scores) / 4)
        trend_agrees = 1.0 if (level >= 0 and trend >= 0) or (level < 0 and trend < 0) else .5
        conviction = min(100.0, 25 + min(abs(level) * 8, 30) + min(abs(delta_3) * 12, 25) + direction_consistency * 10 + depth * 5 + trend_agrees * 5)
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
            "trend_context": round(trend, 2),
            "relative_volume": _f(p.get("relative_volume")),
            "observations": len(scores),
            "as_of": p.get("as_of") or latest_row.as_of,
        })
    rows.sort(key=lambda x: (x["rotation_pressure"], x["conviction"]), reverse=True)
    states = defaultdict(int)
    for row in rows:
        states[row["state"]] += 1
    return {
        "rows": rows,
        "leaders": rows[:8],
        "outflow_risk": sorted([x for x in rows if x["forward_bias"] in {"rotation_out_risk", "avoidance_bias"}], key=lambda x: x["rotation_pressure"])[:8],
        "early_rotation": sorted([x for x in rows if x["forward_bias"] in {"early_rotation_candidate", "watch_for_rotation"}], key=lambda x: x["conviction"], reverse=True)[:8],
        "state_counts": dict(states),
        "methodology": "V4 rotation pressure extends the existing 1D/7D/30D + relative-volume rotation score with change across stored daily observations and 100/200MA trend context. It classifies leadership, weakening, lagging and improving states. Forward-bias labels are heuristic transition signals, not calibrated probabilities or direct fund-flow measurements.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
