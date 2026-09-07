from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import MarketSnapshot, SymbolRegistry
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


def _bar_payloads(data: dict) -> list[dict]:
    provider = "Stooq manual archive"
    source_url = str(data.get("source_url") or "manual-upload://stooq/d_us_txt.zip")
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


def import_stooq_archive(db: Session, archive_path: str, archive_name: str = "d_us_txt.zip") -> dict:
    """Import a manually supplied Stooq U.S. daily ZIP as the canonical broad-market history.

    The archive supplies the historical backbone. Newer Yahoo/Twelve bars may coexist
    in normalized_daily_bars and extend the series beyond the archive date, but they do
    not change the canonical-history designation recorded in pipeline state.
    """
    provider = StooqProvider()
    validation = provider._validate_archive(archive_path)
    sha256 = hashlib.sha256(Path(archive_path).read_bytes()).hexdigest()
    provider.last_bulk_metadata = {
        "url": "manual-upload://stooq/d_us_txt.zip",
        "bytes": os.path.getsize(archive_path),
        "sha256": sha256,
        **validation,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }

    registry_rows = _nasdaq_registry(db)
    exact, aliases = _alias_maps(registry_rows)
    registry_by_symbol = {r.symbol.upper(): r for r in registry_rows}

    bar_buffer: list[dict] = []
    snapshot_buffer: list[MarketSnapshot] = []
    bar_batch = int(os.getenv("MARKET_BAR_UPSERT_BATCH", "10000"))
    snapshot_batch = int(os.getenv("MARKET_SNAPSHOT_BATCH", "500"))

    seen = matched = exact_matches = alias_matches = snapshots = 0
    latest_bar_date = None
    earliest_history_date = None
    unmatched_examples: list[str] = []

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

    for data in provider.iter_us_bulk_history(archive_path, tail=NORMALIZED_HISTORY_DAYS):
        seen += 1
        source_symbol = data["symbol"].upper()
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
        data["provider"] = "Stooq manual archive"
        data["source_url"] = "manual-upload://stooq/d_us_txt.zip"
        matched += 1

        rows = data.get("rows") or []
        if rows:
            latest_bar_date = max(latest_bar_date or rows[-1]["date"], rows[-1]["date"])
            first = data.get("history_start_date") or rows[0]["date"]
            earliest_history_date = min(earliest_history_date or first, first)

        bar_buffer.extend(_bar_payloads(data))
        snap = _snapshot_from_rows(data)
        if snap:
            if data.get("all_time_high") is not None:
                ath = float(data["all_time_high"])
                snap["all_time_high"] = ath
                price = snap.get("price")
                snap["price_vs_ath_percent"] = None if not price or ath == 0 else ((float(price) / ath) - 1.0) * 100.0
                snap["all_time_high_scope"] = "stooq_full_history"
            snap["canonical_history_source"] = "Stooq manual archive"
            snap["latest_bar_source"] = "Stooq manual archive"
            snap["archive_sha256"] = sha256
            snapshot_buffer.append(MarketSnapshot(
                symbol=canonical,
                as_of=str(snap.get("as_of") or ""),
                provider="Stooq manual archive",
                payload=snap,
            ))
            snapshots += 1

        if len(bar_buffer) >= bar_batch:
            flush_bars()
            db.commit()
        if len(snapshot_buffer) >= snapshot_batch:
            flush_snapshots()
            db.commit()

    flush_bars()
    flush_snapshots()
    db.commit()

    universe = len(registry_rows)
    state = {
        "status": "ready",
        "canonical": True,
        "provider": "Stooq",
        "archive_name": archive_name,
        "archive_sha256": sha256,
        "archive_bytes": os.path.getsize(archive_path),
        "archive_data_files": validation.get("data_files"),
        "archive_latest_bar_date": latest_bar_date,
        "archive_history_start_date": earliest_history_date,
        "archive_symbols_seen": seen,
        "nasdaq_symbols_matched": matched,
        "exact_matches": exact_matches,
        "alias_matches": alias_matches,
        "snapshots_written": snapshots,
        "coverage_percent": round((matched / universe) * 100.0, 2) if universe else 0.0,
        "unmatched_archive_examples": unmatched_examples,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "freshness_role": "canonical historical backbone; incremental providers may append newer bars",
    }
    _set_state(db, CANONICAL_STATE_KEY, state)
    return state


def save_upload_to_temp(upload_file, max_bytes: int | None = None) -> str:
    max_bytes = int(max_bytes or os.getenv("STOOQ_MANUAL_UPLOAD_MAX_BYTES", str(2 * 1024 * 1024 * 1024)))
    fd, path = tempfile.mkstemp(prefix="stooq-manual-", suffix=".zip")
    os.close(fd)
    total = 0
    try:
        with open(path, "wb") as out:
            while True:
                chunk = upload_file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Stooq archive exceeds configured upload size limit")
                out.write(chunk)
        return path
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
