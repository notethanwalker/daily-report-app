from __future__ import annotations

from datetime import date, datetime, timezone

POSITIVE_TERMS = (
    "beats estimates", "beat estimates", "raises guidance", "raised guidance", "upgrade", "upgraded",
    "wins contract", "won contract", "approval", "approved", "record revenue", "record sales",
)
NEGATIVE_TERMS = (
    "misses estimates", "missed estimates", "cuts guidance", "cut guidance", "downgrade", "downgraded",
    "investigation", "subpoena", "offering", "bankruptcy", "default", "recall",
)


def _parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def classify_news(bundle: dict) -> dict:
    state = ((bundle.get("sections") or {}).get("news") or {})
    if not state.get("available"):
        return {"label": "missing", "direction": "unknown", "confidence": "none", "reason": "No linked-news cache is available."}
    if not state.get("fresh"):
        return {"label": "stale", "direction": "unknown", "confidence": "none", "reason": "Linked-news cache is outside its freshness window."}
    articles = list((bundle.get("news") or {}).get("top") or [])
    if not articles:
        return {"label": "noise", "direction": "neutral", "confidence": "low", "reason": "Fresh search returned no linked articles for this candidate."}
    positive = negative = 0
    matched = []
    for article in articles:
        title = str(article.get("title") or "").lower()
        p = [term for term in POSITIVE_TERMS if term in title]
        n = [term for term in NEGATIVE_TERMS if term in title]
        if p:
            positive += 1
            matched.extend(p[:1])
        if n:
            negative += 1
            matched.extend(n[:1])
    if positive and not negative:
        return {"label": "potentially_positive", "direction": "bullish", "confidence": "low", "reason": f"Explicit positive event language found in {positive} linked headline(s).", "matched_terms": matched[:4]}
    if negative and not positive:
        return {"label": "potentially_negative", "direction": "bearish", "confidence": "low", "reason": f"Explicit negative event language found in {negative} linked headline(s).", "matched_terms": matched[:4]}
    if positive and negative:
        return {"label": "mixed", "direction": "mixed", "confidence": "low", "reason": "Fresh linked headlines contain both positive and negative event language.", "matched_terms": matched[:4]}
    return {"label": "neutral", "direction": "unknown", "confidence": "low", "reason": "News is linked and fresh, but no strong directional event language was detected."}


def classify_catalysts(bundle: dict, today: date | None = None) -> dict:
    state = ((bundle.get("sections") or {}).get("catalysts") or {})
    if not state.get("available"):
        return {"label": "missing", "urgency": "unknown", "reason": "No catalyst cache is available."}
    if not state.get("fresh"):
        return {"label": "stale", "urgency": "unknown", "reason": "Catalyst cache is outside its freshness window."}
    upcoming = list((bundle.get("catalysts") or {}).get("upcoming") or [])
    if not upcoming:
        return {"label": "none_known", "urgency": "low", "reason": "No upcoming cached company catalyst is currently known."}
    today = today or datetime.now(timezone.utc).date()
    ranked = []
    for event in upcoming:
        d = _parse_date(event.get("date"))
        if not d:
            continue
        days = (d - today).days
        impact = str(event.get("impact") or "low").lower()
        ranked.append((days, impact, event))
    if not ranked:
        return {"label": "unresolved", "urgency": "unknown", "reason": "Catalysts are present but their dates could not be normalized."}
    ranked.sort(key=lambda x: x[0])
    days, impact, event = ranked[0]
    if days <= 7 and impact == "high":
        urgency = "high"
    elif days <= 14 or impact in {"high", "medium"}:
        urgency = "medium"
    else:
        urgency = "low"
    return {"label": "upcoming", "urgency": urgency, "days_until": days, "next": event, "reason": f"Nearest cached catalyst is {days} day(s) away with {impact} stated impact."}


def _flow_direction(event: dict) -> str:
    data = dict(event.get("data") or {})
    explicit = str(data.get("direction") or "").lower()
    if explicit in {"bullish", "bearish"}:
        return explicit
    side = str(data.get("side") or "").lower()
    aggression = str(data.get("aggression") or "").lower()
    buyer = aggression in {"buy", "ask", "above_ask"}
    seller = aggression in {"sell", "bid", "below_bid"}
    if side == "call" and buyer:
        return "bullish"
    if side == "put" and buyer:
        return "bearish"
    if side == "call" and seller:
        return "bearish"
    if side == "put" and seller:
        return "bullish"
    return "ambiguous"


def classify_flow(bundle: dict) -> dict:
    state = ((bundle.get("sections") or {}).get("flow") or {})
    if not state.get("available"):
        return {"label": "missing", "direction": "unknown", "confidence": "none", "reason": "No flow/options cache is available."}
    if not state.get("fresh"):
        return {"label": "stale", "direction": "unknown", "confidence": "none", "reason": "Flow/options cache is outside its freshness window."}
    events = list((bundle.get("flow") or {}).get("top") or [])
    if not events:
        return {"label": "none_observed", "direction": "neutral", "confidence": "low", "reason": "Fresh cache contains no qualifying flow observation for this candidate."}
    directions = [_flow_direction(event) for event in events]
    bull = sum(x == "bullish" for x in directions)
    bear = sum(x == "bearish" for x in directions)
    if bull >= 2 and bear == 0:
        return {"label": "confirmation", "direction": "bullish", "confidence": "medium", "reason": f"{bull} recent observations independently classify as bullish; hedging/closing activity can still not be excluded."}
    if bear >= 2 and bull == 0:
        return {"label": "contradiction", "direction": "bearish", "confidence": "medium", "reason": f"{bear} recent observations independently classify as bearish; hedging/closing activity can still not be excluded."}
    if bull or bear:
        return {"label": "mixed", "direction": "mixed" if bull and bear else "weak", "confidence": "low", "reason": "Directional evidence is present but lacks consistent corroboration."}
    return {"label": "ambiguous", "direction": "unknown", "confidence": "low", "reason": "Observed options activity is not directionally interpretable from the cached execution fields."}


def classify_candidate_evidence(bundle: dict) -> dict:
    return {
        "news": classify_news(bundle),
        "catalysts": classify_catalysts(bundle),
        "flow": classify_flow(bundle),
        "policy": "Evidence labels are descriptive context only. They do not alter Opportunity formula scores or imply calibrated return probabilities.",
    }
