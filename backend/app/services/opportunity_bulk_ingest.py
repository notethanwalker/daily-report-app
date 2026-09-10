from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import MarketSnapshot, SymbolRegistry
from ..normalized_market_models import MarketPipelineState, NormalizedDailyBar
from .market_data_pipeline import (
    BROAD_OPPORTUNITY_HISTORY_DAYS,
    BROAD_OPPORTUNITY_MIN_BARS,
    _nasdaq_registry,
    _snapshot_from_normalized,
    _snapshot_from_rows,
    _upsert_bar_payloads,
)

STATE_KEY = "opportunity_external_ingest"
CURSOR_STATE_KEY = "opportunity_external_cursor"
MIN_BARS = BROAD_OPPORTUNITY_MIN_BARS
RETAIN_DAYS = BROAD_OPPORTUNITY_HISTORY_DAYS
MAX_RECORDS_PER_BATCH = 200
READY_COVERAGE_PERCENT = 95.0
BAR_UPSERT_CHUNK = 3000


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
    """Return True only for common/ordinary equity suitable for the broad scanner."""
    if str(row.asset_type or "").lower() not in {"stock", "equity"}:
        return False
    symbol = str(row.symbol or "").upper()
    name = f" {str(row.name or '').lower()} "
    if not symbol or "$" in symbol:
        return False
    blocked = (
        " warrant", " warrants", " redeemable warrant", " unit", " units",
        " right", " rights", " preferred", " preference", " preferred stock",
        " preferred share", " preferred shares", " notes due", " note due",
        " senior notes", " senior note", " subordinated notes", " subordinated note",
        " debenture", " debentures", " bond", " bonds", " income fund",
        " closed-end fund", " closed end fund", " exchange traded note",
        " etn ", " trust preferred",
    )
    return not any(term in name for term in blocked)


def _eligible_symbols(db: Session) -> list[str]:
    return sorted(r.symbol.upper() for r in _nasdaq_registry(db) if _eligible_stock(r))


def _coverage_rows(db: Session, symbols: list[str] | set[str] | None = None) -> dict[str, dict]:
    query = db.query(
        NormalizedDailyBar.symbol,
        func.count(NormalizedDailyBar.id).label("bars"),
        func.max(NormalizedDailyBar.bar_date).label("latest_bar_date"),
    ).filter(
        NormalizedDailyBar.high.is_not(None),
        NormalizedDailyBar.low.is_not(None),
    )
    if symbols is not None:
        wanted = list(symbols)
        if not wanted:
            return {}
        query = query.filter(NormalizedDailyBar.symbol.in_(wanted))
    rows = query.group_by(NormalizedDailyBar.symbol).all()
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


