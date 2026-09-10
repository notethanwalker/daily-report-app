from __future__ import annotations

from typing import Any

DECISION_CARD_MODEL_VERSION = "decision-card-v4.1"


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _add_unique(items: list[str], value: str | None) -> None:
    if value and value not in items:
        items.append(value)


def _data_quality(candidate: dict) -> dict[str, Any]:
    context = candidate.get("candidate_context") or {}
    sections = context.get("sections") or {}
    states = {}
    available = fresh = 0
    tracked = ("fundamentals", "news", "catalysts", "filings", "flow")
    for key in tracked:
        state = sections.get(key) or {}
        if state.get("available"):
            available += 1
        if state.get("fresh"):
            fresh += 1
        states[key] = "fresh" if state.get("fresh") else "stale" if state.get("available") else "missing"
    verification = str(candidate.get("verification_status") or "unknown")
    feature = str(candidate.get("feature_context_status") or "missing")
    completeness = available / len(tracked)
    freshness = fresh / len(tracked)
    if verification in {"verified", "cross_checked", "matched"} and feature == "available" and freshness >= .8:
        label = "strong"
    elif feature == "available" and completeness >= .6:
        label = "moderate"
    else:
        label = "limited"
    return {
        "label": label,
        "verification": verification,
        "feature_context": feature,
        "section_states": states,
        "context_completeness": round(completeness, 2),
        "context_freshness": round(freshness, 2),
    }


