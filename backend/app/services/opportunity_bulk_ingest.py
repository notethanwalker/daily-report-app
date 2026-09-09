from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import MarketSnapshot, SymbolRegistry
from ..normalized_market_models import MarketPipelineState, NormalizedDailyBar
from ..providers.stooq import symbol_key
from .market_data_pipeline import (
    BROAD_OPPORTUNITY_HISTORY_DAYS,
    BROAD_OPPORTUNITY_MIN_BARS,
    _alias_maps,
    _nasdaq_registry,
    _snapshot_from_normalized,
    _snapshot_from_rows,
    persist_normalized_history,
)

STATE_KEY = "opportunity_external_ingest"
CURSOR_STATE_KEY = "opportunity_external_cursor"
MIN_BARS = BROAD_OPPORTUNITY_MIN_BARS
RETAIN_DAYS = BROAD_OPPORTUNITY_HISTORY_DAYS
MAX_RECORDS_PER_BATCH = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_named_state(db: Session, key: str, payload: dict) -> None:
    row = db.get(MarketPipelineState, key)
    if row:
        row.payload = payload
    else:
        db.add(MarketPipelineState(key=key, payload=payload))
    db.commit()


def _save_state(db: Session, payload: dict) -> None:
    _save_named_state(db, STATE_KEY, payload)


def _eligible_stock(row: SymbolRegistry) -> bool:
    if str(row.asset_type or "").lower() not in {"stock", "equity"}:
        return False
    name = str(row.name or "").lower()
    blocked = (
        " warrant", " warrants", " unit", " units", " right", " rights",
        " preferred", " preference", " notes due", " bond", " fund",
    )
    return not any(term in name for term in blocked)


def _eligible_symbols(db: Session) -> list[str]:
    return sorted(r.symbol.upper() for r in _nasdaq_registry(db) if _eligible_stock(r))


def _coverage_rows(db: Session) -> dict[str, dict]:
    rows = db.query(
        NormalizedDailyBar.symbol,
        func.count(NormalizedDailyBar.id).label("bars"),
        func.max(NormalizedDailyBar.bar_date).label("latest_bar_date"),
    ).filter(
        NormalizedDailyBar.high.is_not(None),
        NormalizedDailyBar.low.is_not(None),
    ).group_by(NormalizedDailyBar.symbol).all()
    return {
        str(symbol).upper(): {"bars": int(bars or 0), "latest_bar_date": str(latest or "")[:10]}
        for symbol, bars, latest in rows
    }


def _covered_symbols(db: Session) -> set[str]:
    return {symbol for symbol, item in _coverage_rows(db).items() if item["bars"] >= MIN_BARS}


def _consensus_market_date(db: Session, eligible: set[str]) -> str | None:
    if not eligible:
        return None
    threshold = max(25, min(250, int(len(eligible) * 0.05)))
    rows = db.query(
        NormalizedDailyBar.bar_date,
        func.count(func.distinct(NormalizedDailyBar.symbol)).label("symbols"),
    ).filter(
        NormalizedDailyBar.symbol.in_(eligible),
        NormalizedDailyBar.high.is_not(None),
        NormalizedDailyBar.low.is_not(None),
    ).group_by(NormalizedDailyBar.bar_date).order_by(NormalizedDailyBar.bar_date.desc()).limit(15).all()
    for bar_date, symbol_count in rows:
        if int(symbol_count or 0) >= threshold:
            return str(bar_date)[:10]
    return str(rows[0][0])[:10] if rows else None


def _coverage(db: Session) -> dict:
    eligible = _eligible_symbols(db)
    covered = _covered_symbols(db)
    covered_count = len(set(eligible) & covered)
    return {
        "eligible_stocks": len(eligible),
        "covered_stocks": covered_count,
        "coverage_percent": round(covered_count / len(eligible) * 100.0, 2) if eligible else 0.0,
        "minimum_bars": MIN_BARS,
        "retained_sessions": RETAIN_DAYS,
    }


