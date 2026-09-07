from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any


@dataclass
class NormalizedFlowEvent:
    event_type: str
    symbol: str
    provider: str
    occurred_at: datetime
    source_url: str
    contract: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    social: dict[str, Any] = field(default_factory=dict)
    provider_score: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def canonical_symbol(self) -> str:
        return self.symbol.strip().upper()

    def fingerprint(self) -> str:
        expiration = str(self.contract.get("expiration") or "")
        strike = str(self.contract.get("strike") or "")
        side = str(self.contract.get("side") or "").lower()
        contracts = str(self.execution.get("contracts") or "")
        premium = str(self.execution.get("premium") or "")
        bucket = self.occurred_at.astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat()
        raw = "|".join([self.canonical_symbol(), expiration, strike, side, bucket, contracts, premium])
        return sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass
class FlowAnalysis:
    significance_score: float
    direction: str
    direction_confidence: float
    reasons: list[str]
    analysis_version: str = "flow-v2"


def _clip(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _ratio_score(value: float | None, baseline: float, cap: float = 100.0) -> float:
    if value is None or value <= 0 or baseline <= 0:
        return 0.0
    return min(cap, (value / baseline) * 25.0)


def score_flow_event(event: NormalizedFlowEvent, *, corroboration_count: int = 0, underlying_relative_volume: float | None = None, market_cap: float | None = None) -> FlowAnalysis:
    """Transparent significance + direction model.

    Significance is intentionally distinct from direction. Provider scores and
    social mentions can raise significance/corroboration, but do not by
    themselves make an observation bullish or bearish.
    """
    execution = event.execution
    premium = _to_float(execution.get("premium"))
    contracts = _to_float(execution.get("contracts"))
    volume = _to_float(execution.get("volume"))
    oi = _to_float(execution.get("open_interest"))
    aggression = str(execution.get("aggression") or "unknown").lower()
    trade_type = str(execution.get("trade_type") or "unknown").lower()

    size_component = max(_ratio_score(premium, 250_000.0), _ratio_score(contracts, 500.0))
    if premium and market_cap and market_cap > 0:
        pct_cap=(premium/market_cap)*100
        size_component=max(size_component,_clip(pct_cap*2500.0))
    vol_oi = (volume / oi) if volume is not None and oi not in (None, 0) else None
    vol_oi_component = _clip((vol_oi or 0.0) * 25.0)

    aggression_component = {
        "above_ask": 100.0,
        "ask": 85.0,
        "buy": 75.0,
        "mid": 45.0,
        "sell": 75.0,
        "bid": 85.0,
        "below_bid": 100.0,
    }.get(aggression, 20.0)

    persistence_component = 35.0 if trade_type == "sweep" else 20.0 if trade_type == "block" else 0.0
    corroboration_component = _clip(corroboration_count * 35.0)
    context_component = _clip(((underlying_relative_volume or 1.0) - 1.0) * 50.0) if underlying_relative_volume is not None else 0.0
    provider_component = _clip(_to_float(event.provider_score) or 0.0)

    significance = (
        0.25 * size_component
        + 0.18 * vol_oi_component
        + 0.16 * aggression_component
        + 0.12 * persistence_component
        + 0.12 * corroboration_component
        + 0.07 * context_component
        + 0.10 * provider_component
    )

    side = str(event.contract.get("side") or "").lower()
    directional_points = 0.0
    reasons: list[str] = []

    if aggression in ("ask", "above_ask", "buy"):
        directional_points += 35.0 if side == "call" else -35.0 if side == "put" else 0.0
        reasons.append(f"{side or 'option'} execution classified as buyer-initiated")
    elif aggression in ("bid", "below_bid", "sell"):
        directional_points -= 35.0 if side == "call" else -35.0 if side == "put" else 0.0
        reasons.append(f"{side or 'option'} execution classified as seller-initiated")
    elif aggression == "mid":
        reasons.append("execution near midpoint is directionally weak")

    if premium is not None:reasons.append(f"estimated premium ${premium:,.0f}")
    if vol_oi is not None:reasons.append(f"volume/open-interest ratio {vol_oi:.2f}x")
    if market_cap and premium:reasons.append(f"premium equals {(premium/market_cap)*100:.4f}% of cached market cap")
    if trade_type == "sweep":reasons.append("sweep structure increases significance, not certainty of direction")
    if corroboration_count:reasons.append(f"corroborated by {corroboration_count} additional observation(s)")
    if event.provider_score is not None:reasons.append(f"provider unusualness score {event.provider_score:.1f}")

    abs_points = abs(directional_points)
    if abs_points < 20:direction = "ambiguous"
    elif directional_points > 0:direction = "bullish"
    elif directional_points < 0:direction = "bearish"
    else:direction = "neutral"

    confidence = _clip(abs_points + min(corroboration_count * 10.0, 25.0))
    if direction == "ambiguous":
        confidence = min(confidence, 35.0)
        reasons.append("hedge/spread/closing activity cannot be excluded")

    return FlowAnalysis(significance_score=round(_clip(significance), 1),direction=direction,direction_confidence=round(confidence, 1),reasons=reasons)


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:return float(value)
    except (TypeError, ValueError):return None
