from __future__ import annotations

from .candidate_context_v4 import candidate_context_map

CONTEXT_ALERT_KINDS={"candidate_context_changed","candidate_flow_changed"}
PORTFOLIO_BREACH_KIND="portfolio_concentration_breach"
V4_ALERT_DEFINITIONS={
    "candidate_context_changed":{"label":"Candidate context changed","scope":"ticker","unit":"state change","description":"Fires when fresh company news/catalyst/filing context changes to a materially different semantic state. Missing/stale-only transitions do not alert."},
    "candidate_flow_changed":{"label":"Flow confirmation changed","scope":"ticker","unit":"state change","description":"Fires when cached candidate flow changes between confirmation, contradiction, and mixed states after a baseline has been established."},
    "portfolio_concentration_breach":{"label":"Portfolio concentration breached","scope":"portfolio","unit":"% portfolio","description":"Fires once when the largest position crosses from below to at/above the selected portfolio-weight threshold."},
}


def candidate_context_alert_state(db,symbol:str):
    bundle=(candidate_context_map(db,[symbol]) or {}).get(str(symbol or "").upper(),{})
    evidence=bundle.get("evidence") or {};verdict=evidence.get("context_verdict") or {}
    label=str(verdict.get("label") or "insufficient");event_risk=bool(verdict.get("event_risk"))
    if label in {"stale","insufficient"} and not event_risk:
        state="unavailable"
    else:
        state=f"{label}|event_risk:{1 if event_risk else 0}"
    sections=bundle.get("sections") or {}
    stamps=[str((sections.get(k) or {}).get("retrieved_at") or "") for k in ("news","catalysts","filings")]
    return 1.0,{"state":state,"label":label,"event_risk":event_risk,"reason":verdict.get("reason"),"confidence":verdict.get("confidence"),"as_of":max(stamps) if any(stamps) else None,"cache_only":True}


def candidate_flow_alert_state(db,symbol:str):
    bundle=(candidate_context_map(db,[symbol]) or {}).get(str(symbol or "").upper(),{})
    persistent=bundle.get("persistent_flow") or {};evidence=(bundle.get("evidence") or {}).get("flow") or {}
    verdict=str(persistent.get("verdict") or evidence.get("label") or "insufficient")
    if verdict not in {"confirmation","contradiction","mixed"}:
        verdict="unavailable" if verdict in {"missing","stale","insufficient","ambiguous","none_observed"} else verdict
    section=(bundle.get("sections") or {}).get("flow") or {}
    return 1.0,{"state":verdict,"verdict":verdict,"direction":persistent.get("direction") or evidence.get("direction"),"confidence":persistent.get("confidence") or evidence.get("confidence"),"active_event_count":persistent.get("active_event_count"),"cluster_count":persistent.get("cluster_count"),"as_of":section.get("retrieved_at"),"cache_only":True}


def evaluate_candidate_context_alert(db,kind:str,symbol:str):
    if kind=="candidate_context_changed":return candidate_context_alert_state(db,symbol)
    if kind=="candidate_flow_changed":return candidate_flow_alert_state(db,symbol)
    return None,{"state":"unavailable"}
