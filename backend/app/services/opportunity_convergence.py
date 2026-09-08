from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import FeatureSnapshot, MarketSnapshot
from ..normalized_market_models import NormalizedDailyBar

MODEL_VERSION = "opportunity-convergence-v1.0"
STATE_ORDER = {"invalidated": -1, "extended": 0, "watching": 1, "approaching": 2, "triggered": 3}
MODEL_CONFIG = {
    "priority": ["Williams reset", "100MA approach from above", "fundamental/theme quality", "confirmation filters"],
    "williams_watch": -55.0,
    "williams_approach": -70.0,
    "williams_trigger": -80.0,
    "ma100_watch_max_pct": 10.0,
    "ma100_approach_range_pct": [0.0, 7.0],
    "ma100_trigger_range_pct": [-1.0, 5.0],
    "quality_approach_min": 55.0,
    "quality_trigger_min": 60.0,
    "invalid_ma100_below_pct": -5.0,
    "invalid_quality_below": 35.0,
    "minimum_confirmations": 3,
}
MODEL_CONFIG_HASH = hashlib.sha256(json.dumps(MODEL_CONFIG, sort_keys=True).encode()).hexdigest()[:12]


def _f(value, default=None):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _latest_market(db: Session, symbol: str):
    row = db.query(MarketSnapshot).filter(MarketSnapshot.symbol == symbol).order_by(MarketSnapshot.retrieved_at.desc()).first()
    if not row:
        return {}, None
    return dict(row.payload or {}), row.retrieved_at


def _latest_feature(db: Session, symbol: str):
    row = db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol == symbol).order_by(FeatureSnapshot.as_of.desc(), FeatureSnapshot.created_at.desc()).first()
    return (dict(row.payload or {}), row.as_of) if row else ({}, None)


def _bars(db: Session, symbol: str, limit: int = 90):
    return db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol == symbol).order_by(NormalizedDailyBar.bar_date.desc()).limit(limit).all()[::-1]


def _rsi14(closes: list[float]):
    if len(closes) < 15:
        return None
    gains = []
    losses = []
    for a, b in zip(closes[-15:-1], closes[-14:]):
        d = b - a
        gains.append(max(d, 0.0)); losses.append(max(-d, 0.0))
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _price_context(bars):
    closes = [float(x.close) for x in bars if x.close is not None]
    if not closes:
        return {"rsi14": None, "drawdown_60d_pct": None, "stabilizing": None, "five_day_return_pct": None, "prior_five_day_return_pct": None}
    current = closes[-1]
    peak = max(closes[-60:]) if closes[-60:] else current
    drawdown = (current / peak - 1.0) * 100 if peak else None
    rsi = _rsi14(closes)
    r5 = (current / closes[-6] - 1.0) * 100 if len(closes) >= 6 and closes[-6] else None
    prior5 = (closes[-6] / closes[-11] - 1.0) * 100 if len(closes) >= 11 and closes[-11] else None
    # Stabilization means the most recent five-day decline has decelerated versus the prior five-day window,
    # or the recent window has turned non-negative.
    stabilizing = None if r5 is None or prior5 is None else (r5 >= 0 or r5 > prior5)
    return {
        "rsi14": round(rsi, 2) if rsi is not None else None,
        "drawdown_60d_pct": round(drawdown, 2) if drawdown is not None else None,
        "stabilizing": stabilizing,
        "five_day_return_pct": round(r5, 2) if r5 is not None else None,
        "prior_five_day_return_pct": round(prior5, 2) if prior5 is not None else None,
    }


def _quality(feature: dict):
    comps = feature.get("components") if isinstance(feature.get("components"), dict) else {}
    vals = []
    # These are existing point-in-time model components; this gate intentionally does not invent future fundamentals.
    for key, weight in (("valuation", .40), ("sector", .30)):
        v = _f(comps.get(key))
        if v is not None:
            vals.append((v, weight))
    buy = _f(feature.get("buy_score"))
    if buy is not None:
        vals.append((buy, .30))
    if not vals:
        return None
    weight = sum(w for _, w in vals)
    return round(sum(v * w for v, w in vals) / weight, 2)


