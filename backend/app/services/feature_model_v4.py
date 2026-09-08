from __future__ import annotations

import asyncio
import hashlib
import json

from ..database import SessionLocal
from ..models import FeatureSnapshot, RefreshQueueItem

MODEL_VERSION = "opportunity-v3.1"
COMPONENT_WEIGHTS = {"technical": .25, "valuation": .20, "sector": .15, "flow": .15, "momentum": .15, "risk": .10}
MODEL_CONFIG_HASH = hashlib.sha256(json.dumps(COMPONENT_WEIGHTS, sort_keys=True).encode()).hexdigest()[:12]
MODEL_CUTOVER_DATE = "2026-09-08"
VERSION_MAINTENANCE_SECONDS = 15 * 60
FEATURE_MAINTENANCE_BATCH = 1000


def version_payload(payload: dict | None) -> dict:
    out = dict(payload or {})
    out.setdefault("model_version", MODEL_VERSION)
    out.setdefault("model_config_hash", MODEL_CONFIG_HASH)
    out.setdefault("model_component_weights", COMPONENT_WEIGHTS)
    return out


def presentation_payload(payload: dict | None, as_of: str | None) -> dict:
    out = dict(payload or {})
    if out.get("model_version"): return out
    if str(as_of or "")[:10] >= MODEL_CUTOVER_DATE: return version_payload(out)
    out["model_version"] = "legacy_unversioned"; out["model_config_hash"] = None
    return out


def maintain_feature_snapshots() -> dict:
    db = SessionLocal();versioned=generated=failed=0
    try:
        completed=db.query(RefreshQueueItem).filter(RefreshQueueItem.data_class=="fundamentals",RefreshQueueItem.status=="complete",RefreshQueueItem.requested_by=="v4_candidate_funnel").order_by(RefreshQueueItem.updated_at.asc()).limit(25).all()
        if completed:
            from .opportunity_model import refresh_feature
            for job in completed:
                try:
                    if refresh_feature(db,job.symbol):
                        generated+=1;job=db.get(RefreshQueueItem,job.id)
                        if job:job.requested_by="v4_candidate_funnel_completed"
                        db.commit()
                    else:
                        job.requested_by="v4_candidate_funnel_feature_failed";job.error="feature_generation:no_feature_payload";failed+=1;db.commit()
                except Exception as exc:
                    db.rollback();job=db.get(RefreshQueueItem,job.id)
                    if job:job.requested_by="v4_candidate_funnel_feature_failed";job.error=f"feature_generation:{str(exc)[:420]}";db.commit()
                    failed+=1
        rows=db.query(FeatureSnapshot).order_by(FeatureSnapshot.id.desc()).limit(FEATURE_MAINTENANCE_BATCH).all()
        for row in rows:
            if (row.payload or {}).get("model_version") or str(row.as_of or "")[:10] < MODEL_CUTOVER_DATE:continue
            row.payload=version_payload(row.payload or {});versioned+=1
        if versioned:db.commit()
        return {"generated":generated,"versioned":versioned,"failed":failed,"cutover_date":MODEL_CUTOVER_DATE}
    except Exception:
        db.rollback();return {"generated":generated,"versioned":versioned,"failed":failed+1,"cutover_date":MODEL_CUTOVER_DATE}
    finally:db.close()


async def feature_version_loop():
    while True:
        await asyncio.to_thread(maintain_feature_snapshots)
        await asyncio.sleep(VERSION_MAINTENANCE_SECONDS)
