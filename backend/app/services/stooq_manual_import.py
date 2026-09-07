from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import MarketSnapshot
from ..providers.stooq import StooqProvider, symbol_key
from .market_data_pipeline import (
    NORMALIZED_HISTORY_DAYS,
    _alias_maps,
    _nasdaq_registry,
    _snapshot_from_rows,
    _upsert_bar_payloads,
    _set_state,
)

CANONICAL_STATE_KEY = "stooq_manual_archive"
COMPACT_FORMAT = "daily-report-stooq-opportunities-v1"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


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


def _compact_manifest(path: str) -> dict | None:
    try:
        with zipfile.ZipFile(path) as zf:
            if "manifest.json" not in zf.namelist() or "symbols.ndjson" not in zf.namelist():
                return None
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            return manifest if manifest.get("format") == COMPACT_FORMAT else None
    except Exception:
        return None


def _iter_compact(path: str):
    with zipfile.ZipFile(path) as zf, zf.open("symbols.ndjson") as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="strict")
        for line in text:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            rows = data.get("rows") or []
            if not data.get("symbol") or len(rows) < 120:
                continue
            yield data


def _import_records(db: Session, records, archive_meta: dict, archive_name: str, package_sha256: str, source_url: str, provider_label: str) -> dict:
    registry_rows = _nasdaq_registry(db)
    exact, aliases = _alias_maps(registry_rows)
    registry_by_symbol = {r.symbol.upper(): r for r in registry_rows}

    bar_buffer: list[dict] = []
    snapshot_buffer: list[MarketSnapshot] = []
    # Keep batches modest for Render free Postgres. 10k-row INSERT/ON CONFLICT statements can
    # stall long enough that the owner upload appears dead before the first commit is visible.
    bar_batch = int(os.getenv("STOOQ_IMPORT_BAR_BATCH", "1000"))
    snapshot_batch = int(os.getenv("STOOQ_IMPORT_SNAPSHOT_BATCH", "100"))
    progress_every = int(os.getenv("STOOQ_IMPORT_PROGRESS_EVERY", "250"))

    seen = matched = exact_matches = alias_matches = snapshots = 0
    latest_bar_date = archive_meta.get("archive_latest_bar_date")
    earliest_history_date = archive_meta.get("archive_history_start_date")
    unmatched_examples: list[str] = []
    started_at = datetime.now(timezone.utc).isoformat()

    _set_state(db, CANONICAL_STATE_KEY, {
        "status": "importing",
        "canonical": False,
        "provider": "Stooq",
        "archive_name": archive_name,
        "archive_sha256": archive_meta.get("source_archive_sha256") or package_sha256,
        "package_sha256": package_sha256,
        "package_format": archive_meta.get("format") or "raw-stooq-zip",
        "package_symbols": archive_meta.get("symbols"),
        "started_at": started_at,
        "seen": 0,
        "matched": 0,
        "snapshots_written": 0,
    })

    def flush_bars():
        nonlocal bar_buffer
        if bar_buffer:
            _upsert_bar_payloads(db, bar_buffer)
            bar_buffer = []

    def flush_snapshots():
        nonlocal snapshot_buffer
        if snapshot_buffer:
            db.add_all(snapshot_buffer)
            snapshot_buffer = []

    def commit_progress():
        flush_bars()
        flush_snapshots()
        db.commit()
        _set_state(db, CANONICAL_STATE_KEY, {
            "status": "importing",
            "canonical": False,
            "provider": "Stooq",
            "archive_name": archive_name,
            "archive_sha256": archive_meta.get("source_archive_sha256") or package_sha256,
            "package_sha256": package_sha256,
            "package_format": archive_meta.get("format") or "raw-stooq-zip",
            "package_symbols": archive_meta.get("symbols"),
            "started_at": started_at,
            "seen": seen,
            "matched": matched,
            "snapshots_written": snapshots,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    for data in records:
        seen += 1
        source_symbol = str(data["symbol"]).upper()
        canonical = source_symbol if source_symbol in exact else aliases.get(symbol_key(source_symbol))
        if not canonical:
            if len(unmatched_examples) < 20:
                unmatched_examples.append(source_symbol)
            continue
        if canonical == source_symbol:
            exact_matches += 1
        else:
            alias_matches += 1
            reg = registry_by_symbol.get(canonical)
            if reg:
                ids = dict(reg.provider_ids or {})
                ids["stooq_symbol"] = source_symbol
                reg.provider_ids = ids

        data["symbol"] = canonical
        data["provider"] = provider_label
        data["source_url"] = source_url
        matched += 1

        rows = data.get("rows") or []
        if rows:
            latest = str(rows[-1].get("date") or "")[:10]
            if latest:
                latest_bar_date = latest if not latest_bar_date or latest > latest_bar_date else latest_bar_date
            first = data.get("history_start_date") or rows[0].get("date")
            if first:
                earliest_history_date = first if not earliest_history_date or first < earliest_history_date else earliest_history_date

        bar_buffer.extend(_bar_payloads(data, provider_label, source_url))
        snap = _snapshot_from_rows(data)
        if snap:
            if data.get("all_time_high") is not None:
                ath = float(data["all_time_high"])
                snap["all_time_high"] = ath
                price = snap.get("price")
                snap["price_vs_ath_percent"] = None if not price or ath == 0 else ((float(price) / ath) - 1.0) * 100.0
                snap["all_time_high_scope"] = "stooq_full_history"
            snap["canonical_history_source"] = "Stooq"
            snap["latest_bar_source"] = provider_label
            snap["archive_sha256"] = archive_meta.get("source_archive_sha256") or package_sha256
            snapshot_buffer.append(MarketSnapshot(
                symbol=canonical,
                as_of=str(snap.get("as_of") or ""),
                provider=provider_label,
                payload=snap,
            ))
            snapshots += 1

        # Bound both SQL statement size and transaction duration. Progress commits also make
        # imports observable and resumable in practice after a failed first attempt.
        if len(bar_buffer) >= bar_batch or len(snapshot_buffer) >= snapshot_batch or matched % progress_every == 0:
            commit_progress()

    flush_bars()
    flush_snapshots()
    db.commit()

    universe = len(registry_rows)
    state = {
        "status": "ready",
        "canonical": True,
        "provider": "Stooq",
        "archive_name": archive_name,
        "archive_sha256": archive_meta.get("source_archive_sha256") or package_sha256,
        "package_sha256": package_sha256,
        "archive_bytes": archive_meta.get("source_archive_bytes") or (os.path.getsize(archive_name) if os.path.exists(archive_name) else None),
        "package_bytes": archive_meta.get("package_bytes"),
        "archive_data_files": archive_meta.get("symbols") or archive_meta.get("data_files"),
        "archive_latest_bar_date": latest_bar_date,
        "archive_history_start_date": earliest_history_date,
        "archive_symbols_seen": seen,
        "nasdaq_symbols_matched": matched,
        "exact_matches": exact_matches,
        "alias_matches": alias_matches,
        "snapshots_written": snapshots,
        "coverage_percent": round((matched / universe) * 100.0, 2) if universe else 0.0,
        "unmatched_archive_examples": unmatched_examples,
        "started_at": started_at,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "freshness_role": "canonical historical backbone; incremental providers may append newer bars",
        "package_format": archive_meta.get("format") or "raw-stooq-zip",
    }
    _set_state(db, CANONICAL_STATE_KEY, state)
    return state


def import_stooq_archive(db: Session, archive_path: str, archive_name: str = "d_us_txt.zip") -> dict:
    """Import either the full Stooq ZIP or the compact local Opportunities package."""
    package_sha256 = _sha256_file(archive_path)
    compact = _compact_manifest(archive_path)
    if compact:
        compact = dict(compact)
        compact["package_bytes"] = os.path.getsize(archive_path)
        return _import_records(
            db,
            _iter_compact(archive_path),
            compact,
            archive_name,
            package_sha256,
            "manual-upload://stooq/stooq_opportunities_package.zip",
            "Stooq compact package",
        )

    provider = StooqProvider()
    validation = provider._validate_archive(archive_path)
    provider.last_bulk_metadata = {
        "url": "manual-upload://stooq/d_us_txt.zip",
        "bytes": os.path.getsize(archive_path),
        "sha256": package_sha256,
        **validation,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
    meta = {
        "format": "raw-stooq-zip",
        "source_archive_sha256": package_sha256,
        "source_archive_bytes": os.path.getsize(archive_path),
        "data_files": validation.get("data_files"),
    }
    return _import_records(
        db,
        provider.iter_us_bulk_history(archive_path, tail=NORMALIZED_HISTORY_DAYS),
        meta,
        archive_name,
        package_sha256,
        "manual-upload://stooq/d_us_txt.zip",
        "Stooq manual archive",
    )