def evaluate_convergence(db: Session, symbol: str) -> dict:
    s = symbol.strip().upper()
    market, retrieved_at = _latest_market(db, s)
    feature, feature_as_of = _latest_feature(db, s)
    bars = _bars(db, s)
    ctx = _price_context(bars)

    wr = _f(market.get("williams_r_14"), _f(feature.get("williams_r")))
    ma100 = _f(market.get("price_vs_ma100_percent"), _f(feature.get("ma100_distance")))
    ma200 = _f(market.get("price_vs_ma200_percent"), _f(feature.get("ma200_distance")))
    rv = _f(market.get("relative_volume"), _f(feature.get("relative_volume")))
    quality = _quality(feature)

    confirmations = {
        "relative_volume": rv is not None and rv >= 1.0,
        "above_or_near_200ma": ma200 is not None and ma200 >= -5.0,
        "rsi_reset": ctx["rsi14"] is not None and 25.0 <= ctx["rsi14"] <= 55.0,
        "meaningful_drawdown": ctx["drawdown_60d_pct"] is not None and ctx["drawdown_60d_pct"] <= -5.0,
        "stabilizing": ctx["stabilizing"] is True,
    }
    available_confirmations = sum(1 for key, val in confirmations.items() if val is not None)
    confirmation_count = sum(1 for val in confirmations.values() if val is True)

    missing = [name for name, value in (("williams_r", wr), ("ma100_distance", ma100), ("quality_score", quality)) if value is None]
    invalid = (ma100 is not None and ma100 < MODEL_CONFIG["invalid_ma100_below_pct"]) or (quality is not None and quality < MODEL_CONFIG["invalid_quality_below"])
    triggered = (
        not missing and not invalid and wr <= MODEL_CONFIG["williams_trigger"]
        and MODEL_CONFIG["ma100_trigger_range_pct"][0] <= ma100 <= MODEL_CONFIG["ma100_trigger_range_pct"][1]
        and quality >= MODEL_CONFIG["quality_trigger_min"]
        and confirmation_count >= MODEL_CONFIG["minimum_confirmations"]
        and ctx["stabilizing"] is not False
    )
    approaching = (
        not missing and not invalid and wr <= MODEL_CONFIG["williams_approach"]
        and MODEL_CONFIG["ma100_approach_range_pct"][0] <= ma100 <= MODEL_CONFIG["ma100_approach_range_pct"][1]
        and quality >= MODEL_CONFIG["quality_approach_min"]
    )
    watching = not missing and not invalid and (wr <= MODEL_CONFIG["williams_watch"] or ma100 <= MODEL_CONFIG["ma100_watch_max_pct"])

    if invalid:
        state = "invalidated"
    elif triggered:
        state = "triggered"
    elif approaching:
        state = "approaching"
    elif watching:
        state = "watching"
    else:
        state = "extended"

    # 0-100 convergence score is descriptive; state gates remain authoritative.
    wr_score = 0.0 if wr is None else max(0.0, min(100.0, (-wr - 40.0) / 40.0 * 100.0))
    if ma100 is None:
        ma_score = 0.0
    elif ma100 < -5:
        ma_score = 0.0
    else:
        ma_score = max(0.0, min(100.0, 100.0 - abs(ma100 - 2.0) * 8.0))
    q_score = max(0.0, min(100.0, quality or 0.0))
    conf_score = confirmation_count / max(len(confirmations), 1) * 100.0
    score = round(wr_score * .35 + ma_score * .30 + q_score * .20 + conf_score * .15, 2)

    as_of = str(market.get("as_of") or feature_as_of or (bars[-1].bar_date if bars else ""))[:10] or None
    event_key = f"{MODEL_VERSION}:{s}:{state}:{as_of}" if state == "triggered" and as_of else None
    return {
        "symbol": s,
        "state": state,
        "state_code": STATE_ORDER[state],
        "convergence_score": score,
        "williams_r": wr,
        "ma100_distance_pct": ma100,
        "ma200_distance_pct": ma200,
        "quality_score": quality,
        "relative_volume": rv,
        "confirmations": confirmations,
        "confirmation_count": confirmation_count,
        "confirmation_total": len(confirmations),
        "price_context": ctx,
        "missing_required_inputs": missing,
        "as_of": as_of,
        "retrieved_at": retrieved_at.isoformat() if retrieved_at else None,
        "model_version": MODEL_VERSION,
        "model_config_hash": MODEL_CONFIG_HASH,
        "model_config": MODEL_CONFIG,
        "event_key": event_key,
        "alert_ready": state == "triggered",
        "interpretation": "Fundamentally/theme-attractive stock nearing a technically favorable entry. Williams reset is primary, 100MA approach from above is secondary, quality is a gate, and confirmations distinguish stabilization from an accelerating decline.",
    }
