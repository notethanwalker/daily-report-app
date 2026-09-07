from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import main as stable
from ..database import get_db
from ..intelligence_cache_models import SecurityIntelligenceCache
from ..models import FundamentalCache, HistoricalDailyBar, SymbolRegistry
from ..providers.gdelt import GdeltProvider
from ..providers.squawkflow import SquawkFlowProvider
from ..providers.yahoo_finance import YahooFinanceProvider
from ..providers.yahoo_options import YahooOptionsProvider
from .events_v4 import _merge_calendar_into_cache, _recent_check
from .research_v4 import _ensure_history

router = APIRouter(prefix="/api/v1", tags=["security-intelligence-v5"])

FLOW_TTL = timedelta(minutes=30)
OPTIONS_ACTIVITY_TTL = timedelta(hours=4)
NEWS_TTL = timedelta(minutes=30)
CATALYST_TTL = timedelta(hours=12)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _fresh(payload: dict, section: str, ttl: timedelta) -> bool:
    dt = _parse_dt((payload.get("section_retrieved_at") or {}).get(section))
    return bool(dt and _now() - dt < ttl)


def _save(db: Session, symbol: str, payload: dict) -> None:
    row = db.get(SecurityIntelligenceCache, symbol)
    if row:
        row.payload = payload
        row.retrieved_at = _now()
    else:
        db.add(SecurityIntelligenceCache(symbol=symbol, payload=payload, retrieved_at=_now()))
    db.commit()


def _global_flow(symbol: str) -> dict:
    live = stable._cached_shared(
        "flow:unusual:100",
        stable.FLOW_CACHE_TTL_SECONDS,
        lambda: SquawkFlowProvider().unusual_options(100),
    )
    events = [e for e in live.get("events", []) if str(e.get("symbol") or "").upper() == symbol]
    events = events[:12]
    return {
        "kind": "unusual_flow" if events else "none",
        "provider": live.get("provider") or "SquawkFlow",
        "source_url": live.get("source_url"),
        "events": events,
        "note": live.get("note"),
        "retrieved_at": live.get("retrieved_at") or _now().isoformat(),
        "usage": live.get("usage") or {},
    }


def _flow_or_activity(symbol: str) -> dict:
    flow = _global_flow(symbol)
    if flow.get("events"):
        return flow
    try:
        activity = YahooOptionsProvider().activity(symbol)
        return {
            "kind": "options_activity",
            "provider": activity.get("provider"),
            "source_url": activity.get("source_url"),
            "events": activity.get("events") or [],
            "note": activity.get("note"),
            "retrieved_at": activity.get("retrieved_at") or _now().isoformat(),
            "usage": {},
        }
    except Exception as exc:
        return {
            "kind": "none",
            "provider": None,
            "events": [],
            "note": f"No unusual-flow match and symbol-specific options activity was unavailable: {str(exc)[:180]}",
            "retrieved_at": _now().isoformat(),
            "usage": {},
        }


def _refresh_calendar(db: Session, symbol: str, payload: dict) -> dict:
    if _recent_check(payload, "company_calendar_retrieved_at", hours=24):
        return payload
    try:
        cal = YahooFinanceProvider().company_calendar(symbol)
        return _merge_calendar_into_cache(db, symbol, cal, "company_calendar_retrieved_at")
    except Exception:
        return payload


def _catalysts(db: Session, symbol: str, refresh_missing: bool) -> dict:
    row = db.get(FundamentalCache, symbol)
    payload = {**(row.payload or {})} if row else {}
    if refresh_missing:
        payload = _refresh_calendar(db, symbol, payload)
    today = date.today()
    upcoming = []
    for field, label, impact in (
        ("earnings_date", "Earnings", "high"),
        ("ex_dividend_date", "Ex-dividend", "medium"),
        ("dividend_date", "Dividend payment", "low"),
        ("earnings_date_estimate", "Estimated earnings window", "high"),
    ):
        raw = payload.get(field)
        if not raw:
            continue
        try:
            d = date.fromisoformat(str(raw)[:10])
        except Exception:
            continue
        if d < today - timedelta(days=2):
            continue
        upcoming.append({
            "kind": field,
            "date": d.isoformat(),
            "title": f"{symbol} {label.lower()}",
            "impact": impact,
            "estimated": field == "earnings_date_estimate",
            "provider": row.provider if row else payload.get("provider") or "Yahoo Finance",
            "source_url": payload.get("source_url") or f"https://finance.yahoo.com/quote/{symbol}",
        })
    upcoming.sort(key=lambda x: x["date"])
    return {"upcoming": upcoming, "retrieved_at": _now().isoformat()}


