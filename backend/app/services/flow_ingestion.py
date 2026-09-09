from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from sqlalchemy.orm import Session

from ..models import FlowEvent
from ..providers.squawkflow import SquawkFlowProvider

FLOW_RETENTION_DAYS = 30
FLOW_BATCH_LIMIT = 100


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _fingerprint(event: dict[str, Any]) -> str:
    data = event.get("data") or {}
    occurred = _parse_time(event.get("occurred_at")).astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat()
    raw = "|".join(
        str(x or "")
        for x in (
            str(event.get("symbol") or "").upper(),
            str(event.get("event_type") or "options").lower(),
            str(data.get("side") or "").lower(),
            data.get("strike"),
            data.get("expiration"),
            occurred,
            data.get("contracts"),
            data.get("premium"),
        )
    )
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def persist_flow_events(db: Session, events: list[dict[str, Any]], provider: str = "SquawkFlow") -> dict[str, Any]:
    """Persist real provider observations with bounded, deterministic dedupe.

    No synthetic observations are generated. Existing rows are identified by a
    fingerprint stored in the JSON payload, allowing repeated provider snapshots
    of the same contract/minute/aggregate to be ignored while preserving later
    changed observations for persistence analysis.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=FLOW_RETENTION_DAYS)
    recent = (
        db.query(FlowEvent)
        .filter(FlowEvent.provider == provider, FlowEvent.occurred_at >= cutoff)
        .order_by(FlowEvent.occurred_at.desc())
        .limit(5000)
        .all()
    )
    existing = {
        str((row.payload or {}).get("_fingerprint"))
        for row in recent
        if (row.payload or {}).get("_fingerprint")
    }
    inserted = 0
    skipped = 0
    for event in events or []:
        symbol = str(event.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        fp = _fingerprint(event)
        if fp in existing:
            skipped += 1
            continue
        payload = {**(event.get("data") or {}), "_fingerprint": fp}
        db.add(
            FlowEvent(
                event_type=str(event.get("event_type") or "options").lower(),
                symbol=symbol,
                provider=str(event.get("provider") or provider),
                outlier_score=float(event.get("outlier_score") or 0.0),
                source_url=str(event.get("source_url") or "https://squawkflow.com/options-flow"),
                payload=payload,
                occurred_at=_parse_time(event.get("occurred_at")),
            )
        )
        existing.add(fp)
        inserted += 1
    if inserted:
        db.commit()
    return {"inserted": inserted, "deduped": skipped, "retention_days": FLOW_RETENTION_DAYS}


def prune_flow_events(db: Session) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=FLOW_RETENTION_DAYS)
    deleted = db.query(FlowEvent).filter(FlowEvent.occurred_at < cutoff).delete(synchronize_session=False)
    if deleted:
        db.commit()
    return int(deleted or 0)


def refresh_flow_cache(db: Session, limit: int = FLOW_BATCH_LIMIT) -> dict[str, Any]:
    payload = SquawkFlowProvider().unusual_options(max(1, min(int(limit), FLOW_BATCH_LIMIT)))
    events = payload.get("events") or []
    persisted = persist_flow_events(db, events, provider=str(payload.get("provider") or "SquawkFlow"))
    pruned = prune_flow_events(db)
    return {
        "provider": payload.get("provider") or "SquawkFlow",
        "retrieved_at": payload.get("retrieved_at"),
        "events": events,
        "meta": payload.get("meta") or {},
        "usage": payload.get("usage") or {},
        "persisted": persisted,
        "pruned": pruned,
    }
