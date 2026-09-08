from __future__ import annotations

import io
import json
import os
import uuid
import zipfile
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import MarketSnapshot
from ..providers.stooq import symbol_key
from .market_data_pipeline import (
    NORMALIZED_HISTORY_DAYS,
    _alias_maps,
    _nasdaq_registry,
    _snapshot_from_rows,
    _upsert_bar_payloads,
    _set_state,
    prune_market_snapshots,
)

CANONICAL_STATE_KEY = "stooq_manual_archive"
COMPACT_FORMAT = "daily-report-stooq-opportunities-v1"
DEFAULT_CHUNK_BYTES = int(os.getenv("STOOQ_DURABLE_CHUNK_BYTES", str(3 * 1024 * 1024)))
DEFAULT_BATCH_SYMBOLS = int(os.getenv("STOOQ_DURABLE_BATCH_SYMBOLS", "500"))
BAR_UPSERT_BATCH = int(os.getenv("STOOQ_DURABLE_BAR_BATCH", "5000"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_tables(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS stooq_import_uploads (
            upload_id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            total_bytes BIGINT NOT NULL,
            received_bytes BIGINT NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            cursor INTEGER NOT NULL DEFAULT 0,
            matched INTEGER NOT NULL DEFAULT 0,
            snapshots_written INTEGER NOT NULL DEFAULT 0,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS stooq_import_chunks (
            upload_id TEXT NOT NULL REFERENCES stooq_import_uploads(upload_id) ON DELETE CASCADE,
            chunk_offset BIGINT NOT NULL,
            chunk_bytes BYTEA NOT NULL,
            PRIMARY KEY (upload_id, chunk_offset)
        )
    """))
    db.commit()


def create_upload(db: Session, filename: str, total_bytes: int) -> dict:
    ensure_tables(db)
    if total_bytes <= 0 or total_bytes > 2 * 1024 * 1024 * 1024:
        raise ValueError("Invalid Stooq package size")
    upload_id = uuid.uuid4().hex
    db.execute(text("""
        INSERT INTO stooq_import_uploads(upload_id, filename, total_bytes, status, metadata)
        VALUES (:upload_id, :filename, :total_bytes, 'uploading', '{}')
    """), {"upload_id": upload_id, "filename": filename, "total_bytes": int(total_bytes)})
    db.commit()
    return {"upload_id": upload_id, "chunk_bytes": DEFAULT_CHUNK_BYTES, "total_bytes": int(total_bytes), "status": "uploading"}


def write_chunk(db: Session, upload_id: str, offset: int, body: bytes) -> dict:
    ensure_tables(db)
    row = db.execute(text("SELECT total_bytes, status FROM stooq_import_uploads WHERE upload_id=:id"), {"id": upload_id}).mappings().first()
    if not row:
        raise FileNotFoundError("Unknown durable Stooq upload")
    if row["status"] != "uploading":
        raise ValueError("Durable Stooq upload is not accepting chunks")
    total = int(row["total_bytes"])
    if offset < 0 or not body or offset + len(body) > total:
        raise ValueError("Invalid Stooq chunk range")
    db.execute(text("""
        INSERT INTO stooq_import_chunks(upload_id, chunk_offset, chunk_bytes)
        VALUES (:id, :offset, :body)
        ON CONFLICT (upload_id, chunk_offset)
        DO UPDATE SET chunk_bytes=EXCLUDED.chunk_bytes
    """), {"id": upload_id, "offset": int(offset), "body": body})
    received = db.execute(text("SELECT COALESCE(SUM(OCTET_LENGTH(chunk_bytes)),0) FROM stooq_import_chunks WHERE upload_id=:id"), {"id": upload_id}).scalar() or 0
    db.execute(text("UPDATE stooq_import_uploads SET received_bytes=:received, updated_at=NOW() WHERE upload_id=:id"), {"received": int(received), "id": upload_id})
    db.commit()
    return {"upload_id": upload_id, "received_bytes": int(received), "total_bytes": total, "status": "uploading"}


def _package_bytes(db: Session, upload_id: str) -> bytes:
    parts = db.execute(text("SELECT chunk_offset, chunk_bytes FROM stooq_import_chunks WHERE upload_id=:id ORDER BY chunk_offset"), {"id": upload_id}).all()
    if not parts:
        raise FileNotFoundError("No durable Stooq package bytes found")
    expected = 0
    out = bytearray()
    for offset, data in parts:
        if int(offset) != expected:
            raise ValueError(f"Stooq package has a gap at byte {expected}")
        raw = bytes(data)
        out.extend(raw)
        expected += len(raw)
    return bytes(out)


def finalize_upload(db: Session, upload_id: str) -> dict:
    ensure_tables(db)
    row = db.execute(text("SELECT * FROM stooq_import_uploads WHERE upload_id=:id"), {"id": upload_id}).mappings().first()
    if not row:
        raise FileNotFoundError("Unknown durable Stooq upload")
    if int(row["received_bytes"]) != int(row["total_bytes"]):
        raise ValueError(f"Archive upload is incomplete: {row['received_bytes']} of {row['total_bytes']} bytes received")
    package = _package_bytes(db, upload_id)
    with zipfile.ZipFile(io.BytesIO(package)) as zf:
        if "manifest.json" not in zf.namelist() or "symbols.ndjson" not in zf.namelist():
            raise ValueError("Durable importer requires the compact Stooq Opportunities package")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if manifest.get("format") != COMPACT_FORMAT:
            raise ValueError("Unsupported Stooq compact package format")
    metadata = {
        "format": manifest.get("format"),
        "symbols": int(manifest.get("symbols") or 0),
        "source_archive_sha256": manifest.get("source_archive_sha256"),
        "archive_latest_bar_date": manifest.get("archive_latest_bar_date"),
        "archive_history_start_date": manifest.get("archive_history_start_date"),
        "finalized_at": _now(),
    }
    db.execute(text("""
        UPDATE stooq_import_uploads
        SET status='queued', cursor=0, matched=0, snapshots_written=0, metadata=:metadata, updated_at=NOW()
        WHERE upload_id=:id
    """), {"metadata": json.dumps(metadata, separators=(",", ":")), "id": upload_id})
    db.commit()
    _set_state(db, CANONICAL_STATE_KEY, {
        "status": "queued",
        "canonical": False,
        "provider": "Stooq",
        "archive_name": row["filename"],
        "package_format": COMPACT_FORMAT,
        "package_symbols": metadata["symbols"],
        "seen": 0,
        "matched": 0,
        "snapshots_written": 0,
        "durable_upload_id": upload_id,
        "updated_at": _now(),
    })
    return {"upload_id": upload_id, "status": "queued", "metadata": metadata}


def status(db: Session, upload_id: str | None = None) -> dict:
    ensure_tables(db)
    if upload_id:
        row = db.execute(text("SELECT * FROM stooq_import_uploads WHERE upload_id=:id"), {"id": upload_id}).mappings().first()
    else:
        row = db.execute(text("SELECT * FROM stooq_import_uploads ORDER BY created_at DESC LIMIT 1")).mappings().first()
    if not row:
        raise FileNotFoundError("No durable Stooq import found")
    out = dict(row)
    out["metadata"] = json.loads(out.get("metadata") or "{}")
    for key in ("created_at", "updated_at"):
        if out.get(key) is not None:
            out[key] = out[key].isoformat()
    return out


def _iter_records(package: bytes, start: int, limit: int):
    with zipfile.ZipFile(io.BytesIO(package)) as zf, zf.open("symbols.ndjson") as raw:
        yielded = 0
        index = 0
        for raw_line in raw:
            line = raw_line.strip()
            if not line:
                continue
            data = json.loads(line)
            rows = data.get("rows") or []
            if not data.get("symbol") or len(rows) < 120:
                continue
            if index < start:
                index += 1
                continue
            if yielded >= limit:
                return
            yielded += 1
            index += 1
            yield index, data


def _bar_payloads(data: dict, provider: str, source_url: str) -> list[dict]:
    out = []
    for row in (data.get("rows") or [])[-NORMALIZED_HISTORY_DAYS:]:
        close = row.get("close")
        dt = str(row.get("date") or "")[:10]
        if not dt or close is None:
            continue
        out.append({
            "symbol": data["symbol"].upper(),
            "bar_date": dt,
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": close,
            "volume": row.get("volume") or 0.0,
            "provider": provider,
            "source_url": source_url,
        })
    return out


def process_batch(db: Session, batch_symbols: int | None = None) -> dict:
    ensure_tables(db)
    row = db.execute(text("""
        SELECT * FROM stooq_import_uploads
        WHERE status IN ('queued','importing')
        ORDER BY created_at DESC LIMIT 1
        FOR UPDATE SKIP LOCKED
    """)).mappings().first()
    if not row:
        return {"status": "idle", "message": "No queued durable Stooq import"}
    upload_id = row["upload_id"]
    cursor = int(row["cursor"] or 0)
    matched_total = int(row["matched"] or 0)
    snapshots_total = int(row["snapshots_written"] or 0)
    metadata = json.loads(row["metadata"] or "{}")
    package_symbols = int(metadata.get("symbols") or 0)
    limit = max(1, min(int(batch_symbols or DEFAULT_BATCH_SYMBOLS), 2000))
    db.execute(text("UPDATE stooq_import_uploads SET status='importing', updated_at=NOW() WHERE upload_id=:id"), {"id": upload_id})
    db.commit()

    package = _package_bytes(db, upload_id)
    registry_rows = _nasdaq_registry(db)
    exact, aliases = _alias_maps(registry_rows)
    registry_by_symbol = {r.symbol.upper(): r for r in registry_rows}
    bars: list[dict] = []
    snapshots: list[MarketSnapshot] = []
    processed = matched_batch = 0
    last_cursor = cursor

    for next_cursor, data in _iter_records(package, cursor, limit):
        processed += 1
        last_cursor = next_cursor
        source_symbol = str(data["symbol"]).upper()
        canonical = source_symbol if source_symbol in exact else aliases.get(symbol_key(source_symbol))
        if not canonical:
            continue
        if canonical != source_symbol:
            reg = registry_by_symbol.get(canonical)
            if reg:
                ids = dict(reg.provider_ids or {})
                ids["stooq_symbol"] = source_symbol
                reg.provider_ids = ids
        data["symbol"] = canonical
        data["provider"] = "Stooq compact package"
        data["source_url"] = "durable-upload://stooq/stooq_opportunities_package.zip"
        matched_batch += 1
        bars.extend(_bar_payloads(data, data["provider"], data["source_url"]))
        snap = _snapshot_from_rows(data)
        if snap:
            if data.get("all_time_high") is not None:
                ath = float(data["all_time_high"])
                snap["all_time_high"] = ath
                price = snap.get("price")
                snap["price_vs_ath_percent"] = None if not price or ath == 0 else ((float(price) / ath) - 1.0) * 100.0
                snap["all_time_high_scope"] = "stooq_full_history"
            snap["canonical_history_source"] = "Stooq"
            snap["latest_bar_source"] = "Stooq compact package"
            snap["technical_source"] = "normalized_daily_bars"
            snap["is_materialized_cache"] = True
            snapshots.append(MarketSnapshot(symbol=canonical, as_of=str(snap.get("as_of") or ""), provider="Stooq compact package", payload=snap))

    for start in range(0, len(bars), BAR_UPSERT_BATCH):
        _upsert_bar_payloads(db, bars[start:start + BAR_UPSERT_BATCH])
    db.flush()
    if snapshots:
        db.add_all(snapshots)
    matched_total += matched_batch
    snapshots_total += len(snapshots)
    complete = processed < limit or (package_symbols and last_cursor >= package_symbols)
    next_status = "ready" if complete else "importing"
    db.execute(text("""
        UPDATE stooq_import_uploads
        SET status=:status, cursor=:cursor, matched=:matched, snapshots_written=:snapshots, updated_at=NOW()
        WHERE upload_id=:id
    """), {"status": next_status, "cursor": last_cursor, "matched": matched_total, "snapshots": snapshots_total, "id": upload_id})
    db.commit()

    canonical_state = {
        "status": "ready" if complete else "importing",
        "canonical": bool(complete),
        "provider": "Stooq",
        "archive_name": row["filename"],
        "archive_sha256": metadata.get("source_archive_sha256"),
        "package_format": COMPACT_FORMAT,
        "package_symbols": package_symbols,
        "seen": last_cursor,
        "matched": matched_total,
        "snapshots_written": snapshots_total,
        "durable_upload_id": upload_id,
        "progress_percent": round((last_cursor / package_symbols) * 100.0, 2) if package_symbols else None,
        "updated_at": _now(),
    }
    if complete:
        canonical_state["imported_at"] = _now()
        canonical_state["archive_latest_bar_date"] = metadata.get("archive_latest_bar_date")
        canonical_state["archive_history_start_date"] = metadata.get("archive_history_start_date")
        canonical_state["coverage_percent"] = round((matched_total / len(registry_rows)) * 100.0, 2) if registry_rows else 0.0
    _set_state(db, CANONICAL_STATE_KEY, canonical_state)

    if complete:
        prune_market_snapshots(db)
        db.execute(text("DELETE FROM stooq_import_chunks WHERE upload_id=:id"), {"id": upload_id})
        db.commit()

    return {
        "status": next_status,
        "upload_id": upload_id,
        "processed_this_batch": processed,
        "matched_this_batch": matched_batch,
        "cursor": last_cursor,
        "package_symbols": package_symbols,
        "progress_percent": canonical_state.get("progress_percent"),
        "matched": matched_total,
        "snapshots_written": snapshots_total,
    }
