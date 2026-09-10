from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..normalized_market_models import MarketPipelineState

STATE_PREFIX = "opp_funnel_v4:"
MAX_RECENT_TRANSITIONS = 100


def _state_key(user: str, criteria: dict, filters: list[dict]) -> str:
    canonical = json.dumps(
        {"user": user, "criteria": criteria, "filters": filters},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:40]
    return f"{STATE_PREFIX}{digest}"


def _snapshot(candidates: list[dict]) -> dict[str, dict]:
    return {
        str(c.get("symbol") or "").upper(): {
            "stage": str(c.get("attention_stage") or "watch"),
            "formula_rank": c.get("formula_rank"),
            "priority_rank": c.get("priority_rank"),
            "formula_score": c.get("formula_score"),
            "contextual_priority_score": c.get("contextual_priority_score"),
        }
        for c in candidates
        if c.get("symbol")
    }


def diff_transitions(previous: dict[str, dict], current: dict[str, dict], at: str) -> list[dict]:
    transitions: list[dict] = []
    for symbol, now in current.items():
        before = previous.get(symbol)
        if before and before.get("stage") != now.get("stage"):
            transitions.append({
                "symbol": symbol,
                "from": before.get("stage"),
                "to": now.get("stage"),
                "at": at,
                "formula_rank": now.get("formula_rank"),
                "priority_rank": now.get("priority_rank"),
                "formula_score": now.get("formula_score"),
            })
    for symbol, before in previous.items():
        if symbol not in current:
            transitions.append({
                "symbol": symbol,
                "from": before.get("stage"),
                "to": "out_of_shortlist",
                "at": at,
                "formula_rank": None,
                "priority_rank": None,
                "formula_score": None,
            })
    return transitions


def record_funnel_state(
    db: Session,
    *,
    user: str,
    criteria: dict,
    filters: list[dict],
    payload: dict,
) -> dict:
    key = _state_key(user, criteria, filters)
    row = db.get(MarketPipelineState, key)
    stored = dict(row.payload or {}) if row else {}
    previous = dict(stored.get("snapshot") or {})
    current = _snapshot(list(payload.get("candidates") or []))
    at = str(payload.get("generated_at") or datetime.now(timezone.utc).isoformat())
    changes = diff_transitions(previous, current, at) if previous else []
    recent = (list(stored.get("recent_transitions") or []) + changes)[-MAX_RECENT_TRANSITIONS:]
    state = {
        "snapshot": current,
        "recent_transitions": recent,
        "last_generated_at": at,
    }
    if row:
        row.payload = state
    else:
        db.add(MarketPipelineState(key=key, payload=state))
    db.commit()
    return {
        **payload,
        "stage_transitions": changes,
        "recent_stage_transitions": list(reversed(recent[-20:])),
        "transition_tracking": {
            "persistent": True,
            "formula_scoped": True,
            "new_candidates_are_not_reported_as_stage_changes": True,
        },
    }
