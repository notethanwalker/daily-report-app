from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from sqlalchemy import text

from ..database import SessionLocal
from ..normalized_market_models import MarketPipelineState


DEFAULT_BUDGET_BYTES = 400 * 1024 * 1024
DEFAULT_STOP_RATIO = 0.90


def _truthy(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def free_tier_mode() -> bool:
    return _truthy("FREE_TIER_DATABASE_MODE", "true")


def broad_ingest_enabled() -> bool:
    return _truthy("ENABLE_BROAD_MARKET_INGEST", "false") and not free_tier_mode()


def durable_archive_enabled() -> bool:
    return _truthy("ENABLE_DATABASE_ARCHIVE_UPLOADS", "false") and not free_tier_mode()


def storage_budget_bytes() -> int:
    return max(64 * 1024 * 1024, int(os.getenv("DATABASE_STORAGE_BUDGET_BYTES", str(DEFAULT_BUDGET_BYTES))))


def database_size_bytes(db) -> int:
    return int(db.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0)


def capacity_status(db) -> dict:
    size = database_size_bytes(db)
    budget = storage_budget_bytes()
    ratio = size / budget if budget else 1.0
    return {
        "size_bytes": size,
        "budget_bytes": budget,
        "used_ratio": round(ratio, 6),
        "writes_blocked": ratio >= float(os.getenv("DATABASE_STORAGE_STOP_RATIO", str(DEFAULT_STOP_RATIO))),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def require_bulk_capacity(db) -> dict:
    status = capacity_status(db)
    if status["writes_blocked"]:
        raise RuntimeError(
            "Database storage guard blocked a bulk write at "
            f"{status['used_ratio']:.1%} of the configured budget"
        )
    return status


def record_capacity_status() -> dict:
    db = SessionLocal()
    try:
        status = capacity_status(db)
        row = db.get(MarketPipelineState, "database_capacity")
        if row:
            row.payload = status
        else:
            db.add(MarketPipelineState(key="database_capacity", payload=status))
        db.commit()
        return status
    finally:
        db.close()


async def storage_guard_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(record_capacity_status)
        except Exception:
            pass
        await asyncio.sleep(30 * 60)
