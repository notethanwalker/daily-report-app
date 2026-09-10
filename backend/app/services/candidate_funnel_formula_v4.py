from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import FeatureSnapshot, MarketSnapshot, SymbolRegistry
from .candidate_funnel_v4 import (
    DEEP_ENRICHMENT_LIMIT,
    _f,
    _latest_feature_map,
    _latest_market_map,
    _setup_type,
    _shortlist_bars,
    enqueue_deep_enrichment,
)
from .classification_v4 import blend_rotation_context
from .opportunity_convergence import evaluate_convergence_inputs
from .opportunity_formula_v4 import build_opportunity_index, formula_metadata

FORMULA_FUNNEL_MODEL_VERSION = "candidate-funnel-formula-v4.1"
SOURCE_MULTIPLIER = 4
MIN_SOURCE_ROWS = 200


def _attention_stage(item: dict) -> str:
    score = _f(item.get("formula_score"), 0)
    state = str((item.get("convergence") or {}).get("state") or "extended")
    enriched = item.get("enrichment_status") == "full"
    rotation = str(item.get("rotation_state") or "")

    if score >= 80 and state in {"approaching", "triggered"} and enriched and rotation in {"leading_accelerating", "leading_stable", "recovering"}:
        return "high_conviction"
    if score >= 70 and state in {"approaching", "triggered"}:
        return "actionable"
    if score >= 60 or state in {"watching", "approaching"}:
        return "developing"
    return "watch"


def _context_score(formula_score: float, macro_fit: float, base_buy: float, feature_ready: bool) -> float:
    """Formula remains dominant; enrichment can refine priority but cannot replace discovery."""
    base_weight = 0.80 if feature_ready else 0.90
    feature_weight = 0.10 if feature_ready else 0.0
    value = formula_score * base_weight + (50.0 + macro_fit) * 0.10 + base_buy * feature_weight
    return max(0.0, min(100.0, value))


