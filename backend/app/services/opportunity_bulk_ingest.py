from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import MarketSnapshot, SymbolRegistry
from ..normalized_market_models import MarketPipelineState, NormalizedDailyBar
from ..providers.stooq import symbol_key
from .market_data_pipeline import (
    NORMALIZED_HISTORY_DAYS,
    _alias_maps,
    _nasdaq_registry,
    _snapshot_from_rows,
    persist_normalized_history,
)

STATE_KEY = "opportunity_external_ingest"
MIN_BARS = 220
MAX_RECORDS_PER_BATCH = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_state(db: Session, payload: dict) -> None:
    row = db.get(MarketPipelineState, STATE_KEY)
    if row:
        row.payload = payload
    else:
        db.add(MarketPipelineState(key=STATE_KEY, payload=payload))
    db.commit()


def _eligible_stock(row: SymbolRegistry) -> bool:
    if str(row.asset_type or "").lower() not in {"stock", "equity"}:
        return False
    name = str(row.name or "").lower()
    blocked = (
        " warrant", " warrants", " unit", " units", " right", " rights",
        " preferred", " preference", " notes due", " bond", " fund",
    )
    return not any(term in name for term in blocked)


def _coverage(db: Session) -> dict:
    registry_rows = _nasdaq_registry(db)
    eligible_symbols = {r.symbol.upper() for r in registry_rows if _eligible_stock(r)}
    covered = {
        symbol for (symbol,) in db.query(NormalizedDailyBar.symbol)
        .filter(NormalizedDailyBar.symbol.in_(eligible_symbols))
        .group_by(NormalizedDailyBar.symbol)
        .having(func.count(NormalizedDailyBar.id) >= MIN_BARS)
        .all()
    } if eligible_symbols else set()
    return {
        "eligible_stocks": len(eligible_symbols),
        "covered_stocks": len(covered),
        "coverage_percent": round(len(covered) / len(eligible_symbols) * 100.0, 2) if eligible_symbols else 0.0,
    }


def missing_opportunity_symbols(db: Session, *, limit: int = 500, cursor: str = "") -> dict:
    limit = max(1, min(int(limit), 1000))
    eligible = sorted(r.symbol.upper() for r in _nasdaq_registry(db) if _eligible_stock(r))
    covered = {
        symbol for (symbol,) in db.query(NormalizedDailyBar.symbol)
        .group_by(NormalizedDailyBar.symbol)
        .having(func.count(NormalizedDailyBar.id) >= MIN_BARS)
        .all()
    }
    missing = [s for s in eligible if s not in covered and (not cursor or s > cursor)]
    selected = missing[:limit]
    return {
        "symbols": selected,
        "cursor": selected[-1] if selected else cursor,
        "remaining_from_cursor": len(missing),
        "coverage": {
            "eligible_stocks": len(eligible),
            "covered_stocks": len(set(eligible) & covered),
            "coverage_percent": round(len(set(eligible) & covered) / len(eligible) * 100.0, 2) if eligible else 0.0,
        },
    }


def ingest_opportunity_batch(
    db: Session,
    records: list[dict],
    *,
    source: str,
    source_url: str = "",
    batch_id: str | None = None,
) -> dict:
    if not records:
        raise ValueError("Bulk Opportunity ingest requires at least one record")
    if len(records) > MAX_RECORDS_PER_BATCH:
        raise ValueError(f"Bulk Opportunity ingest is limited to {MAX_RECORDS_PER_BATCH} symbols per request")

    registry_rows = _nasdaq_registry(db)
    exact, aliases = _alias_maps(registry_rows)
    registry_by_symbol: dict[str, SymbolRegistry] = {r.symbol.upper(): r for r in registry_rows}

    accepted = rejected = bars_touched = snapshots_written = 0
    rejected_examples: list[dict] = []
    accepted_symbols: list[str] = []
    newest_bar = None

    for raw in records:
        source_symbol = str(raw.get("symbol") or "").strip().upper()
        rows = list(raw.get("rows") or [])
        canonical = source_symbol if source_symbol in exact else aliases.get(symbol_key(source_symbol))
        if not canonical:
            rejected += 1
            if len(rejected_examples) < 12:
                rejected_examples.append({"symbol": source_symbol or None, "reason": "symbol_not_in_current_nasdaq_universe"})
            continue

        registry = registry_by_symbol.get(canonical)
        if not registry or not _eligible_stock(registry):
            rejected += 1
            if len(rejected_examples) < 12:
                rejected_examples.append({"symbol": source_symbol, "reason": "not_common_equity"})
            continue

        usable = [
            r for r in rows
            if r.get("close") is not None and r.get("high") is not None and r.get("low") is not None and str(r.get("date") or "")[:10]
        ]
        if len(usable) < MIN_BARS:
            rejected += 1
            if len(rejected_examples) < 12:
                rejected_examples.append({"symbol": source_symbol, "reason": f"insufficient_ohlcv:{len(usable)}"})
            continue

        data = {
            "symbol": canonical,
            "rows": usable[-NORMALIZED_HISTORY_DAYS:],
            "provider": source,
            "source_url": source_url,
            "retrieved_at": _now(),
        }
        try:
            bars_touched += persist_normalized_history(db, data, commit=False, keep_days=NORMALIZED_HISTORY_DAYS)
            snapshot = _snapshot_from_rows(data, min_bars=MIN_BARS, tail_days=NORMALIZED_HISTORY_DAYS)
            if not snapshot:
                raise RuntimeError("technical snapshot could not be calculated")
            snapshot["canonical_history_source"] = source
            snapshot["latest_bar_source"] = source
            snapshot["technical_source"] = "normalized_daily_bars"
            snapshot["is_materialized_cache"] = True
            snapshot["opportunity_bulk_ingest"] = True
            if raw.get("all_time_high") is not None:
                try:
                    ath = float(raw["all_time_high"])
                    snapshot["all_time_high"] = ath
                    price = snapshot.get("price")
                    snapshot["price_vs_ath_percent"] = None if not price or ath == 0 else ((float(price) / ath) - 1.0) * 100.0
                except (TypeError, ValueError):
                    pass
            db.add(MarketSnapshot(
                symbol=canonical,
                as_of=str(snapshot.get("as_of") or ""),
                provider=source,
                payload=snapshot,
            ))
            accepted += 1
            snapshots_written += 1
            accepted_symbols.append(canonical)
            last_date = str(usable[-1].get("date") or "")[:10]
            if last_date:
                newest_bar = max(newest_bar or last_date, last_date)
        except Exception as exc:
            db.rollback()
            rejected += 1
            if len(rejected_examples) < 12:
                rejected_examples.append({"symbol": source_symbol, "reason": str(exc)[:180]})

    db.commit()
    coverage = _coverage(db)
    state = {
        "status": "running",
        "source": source,
        "source_url": source_url,
        "batch_id": batch_id,
        "requested": len(records),
        "accepted": accepted,
        "rejected": rejected,
        "bars_touched": bars_touched,
        "snapshots_written": snapshots_written,
        "newest_bar_date": newest_bar,
        "coverage": coverage,
        "rejected_examples": rejected_examples,
        "completed_at": _now(),
    }
    _save_state(db, state)
    return {**state, "accepted_symbols": accepted_symbols[:25]}
