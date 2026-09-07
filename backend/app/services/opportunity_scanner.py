from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import MarketSnapshot, SymbolRegistry


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
    """10% confirmation = 5% true 100MA slope + 5% true approach velocity."""
    slope = _f(payload.get("ma100_slope_20d_percent"))
    approach = _f(payload.get("approach_velocity_100_5d"))

    # A roughly +2.5% 20-session rise in the 100MA reaches full trend credit;
    # an equivalent decline reaches zero. Missing evidence is neutral, not positive.
    slope_score = 50.0 if slope is None else max(0.0, min(100.0, 50.0 + slope * 20.0))
    # Positive approach means distance-to-MA contracted over the last five sessions.
    # +/-5 percentage points spans the scoring range.
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
    # Nasdaq Trader registry membership is acceptable only when it is not explicitly an ETF.
    return bool(registry and (registry.provider_ids or {}).get("universe_source") == "Nasdaq Trader" and asset != "etf")


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
    scanned = eligible = 0
    etfs_excluded = 0
    newest = None

    for row in _latest_snapshot_rows(db):
        payload = row.payload or {}
        reg = registry.get(row.symbol.upper())
        asset = _asset_type(reg, payload)
        if "etf" in asset and not include_etfs:
            etfs_excluded += 1
            continue
        if not _is_scannable(reg, payload, include_etfs):
            continue
        scanned += 1
        williams = _f(payload.get("williams_r_14"))
        ma100_distance = _f(payload.get("price_vs_ma100_percent"))
        price = _f(payload.get("price"))
        if williams is None or ma100_distance is None or price is None:
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
        }
        newest = row.retrieved_at if newest is None or row.retrieved_at > newest else newest
        {"strong": strong, "weak": weak, "near": near}[bucket].append(item)

    for rows in (strong, weak, near):
        rows.sort(key=lambda x: (x["score"], -x["williams_r_14"], -x["price_vs_ma100_percent"]), reverse=True)

    result = {
        "strong": strong[:limit_per_bucket],
        "weak": weak[:limit_per_bucket],
        "counts": {
            "cached_symbols_scanned": scanned,
            "technically_eligible": eligible,
            "strong": len(strong),
            "weak": len(weak),
            "etfs_excluded": etfs_excluded,
        },
        "include_etfs": include_etfs,
        "thresholds": THRESHOLDS.__dict__,
        "weights": {"williams": 60, "ma100_proximity": 30, "confirmation": 10},
        "confirmation_weights": {"ma100_slope": 5, "approach_velocity": 5},
        "last_cache_update": newest.isoformat() if newest else None,
        "data_strategy": "Ranks one latest normalized snapshot per U.S. stock by default. ETFs are opt-in. Ranking performs zero provider calls; technicals come from canonical normalized OHLCV.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if include_near:
        result["near"] = near[:limit_per_bucket]
        result["counts"]["near"] = len(near)
    return result