def _linked_news(db: Session, symbol: str) -> dict:
    reg = db.get(SymbolRegistry, symbol)
    name = (reg.name or "").strip() if reg else ""
    query = f'("{symbol}" OR "{name}")' if name and name.upper() != symbol else f'"{symbol}"'
    try:
        data = GdeltProvider().search(query, max_records=24, timespan="7d")
        articles = data.get("articles") or []
    except Exception as exc:
        return {"articles": [], "provider": "GDELT", "retrieved_at": _now().isoformat(), "error": str(exc)[:180]}
    terms = {symbol.upper()}
    if name:
        terms.add(name.upper())
    matched = []
    for a in articles:
        text = f"{a.get('title','')} {a.get('why_it_matters','')} {' '.join(a.get('topics') or [])} {' '.join(a.get('sectors') or [])}".upper()
        hits = [t for t in terms if len(t) >= 3 and t in text]
        if hits:
            matched.append({**a, "matched_terms": hits[:4], "relationship": "linked news; text match does not prove causality"})
    return {"articles": matched[:16], "provider": data.get("provider") or "GDELT", "retrieved_at": _now().isoformat(), "query": query}


def _history(db: Session, symbol: str, days: int, refresh_missing: bool) -> dict:
    if refresh_missing:
        _ensure_history(db, symbol)
    rows = db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol == symbol).order_by(HistoricalDailyBar.bar_date.desc()).limit(max(30, min(days, 730))).all()
    rows = list(reversed(rows))
    return {
        "bars": [{"date": r.bar_date, "close": r.close, "volume": r.volume, "provider": r.provider, "source_url": r.source_url} for r in rows],
        "count": len(rows),
        "retrieved_at": _now().isoformat(),
    }


@router.get("/security/{symbol}/intelligence")
def security_intelligence(
    symbol: str,
    refresh_missing: bool = Query(default=True),
    force: bool = Query(default=False),
    history_days: int = Query(default=365, ge=30, le=730),
    db: Session = Depends(get_db),
):
    s = symbol.strip().upper()
    row = db.get(SecurityIntelligenceCache, s)
    payload = {**(row.payload or {})} if row else {"symbol": s, "section_retrieved_at": {}}
    stamps = {**(payload.get("section_retrieved_at") or {})}

    flow_ttl = FLOW_TTL if (payload.get("flow") or {}).get("kind") == "unusual_flow" else OPTIONS_ACTIVITY_TTL
    if force or not _fresh(payload, "flow", flow_ttl):
        payload["flow"] = _flow_or_activity(s)
        stamps["flow"] = _now().isoformat()

    if force or not _fresh(payload, "catalysts", CATALYST_TTL):
        payload["catalysts"] = _catalysts(db, s, refresh_missing)
        stamps["catalysts"] = _now().isoformat()

    if force or not _fresh(payload, "news", NEWS_TTL):
        payload["news"] = _linked_news(db, s)
        stamps["news"] = _now().isoformat()

    # History comes from the persistent daily-bar store and does not consume a news/options quota.
    payload["history"] = _history(db, s, history_days, refresh_missing)
    stamps["history"] = _now().isoformat()
    payload["section_retrieved_at"] = stamps
    payload["symbol"] = s
    payload["cache_policy"] = {
        "unusual_flow_minutes": int(FLOW_TTL.total_seconds() / 60),
        "options_activity_hours": int(OPTIONS_ACTIVITY_TTL.total_seconds() / 3600),
        "news_minutes": int(NEWS_TTL.total_seconds() / 60),
        "catalysts_hours": int(CATALYST_TTL.total_seconds() / 3600),
        "shared_across_tabs": True,
    }
    _save(db, s, payload)
    return payload
