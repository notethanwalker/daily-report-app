from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import MarketSnapshot, SymbolRegistry
from ..normalized_market_models import MarketPipelineState


@dataclass(frozen=True)
class OpportunityThresholds:
    strong_williams_max: float = -80.0
    strong_ma100_min: float = 0.0
    strong_ma100_max: float = 5.0
    weak_williams_max: float = -65.0
    weak_ma100_min: float = 0.0
    weak_ma100_max: float = 10.0
    near_williams_max: float = -55.0
    near_ma100_min: float = 0.0
    near_ma100_max: float = 15.0


THRESHOLDS = OpportunityThresholds()
MIN_PRICE = float(os.getenv("OPPORTUNITY_MIN_PRICE", "2"))
MIN_AVG_DOLLAR_VOLUME_20D = float(os.getenv("OPPORTUNITY_MIN_AVG_DOLLAR_VOLUME_20D", "5000000"))


def _f(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _latest_snapshot_rows(db: Session) -> list[MarketSnapshot]:
    latest = db.query(
        MarketSnapshot.symbol,
        func.max(MarketSnapshot.id).label("latest_id"),
    ).group_by(MarketSnapshot.symbol).subquery()
    return db.query(MarketSnapshot).join(latest, MarketSnapshot.id == latest.c.latest_id).all()


def _registry_map(db: Session) -> dict[str, SymbolRegistry]:
    return {r.symbol.upper(): r for r in db.query(SymbolRegistry).all()}


def _pipeline_state(db: Session, key: str) -> dict:
    row = db.get(MarketPipelineState, key)
    return dict(row.payload or {}) if row else {}


def _williams_score(williams: float) -> float:
    return max(0.0, min(100.0, (-50.0 - williams) * 2.0))


def _ma100_score(distance: float) -> float:
    if distance < 0:
        return 0.0
    if distance <= 1:
        return 100.0
    if distance <= 2:
        return 90.0
    if distance <= 3:
        return 80.0
    if distance <= 5:
        return 60.0
    if distance <= 8:
        return 30.0
    if distance <= 10:
        return 15.0
    return 0.0


def _confirmation_score(payload: dict) -> tuple[float, dict]:
    slope = _f(payload.get("ma100_slope_20d_percent"))
    approach = _f(payload.get("approach_velocity_100_5d"))
    slope_score = 50.0 if slope is None else max(0.0, min(100.0, 50.0 + slope * 20.0))
    approach_score = 50.0 if approach is None else max(0.0, min(100.0, 50.0 + approach * 10.0))
    confirmation = (slope_score + approach_score) / 2.0
    return confirmation, {
        "ma100_slope_20d_percent": None if slope is None else round(slope, 3),
        "approach_velocity_100_5d": None if approach is None else round(approach, 3),
        "ma_slope_score": round(slope_score, 1),
        "approach_score": round(approach_score, 1),
    }


def _bucket(williams: float, ma100_distance: float, t: OpportunityThresholds = THRESHOLDS) -> str | None:
    if williams <= t.strong_williams_max and t.strong_ma100_min <= ma100_distance <= t.strong_ma100_max:
        return "strong"
    if williams <= t.weak_williams_max and t.weak_ma100_min <= ma100_distance <= t.weak_ma100_max:
        return "weak"
    if williams <= t.near_williams_max and t.near_ma100_min <= ma100_distance <= t.near_ma100_max:
        return "near"
    return None


def _asset_type(registry: SymbolRegistry | None, payload: dict) -> str:
    return str((registry.asset_type if registry else None) or payload.get("type") or payload.get("asset_type") or "").strip().lower()


def _is_scannable(registry: SymbolRegistry | None, payload: dict, include_etfs: bool) -> bool:
    asset = _asset_type(registry, payload)
    if "etf" in asset:
        return include_etfs
    if any(x in asset for x in ("stock", "equity", "common")):
        return True
    return bool(registry and (registry.provider_ids or {}).get("universe_source") == "Nasdaq Trader" and asset != "etf")


def _registry_scannable_count(registry: dict[str, SymbolRegistry], include_etfs: bool) -> int:
    count = 0
    for reg in registry.values():
        if _is_scannable(reg, {}, include_etfs):
            count += 1
    return count


def scan_cached_market(
    db: Session,
    include_near: bool = False,
    limit_per_bucket: int = 200,
    include_etfs: bool = False,
) -> dict:
    registry = _registry_map(db)
    strong: list[dict] = []
    weak: list[dict] = []
    near: list[dict] = []
    scanned = technical_complete = eligible = 0
    etfs_excluded = liquidity_excluded = incomplete_technicals = 0
    verified = primary_only = verification_unknown = 0
    newest = None

    latest_rows = _latest_snapshot_rows(db)
    for row in latest_rows:
        payload = row.payload or {}
        reg = registry.get(row.symbol.upper())
        newest = row.retrieved_at if newest is None or row.retrieved_at > newest else newest
        asset = _asset_type(reg, payload)
        if "etf" in asset and not include_etfs:
            etfs_excluded += 1
            continue
        if not _is_scannable(reg, payload, include_etfs):
            continue
        scanned += 1
        verification_status = str(payload.get("verification_status") or "").lower()
        if verification_status in {"verified", "cross_checked", "matched"}:
            verified += 1
        elif verification_status in {"primary_only", "single_source"}:
            primary_only += 1
        else:
            verification_unknown += 1
        williams = _f(payload.get("williams_r_14"))
        ma100_distance = _f(payload.get("price_vs_ma100_percent"))
        price = _f(payload.get("price"))
        avg_dollar_volume = _f(payload.get("average_dollar_volume_20d"))
        if williams is None or ma100_distance is None or price is None:
            incomplete_technicals += 1
            continue
        technical_complete += 1
        if price < MIN_PRICE or avg_dollar_volume is None or avg_dollar_volume < MIN_AVG_DOLLAR_VOLUME_20D:
            liquidity_excluded += 1
            continue
        eligible += 1
        bucket = _bucket(williams, ma100_distance)
        if bucket is None:
            continue
        confirmation, detail = _confirmation_score(payload)
        wscore = _williams_score(williams)
        mscore = _ma100_score(ma100_distance)
        score = .60 * wscore + .30 * mscore + .10 * confirmation
        item = {
            "symbol": row.symbol.upper(),
            "name": (reg.name if reg else None) or payload.get("name"),
            "sector": (reg.sector if reg else None) or payload.get("sector"),
            "asset_type": (reg.asset_type if reg else None) or payload.get("asset_type"),
            "bucket": bucket,
            "score": round(score, 1),
            "williams_r_14": round(williams, 2),
            "price_vs_ma100_percent": round(ma100_distance, 2),
            "price": round(price, 4),
            "ma100": _f(payload.get("ma100")),
            "ma200": _f(payload.get("ma200")),
            "change_percent": _f(payload.get("change_percent")),
            "seven_day_percent": _f(payload.get("seven_day_percent")),
            "thirty_day_percent": _f(payload.get("thirty_day_percent")),
            "average_dollar_volume_20d": round(avg_dollar_volume, 2),
            "relative_volume": _f(payload.get("relative_volume")),
            "components": {
                "williams": round(wscore, 1),
                "ma100_proximity": round(mscore, 1),
                "confirmation": round(confirmation, 1),
            },
            "confirmation": detail,
            "as_of": payload.get("as_of") or row.as_of,
            "retrieved_at": row.retrieved_at.isoformat(),
            "provider": payload.get("provider") or row.provider,
            "source_url": payload.get("source_url"),
            "technical_source": payload.get("technical_source"),
            "canonical_history_source": payload.get("canonical_history_source"),
            "latest_bar_source": payload.get("latest_bar_source") or payload.get("provider") or row.provider,
            "verification_status": payload.get("verification_status") or "unknown",
        }
        {"strong": strong, "weak": weak, "near": near}[bucket].append(item)

    for rows in (strong, weak, near):
        rows.sort(key=lambda x: (x["score"], -x["williams_r_14"], -x["price_vs_ma100_percent"]), reverse=True)

    registry_scannable = _registry_scannable_count(registry, include_etfs)
    coverage_pct = round(scanned / registry_scannable * 100.0, 1) if registry_scannable else 0.0
    technical_coverage_pct = round(technical_complete / scanned * 100.0, 1) if scanned else 0.0
    stooq = _pipeline_state(db, "stooq_manual_archive")
    canonical_ready = stooq.get("status") == "ready" and bool(stooq.get("canonical"))
    broad_state = "ready" if canonical_ready and coverage_pct >= 95 else "partial"
    data_strategy = (
        "Canonical broad archive is ready. Ranking reads only the normalized/cached market layer and performs zero provider calls."
        if canonical_ready
        else "Broad archive is not canonical. Ranking is limited to symbols with valid cached market snapshots; coverage is reported explicitly and no market-wide completeness claim is made. The scan performs zero provider calls."
    )

    result = {
        "strong": strong[:limit_per_bucket],
        "weak": weak[:limit_per_bucket],
        "counts": {
            "registry_symbols": len(registry),
            "registry_scannable": registry_scannable,
            "cached_snapshot_symbols": len(latest_rows),
            "cached_symbols_scanned": scanned,
            "technical_inputs_complete": technical_complete,
            "technically_eligible": eligible,
            "incomplete_technicals": incomplete_technicals,
            "strong": len(strong),
            "weak": len(weak),
            "etfs_excluded": etfs_excluded,
            "liquidity_excluded": liquidity_excluded,
        },
        "coverage": {
            "state": broad_state,
            "market_wide_ready": broad_state == "ready",
            "cached_snapshot_coverage_percent": coverage_pct,
            "technical_coverage_percent": technical_coverage_pct,
            "registry_scannable": registry_scannable,
            "cached_scannable": scanned,
            "technical_complete": technical_complete,
            "limitation": None if broad_state == "ready" else "Results are valid for the cached subset only; the current scan must not be interpreted as complete U.S. market coverage.",
        },
        "verification": {
            "verified": verified,
            "primary_only": primary_only,
            "unknown": verification_unknown,
        },
        "archive_state": {
            "status": stooq.get("status") or "unknown",
            "canonical": bool(stooq.get("canonical")),
            "coverage_ratio": stooq.get("coverage_ratio"),
        },
        "include_etfs": include_etfs,
        "thresholds": THRESHOLDS.__dict__,
        "liquidity_filter": {
            "min_price": MIN_PRICE,
            "min_average_dollar_volume_20d": MIN_AVG_DOLLAR_VOLUME_20D,
        },
        "weights": {"williams": 60, "ma100_proximity": 30, "confirmation": 10},
        "confirmation_weights": {"ma100_slope": 5, "approach_velocity": 5},
        "last_cache_update": newest.isoformat() if newest else None,
        "data_strategy": data_strategy,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if include_near:
        result["near"] = near[:limit_per_bucket]
        result["counts"]["near"] = len(near)
    return result