def build_decision_card(candidate: dict) -> dict[str, Any]:
    context = candidate.get("candidate_context") or {}
    evidence = context.get("evidence") or {}
    verdict = evidence.get("context_verdict") or {}
    flow = context.get("persistent_flow") or {}
    fit = candidate.get("portfolio_fit") or {}
    convergence = candidate.get("convergence") or {}
    raw = candidate.get("raw_criteria") or {}

    bull: list[str] = []
    bear: list[str] = []
    blockers: list[str] = []
    upgrades: list[str] = []
    downgrades: list[str] = []
    invalidation: list[str] = []

    score = _num(candidate.get("formula_score"), 0.0) or 0.0
    wr = _num(candidate.get("williams_r_14"))
    ma100 = _num(candidate.get("price_vs_ma100_percent"))
    ma_slope = _num(raw.get("ma100_slope"))
    approach = _num(raw.get("approach_velocity"))
    state = str(convergence.get("state") or "unavailable")

    if score >= 80:
        _add_unique(bull, f"Active formula ranks this as a strong setup ({score:.1f}/100; rank #{candidate.get('formula_rank')}).")
    elif score >= 70:
        _add_unique(bull, f"Active formula identifies a favorable setup ({score:.1f}/100).")
    else:
        _add_unique(bear, f"Active formula score is not yet strong ({score:.1f}/100).")

    if wr is not None:
        if wr <= -80:
            _add_unique(bull, f"Williams %R is deeply oversold at {wr:.1f}, matching the default mean-reversion hypothesis.")
        elif wr > -55:
            _add_unique(bear, f"Williams %R at {wr:.1f} is outside the preferred oversold zone.")
            _add_unique(upgrades, "Williams %R moves back into the selected oversold region.")

    if ma100 is not None:
        if 0 <= ma100 <= 5:
            _add_unique(bull, f"Price is {ma100:.1f}% above the 100-day average, inside the preferred support-approach zone.")
        elif ma100 < 0:
            _add_unique(bear, f"Price is {abs(ma100):.1f}% below the 100-day average rather than approaching it from above.")
            _add_unique(invalidation, "Price remains below the 100-day average and the selected setup requires support from above.")
        elif ma100 > 10:
            _add_unique(bear, f"Price remains {ma100:.1f}% above the 100-day average; support proximity is weak.")
            _add_unique(upgrades, "Price approaches the 100-day average from above without structural deterioration.")

    if ma_slope is not None:
        if ma_slope > 0:
            _add_unique(bull, "The 100-day average is rising, supporting the interpretation of a pullback within an established trend.")
        elif ma_slope < 0:
            _add_unique(bear, "The 100-day average is declining, weakening the support/mean-reversion interpretation.")
            _add_unique(downgrades, "100-day trend slope continues to deteriorate.")

    if approach is not None and approach > 0:
        _add_unique(bull, "Approach velocity indicates price is moving toward the selected support condition.")

    if state in {"approaching", "triggered"}:
        _add_unique(bull, f"Convergence state is {state}, so the technical setup is near or at its defined trigger.")
    elif state == "invalidated":
        _add_unique(blockers, "Technical convergence state is invalidated.")
        _add_unique(invalidation, "The convergence model remains invalidated until its required conditions reset.")
    elif state in {"extended", "unavailable"}:
        _add_unique(blockers, f"Convergence state is {state}; the setup is not currently trigger-ready.")
        _add_unique(upgrades, "Convergence advances to Approaching or Triggered with aligned data.")

    # Persistent flow is decision-relevant confirming/contradicting evidence. Evaluate it
    # before lower-priority regime/context prose so it cannot be silently dropped by the
    # bounded bull/bear lists on evidence-rich candidates.
    flow_verdict = str(flow.get("verdict") or "insufficient")
    flow_conf = str(flow.get("confidence") or "none")
    if flow_verdict == "confirmation":
        _add_unique(bull, f"Persistent options flow is bullish confirmation at {flow_conf} confidence.")
    elif flow_verdict == "contradiction":
        _add_unique(bear, f"Persistent options flow contradicts the long setup at {flow_conf} confidence.")
        if flow_conf == "medium":
            _add_unique(blockers, "Medium-confidence bearish persistent flow blocks High Conviction status.")
    elif flow_verdict == "mixed":
        _add_unique(blockers, "Persistent flow is mixed and should not be used as confirmation.")

    rotation = str(candidate.get("rotation_state") or "unknown")
    if rotation in {"leading_accelerating", "leading_stable", "recovering"}:
        _add_unique(bull, f"Rotation backdrop is {rotation.replace('_', ' ')}, providing supportive regime context.")
    elif rotation in {"weakening", "lagging", "outflow_risk"}:
        _add_unique(bear, f"Rotation backdrop is {rotation.replace('_', ' ')}, opposing the setup.")
        _add_unique(upgrades, "Sector/theme rotation stabilizes or turns supportive.")

    context_label = str(verdict.get("label") or "insufficient")
    if context_label == "supportive":
        _add_unique(bull, "Fresh company-specific news context is supportive, with low-confidence directional classification.")
    elif context_label == "contradictory":
        _add_unique(bear, "Fresh company-specific news context is contradictory to the long setup.")
        _add_unique(downgrades, "Negative company-specific news is corroborated by subsequent disclosures or fundamentals.")
    elif context_label in {"stale", "insufficient"}:
        _add_unique(blockers, f"Company context is {context_label}; do not infer confirmation from missing evidence.")

    if verdict.get("event_risk"):
        _add_unique(bear, "A near-term catalyst or recent filing creates elevated event risk; this is not directional confirmation.")

    if fit.get("available"):
        fit_score = _num(fit.get("score"))
        if fit_score is not None and fit_score >= 70:
            _add_unique(bull, f"Portfolio Fit is favorable ({fit_score:.1f}/100), but remains an experimental diversification measure rather than alpha.")
        elif fit_score is not None and fit_score < 40:
            _add_unique(bear, f"Portfolio Fit is weak ({fit_score:.1f}/100), indicating concentration/correlation cost despite the asset setup.")
            _add_unique(blockers, "Portfolio concentration/correlation makes this less attractive as an incremental position than its standalone setup implies.")

    if candidate.get("decision_warning"):
        _add_unique(blockers, str(candidate["decision_warning"]))

    _add_unique(downgrades, "Formula score materially deteriorates or the stock exits the selected hard-screen conditions.")
    _add_unique(downgrades, "Convergence transitions to Invalidated.")
    _add_unique(upgrades, "Formula rank and score improve while data quality remains stable or improves.")
    _add_unique(invalidation, "Any user-selected hard filter ceases to be satisfied.")

    quality = _data_quality(candidate)
    if quality["label"] == "limited":
        _add_unique(blockers, "Data quality/context coverage is limited; confidence should remain constrained until missing inputs are refreshed.")

    return {
        "model_version": DECISION_CARD_MODEL_VERSION,
        "symbol": candidate.get("symbol"),
        "attention_stage": candidate.get("attention_stage"),
        "asset_opportunity": {"score": candidate.get("formula_score"), "rank": candidate.get("formula_rank")},
        "portfolio_fit": {"score": fit.get("score"), "rank": candidate.get("portfolio_adjusted_rank"), "confidence": fit.get("confidence"), "status": fit.get("status")},
        "context_verdict": verdict,
        "flow_confirmation": candidate.get("flow_confirmation") or {"verdict": flow_verdict, "direction": flow.get("direction"), "confidence": flow_conf, "score_effect": 0},
        "data_quality": quality,
        "bull_case": bull[:8],
        "bear_case": bear[:8],
        "blockers": blockers[:8],
        "invalidation": invalidation[:6],
        "upgrade_triggers": upgrades[:6],
        "downgrade_triggers": downgrades[:6],
        "policy": "Decision Card is a transparent synthesis layer. It creates no additional master score and does not convert contextual evidence into calibrated return probabilities.",
    }


def attach_decision_cards(candidates: list[dict]) -> None:
    for candidate in candidates:
        candidate["decision_card"] = build_decision_card(candidate)
