from __future__ import annotations

import asyncio
import html
import os
import re
from urllib.parse import urljoin

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


def _candidate_urls(base_url: str, text_body: str) -> list[str]:
    cleaned = html.unescape(text_body).replace("\\/", "/")
    found: list[str] = []
    patterns = [
        r'https?://[^\s"\'<>]+',
        r'(?:href|src)=["\']([^"\']+)["\']',
        r'["\'](\/[^"\']*(?:download|file|object|storage|zip)[^"\']*)["\']',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, cleaned, flags=re.I):
            value = match if isinstance(match, str) else match[0]
            value = value.strip().rstrip(",);}")
            if not value:
                continue
            url = urljoin(base_url, value)
            if url.startswith("http") and url not in found:
                found.append(url)
    def score(url: str) -> tuple[int, int]:
        low = url.lower()
        s = 0
        for term, weight in ((".zip", 100), ("download", 50), ("object", 30), ("storage", 25), ("file", 20), ("api", 10)):
            if term in low:
                s += weight
        if low.endswith(".js"):
            s -= 20
        return (-s, len(url))
    return sorted(found, key=score)


def _recover_remote_share(db) -> bool:
    share_url = (os.getenv("STOOQ_RECOVERY_SHARE_URL") or "").strip()
    if not share_url:
        return False
    ensure_tables(db)
    existing = db.execute(text("SELECT COUNT(*) FROM stooq_import_uploads WHERE status IN ('uploading','queued','importing')")).scalar() or 0
    if existing:
        return False
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/zip,application/octet-stream;q=0.9,*/*;q=0.8",
    }
    attempts = []
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, read=180.0), follow_redirects=True, headers=headers) as client:
            response = client.get(share_url)
            attempts.append({"url": str(response.url), "status": response.status_code, "content_type": response.headers.get("content-type"), "bytes": len(response.content)})
            response.raise_for_status()
            if _enqueue_bytes(db, response.content):
                _save_recovery_state(db, {"status": "queued", "source": str(response.url), "bytes": len(response.content), "attempts": attempts})
                return True
            body = response.text
            candidates = _candidate_urls(str(response.url), body)
            # Inspect likely direct links first, then JS bundles because some share pages
            # reveal their download endpoint only in client-side code.
            expanded = list(candidates[:30])
            for candidate in list(candidates[:15]):
                if not candidate.lower().split("?", 1)[0].endswith(".js"):
                    continue
                try:
                    js = client.get(candidate)
                    if js.status_code == 200 and len(js.content) < 5_000_000:
                        for nested in _candidate_urls(str(js.url), js.text):
                            if nested not in expanded:
                                expanded.append(nested)
                except Exception:
                    continue
            for candidate in expanded[:60]:
                try:
                    item = client.get(candidate)
                    attempts.append({"url": str(item.url), "status": item.status_code, "content_type": item.headers.get("content-type"), "bytes": len(item.content)})
                    if item.status_code == 200 and _enqueue_bytes(db, item.content):
                        _save_recovery_state(db, {"status": "queued", "source": str(item.url), "bytes": len(item.content), "attempts": attempts[-12:]})
                        return True
                except Exception as exc:
                    attempts.append({"url": candidate[:300], "error": str(exc)[:180]})
            _save_recovery_state(db, {"status": "not_resolved", "share_url": share_url, "candidate_count": len(expanded), "attempts": attempts[-20:]})
    except Exception as exc:
        db.rollback()
        try:
            _save_recovery_state(db, {"status": "failed", "share_url": share_url, "error": str(exc)[:500], "attempts": attempts[-10:]})
        except Exception:
            db.rollback()
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
    if payload.get("status") not in {"importing", "awaiting_reupload"} or payload.get("canonical"):
        return
    payload["status"] = "awaiting_reupload"
    payload["canonical"] = False
    payload["reason"] = "legacy Render background import was interrupted and its ephemeral archive bytes were lost; durable recovery is awaiting source bytes"
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
        except Exception:
            db.rollback()
            delay = 30
        finally:
            db.close()
        await asyncio.sleep(delay)
