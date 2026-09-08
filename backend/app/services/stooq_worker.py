from __future__ import annotations

import asyncio
import os
import re

import httpx
from sqlalchemy import text

from ..database import SessionLocal
from ..normalized_market_models import MarketPipelineState
from .stooq_durable_import import create_upload, ensure_tables, finalize_upload, process_batch, write_chunk
from .stooq_upload_session import UPLOAD_ROOT


def _save_recovery_state(db, payload: dict) -> None:
    row = db.get(MarketPipelineState, "stooq_remote_recovery")
    if row:
        row.payload = payload
    else:
        db.add(MarketPipelineState(key="stooq_remote_recovery", payload=payload))
    db.commit()


def _enqueue_bytes(db, raw: bytes, filename: str = "stooq_opportunities_package.zip") -> bool:
    if not raw.startswith(b"PK"):
        return False
    session = create_upload(db, filename, len(raw))
    upload_id = session["upload_id"]
    chunk_size = int(session["chunk_bytes"])
    for offset in range(0, len(raw), chunk_size):
        write_chunk(db, upload_id, offset, raw[offset:offset + chunk_size])
    finalize_upload(db, upload_id)
    return True


def _recover_remote_share(db) -> bool:
    share_url = (os.getenv("STOOQ_RECOVERY_SHARE_URL") or "").strip()
    if not share_url:
        return False
    ensure_tables(db)
    active = db.execute(text("SELECT COUNT(*) FROM stooq_import_uploads WHERE status IN ('uploading','queued','importing')")).scalar() or 0
    if active:
        return False
    match = re.search(r"/(?:ja|en/)?f/([0-9A-Za-z_-]+)", share_url)
    if not match:
        match = re.search(r"/f/([0-9A-Za-z_-]+)", share_url)
    if not match:
        _save_recovery_state(db, {"status": "failed", "error": "Could not parse firestorage share id", "share_url": share_url})
        return False
    share_id = match.group(1)
    headers = {"User-Agent": "Mozilla/5.0 Chrome/152", "Accept": "application/json,application/zip,application/octet-stream,*/*"}
    attempts = []
    with httpx.Client(timeout=httpx.Timeout(30.0, read=240.0), follow_redirects=True, headers=headers) as client:
        for api_base in ("https://api.firestorage.ai/dev/file", "https://api.firestorage.ai/prod/file"):
            try:
                listing_url = f"{api_base}/shares/{share_id}/files?maxResults=1000"
                listing = client.get(listing_url)
                attempts.append({"step": "list", "url": listing_url, "status": listing.status_code, "bytes": len(listing.content)})
                if listing.status_code != 200:
                    continue
                payload = listing.json()
                files = list(payload.get("files") or [])
                if not files:
                    continue
                files.sort(key=lambda item: (0 if str(item.get("name") or item.get("fileName") or "").lower().endswith(".zip") else 1))
                for item in files:
                    file_id = item.get("fileId") or item.get("file_id") or item.get("id")
                    filename = item.get("name") or item.get("fileName") or "stooq_opportunities_package.zip"
                    if not file_id:
                        continue
                    download_api = f"{api_base}/shares/{share_id}/files/{file_id}/download"
                    signed = client.post(download_api)
                    attempts.append({"step": "sign", "url": download_api, "status": signed.status_code, "bytes": len(signed.content), "file_id": str(file_id)})
                    if signed.status_code != 200:
                        continue
                    signed_payload = signed.json()
                    download_url = signed_payload.get("downloadUrl") or signed_payload.get("download_url") or signed_payload.get("url")
                    if not download_url:
                        continue
                    blob = client.get(download_url)
                    attempts.append({"step": "download", "status": blob.status_code, "bytes": len(blob.content), "content_type": blob.headers.get("content-type"), "file_id": str(file_id)})
                    if blob.status_code == 200 and _enqueue_bytes(db, blob.content, str(filename)):
                        _save_recovery_state(db, {
                            "status": "queued",
                            "share_id": share_id,
                            "api_base": api_base,
                            "file_id": str(file_id),
                            "filename": str(filename),
                            "bytes": len(blob.content),
                            "attempts": attempts[-12:],
                        })
                        return True
            except Exception as exc:
                db.rollback()
                attempts.append({"api_base": api_base, "error": str(exc)[:500]})
        _save_recovery_state(db, {"status": "failed", "share_id": share_id, "share_url": share_url, "attempts": attempts[-20:]})
    return False


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
    if payload.get("canonical"):
        return
    payload["status"] = "awaiting_reupload"
    payload["canonical"] = False
    payload["reason"] = "durable recovery source has not yet been queued"
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
                    recovered = await asyncio.to_thread(_recover_remote_share, db)
                if not recovered:
                    await asyncio.to_thread(_mark_awaiting_reupload, db)
                recovered_checked = True
            result = await asyncio.to_thread(process_batch, db)
            if result.get("status") == "importing":
                delay = 5
            elif result.get("status") == "ready":
                delay = 60
        except Exception as exc:
            db.rollback()
            try:
                _save_recovery_state(db, {"status": "worker_error", "error": str(exc)[:500]})
            except Exception:
                db.rollback()
            delay = 30
        finally:
            db.close()
        await asyncio.sleep(delay)
