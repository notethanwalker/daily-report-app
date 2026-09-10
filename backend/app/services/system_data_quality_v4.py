from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from ..models import FeatureSnapshot, FundamentalCache, HistoricalDailyBar, MarketSnapshot, RefreshQueueItem, UserWatchlistItem, WatchlistItem
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from .data_quality_v4 import build_quality_summary
from .provider_orchestrator import is_stale


def _history_quality(db:Session,symbol:str,now:datetime):
    row=db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol==symbol).order_by(HistoricalDailyBar.bar_date.desc()).first()
    if not row:return {"available":False,"fresh":False,"degrade_reason":"no stored historical bars"},None
    try:age_days=(now.date()-date.fromisoformat(str(row.bar_date)[:10])).days
    except Exception:return {"available":True,"fresh":False,"degrade_reason":"latest historical bar date is invalid"},row
    return {"available":True,"fresh":age_days<=3,"degrade_reason":None if age_days<=3 else f"latest historical bar is {age_days} calendar days old"},row


def relevant_symbols(db:Session,user:str)->list[str]:
    symbols={r.symbol for r in db.query(WatchlistItem).all()}
    symbols|={r.symbol for r in db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email==user).all() if r.symbol!="__INITIALIZED__"}
    portfolio_ids=[r.id for r in db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email==user).all()]
    if portfolio_ids:symbols|={r.symbol for r in db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id.in_(portfolio_ids)).all()}
    return sorted(str(s).upper() for s in symbols if s)


def symbol_quality(db:Session,symbol:str,now:datetime|None=None)->dict:
    now=now or datetime.now(timezone.utc);symbol=symbol.upper()
    market=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol).order_by(MarketSnapshot.retrieved_at.desc()).first();fund=db.get(FundamentalCache,symbol);feature=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==symbol).order_by(FeatureSnapshot.created_at.desc()).first();history_state,history=_history_quality(db,symbol,now)
    market_fresh=bool(market and not is_stale(market.retrieved_at,"market",now));fund_fresh=bool(fund and not is_stale(fund.retrieved_at,"fundamentals",now))
    market_state={"available":bool(market),"fresh":market_fresh,"degrade_reason":None if market_fresh else "market snapshot is missing or stale"}
    fund_state={"available":bool(fund),"fresh":fund_fresh,"degrade_reason":None if fund_fresh else "fundamentals are missing or stale"}
    failures=[]
    failed=db.query(RefreshQueueItem).filter(RefreshQueueItem.symbol==symbol,RefreshQueueItem.status=="failed").order_by(RefreshQueueItem.updated_at.desc()).limit(5).all()
    for row in failed:failures.append({"code":"refresh_failed","severity":"error","data_class":row.data_class,"detail":row.error or "refresh failed"})
    sources=[]
    if market:sources.append({"provider":market.provider,"retrieved_at":market.retrieved_at,"source_url":((market.payload or {}).get("source_url"))})
    if fund:sources.append({"provider":fund.provider,"retrieved_at":fund.retrieved_at,"source_url":((fund.payload or {}).get("source_url"))})
    if history:sources.append({"provider":history.provider,"retrieved_at":history.retrieved_at,"source_url":history.source_url})
    q=build_quality_summary(sections={"market":market_state,"fundamentals":fund_state,"history":history_state},required_sections=["market","fundamentals","history"],verification_status=((market.payload or {}).get("verification_status") if market else None),feature_status="available" if feature else "missing",failures=failures,source_rows=sources,now=now)
    return {"symbol":symbol,**q}


def system_quality(db:Session,user:str)->dict:
    now=datetime.now(timezone.utc);rows=[symbol_quality(db,s,now) for s in relevant_symbols(db,user)];problems=[]
    for row in rows:
        for p in row.get("problems") or []:problems.append({"symbol":row["symbol"],**p})
    severity_order={"error":0,"warning":1,"info":2};problems.sort(key=lambda p:(severity_order.get(str(p.get("severity")),9),p.get("symbol") or "",p.get("data_class") or ""))
    counts={state:sum(1 for r in rows if r.get("state")==state) for state in ("verified","fresh","degraded","incomplete","failed")}
    avg=sum(float(r.get("confidence") or 0) for r in rows)/len(rows) if rows else 0.0
    return {"generated_at":now.isoformat(),"symbols":rows,"problems":problems,"problem_count":len(problems),"quality_counts":counts,"average_confidence":round(avg,4),"average_confidence_percent":round(avg*100,1),"policy":"Unified Data Problems uses the same data-quality taxonomy and confidence model as Decision Cards and Opportunity quality-adjusted ranking."}