def _coverage_from_state(db: Session) -> dict | None:
    row = db.get(MarketPipelineState, STATE_KEY)
    payload = dict(row.payload or {}) if row else {}
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        return None
    try:
        eligible = int(coverage.get("eligible_stocks") or 0)
        covered = int(coverage.get("covered_stocks") or 0)
    except (TypeError, ValueError):
        return None
    if eligible <= 0 or covered < 0 or covered > eligible:
        return None
    return {
        "eligible_stocks": eligible,
        "covered_stocks": covered,
        "coverage_percent": round(covered / eligible * 100.0, 2),
        "minimum_bars": MIN_BARS,
        "retained_sessions": RETAIN_DAYS,
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


def missing_opportunity_symbols(db: Session, *, limit: int = 500, cursor: str = "") -> dict:
    limit = max(1, min(int(limit), 1000))
    coverage = _coverage(db)
    if float(coverage.get("coverage_percent") or 0) >= READY_COVERAGE_PERCENT:
        refresh = opportunity_refresh_targets(db, limit=limit)
        if refresh.get("symbols"):
            refresh["policy"] = "Broad coverage is ready; refresh stale covered symbols with recent bars before retrying residual unavailable listings."
            return refresh

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

    return {
        "symbols": selected,
        "cursor": next_cursor,
        "previous_cursor": effective_cursor,
        "wrapped": wrapped,
        "remaining_missing": len(missing_all),
        "mode": "bootstrap",
        "coverage": coverage,
        "policy": "Rotate through missing common equities; unavailable or too-young listings do not pin the queue.",
    }


def _bar_payloads(symbol: str, rows: list[dict], source: str, source_url: str) -> list[dict]:
    payloads = []
    for item in rows[-RETAIN_DAYS:]:
        dt = str(item.get("date") or "")[:10]
        close = item.get("close")
        if not dt or close is None:
            continue
        payloads.append({
            "symbol": symbol,
            "bar_date": dt,
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "close": close,
            "volume": item.get("volume") or 0.0,
            "provider": source,
            "source_url": source_url,
        })
    return payloads


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

    source_symbols = sorted({str(r.get("symbol") or "").strip().upper() for r in records if r.get("symbol")})
    registry_rows = db.query(SymbolRegistry).filter(SymbolRegistry.symbol.in_(source_symbols)).all()
    registry_by_symbol = {r.symbol.upper(): r for r in registry_rows}
    coverage_before = _coverage_rows(db, source_symbols)
    prior_coverage = _coverage_from_state(db)

    accepted = rejected = bars_touched = snapshots_written = 0
    refresh_updates = bootstrap_updates = 0
    rejected_examples: list[dict] = []
    accepted_symbols: list[str] = []
    newest_bar = None
    all_bar_payloads: list[dict] = []
    snapshot_rows: list[MarketSnapshot] = []
    refresh_records: list[tuple[str, list[dict], dict]] = []

    for raw in records:
        source_symbol = str(raw.get("symbol") or "").strip().upper()
        registry = registry_by_symbol.get(source_symbol)
        if not registry:
            rejected += 1
            if len(rejected_examples) < 12:
                rejected_examples.append({"symbol": source_symbol or None, "reason": "symbol_not_in_current_nasdaq_universe"})
            continue
        if not _eligible_stock(registry):
            rejected += 1
            if len(rejected_examples) < 12:
                rejected_examples.append({"symbol": source_symbol, "reason": "not_common_equity"})
            continue

        usable = [
            r for r in list(raw.get("rows") or [])
            if r.get("close") is not None and r.get("high") is not None and r.get("low") is not None
            and str(r.get("date") or "")[:10]
        ]
        existing_bars = int(coverage_before.get(source_symbol, {}).get("bars") or 0)
        is_refresh = existing_bars >= MIN_BARS
        if not usable or (not is_refresh and len(usable) < MIN_BARS):
            rejected += 1
            if len(rejected_examples) < 12:
                rejected_examples.append({"symbol": source_symbol, "reason": f"insufficient_ohlcv:{len(usable)}" if usable else "no_usable_ohlcv"})
            continue

        data = {
            "symbol": source_symbol,
            "rows": usable[-RETAIN_DAYS:],
            "provider": source,
            "source_url": source_url,
            "retrieved_at": _now(),
        }
        if is_refresh and len(usable) < MIN_BARS:
            refresh_records.append((source_symbol, usable, raw))
            continue

        snapshot = _snapshot_from_rows(data, min_bars=MIN_BARS, tail_days=RETAIN_DAYS)
        if not snapshot:
            rejected += 1
            if len(rejected_examples) < 12:
                rejected_examples.append({"symbol": source_symbol, "reason": "technical snapshot could not be calculated"})
            continue
        snapshot["canonical_history_source"] = source
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
        payloads = _bar_payloads(source_symbol, usable, source, source_url)
        all_bar_payloads.extend(payloads)
        snapshot_rows.append(MarketSnapshot(symbol=source_symbol, as_of=str(snapshot.get("as_of") or ""), provider=source, payload=snapshot))
        bars_touched += len(payloads)
        accepted += 1
        snapshots_written += 1
        refresh_updates += int(is_refresh)
        bootstrap_updates += int(not is_refresh)
        accepted_symbols.append(source_symbol)
        last_date = str(usable[-1].get("date") or "")[:10]
        if last_date:
            newest_bar = max(newest_bar or last_date, last_date)

    try:
        for offset in range(0, len(all_bar_payloads), BAR_UPSERT_CHUNK):
            _upsert_bar_payloads(db, all_bar_payloads[offset:offset + BAR_UPSERT_CHUNK])
        if snapshot_rows:
            db.add_all(snapshot_rows)
        db.commit()
    except Exception:
        db.rollback()
        raise

    # Short incremental refreshes need cached history merged before technical calculation;
    # keep that uncommon steady-state path explicit and correctness-first.
    for source_symbol, usable, raw in refresh_records:
        try:
            payloads = _bar_payloads(source_symbol, usable, source, source_url)
            _upsert_bar_payloads(db, payloads)
            db.flush()
            snapshot = _snapshot_from_normalized(db, source_symbol, min_bars=MIN_BARS, tail_days=RETAIN_DAYS)
            if not snapshot:
                raise RuntimeError("technical snapshot could not be calculated")
            snapshot["latest_bar_source"] = source
            snapshot["technical_source"] = "normalized_daily_bars"
            snapshot["is_materialized_cache"] = True
            snapshot["opportunity_bulk_ingest"] = True
            snapshot["opportunity_refresh_mode"] = "incremental"
            db.add(MarketSnapshot(symbol=source_symbol, as_of=str(snapshot.get("as_of") or ""), provider=source, payload=snapshot))
            db.commit()
            bars_touched += len(payloads)
            accepted += 1
            snapshots_written += 1
            refresh_updates += 1
            accepted_symbols.append(source_symbol)
        except Exception as exc:
            db.rollback()
            rejected += 1
            if len(rejected_examples) < 12:
                rejected_examples.append({"symbol": source_symbol, "reason": str(exc)[:180]})

    if prior_coverage and prior_coverage["eligible_stocks"] > 0:
        covered_count = min(prior_coverage["eligible_stocks"], prior_coverage["covered_stocks"] + bootstrap_updates)
        coverage = {
            **prior_coverage,
            "covered_stocks": covered_count,
            "coverage_percent": round(covered_count / prior_coverage["eligible_stocks"] * 100.0, 2),
        }
    else:
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
