from __future__ import annotations

WILLIAMS_OVERSOLD_THRESHOLD = -80.0
MA100_APPROACH_MAX_PCT = 5.0


def williams_state(market: dict):
    raw = market.get("williams_r_14")
    if raw is None:
        return None, {"state": "unavailable", "as_of": market.get("as_of"), "williams_r": None}
    value = float(raw)
    state = "oversold" if value <= WILLIAMS_OVERSOLD_THRESHOLD else "recovered"
    return value, {"state": state, "as_of": market.get("as_of"), "williams_r": value, "threshold": WILLIAMS_OVERSOLD_THRESHOLD}


def ma100_approach_state(market: dict):
    raw = market.get("price_vs_ma100_percent")
    if raw is None:
        return None, {"state": "unavailable", "as_of": market.get("as_of"), "signed_distance": None}
    value = float(raw)
    if value < 0:
        state = "below"
    elif value <= MA100_APPROACH_MAX_PCT:
        state = "approaching"
    else:
        state = "extended"
    return value, {"state": state, "as_of": market.get("as_of"), "signed_distance": value, "approach_max_pct": MA100_APPROACH_MAX_PCT}


def combined_technical_state(market: dict):
    wr = market.get("williams_r_14")
    dist = market.get("price_vs_ma100_percent")
    if wr is None or dist is None:
        return None, {"state": "unavailable", "as_of": market.get("as_of"), "williams_r": wr, "ma100_distance": dist}
    wr = float(wr)
    dist = float(dist)
    triggered = wr <= WILLIAMS_OVERSOLD_THRESHOLD and 0 <= dist <= MA100_APPROACH_MAX_PCT
    return (1.0 if triggered else 0.0), {
        "state": "triggered" if triggered else "watching",
        "as_of": market.get("as_of"),
        "williams_r": wr,
        "ma100_distance": dist,
        "williams_threshold": WILLIAMS_OVERSOLD_THRESHOLD,
        "ma100_max_pct": MA100_APPROACH_MAX_PCT,
    }


def transition_entered(kind: str, previous: str | None, current: str, meta: dict | None = None) -> bool:
    meta = meta or {}
    if kind == "opportunity_convergence":
        return current == "triggered" and previous != "triggered" and bool(meta.get("alert_ready"))
    if kind == "williams_oversold_entry":
        return current == "oversold" and previous is not None and previous != "oversold"
    if kind == "williams_oversold_recovery":
        return current == "recovered" and previous == "oversold"
    if kind == "ma100_approach_from_above":
        return current == "approaching" and previous == "extended"
    if kind == "williams_ma100_trigger":
        return current == "triggered" and previous is not None and previous != "triggered"
    if kind == "opportunity_invalidated":
        return current == "invalidated" and previous is not None and previous != "invalidated"
    if kind == "opportunity_formula_score":
        return current == "at_or_above" and previous == "below"
    if kind == "opportunity_formula_rank":
        return current == "inside" and previous == "outside"
    return False
