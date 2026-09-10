from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .. import main as stable
from ..intelligence_cache_models import SecurityIntelligenceCache
from ..models import FundamentalCache, HistoricalDailyBar, SymbolRegistry
from ..providers.gdelt import GdeltProvider
from ..providers.sec_filings import SecFilingsProvider
from ..providers.squawkflow import SquawkFlowProvider
from ..providers.yahoo_finance import YahooFinanceProvider
from ..providers.yahoo_options import YahooOptionsProvider
from ..routers.events_v4 import _merge_calendar_into_cache, _recent_check

FLOW_TTL = timedelta(minutes=30)
OPTIONS_ACTIVITY_TTL = timedelta(hours=4)
NEWS_TTL = timedelta(minutes=30)
CATALYST_TTL = timedelta(hours=12)
FILINGS_TTL = timedelta(hours=6)


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
    events = [e for e in live.get("events", []) if str(e.get("symbol") or "").upper() == symbol][:12]
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
        return {"kind": "none", "provider": None, "events": [], "note": f"No unusual-flow match and symbol-specific options activity was unavailable: {str(exc)[:180]}", "retrieved_at": _now().isoformat(), "usage": {}}


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
    for field, label, impact in (("earnings_date", "Earnings", "high"), ("ex_dividend_date", "Ex-dividend", "medium"), ("dividend_date", "Dividend payment", "low"), ("earnings_date_estimate", "Estimated earnings window", "high")):
        raw = payload.get(field)
        if not raw:
            continue
        try:
            d = date.fromisoformat(str(raw)[:10])
        except Exception:
            continue
        if d < today - timedelta(days=2):
            continue
        upcoming.append({"kind": field, "date": d.isoformat(), "title": f"{symbol} {label.lower()}", "impact": impact, "estimated": field == "earnings_date_estimate", "provider": row.provider if row else payload.get("provider") or "Yahoo Finance", "source_url": payload.get("source_url") or f"https://finance.yahoo.com/quote/{symbol}"})
    upcoming.sort(key=lambda x: x["date"])
    return {"upcoming": upcoming, "retrieved_at": _now().isoformat()}


def _linked_news(db: Session, symbol: str) -> dict:
    reg = db.get(SymbolRegistry, symbol)
    name = (reg.name or "").strip() if reg else ""
    query = f'(\"{symbol}\" OR \"{name}\")' if name and name.upper() != symbol else f'\"{symbol}\"'
    try:
        data = GdeltProvider().search(query, max_records=24, timespan="7d")
        articles = data.get("articles") or []
    except Exception as exc:
        return {"articles": [], "provider": "GDELT", "retrieved_at": _now().isoformat(), "error": str(exc)[:180]}
    terms = {symbol.upper()}
    if name:
        terms.add(name.upper())
    matched = []
    for article in articles:
        text = f"{article.get('title','')} {article.get('why_it_matters','')} {' '.join(article.get('topics') or [])} {' '.join(article.get('sectors') or [])}".upper()
        hits = [term for term in terms if len(term) >= 3 and term in text]
        if hits:
            matched.append({**article, "matched_terms": hits[:4], "relationship": "linked news; text match does not prove causality"})
    return {"articles": matched[:16], "provider": data.get("provider") or "GDELT", "retrieved_at": _now().isoformat(), "query": query}


def _recent_filings(symbol: str) -> dict:
    try:
        return SecFilingsProvider().recent(symbol, limit=12)
    except Exception as exc:
        return {"symbol": symbol, "filings": [], "provider": "SEC EDGAR", "retrieved_at": _now().isoformat(), "error": str(exc)[:180], "policy": "SEC filing lookup failed; no directional inference is made from missing filing data."}


def _history(db: Session, symbol: str, days: int) -> dict:
    rows = db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol == symbol).order_by(HistoricalDailyBar.bar_date.desc()).limit(max(30, min(days, 730))).all()
    rows = list(reversed(rows))
    return {"bars": [{"date": r.bar_date, "close": r.close, "volume": r.volume, "provider": r.provider, "source_url": r.source_url} for r in rows], "count": len(rows), "retrieved_at": _now().isoformat(), "refresh_policy": "stored_only; use the research enrichment queue for missing history"}


def refresh_security_intelligence(db: Session, symbol: str, *, refresh_missing: bool = True, force: bool = False, history_days: int = 365) -> dict:
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
    if force or not _fresh(payload, "filings", FILINGS_TTL):
        payload["filings"] = _recent_filings(s)
        stamps["filings"] = _now().isoformat()
    payload["history"] = _history(db, s, history_days)
    stamps["history"] = _now().isoformat()
    payload["section_retrieved_at"] = stamps
    payload["symbol"] = s
    payload["cache_policy"] = {"unusual_flow_minutes": int(FLOW_TTL.total_seconds()/60), "options_activity_hours": int(OPTIONS_ACTIVITY_TTL.total_seconds()/3600), "news_minutes": int(NEWS_TTL.total_seconds()/60), "catalysts_hours": int(CATALYST_TTL.total_seconds()/3600), "filings_hours": int(FILINGS_TTL.total_seconds()/3600), "shared_across_tabs": True}
    _save(db, s, payload)
    return payload
