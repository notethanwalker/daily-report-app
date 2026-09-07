from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

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
    rows = db.query(MarketSnapshot).order_by(MarketSnapshot.symbol, MarketSnapshot.retrieved_at.desc()).all()
    latest: dict[str, MarketSnapshot] = {}
    for row in rows:
        latest.setdefault(row.symbol.upper(), row)
    return list(latest.values())


def _registry_map(db: Session) -> dict[str, SymbolRegistry]:
    return {r.symbol.upper(): r for r in db.query(SymbolRegistry).all()}


def _williams_score(williams: float) -> float:
    # -50 => 0, -80 => 60, -100 => 100. Clamp for stability.
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
    ma100 = _f(payload.get("ma100"))
    ma50 = _f(payload.get("ma50"))
    d7 = _f(payload.get("seven_day_percent"))
    d30 = _f(payload.get("thirty_day_percent"))

    slope_proxy = None
    if ma100 not in (None, 0) and ma50 is not None:
        slope_proxy = ((ma50 / ma100) - 1.0) * 100.0
    slope_score = 50.0 if slope_proxy is None else max(0.0, min(100.0, 50.0 + slope_proxy * 12.5))

    # Until rolling distance history is persisted market-wide, use recent downside
    # momentum as a conservative approach-direction proxy. This can later be
    # replaced without changing the API contract.
    approach_proxy = None
    if d7 is not None or d30 is not None:
        approach_proxy = (d7 or 0.0) * 0.7 + (d30 or 0.0) * 0.3
    approach_score = 50.0 if approach_proxy is None else max(0.0, min(100.0, 50.0 - approach_proxy * 5.0))

    return (slope_score + approach_score) / 2.0, {
        "ma_trend_proxy": None if slope_proxy is None else round(slope_proxy, 2),
        "approach_proxy": None if approach_proxy is None else round(approach_proxy, 2),
    }


def _bucket(williams: float, ma100_distance: float, t: OpportunityThresholds = THRESHOLDS) -> str | None:
    if williams <= t.strong_williams_max and t.strong_ma100_min <= ma100_distance <= t.strong_ma100_max:
        return "strong"
    if williams <= t.weak_williams_max and t.weak_ma100_min <= ma100_distance <= t.weak_ma100_max:
        return "weak"
    if williams <= t.near_williams_max and t.near_ma100_min <= ma100_distance <= t.near_ma100_max:
        return "near"
    return None


def _is_equity_like(registry: SymbolRegistry | None, payload: dict) -> bool:
    asset = str((registry.asset_type if registry else None) or payload.get("type") or payload.get("asset_type") or "").lower()
    if not asset:
        return True
    return any(x in asset for x in ("stock", "equity", "common", "etf"))


def scan_cached_market(db: Session, include_near: bool = False, limit_per_bucket: int = 200) -> dict:
    registry = _registry_map(db)
    strong: list[dict] = []
    weak: list[dict] = []
    near: list[dict] = []
    scanned = eligible = 0
    newest = None

    for row in _latest_snapshot_rows(db):
        scanned += 1
        payload = row.payload or {}
        reg = registry.get(row.symbol.upper())
        if not _is_equity_like(reg, payload):
            continue

        williams = _f(payload.get("williams_r_14"))
        ma100_distance = _f(payload.get("price_vs_ma100_percent"))
        price = _f(payload.get("price"))
        if williams is None or ma100_distance is None or price is None:
            continue
        eligible += 1

        bucket = _bucket(williams, ma100_distance)
        if bucket is None:
            continue

        confirmation, confirmation_detail = _confirmation_score(payload)
        wscore = _williams_score(williams)
        mscore = _ma100_score(ma100_distance)
        score = 0.60 * wscore + 0.30 * mscore + 0.10 * confirmation

        item = {
            "symbol": row.symbol.upper(),
            "name": (reg.name if reg else None) or payload.get("name"),
            "sector": (reg.sector if reg else None) or payload.get("sector"),
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
            "confirmation": confirmation_detail,
            "as_of": payload.get("as_of") or row.as_of,
            "retrieved_at": row.retrieved_at.isoformat(),
            "provider": payload.get("provider") or row.provider,
            "source_url": payload.get("source_url"),
        }
        newest = row.retrieved_at if newest is None or row.retrieved_at > newest else newest
        {"strong": strong, "weak": weak, "near": near}[bucket].append(item)

    for rows in (strong, weak, near):
        rows.sort(key=lambda x: (x["score"], -x["williams_r_14"], -x["price_vs_ma100_percent"]), reverse=True)

    result = {
        "strong": strong[:limit_per_bucket],
        "weak": weak[:limit_per_bucket],
        "counts": {"cached_symbols_scanned": scanned, "technically_eligible": eligible, "strong": len(strong), "weak": len(weak)},
        "thresholds": THRESHOLDS.__dict__,
        "weights": {"williams": 60, "ma100_proximity": 30, "confirmation": 10},
        "last_cache_update": newest.isoformat() if newest else None,
        "data_strategy": "Ranks only normalized cached market snapshots. This endpoint performs zero external provider requests. Broad-universe ingestion should populate the shared snapshot/history cache in bulk, then every tab can reuse the same normalized technical state.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if include_near:
        result["near"] = near[:limit_per_bucket]
        result["counts"]["near"] = len(near)
    return result
