from __future__ import annotations

import asyncio
import hashlib
import json

from ..database import SessionLocal
from ..models import FeatureSnapshot

MODEL_VERSION = "opportunity-v3.1"
COMPONENT_WEIGHTS = {"technical": .25, "valuation": .20, "sector": .15, "flow": .15, "momentum": .15, "risk": .10}
MODEL_CONFIG_HASH = hashlib.sha256(json.dumps(COMPONENT_WEIGHTS, sort_keys=True).encode()).hexdigest()[:12]
VERSION_MAINTENANCE_SECONDS = 60 * 60


def version_payload(payload: dict | None) -> dict:
    out = dict(payload or {})
    out.setdefault("model_version", MODEL_VERSION)
    out.setdefault("model_config_hash", MODEL_CONFIG_HASH)
    out.setdefault("model_component_weights", COMPONENT_WEIGHTS)
    return out


def version_unversioned_snapshots() -> int:
    db = SessionLocal()
    changed = 0
    try:
        rows = db.query(FeatureSnapshot).all()
        for row in rows:
            payload = row.payload or {}
            if payload.get("model_version"):
                continue
            row.payload = version_payload(payload)
            changed += 1
        if changed:
            db.commit()
        return changed
    except Exception:
        db.rollback()
        return 0
    finally:
        db.close()


async def feature_version_loop():
    """Tags newly persisted feature snapshots outside read requests."""
    while True:
        await asyncio.to_thread(version_unversioned_snapshots)
        await asyncio.sleep(VERSION_MAINTENANCE_SECONDS)
