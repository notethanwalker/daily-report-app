from __future__ import annotations

import asyncio

from sqlalchemy import text

from ..database import SessionLocal
from ..normalized_market_models import MarketPipelineState
from .stooq_durable_import import create_upload, ensure_tables, finalize_upload, process_batch, write_chunk
from .stooq_upload_session import UPLOAD_ROOT


def _recover_legacy_upload(db) -> bool:
    ensure_tables(db)
    existing = db.execute(text("SELECT COUNT(*) FROM stooq_import_uploads WHERE status IN ('uploading','queued','importing')")).scalar() or 0
    if existing:
        return False
    if not UPLOAD_ROOT.exists():
        return False
    candidates = sorted(UPLOAD_ROOT.glob("*/archive.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for archive in candidates:
        try:
            size = archive.stat().st_size
            if size <= 0:
                continue
            session = create_upload(db, archive.name, size)
            upload_id = session["upload_id"]
            chunk_size = int(session["chunk_bytes"])
            offset = 0
            with open(archive, "rb") as handle:
                while True:
                    chunk = handle.read(chunk_size)
                    if not chunk:
                        break
                    write_chunk(db, upload_id, offset, chunk)
                    offset += len(chunk)
            finalize_upload(db, upload_id)
            return True
        except Exception:
            db.rollback()
    return False


def _mark_awaiting_reupload(db) -> None:
    active = db.execute(text("SELECT COUNT(*) FROM stooq_import_uploads WHERE status IN ('uploading','queued','importing')")).scalar() or 0
    if active:
        return
    row = db.get(MarketPipelineState, "stooq_manual_archive")
    if not row:
        return
    payload = dict(row.payload or {})
    if payload.get("status") != "importing" or payload.get("canonical"):
        return
    payload["status"] = "awaiting_reupload"
    payload["canonical"] = False
    payload["reason"] = "legacy Render background import was interrupted and its ephemeral archive bytes were lost; durable re-upload required"
    row.payload = payload
    db.commit()


async def stooq_import_loop() -> None:
    await asyncio.sleep(20)
    recovered_checked = False
    while True:
        db = SessionLocal()
        delay = 60
        try:
            if not recovered_checked:
                recovered = await asyncio.to_thread(_recover_legacy_upload, db)
                if not recovered:
                    await asyncio.to_thread(_mark_awaiting_reupload, db)
                recovered_checked = True
            result = await asyncio.to_thread(process_batch, db)
            if result.get("status") == "importing":
                delay = 5
            elif result.get("status") == "ready":
                delay = 60
        except Exception:
            db.rollback()
            delay = 30
        finally:
            db.close()
        await asyncio.sleep(delay)
