from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import FeatureSnapshot, MarketSnapshot, SymbolRegistry
from .opportunity_scanner import scan_cached_market


def _f(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _latest_feature(db: Session, symbol: str) -> dict:
    row = db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol == symbol).order_by(FeatureSnapshot.as_of.desc(), FeatureSnapshot.created_at.desc()).first()
    return dict(row.payload or {}) if row else {}


def _latest_market(db: Session, symbol: str) -> dict:
    row = db.query(MarketSnapshot).filter(MarketSnapshot.symbol == symbol).order_by(MarketSnapshot.retrieved_at.desc()).first()
    return dict(row.payload or {}) if row else {}


def build_candidate_funnel(db: Session, rotation: dict, limit: int = 50) -> dict:
    scan = scan_cached_market(db, include_near=True, limit_per_bucket=max(limit * 4, 200), include_etfs=False)
    source_rows = []
    for bucket, base_bonus in (("strong", 8.0), ("weak", 4.0), ("near", 0.0)):
        for row in scan.get(bucket, []):
            source_rows.append((row, base_bonus))

    rotation_by_name = {str(x.get("name") or ""): x for x in rotation.get("rows", [])}
    registry = {x.symbol.upper(): x for x in db.query(SymbolRegistry).all()}
    ranked = []
    for row, bucket_bonus in source_rows:
        symbol = row["symbol"]
        reg = registry.get(symbol)
        market = _latest_market(db, symbol)
        feature = _latest_feature(db, symbol)
        sector = (reg.sector if reg else None) or market.get("sector") or row.get("sector")
        macro = rotation_by_name.get(str(sector)) or {}
        rotation_pressure = _f(macro.get("rotation_pressure"), 0.0)
        conviction = _f(macro.get("conviction"), 50.0)
        macro_fit = max(-15.0, min(15.0, rotation_pressure * 3.0))
        base_buy = _f(feature.get("buy_score"), row.get("score") or 0.0)
        technical = _f(row.get("score"), 0.0)
        liquidity = _f(row.get("average_dollar_volume_20d"), 0.0)
        liquidity_score = min(5.0, max(0.0, liquidity / 100_000_000 * 5.0))
        final_score = technical * .55 + base_buy * .25 + (50 + macro_fit) * .15 + liquidity_score + bucket_bonus
        ranked.append({
            "symbol": symbol,
            "name": row.get("name") or (reg.name if reg else None),
            "sector": sector,
            "bucket": row.get("bucket"),
            "funnel_score": round(final_score, 2),
            "technical_score": round(technical, 1),
            "base_buy_score": round(base_buy, 1),
            "rotation_pressure": round(rotation_pressure, 3),
            "rotation_state": macro.get("state"),
            "rotation_conviction": round(conviction, 1),
            "williams_r_14": row.get("williams_r_14"),
            "price_vs_ma100_percent": row.get("price_vs_ma100_percent"),
            "average_dollar_volume_20d": row.get("average_dollar_volume_20d"),
            "price": row.get("price"),
            "as_of": row.get("as_of"),
            "provider": row.get("provider"),
            "explain": {
                "stage_1_universe": "Broad cached stock universe after price/liquidity filters",
                "stage_2_technical": f"{row.get('bucket')} Williams/100MA setup",
                "stage_3_macro": macro.get("state") or "sector unavailable",
                "stage_4_score": "Technical setup remains dominant; existing buy score and sector rotation refine ranking.",
            },
        })
    ranked.sort(key=lambda x: x["funnel_score"], reverse=True)
    return {
        "stages": [
            {"name": "Universe", "input": scan.get("counts", {}).get("cached_symbols_scanned", 0), "output": scan.get("counts", {}).get("technically_eligible", 0), "rule": "Cached equities only; minimum price and average-dollar-volume filters."},
            {"name": "Technical setup", "input": scan.get("counts", {}).get("technically_eligible", 0), "output": len(source_rows), "rule": "Williams %R + approach to 100MA, preserving strong/weak/near buckets."},
            {"name": "Macro fit", "input": len(source_rows), "output": len(source_rows), "rule": "Attach sector rotation pressure/state without discarding technically strong counter-rotation candidates."},
            {"name": "Rank", "input": len(source_rows), "output": min(limit, len(ranked)), "rule": "55% scanner technical score, 25% existing buy score, 15% macro context, plus liquidity and setup-tier bonuses."},
        ],
        "candidates": ranked[:limit],
        "source_scan_counts": scan.get("counts", {}),
        "methodology": "The funnel is intentionally candidate-first and cache-first. It narrows the broad universe using the existing Williams/100MA scanner before applying richer scoring, which avoids brute-force provider calls across thousands of random tickers.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