def build_formula_candidate_funnel(
    db: Session,
    rotation: dict,
    *,
    criteria: dict | None = None,
    filters: list[dict] | None = None,
    limit: int = 50,
    enqueue_enrichment: bool = False,
) -> dict:
    source_limit = min(1000, max(MIN_SOURCE_ROWS, limit * SOURCE_MULTIPLIER))
    index = build_opportunity_index(
        db,
        criteria=criteria,
        filters=filters,
        include_etfs=False,
        limit=source_limit,
        sort_by="score",
        sort_dir="desc",
    )
    source = list(index.get("rows") or [])
    source_symbols = [row["symbol"] for row in source]
    registry = {
        x.symbol.upper(): x
        for x in db.query(SymbolRegistry).filter(SymbolRegistry.symbol.in_(source_symbols)).all()
    } if source_symbols else {}
    market_map = _latest_market_map(db, source_symbols)
    feature_map = _latest_feature_map(db, source_symbols)
    ranked: list[dict] = []

    for row in source:
        symbol = row["symbol"]
        reg = registry.get(symbol)
        market = dict(market_map.get(symbol) or {})
        feature = dict(feature_map.get(symbol) or {})
        sector = (reg.sector if reg else None) or market.get("sector") or row.get("sector")
        industry = (reg.industry if reg else None) or market.get("industry") or row.get("industry")
        themes = (reg.themes if reg else None) or market.get("themes")
        macro = blend_rotation_context(rotation, symbol, sector, industry, themes)
        pressure = _f(macro.get("rotation_pressure"))
        conviction = max(0.0, min(100.0, _f(macro.get("conviction"))))
        confidence = conviction / 100.0 if macro.get("transition_ready") else min(conviction / 100.0, 0.45)
        macro_fit = max(-15.0, min(15.0, pressure * 3.0)) * confidence
        formula_score = _f(row.get("score"))

        if feature:
            base_buy = _f(feature.get("buy_score"), 50.0)
            base_source = "persisted_opportunity_model"
            enrichment = "full"
        else:
            base_buy = 50.0
            base_source = "neutral_pending_enrichment"
            enrichment = "scanner_only"

        contextual = _context_score(formula_score, macro_fit, base_buy, bool(feature))
        raw_criteria = dict(row.get("raw_criteria") or {})
        ranked.append({
            "symbol": symbol,
            "name": row.get("name") or (reg.name if reg else None),
            "sector": sector,
            "industry": industry,
            "formula_rank": row.get("formula_rank"),
            "formula_score": round(formula_score, 2),
            "contextual_priority_score": round(contextual, 2),
            "criterion_scores": row.get("criterion_scores") or {},
            "raw_criteria": raw_criteria,
            "rotation_proxy": macro.get("dominant_proxy"),
            "rotation_proxy_basis": macro.get("basis"),
            "rotation_exposures": macro.get("exposures"),
            "rotation_components": macro.get("components"),
            "setup_type": _setup_type(macro),
            "base_buy_score": round(base_buy, 1),
            "base_buy_source": base_source,
            "rotation_pressure": round(pressure, 3),
            "rotation_state": macro.get("state"),
            "rotation_conviction": round(conviction, 1),
            "macro_confidence_factor": round(confidence, 3),
            "williams_r_14": raw_criteria.get("williams"),
            "price_vs_ma100_percent": raw_criteria.get("ma100_proximity"),
            "average_dollar_volume_20d": row.get("average_dollar_volume_20d"),
            "price": row.get("price"),
            "as_of": row.get("as_of"),
            "provider": row.get("provider"),
            "source_url": row.get("source_url"),
            "verification_status": row.get("verification_status"),
            "enrichment_status": enrichment,
            "needs_deep_enrichment": enrichment != "full",
            "_market": market,
            "_feature": feature,
            "explain": {
                "stage_1_universe": "Full cached scannable stock universe after explicit technical/liquidity eligibility and optional hard screens.",
                "stage_2_formula": f"Formula rank #{row.get('formula_rank')} at {formula_score:.1f}/100 using the active weighted criteria.",
                "stage_3_context": f"Rotation contribution is bounded and confidence-weighted ({confidence:.2f}); persisted buy score contributes only when already cached.",
                "stage_4_priority": "Formula score remains dominant. Liquidity adds no ranking bonus because it is already an eligibility gate.",
            },
        })

    ranked.sort(key=lambda x: (x["contextual_priority_score"], x["formula_score"]), reverse=True)
    short = ranked[:limit]
    bars_by_symbol = _shortlist_bars(db, [x["symbol"] for x in short])
    convergence_counts = {"extended": 0, "watching": 0, "approaching": 0, "triggered": 0, "invalidated": 0, "unavailable": 0}
    attention_counts = {"watch": 0, "developing": 0, "actionable": 0, "high_conviction": 0}

    for priority_rank, item in enumerate(short, start=1):
        item["priority_rank"] = priority_rank
        market = item.pop("_market", {})
        feature = item.pop("_feature", {})
        retrieved_at = market.pop("__retrieved_at", None)
        feature_as_of = feature.pop("__as_of", None)
        try:
            conv = evaluate_convergence_inputs(
                item["symbol"], market, feature, bars_by_symbol.get(item["symbol"], []), retrieved_at, feature_as_of
            )
            item["convergence"] = {k: conv.get(k) for k in (
                "state", "raw_state", "state_code", "convergence_score", "williams_r",
                "ma100_distance_pct", "ma200_distance_pct", "quality_score", "quality_detail",
                "confirmation_count", "confirmation_available", "confirmation_possible",
                "confirmation_evidence_ready", "price_context", "data_alignment",
                "missing_required_inputs", "as_of", "model_version", "model_config_hash", "alert_ready",
            )}
            state = str(conv.get("state") or "extended")
        except Exception as exc:
            item["convergence"] = {"state": "unavailable", "error": str(exc)[:160], "alert_ready": False}
            state = "unavailable"
        convergence_counts[state] = convergence_counts.get(state, 0) + 1
        item["attention_stage"] = _attention_stage(item)
        attention_counts[item["attention_stage"]] += 1

    deep = [x["symbol"] for x in short if x["needs_deep_enrichment"]][:DEEP_ENRICHMENT_LIMIT]
    queued = enqueue_deep_enrichment(db, deep) if enqueue_enrichment and deep else 0
    counts = index.get("counts") or {}
    return {
        "model_version": FORMULA_FUNNEL_MODEL_VERSION,
        "formula": formula_metadata(criteria, filters),
        "source_index_counts": counts,
        "source_rows_considered": len(source),
        "candidates": short,
        "attention_counts": attention_counts,
        "convergence_counts": convergence_counts,
        "deep_enrichment_symbols": deep,
        "deep_enrichment_jobs_added": queued,
        "last_cache_update": index.get("last_cache_update"),
        "stages": [
            {"name": "Universe", "input": counts.get("scannable", 0), "output": counts.get("liquidity_eligible", 0), "rule": "Cached scannable stocks with required technicals and liquidity."},
            {"name": "Hard screens", "input": counts.get("liquidity_eligible", 0), "output": counts.get("formula_complete", 0), "rule": "User-selected requirements apply before scoring and contribute no points."},
            {"name": "Formula rank", "input": counts.get("formula_complete", 0), "output": len(source), "rule": f"Take up to {source_limit} highest active-formula scores for cheap contextual evaluation."},
            {"name": "Context", "input": len(source), "output": len(short), "rule": "Formula remains dominant; bounded rotation and already-cached feature context refine priority. No provider calls."},
            {"name": "Readiness", "input": len(short), "output": attention_counts["actionable"] + attention_counts["high_conviction"], "rule": "Classify Watch → Developing → Actionable → High Conviction using formula strength plus convergence and available confirmation."},
            {"name": "Deep enrichment", "input": len(short), "output": len(deep), "rule": f"At most {DEEP_ENRICHMENT_LIMIT} finalists missing cached enrichment are eligible for an explicit enrichment request."},
        ],
        "methodology": "Formula-first candidate funnel. The active Opportunity Formula defines discovery across the full cached universe; contextual layers can refine priority but cannot redefine formula rank. Liquidity is a gate, never a bonus. Ranking itself performs zero provider calls.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
