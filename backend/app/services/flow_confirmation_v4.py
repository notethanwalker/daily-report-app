from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import FlowEvent
from .flow_pipeline import NormalizedFlowEvent, score_flow_event

FLOW_CONFIRMATION_MODEL_VERSION = "flow-confirmation-v4.1"
DEFAULT_LOOKBACK_HOURS = 72
MAX_EVENTS_PER_SYMBOL = 250
BURST_GAP_MINUTES = 120


def _utc(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _expiration(payload: dict) -> date | None:
    raw = payload.get("expiration")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except Exception:
        return None


def _active_contract(payload: dict, today: date) -> bool:
    expiry = _expiration(payload)
    return expiry is None or expiry >= today


def _contract_key(payload: dict) -> tuple[str, str, str]:
    side = str(payload.get("side") or "unknown").lower()
    strike = str(payload.get("strike") or "unknown")
    expiration = str(payload.get("expiration") or "unknown")[:10]
    return side, strike, expiration


def _to_normalized(row: FlowEvent) -> NormalizedFlowEvent:
    payload = dict(row.payload or {})
    return NormalizedFlowEvent(
        event_type=str(row.event_type or "options"),
        symbol=str(row.symbol or "").upper(),
        provider=str(row.provider or "unknown"),
        occurred_at=_utc(row.occurred_at),
        source_url=str(row.source_url or ""),
        contract={
            "side": payload.get("side"),
            "strike": payload.get("strike"),
            "expiration": payload.get("expiration"),
        },
        execution={
            "premium": payload.get("premium"),
            "contracts": payload.get("contracts"),
            "volume": payload.get("volume"),
            "open_interest": payload.get("open_interest"),
            "aggression": payload.get("aggression"),
            "trade_type": payload.get("trade_type"),
        },
        provider_score=row.outlier_score,
        raw=payload.get("raw") or {},
    )


def _burst_count(times: list[datetime]) -> tuple[int, int]:
    if not times:
        return 0, 0
    ordered = sorted(_utc(x) for x in times)
    bursts = 1
    largest = 1
    current = 1
    for previous, current_time in zip(ordered, ordered[1:]):
        if current_time - previous <= timedelta(minutes=BURST_GAP_MINUTES):
            current += 1
            largest = max(largest, current)
        else:
            bursts += 1
            current = 1
    return bursts, largest


def analyze_flow_rows(rows: list[FlowEvent], *, now: datetime | None = None) -> dict[str, Any]:
    now = _utc(now)
    today = now.date()
    active: list[FlowEvent] = []
    expired = 0
    for row in rows:
        payload = dict(row.payload or {})
        if not _active_contract(payload, today):
            expired += 1
            continue
        active.append(row)

    clusters: dict[tuple[str, str, str], list[FlowEvent]] = defaultdict(list)
    expiration_counts: Counter[str] = Counter()
    directions: list[str] = []
    analyses = []
    for row in active:
        payload = dict(row.payload or {})
        clusters[_contract_key(payload)].append(row)
        expiry = str(payload.get("expiration") or "unknown")[:10]
        expiration_counts[expiry] += 1

    for key, members in clusters.items():
        corroboration = max(0, len({str(x.provider or "unknown") for x in members}) - 1)
        for row in members:
            analysis = score_flow_event(_to_normalized(row), corroboration_count=corroboration)
            directions.append(analysis.direction)
            analyses.append((row, analysis, key))

    bull = sum(x == "bullish" for x in directions)
    bear = sum(x == "bearish" for x in directions)
    ambiguous = len(directions) - bull - bear
    directional = bull + bear
    majority = max(bull, bear)
    consistency = (majority / directional) if directional else 0.0
    dominant = "bullish" if bull > bear else "bearish" if bear > bull else "mixed" if bull and bear else "unknown"

    repeated_contracts = sum(len(items) >= 2 for items in clusters.values())
    repeated_expirations = sum(count >= 2 for expiry, count in expiration_counts.items() if expiry != "unknown")
    bursts, largest_burst = _burst_count([row.occurred_at for row in active])

    if directional >= 2 and consistency >= 0.70:
        verdict = "confirmation" if dominant == "bullish" else "contradiction"
    elif directional >= 2 and bull and bear:
        verdict = "mixed"
    elif directional == 1:
        verdict = "weak_directional"
    else:
        verdict = "insufficient"

    # Confidence is intentionally capped at medium until provider-side opening/closing
    # and spread/hedge classification is available.
    if verdict in {"confirmation", "contradiction"} and directional >= 3 and consistency >= 0.75 and (repeated_contracts or largest_burst >= 2):
        confidence = "medium"
    elif verdict in {"confirmation", "contradiction", "mixed", "weak_directional"}:
        confidence = "low"
    else:
        confidence = "none"

    cluster_rows = []
    for key, members in clusters.items():
        side, strike, expiration = key
        member_analyses = [a for row, a, k in analyses if k == key]
        cluster_directions = Counter(a.direction for a in member_analyses)
        times = sorted(_utc(x.occurred_at) for x in members)
        cluster_rows.append({
            "side": side,
            "strike": strike,
            "expiration": expiration,
            "observations": len(members),
            "providers": sorted({str(x.provider or "unknown") for x in members}),
            "direction_counts": dict(cluster_directions),
            "first_seen": times[0].isoformat() if times else None,
            "last_seen": times[-1].isoformat() if times else None,
            "max_significance": round(max((a.significance_score for a in member_analyses), default=0.0), 1),
        })
    cluster_rows.sort(key=lambda x: (x["observations"], x["max_significance"]), reverse=True)

    return {
        "model_version": FLOW_CONFIRMATION_MODEL_VERSION,
        "verdict": verdict,
        "direction": dominant,
        "confidence": confidence,
        "active_event_count": len(active),
        "expired_filtered_count": expired,
        "direction_counts": {"bullish": bull, "bearish": bear, "ambiguous": ambiguous},
        "directional_consistency": round(consistency, 3),
        "repeated_contract_count": repeated_contracts,
        "repeated_expiration_count": repeated_expirations,
        "time_burst_count": bursts,
        "largest_time_burst": largest_burst,
        "clusters": cluster_rows[:8],
        "score_effect": 0,
        "policy": "Persistent flow is confirmation context, not core alpha. Expired contracts are excluded. Premium/significance can rank observations but cannot by itself determine direction or Opportunity score. Confidence is capped at medium because hedges, spreads, rolls, and opening/closing status may be unknown.",
        "as_of": now.isoformat(),
    }


def build_flow_confirmation(db: Session, symbol: str, *, lookback_hours: int = DEFAULT_LOOKBACK_HOURS, now: datetime | None = None) -> dict[str, Any]:
    now = _utc(now)
    cutoff = now - timedelta(hours=max(1, min(int(lookback_hours), 30 * 24)))
    rows = (
        db.query(FlowEvent)
        .filter(FlowEvent.symbol == str(symbol).upper(), FlowEvent.occurred_at >= cutoff)
        .order_by(FlowEvent.occurred_at.desc())
        .limit(MAX_EVENTS_PER_SYMBOL)
        .all()
    )
    result = analyze_flow_rows(rows, now=now)
    result["symbol"] = str(symbol).upper()
    result["lookback_hours"] = int((now - cutoff).total_seconds() // 3600)
    return result
