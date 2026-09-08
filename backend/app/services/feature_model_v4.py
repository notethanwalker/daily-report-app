from __future__ import annotations

import asyncio
import hashlib
import json

from ..database import SessionLocal
from ..models import FeatureSnapshot, RefreshQueueItem

MODEL_VERSION = "opportunity-v3.1"
COMPONENT_WEIGHTS = {"technical": .25, "valuation": .20, "sector": .15, "flow": .15, "momentum": .15, "risk": .10}
MODEL_CONFIG_HASH = hashlib.sha256(json.dumps(COMPONENT_WEIGHTS, sort_keys=True).encode()).hexdigest()[:12]
VERSION_MAINTENANCE_SECONDS = 15 * 60


def version_payload(payload: dict | None) -> dict:
    out = dict(payload or {})
    out.setdefault("model_version", MODEL_VERSION)
    out.setdefault("model_config_hash", MODEL_CONFIG_HASH)
    out.setdefault("model_component_weights", COMPONENT_WEIGHTS)
    return out


def maintain_feature_snapshots() -> dict:
    db = SessionLocal()
    versioned = generated = 0
    try:
        # Fundamentals requested by the v4 shortlist are only useful to the
        # opportunity layer once a richer FeatureSnapshot is generated. The
        # lazy import avoids a module-cycle during app startup.
        completed = db.query(RefreshQueueItem).filter(
            RefreshQueueItem.data_class == "fundamentals",
            RefreshQueueItem.status == "complete",
            RefreshQueueItem.requested_by == "v4_candidate_funnel",
        ).order_by(RefreshQueueItem.updated_at.asc()).limit(25).all()
        if completed:
            from ..routers.intelligence import _refresh_feature
            for job in completed:
                try:
                    if _refresh_feature(db, job.symbol):
                        generated += 1
                        job.requested_by = "v4_candidate_funnel_completed"
                        db.commit()
                except Exception as exc:
                    db.rollback()
                    job = db.get(RefreshQueueItem, job.id)
                    if job:
                        job.error = f"feature_generation:{str(exc)[:420]}"
                        db.commit()

        rows = db.query(FeatureSnapshot).filter(~FeatureSnapshot.payload.has_key("model_version")).limit(1000).all()  # type: ignore[attr-defined]
        for row in rows:
            row.payload = version_payload(row.payload or {})
            versioned += 1
        if versioned:
            db.commit()
        return {"generated": generated, "versioned": versioned}
    except Exception:
        db.rollback()
        # JSON has_key support differs across SQLite/Postgres. Fall back to a
        # portable bounded scan if the dialect cannot express the predicate.
        try:
            rows = db.query(FeatureSnapshot).order_by(FeatureSnapshot.id.desc()).limit(1000).all()
            for row in rows:
                if (row.payload or {}).get("model_version"):
                    continue
                row.payload = version_payload(row.payload or {})
                versioned += 1
            if versioned:
                db.commit()
        except Exception:
            db.rollback()
        return {"generated": generated, "versioned": versioned}
    finally:
        db.close()


async def feature_version_loop():
    """Completes v4 shortlist enrichment and versions snapshots off the read path."""
    while True:
        await asyncio.to_thread(maintain_feature_snapshots)
        await asyncio.sleep(VERSION_MAINTENANCE_SECONDS)
