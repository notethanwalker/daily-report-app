from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import MarketSnapshot, SymbolRegistry
from ..normalized_market_models import NormalizedDailyBar
from ..providers.nasdaq_trader import NasdaqTraderProvider
from ..providers.stooq import StooqProvider
from ..providers.twelve_data import TwelveDataProvider
from ..providers.yahoo_finance import YahooFinanceProvider
from .calculations import build_market_snapshot


FREE_SOURCE_POLICY = {
    "universe": "Nasdaq Trader",
    "broad_history_primary": "Stooq",
    "tracked_refresh": "Twelve Data",
    "repair_verification": "Yahoo Finance",
}


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def sync_us_symbol_universe(db: Session) -> dict:
    payload = NasdaqTraderProvider().us_equity_universe()
    created = updated = 0
    for item in payload["symbols"]:
        symbol = item["symbol"]
        row = db.get(SymbolRegistry, symbol)
        if not row:
            row = SymbolRegistry(symbol=symbol, themes={}, provider_ids={})
            db.add(row)
            created += 1
        else:
            updated += 1
        row.name = item.get("name") or row.name
        row.exchange = item.get("exchange") or row.exchange
        row.asset_type = item.get("asset_type") or row.asset_type
        ids = dict(row.provider_ids or {})
        ids["universe_source"] = "Nasdaq Trader"
        row.provider_ids = ids
    db.commit()
    return {"symbols": len(payload["symbols"]), "created": created, "updated": updated, "provider": payload["provider"], "retrieved_at": payload["retrieved_at"]}


def _normalize_twelve(symbol: str, raw: dict) -> dict:
    rows = []
    for item in raw.get("values") or raw.get("data") or []:
        dt = str(item.get("datetime") or item.get("date") or "")[:10]
        close = _number(item.get("close"))
        if not dt or close is None:
            continue
        rows.append({
            "date": dt,
            "open": _number(item.get("open")),
            "high": _number(item.get("high")),
            "low": _number(item.get("low")),
            "close": close,
            "volume": _number(item.get("volume")) or 0.0,
        })
    rows.sort(key=lambda x: x["date"])
    return {"symbol": symbol, "rows": rows, "provider": "Twelve Data", "source_url": "https://twelvedata.com/docs", "retrieved_at": datetime.now(timezone.utc).isoformat()}


def _history_from_sources(symbol: str, prefer: str = "stooq") -> tuple[dict, list[str]]:
    s = symbol.strip().upper()
    errors = []
    order = ["stooq", "twelve", "yahoo"] if prefer == "stooq" else ["twelve", "stooq", "yahoo"]
    for source in order:
        try:
            if source == "stooq":
                data = StooqProvider().daily_history(s)
            elif source == "twelve":
                data = _normalize_twelve(s, TwelveDataProvider().daily_history(s, outputsize=750))
            else:
                data = YahooFinanceProvider().daily_history(s, period="5y")
            if len(data.get("rows") or []) >= 14:
                return data, errors
            errors.append(f"{source}: insufficient history")
        except Exception as exc:
            errors.append(f"{source}: {str(exc)[:180]}")
    raise RuntimeError("; ".join(errors) or f"No free history source available for {s}")


def persist_normalized_history(db: Session, data: dict) -> int:
    symbol = data["symbol"].upper()
    provider = str(data.get("provider") or "Unknown")
    source_url = str(data.get("source_url") or "")
    existing = {
        row.bar_date: row
        for row in db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol == symbol).all()
    }
    touched = 0
    for item in data.get("rows") or []:
        dt = str(item.get("date") or "")[:10]
        close = _number(item.get("close"))
        if not dt or close is None:
            continue
        row = existing.get(dt)
        if not row:
            row = NormalizedDailyBar(symbol=symbol, bar_date=dt, close=close, volume=_number(item.get("volume")) or 0.0, provider=provider, source_url=source_url)
            db.add(row)
        row.open = _number(item.get("open"))
        row.high = _number(item.get("high"))
        row.low = _number(item.get("low"))
        row.close = close
        row.volume = _number(item.get("volume")) or 0.0
        row.provider = provider
        row.source_url = source_url
        touched += 1
    db.commit()
    return touched


def _snapshot_from_normalized(db: Session, symbol: str) -> dict | None:
    rows = db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol == symbol.upper()).order_by(NormalizedDailyBar.bar_date.asc()).all()
    usable = [r for r in rows if r.high is not None and r.low is not None]
    if len(usable) < 200:
        return None
    values = [{"datetime": r.bar_date, "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": r.volume} for r in rows]
    raw = {"history": {"values": values, "meta": {"symbol": symbol.upper()}}, "provider": rows[-1].provider, "source_url": rows[-1].source_url, "retrieved_at": datetime.now(timezone.utc).isoformat()}
    return build_market_snapshot(raw)


def refresh_symbol(db: Session, symbol: str, tracked: bool = False) -> dict:
    prefer = "twelve" if tracked else "stooq"
    data, errors = _history_from_sources(symbol, prefer=prefer)
    touched = persist_normalized_history(db, data)
    snapshot = _snapshot_from_normalized(db, symbol)
    if snapshot:
        db.add(MarketSnapshot(symbol=symbol.upper(), as_of=str(snapshot.get("as_of") or ""), provider=str(snapshot.get("provider") or data.get("provider") or "Normalized cache"), payload=snapshot))
        db.commit()
    return {"symbol": symbol.upper(), "provider": data.get("provider"), "bars_touched": touched, "snapshot_ready": snapshot is not None, "fallback_errors": errors}


def bootstrap_needed_symbols(db: Session, limit: int = 8) -> list[str]:
    counts = dict(db.query(NormalizedDailyBar.symbol, func.count(NormalizedDailyBar.id)).group_by(NormalizedDailyBar.symbol).all())
    rows = db.query(SymbolRegistry).filter(SymbolRegistry.asset_type.in_(["Stock", "ETF", "Equity", None])).order_by(SymbolRegistry.symbol).all()
    return [r.symbol for r in rows if counts.get(r.symbol, 0) < 200][:limit]


def bootstrap_market_batch(db: Session, limit: int = 8) -> dict:
    symbols = bootstrap_needed_symbols(db, limit=limit)
    results = []
    for symbol in symbols:
        try:
            results.append(refresh_symbol(db, symbol, tracked=False))
        except Exception as exc:
            db.rollback()
            results.append({"symbol": symbol, "error": str(exc)[:240]})
    return {"requested": len(symbols), "results": results, "policy": FREE_SOURCE_POLICY}


def pipeline_status(db: Session) -> dict:
    universe = db.query(SymbolRegistry).count()
    bars = db.query(NormalizedDailyBar).count()
    covered = db.query(NormalizedDailyBar.symbol).group_by(NormalizedDailyBar.symbol).having(func.count(NormalizedDailyBar.id) >= 200).count()
    latest = db.query(NormalizedDailyBar).order_by(NormalizedDailyBar.bar_date.desc()).first()
    return {
        "policy": FREE_SOURCE_POLICY,
        "universe_symbols": universe,
        "symbols_with_200_plus_bars": covered,
        "normalized_bar_count": bars,
        "latest_bar_date": latest.bar_date if latest else None,
        "broad_scan_ready": covered > 0,
    }