def missing_opportunity_symbols(db: Session, *, limit: int = 500, cursor: str = "") -> dict:
    limit = max(1, min(int(limit), 1000))
    eligible = _eligible_symbols(db)
    covered = _covered_symbols(db)
    missing_all = [s for s in eligible if s not in covered]

    cursor_state = db.get(MarketPipelineState, CURSOR_STATE_KEY)
    stored_cursor = str((cursor_state.payload or {}).get("cursor") or "") if cursor_state else ""
    effective_cursor = cursor.strip().upper() or stored_cursor
    after = [s for s in missing_all if not effective_cursor or s > effective_cursor]
    selected = after[:limit]
    wrapped = False
    if len(selected) < limit and effective_cursor and missing_all:
        needed = limit - len(selected)
        before = [s for s in missing_all if s <= effective_cursor and s not in selected]
        if before:
            selected.extend(before[:needed])
            wrapped = True

    next_cursor = selected[-1] if selected else effective_cursor
    _save_named_state(db, CURSOR_STATE_KEY, {
        "cursor": next_cursor,
        "previous_cursor": effective_cursor,
        "wrapped": wrapped,
        "selected": len(selected),
        "missing_total": len(missing_all),
        "updated_at": _now(),
    })

    covered_count = len(set(eligible) & covered)
    return {
        "symbols": selected,
        "cursor": next_cursor,
        "previous_cursor": effective_cursor,
        "wrapped": wrapped,
        "remaining_missing": len(missing_all),
        "mode": "bootstrap",
        "coverage": {
            "eligible_stocks": len(eligible),
            "covered_stocks": covered_count,
            "coverage_percent": round(covered_count / len(eligible) * 100.0, 2) if eligible else 0.0,
            "minimum_bars": MIN_BARS,
            "retained_sessions": RETAIN_DAYS,
        },
    }


def opportunity_refresh_targets(db: Session, *, limit: int = 200) -> dict:
    limit = max(1, min(int(limit), 1000))
    eligible = set(_eligible_symbols(db))
    coverage_rows = _coverage_rows(db)
    covered = {s for s in eligible if coverage_rows.get(s, {}).get("bars", 0) >= MIN_BARS}
    reference_date = _consensus_market_date(db, eligible)
    stale = []
    if reference_date:
        stale = sorted(
            (
                (coverage_rows.get(symbol, {}).get("latest_bar_date") or "", symbol)
                for symbol in covered
                if (coverage_rows.get(symbol, {}).get("latest_bar_date") or "") < reference_date
            ),
            key=lambda item: (item[0], item[1]),
        )
    selected = [symbol for _, symbol in stale[:limit]]
    return {
        "symbols": selected,
        "mode": "refresh",
        "reference_date": reference_date,
        "stale_count": len(stale),
        "coverage": _coverage(db),
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
    coverage_before = _coverage_rows(db)

    accepted = rejected = bars_touched = snapshots_written = 0
    refresh_updates = bootstrap_updates = 0
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
            if r.get("close") is not None
            and r.get("high") is not None
            and r.get("low") is not None
            and str(r.get("date") or "")[:10]
        ]
        existing_bars = int(coverage_before.get(canonical, {}).get("bars") or 0)
        is_refresh = existing_bars >= MIN_BARS
        if not usable or (not is_refresh and len(usable) < MIN_BARS):
            rejected += 1
            if len(rejected_examples) < 12:
                rejected_examples.append({
                    "symbol": source_symbol,
                    "reason": f"insufficient_ohlcv:{len(usable)}" if usable else "no_usable_ohlcv",
                })
            continue

        data = {
            "symbol": canonical,
            "rows": usable[-RETAIN_DAYS:],
            "provider": source,
            "source_url": source_url,
            "retrieved_at": _now(),
        }
        try:
            with db.begin_nested():
                touched = persist_normalized_history(db, data, commit=False, keep_days=RETAIN_DAYS)
                if is_refresh and len(usable) < MIN_BARS:
                    db.flush()
                    snapshot = _snapshot_from_normalized(
                        db,
                        canonical,
                        min_bars=MIN_BARS,
                        tail_days=RETAIN_DAYS,
                    )
                else:
                    snapshot = _snapshot_from_rows(data, min_bars=MIN_BARS, tail_days=RETAIN_DAYS)
                if not snapshot:
                    raise RuntimeError("technical snapshot could not be calculated")
                snapshot["canonical_history_source"] = source if not is_refresh else (
                    snapshot.get("canonical_history_source") or "normalized_daily_bars"
                )
                snapshot["latest_bar_source"] = source
                snapshot["technical_source"] = "normalized_daily_bars"
                snapshot["is_materialized_cache"] = True
                snapshot["opportunity_bulk_ingest"] = True
                snapshot["opportunity_refresh_mode"] = "incremental" if is_refresh else "bootstrap"
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
                db.flush()

            bars_touched += touched
            accepted += 1
            snapshots_written += 1
            refresh_updates += int(is_refresh)
            bootstrap_updates += int(not is_refresh)
            accepted_symbols.append(canonical)
            last_date = str(usable[-1].get("date") or "")[:10]
            if last_date:
                newest_bar = max(newest_bar or last_date, last_date)
        except Exception as exc:
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
        "bootstrap_updates": bootstrap_updates,
        "refresh_updates": refresh_updates,
        "bars_touched": bars_touched,
        "snapshots_written": snapshots_written,
        "newest_bar_date": newest_bar,
        "coverage": coverage,
        "rejected_examples": rejected_examples,
        "completed_at": _now(),
    }
    _save_state(db, state)
    return {**state, "accepted_symbols": accepted_symbols[:25]}
