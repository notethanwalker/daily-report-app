from __future__ import annotations

from datetime import datetime, timezone
from statistics import median

from sqlalchemy.orm import Session

from ..models import FundamentalCache, SymbolRegistry
from ..v4_models import FundamentalAssessmentSnapshotV4
from .fundamental_assessment_v4 import MODEL_VERSION, assess_fundamentals


def _num(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def persist_assessment_snapshot(db: Session, symbol: str, fundamental_payload: dict, *, commit: bool = False) -> dict:
    symbol = str(symbol or "").upper()
    assessment = assess_fundamentals(fundamental_payload)
    observation_date = datetime.now(timezone.utc).date().isoformat()
    row = db.query(FundamentalAssessmentSnapshotV4).filter(
        FundamentalAssessmentSnapshotV4.symbol == symbol,
        FundamentalAssessmentSnapshotV4.observation_date == observation_date,
        FundamentalAssessmentSnapshotV4.model_version == MODEL_VERSION,
    ).first()
    payload = {
        "assessment": assessment,
        "fundamental_source": fundamental_payload.get("provider"),
        "fundamental_retrieved_at": fundamental_payload.get("retrieved_at"),
        "source_url": fundamental_payload.get("source_url"),
    }
    if row:
        row.quality_score = assessment.get("quality_score")
        row.valuation_score = assessment.get("valuation_score")
        row.anomaly = str(assessment.get("anomaly") or "neutral")
        row.payload = payload
    else:
        row = FundamentalAssessmentSnapshotV4(
            symbol=symbol,
            observation_date=observation_date,
            quality_score=assessment.get("quality_score"),
            valuation_score=assessment.get("valuation_score"),
            anomaly=str(assessment.get("anomaly") or "neutral"),
            payload=payload,
            model_version=MODEL_VERSION,
        )
        db.add(row)
    if commit:
        db.commit()
    return assessment


def assessment_history(db: Session, symbol: str, limit: int = 365) -> dict:
    rows = db.query(FundamentalAssessmentSnapshotV4).filter(
        FundamentalAssessmentSnapshotV4.symbol == str(symbol).upper(),
        FundamentalAssessmentSnapshotV4.model_version == MODEL_VERSION,
    ).order_by(FundamentalAssessmentSnapshotV4.observation_date.desc()).limit(max(1, min(limit, 1000))).all()
    history = [{
        "date": row.observation_date,
        "quality_score": row.quality_score,
        "valuation_score": row.valuation_score,
        "anomaly": row.anomaly,
    } for row in reversed(rows)]
    return {
        "available": len(history) >= 2,
        "observations": len(history),
        "history": history,
        "first_observation": history[0]["date"] if history else None,
        "latest_observation": history[-1]["date"] if history else None,
        "policy": "Historical assessment uses only stored point-in-time daily snapshots accumulated by V4. No historical valuation is reconstructed from today's fundamentals.",
    }


def _percentile(value: float | None, values: list[float]) -> float | None:
    if value is None or not values:
        return None
    below = sum(1 for x in values if x < value)
    equal = sum(1 for x in values if x == value)
    return round((below + 0.5 * equal) / len(values) * 100.0, 1)


def peer_context(db: Session, symbol: str, assessment: dict | None = None) -> dict:
    symbol = str(symbol or "").upper()
    registry = db.get(SymbolRegistry, symbol)
    target_cache = db.get(FundamentalCache, symbol)
    target_assessment = assessment or (assess_fundamentals(target_cache.payload or {}) if target_cache else {})
    if not registry:
        return {"available": False, "peer_count": 0, "basis": None, "policy": "Peer comparison requires SymbolRegistry sector/industry metadata and cached fundamentals."}

    candidates = db.query(SymbolRegistry).filter(SymbolRegistry.symbol != symbol).all()
    same_industry = [r for r in candidates if registry.industry and r.industry == registry.industry]
    same_sector = [r for r in candidates if registry.sector and r.sector == registry.sector]
    peers = same_industry if len(same_industry) >= 5 else same_sector
    basis = "industry" if len(same_industry) >= 5 else "sector" if peers else None
    if not peers:
        return {"available": False, "peer_count": 0, "basis": None, "policy": "No cached comparable peer group is available."}

    peer_symbols = [r.symbol for r in peers]
    caches = {r.symbol: r for r in db.query(FundamentalCache).filter(FundamentalCache.symbol.in_(peer_symbols)).all()}
    rows = []
    for peer in peers:
        cache = caches.get(peer.symbol)
        if not cache:
            continue
        a = assess_fundamentals(cache.payload or {})
        rows.append({
            "symbol": peer.symbol,
            "quality_score": _num(a.get("quality_score")),
            "valuation_score": _num(a.get("valuation_score")),
            "pe_ratio": _num((cache.payload or {}).get("pe_ratio")) if (a.get("valuation_applicability") or {}).get("pe_meaningful") else None,
            "price_to_sales_ratio": _num((cache.payload or {}).get("price_to_sales_ratio")),
        })

    q_values = [x["quality_score"] for x in rows if x["quality_score"] is not None]
    v_values = [x["valuation_score"] for x in rows if x["valuation_score"] is not None]
    pe_values = [x["pe_ratio"] for x in rows if x["pe_ratio"] is not None]
    ps_values = [x["price_to_sales_ratio"] for x in rows if x["price_to_sales_ratio"] is not None]
    target_inputs = target_assessment.get("inputs") or {}
    target_pe = _num(target_inputs.get("pe_ratio")) if (target_assessment.get("valuation_applicability") or {}).get("pe_meaningful") else None
    target_ps = _num(target_inputs.get("price_to_sales_ratio"))
    tq = _num(target_assessment.get("quality_score")); tv = _num(target_assessment.get("valuation_score"))

    return {
        "available": len(rows) >= 3,
        "basis": basis,
        "peer_count": len(rows),
        "quality_percentile": _percentile(tq, q_values),
        "valuation_quality_percentile": _percentile(tv, v_values),
        "pe_percentile": _percentile(target_pe, pe_values),
        "price_to_sales_percentile": _percentile(target_ps, ps_values),
        "peer_medians": {
            "quality_score": round(median(q_values), 1) if q_values else None,
            "valuation_score": round(median(v_values), 1) if v_values else None,
            "pe_ratio": round(median(pe_values), 2) if pe_values else None,
            "price_to_sales_ratio": round(median(ps_values), 2) if ps_values else None,
        },
        "policy": "Peer context is cross-sectional and cache-only. Higher quality/valuation-quality percentile is better; raw P/E and P/S percentiles are descriptive and lower multiples are not automatically better.",
    }


def build_fundamental_context(db: Session, symbol: str, fundamental_payload: dict) -> dict:
    assessment = assess_fundamentals(fundamental_payload)
    return {
        "assessment": assessment,
        "peer_context": peer_context(db, symbol, assessment),
        "history": assessment_history(db, symbol),
    }
