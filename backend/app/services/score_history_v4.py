from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy.orm import Session

from ..models import FeatureSnapshot

MODEL_VERSION = "opportunity-v3.1"
COMPONENT_WEIGHTS = {"technical": .25, "valuation": .20, "sector": .15, "flow": .15, "momentum": .15, "risk": .10}
MODEL_CONFIG_HASH = hashlib.sha256(json.dumps(COMPONENT_WEIGHTS, sort_keys=True).encode()).hexdigest()[:12]


def _f(v, default=None):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _snapshot_version(payload: dict) -> dict:
    return {
        "model_version": payload.get("model_version") or "legacy_unversioned",
        "model_config_hash": payload.get("model_config_hash"),
    }


def _component_changes(cur: dict, prev: dict) -> list[dict]:
    c = cur.get("components") or {}
    p = prev.get("components") or {}
    out = []
    for key in sorted(set(c) | set(p)):
        now = _f(c.get(key)); old = _f(p.get(key))
        if now is None:
            continue
        delta = None if old is None else now - old
        weight = COMPONENT_WEIGHTS.get(key)
        contribution_delta = None if delta is None or weight is None else delta * weight
        out.append({
            "component": key,
            "value": round(now, 2),
            "previous": None if old is None else round(old, 2),
            "delta": None if delta is None else round(delta, 2),
            "weight": weight,
            "buy_score_contribution_delta": None if contribution_delta is None else round(contribution_delta, 3),
        })
    return sorted(out, key=lambda x: abs(x.get("buy_score_contribution_delta") or 0), reverse=True)


def _drivers(cur: dict, prev: dict) -> list[dict]:
    drivers = []
    fields = [
        ("williams_r", "Williams %R", "more negative = more oversold"),
        ("ma100_distance", "100MA distance", "closer to 0 from above improves the intended setup"),
        ("ma200_distance", "200MA distance", "trend/support context"),
        ("return_7d", "7-day return", "short-term momentum"),
        ("return_30d", "30-day return", "intermediate momentum"),
        ("relative_volume", "relative volume", "participation/confirmation"),
        ("sector_score", "sector score", "macro/rotation context"),
        ("bullish_flow", "bullish flow", "stored options-flow context"),
        ("bearish_flow", "bearish flow", "stored options-flow context"),
    ]
    for key, label, meaning in fields:
        now = _f(cur.get(key)); old = _f(prev.get(key))
        if now is None:
            continue
        delta = None if old is None else now-old
        drivers.append({"field": key, "label": label, "value": round(now, 3), "previous": None if old is None else round(old, 3), "delta": None if delta is None else round(delta, 3), "meaning": meaning})
    return sorted(drivers, key=lambda x: abs(x.get("delta") or 0), reverse=True)


def build_score_history(db: Session, symbol: str, limit: int = 90) -> dict:
    s = symbol.strip().upper()
    rows = db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol == s).order_by(FeatureSnapshot.as_of.desc(), FeatureSnapshot.created_at.desc()).limit(limit).all()
    chronological = list(reversed(rows))
    history = []
    for row in chronological:
        p = row.payload or {}
        history.append({
            "as_of": row.as_of,
            "buy_score": _f(p.get("buy_score")),
            "sell_score": _f(p.get("sell_score")),
            "components": p.get("components") or {},
            "williams_r": _f(p.get("williams_r")),
            "ma100_distance": _f(p.get("ma100_distance")),
            "sector_score": _f(p.get("sector_score")),
            **_snapshot_version(p),
        })
    latest = rows[0].payload if rows else {}
    previous = rows[1].payload if len(rows) > 1 else {}
    buy_now = _f(latest.get("buy_score")); buy_prev = _f(previous.get("buy_score"))
    change = None if buy_now is None or buy_prev is None else buy_now-buy_prev
    components = _component_changes(latest, previous)
    positive = [x for x in components if (x.get("buy_score_contribution_delta") or 0) > 0][:3]
    negative = [x for x in components if (x.get("buy_score_contribution_delta") or 0) < 0][:3]
    version_changed = bool(rows and len(rows) > 1 and _snapshot_version(latest) != _snapshot_version(previous))
    attributed = sum(x.get("buy_score_contribution_delta") or 0 for x in components)
    attribution_gap = None if change is None else change-attributed
    return {
        "symbol": s,
        "history": history,
        "latest": history[-1] if history else None,
        "previous": history[-2] if len(history) >= 2 else None,
        "buy_score_change": None if change is None else round(change, 2),
        "component_changes": components,
        "largest_positive_drivers": positive,
        "largest_negative_drivers": negative,
        "raw_driver_changes": _drivers(latest, previous),
        "attributed_score_change": None if change is None else round(attributed, 3),
        "attribution_gap": None if attribution_gap is None else round(attribution_gap, 3),
        "model_version_changed": version_changed,
        "current_model_spec": {"model_version": MODEL_VERSION, "model_config_hash": MODEL_CONFIG_HASH, "component_weights": COMPONENT_WEIGHTS},
        "explanation": "Point-in-time snapshots are compared without future-data recomputation. Weighted component deltas provide exact attribution when both snapshots use the same formula. Raw inputs are supporting evidence, not direct causal attribution. Legacy snapshots are explicitly marked unversioned.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
