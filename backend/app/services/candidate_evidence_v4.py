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


def classify_filings(bundle: dict, today: date | None = None) -> dict:
    state = ((bundle.get("sections") or {}).get("filings") or {})
    if not state.get("available"):
        return {"label": "missing", "urgency": "unknown", "direction": "unknown", "reason": "No SEC filing cache is available."}
    if not state.get("fresh"):
        return {"label": "stale", "urgency": "unknown", "direction": "unknown", "reason": "SEC filing cache is outside its freshness window."}
    filings = list((bundle.get("filings") or {}).get("top") or [])
    if not filings:
        return {"label": "none_recent", "urgency": "low", "direction": "neutral", "reason": "No tracked recent SEC filing is present in the fresh cache."}
    today = today or datetime.now(timezone.utc).date()
    ranked = []
    for filing in filings:
        filed = _parse_date(filing.get("filed_at"))
        if not filed:
            continue
        age = (today - filed).days
        ranked.append((age, str(filing.get("form") or ""), filing))
    if not ranked:
        return {"label": "unresolved", "urgency": "unknown", "direction": "unknown", "reason": "SEC filings are present but filing dates could not be normalized."}
    ranked.sort(key=lambda x: x[0])
    age, form, filing = ranked[0]
    if form in {"8-K", "8-K/A", "6-K"} and age <= 7:
        label, urgency = "recent_event_disclosure", "medium"
    elif form in {"10-Q", "10-Q/A", "10-K", "10-K/A", "20-F", "20-F/A"} and age <= 14:
        label, urgency = "recent_periodic_report", "medium"
    else:
        label, urgency = "recent_filing", "low"
    return {
        "label": label,
        "urgency": urgency,
        "direction": "unknown",
        "days_since": age,
        "latest": filing,
        "reason": f"Most recent tracked SEC filing is {form or 'unknown form'}, filed {age} day(s) ago. Form type alone is not directional.",
    }


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


def synthesize_context_verdict(news: dict, catalysts: dict, filings: dict | None = None) -> dict:
    """Summarize company context without translating it into alpha points."""
    filings = filings or {"label": "missing", "urgency": "unknown"}
    news_label = str(news.get("label") or "missing")
    catalyst_label = str(catalysts.get("label") or "missing")
    urgency = str(catalysts.get("urgency") or "unknown")
    filing_urgency = str(filings.get("urgency") or "unknown")

    if news_label == "potentially_positive":
        label = "supportive"
        reason = "Fresh linked news contains explicit positive event language."
    elif news_label == "potentially_negative":
        label = "contradictory"
        reason = "Fresh linked news contains explicit negative event language."
    elif news_label == "mixed":
        label = "mixed"
        reason = "Fresh linked news contains conflicting directional event language."
    elif news_label == "stale" and catalyst_label == "stale" and str(filings.get("label")) == "stale":
        label = "stale"
        reason = "News, catalyst, and filing evidence are outside their freshness windows."
    elif news_label == "missing" and catalyst_label == "missing" and str(filings.get("label")) == "missing":
        label = "insufficient"
        reason = "News, catalyst, and filing evidence are all unavailable."
    else:
        label = "neutral"
        reason = "No fresh directional company-news signal is established."

    event_risk = urgency in {"high", "medium"} or filing_urgency == "medium"
    if urgency in {"high", "medium"}:
        reason += f" A {urgency}-urgency catalyst is approaching and is treated as event risk, not directional confirmation."
    if filing_urgency == "medium":
        reason += " A recent SEC event/periodic filing is present and is treated as event information, not directional confirmation."

    return {
        "label": label,
        "event_risk": event_risk,
        "catalyst_urgency": urgency,
        "filing_urgency": filing_urgency,
        "confidence": "low" if label in {"supportive", "contradictory", "mixed"} else "none",
        "reason": reason,
        "score_effect": 0,
        "policy": "Context verdict is descriptive only and contributes zero Opportunity-score points until independently validated.",
    }


def classify_candidate_evidence(bundle: dict) -> dict:
    news = classify_news(bundle)
    catalysts = classify_catalysts(bundle)
    filings = classify_filings(bundle)
    flow = classify_flow(bundle)
    return {
        "news": news,
        "catalysts": catalysts,
        "filings": filings,
        "flow": flow,
        "context_verdict": synthesize_context_verdict(news, catalysts, filings),
        "policy": "Evidence labels are descriptive context only. They do not alter Opportunity formula scores or imply calibrated return probabilities.",
    }
