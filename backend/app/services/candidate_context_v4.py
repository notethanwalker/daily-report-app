from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..intelligence_cache_models import SecurityIntelligenceCache
from ..models import FundamentalCache, RefreshQueueItem
from .provider_orchestrator import FRESHNESS_POLICIES, is_stale

CONTEXT_MODEL_VERSION = "candidate-context-v4.2"
NEWS_TTL = timedelta(minutes=30)
FLOW_TTL = timedelta(minutes=30)
CATALYST_TTL = timedelta(hours=12)
FUNDAMENTAL_TARGET_LIMIT = 12


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _section_state(payload: dict, section: str, ttl: timedelta, now: datetime) -> dict:
    stamp = _parse_dt((payload.get("section_retrieved_at") or {}).get(section))
    age = (now - stamp).total_seconds() if stamp else None
    return {
        "available": bool(payload.get(section)),
        "fresh": bool(stamp and age is not None and age <= ttl.total_seconds()),
        "retrieved_at": stamp.isoformat() if stamp else None,
        "age_seconds": round(age, 1) if age is not None else None,
    }


def _fundamental_state(row: FundamentalCache | None, now: datetime) -> dict:
    return {
        "available": bool(row),
        "fresh": bool(row and not is_stale(row.retrieved_at, "fundamentals", now)),
        "retrieved_at": row.retrieved_at.isoformat() if row and row.retrieved_at else None,
        "provider": row.provider if row else None,
    }


def candidate_context_map(db: Session, symbols: list[str]) -> dict[str, dict]:
    symbols = sorted({str(x).upper() for x in symbols if x})
    if not symbols:
        return {}
    now = _now()
    intel_rows = db.query(SecurityIntelligenceCache).filter(SecurityIntelligenceCache.symbol.in_(symbols)).all()
    fund_rows = db.query(FundamentalCache).filter(FundamentalCache.symbol.in_(symbols)).all()
    intel = {row.symbol.upper(): row for row in intel_rows}
    funds = {row.symbol.upper(): row for row in fund_rows}
    out: dict[str, dict] = {}
    for symbol in symbols:
        irow = intel.get(symbol)
        payload = dict(irow.payload or {}) if irow else {}
        news = dict(payload.get("news") or {})
        flow = dict(payload.get("flow") or {})
        catalysts = dict(payload.get("catalysts") or {})
        sections = {
            "news": _section_state(payload, "news", NEWS_TTL, now),
            "flow": _section_state(payload, "flow", FLOW_TTL, now),
            "catalysts": _section_state(payload, "catalysts", CATALYST_TTL, now),
            "fundamentals": _fundamental_state(funds.get(symbol), now),
        }
        articles = list(news.get("articles") or [])
        events = list(flow.get("events") or [])
        upcoming = list(catalysts.get("upcoming") or [])
        out[symbol] = {
            "model_version": CONTEXT_MODEL_VERSION,
            "sections": sections,
            "news": {
                "count": len(articles),
                "top": articles[:3],
                "provider": news.get("provider"),
            },
            "flow": {
                "kind": flow.get("kind") or "none",
                "count": len(events),
                "top": events[:3],
                "provider": flow.get("provider"),
                "note": flow.get("note"),
            },
            "catalysts": {
                "count": len(upcoming),
                "upcoming": upcoming[:4],
            },
            "cache_only": True,
        }
    return out


def _context_priority(candidate: dict) -> tuple:
    stage = str(candidate.get("attention_stage") or "watch")
    order = {"high_conviction": 4, "actionable": 3, "developing": 2, "watch": 1}
    return (order.get(stage, 0), float(candidate.get("contextual_priority_score") or 0), float(candidate.get("formula_score") or 0))


def candidate_fundamental_targets(candidates: list[dict], limit: int = FUNDAMENTAL_TARGET_LIMIT) -> list[str]:
    selected = sorted(candidates, key=_context_priority, reverse=True)
    targets: list[str] = []
    for candidate in selected:
        state = ((candidate.get("candidate_context") or {}).get("sections") or {}).get("fundamentals") or {}
        if state.get("fresh"):
            continue
        symbol = str(candidate.get("symbol") or "").upper()
        if symbol and symbol not in targets:
            targets.append(symbol)
        if len(targets) >= max(0, min(limit, FUNDAMENTAL_TARGET_LIMIT)):
            break
    return targets


def enqueue_candidate_fundamentals(db: Session, candidates: list[dict], limit: int = FUNDAMENTAL_TARGET_LIMIT) -> list[str]:
    targets = candidate_fundamental_targets(candidates, limit)
    queued: list[str] = []
    for symbol in targets:
        active = db.query(RefreshQueueItem).filter(
            RefreshQueueItem.symbol == symbol,
            RefreshQueueItem.data_class == "fundamentals",
            RefreshQueueItem.status.in_(["queued", "running"]),
        ).first()
        if active:
            continue
        db.add(RefreshQueueItem(
            symbol=symbol,
            data_class="fundamentals",
            priority=max(75, FRESHNESS_POLICIES["fundamentals"].priority),
            requested_by="opportunity_formula_funnel",
        ))
        queued.append(symbol)
    if queued:
        db.commit()
    return queued


def attach_candidate_context(db: Session, candidates: list[dict]) -> dict:
    context = candidate_context_map(db, [x.get("symbol") for x in candidates])
    coverage = {"fundamentals": 0, "news": 0, "flow": 0, "catalysts": 0}
    fresh = {"fundamentals": 0, "news": 0, "flow": 0, "catalysts": 0}
    for candidate in candidates:
        bundle = context.get(str(candidate.get("symbol") or "").upper(), {})
        candidate["candidate_context"] = bundle
        for section, state in (bundle.get("sections") or {}).items():
            if section not in coverage:
                continue
            if state.get("available"):
                coverage[section] += 1
            if state.get("fresh"):
                fresh[section] += 1
    return {
        "model_version": CONTEXT_MODEL_VERSION,
        "candidate_count": len(candidates),
        "available": coverage,
        "fresh": fresh,
        "policy": "Cache-first context only. Ranking and automatic shortlist refresh perform zero news/flow/event provider calls.",
    }
