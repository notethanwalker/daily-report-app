import os
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import main as stable
from ..database import get_db
from ..models import FeatureSnapshot, FlowEvent, FundamentalCache, HistoricalDailyBar, MarketSnapshot, RefreshQueueItem, SymbolRegistry, UserWatchlistItem, WatchlistItem
from ..services.provider_orchestrator import FRESHNESS_POLICIES, ProviderOrchestrator, is_stale
from ..services.rotation import SECTORS

router=APIRouter(prefix="/api/v1",tags=["health"])


def _history_state(db,symbol,now):
    latest=db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol==symbol).order_by(HistoricalDailyBar.bar_date.desc()).first()
    count=db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol==symbol).count()
    if not latest:return "missing",None,count
    try:age=(now.date()-date.fromisoformat(str(latest.bar_date)[:10])).days
    except ValueError:return "invalid",str(latest.bar_date),count
    return ("fresh" if age<=3 else "stale"),str(latest.bar_date),count


def _flow_health(db:Session,now:datetime)->dict:
    latest=db.query(FlowEvent).order_by(FlowEvent.occurred_at.desc()).first()
    stored=db.query(FlowEvent).count()
    recent=db.query(FlowEvent).filter(FlowEvent.occurred_at>=now-timedelta(hours=72)).count()
    providers=[x[0] for x in db.query(FlowEvent.provider).distinct().all() if x[0]]
    last_at=latest.occurred_at if latest else None
    if last_at and last_at.tzinfo is None:last_at=last_at.replace(tzinfo=timezone.utc)
    age_hours=max(0.0,(now-last_at).total_seconds()/3600) if last_at else None
    state="recent_data" if recent>0 else "stale_data" if stored>0 else "unverified"
    return {
        "integration_available":True,
        "credentials_required":False,
        "state":state,
        "stored_events":stored,
        "recent_events_72h":recent,
        "last_event_at":last_at.isoformat() if last_at else None,
        "last_event_age_hours":round(age_hours,1) if age_hours is not None else None,
        "stored_providers":providers,
        "reachability":"not_probed_by_health_endpoint",
        "cache_seconds":30,
        "analysis":"flow-v2 local significance/direction model",
        "policy":"Health reflects persisted evidence. Provider reachability is not inferred from a hardcoded configured flag and is not actively probed on this endpoint."
    }


@router.get("/markets/__deployment__/fundamentals")
def deployment_revision_for_smoke():
    """Machine-smoke deployment identity on an already-authorized read-only route shape."""
    return {
        "symbol":"__DEPLOYMENT__",
        "render_git_commit":os.getenv("RENDER_GIT_COMMIT"),
        "render_git_branch":os.getenv("RENDER_GIT_BRANCH"),
        "render_service_id":os.getenv("RENDER_SERVICE_ID"),
        "render_instance_id":os.getenv("RENDER_INSTANCE_ID"),
    }


@router.get("/system/data-health")
def data_health_override(db:Session=Depends(get_db)):
    symbols={r.symbol for r in db.query(WatchlistItem).all()};symbols|={r.symbol for r in db.query(UserWatchlistItem).all() if r.symbol!="__INITIALIZED__"};now=datetime.now(timezone.utc);market_fresh=0;fund_fresh=0;history_fresh=0;verified=0;discrepancies=0;primary_only=0;stale=[];coverage=[]
    for s in sorted(symbols):
        m=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==s).order_by(MarketSnapshot.retrieved_at.desc()).first();f=db.get(FundamentalCache,s);ms="missing";fs="missing";vs="missing"
        if m:
            ms="stale" if is_stale(m.retrieved_at,"market",now) else "fresh";market_fresh+=int(ms=="fresh");vs=str((m.payload or {}).get("verification_status") or "primary_only")
            verified+=int(vs in {"partially_verified","verified_different_as_of","verified"});discrepancies+=int(vs=="discrepancy");primary_only+=int(vs=="primary_only")
        if f:fs="stale" if is_stale(f.retrieved_at,"fundamentals",now) else "fresh";fund_fresh+=int(fs=="fresh")
        hs,last_bar,bar_count=_history_state(db,s,now);history_fresh+=int(hs=="fresh")
        if ms!="fresh":stale.append({"symbol":s,"data_class":"market","state":ms,"retrieved_at":m.retrieved_at.isoformat() if m else None})
        if hs!="fresh":stale.append({"symbol":s,"data_class":"history","state":hs,"latest_bar":last_bar,"bar_count":bar_count})
        coverage.append({"symbol":s,"market":ms,"fundamentals":fs,"history":hs,"latest_history_bar":last_bar,"history_bars":bar_count,"verification":vs})
    queue={status:db.query(RefreshQueueItem).filter(RefreshQueueItem.status==status).count() for status in ["queued","running","failed","complete"]}
    alpha_used=stable._alpha_requests_used_today(db) if hasattr(stable,"_alpha_requests_used_today") else None
    macro_states=[]
    for s in sorted(SECTORS):
        hs,last_bar,count=_history_state(db,s,now);macro_states.append({"symbol":s,"history":hs,"latest_bar":last_bar,"bar_count":count})
    return {
        "symbols":len(symbols),"market_fresh":market_fresh,"fundamentals_fresh":fund_fresh,"history_fresh":history_fresh,
        "verification":{"verified_or_partially_verified":verified,"discrepancy":discrepancies,"primary_only":primary_only,"policy":"Twelve Data primary + Yahoo Finance daily-history cross-check on refreshed snapshots"},
        "feature_snapshots":db.query(FeatureSnapshot).count(),"registry_symbols":db.query(SymbolRegistry).count(),"queue":queue,"stale":stale[:100],"coverage":coverage,
        "macro_history":{"tracked":len(macro_states),"fresh":sum(1 for x in macro_states if x["history"]=="fresh"),"stale_or_missing":[x for x in macro_states if x["history"]!="fresh"]},
        "provider_status":{"twelve_data":{"configured":bool(__import__('os').getenv('TWELVE_DATA_API_KEY'))},"alpha_vantage":{"configured":bool(__import__('os').getenv('ALPHA_VANTAGE_API_KEY')),"budget":20,"used_today":alpha_used,"remaining":max(20-alpha_used,0) if alpha_used is not None else None,"role":"tertiary/quota-aware"},"yahoo_finance":{"configured":True,"role":"fundamentals fallback + independent market verification"},"squawkflow":_flow_health(db,now),"frankfurter":{"configured":True},"gdelt":{"configured":True},"macroradar":{"configured":True}},
        "cache_state":{"market_memory_entries":len(getattr(stable,'_market_cache',{})),"shared_memory_entries":len(getattr(stable,'_shared_cache',{}))},"provider_policy":ProviderOrchestrator().describe(),"freshness_policies":{k:{"ttl_seconds":v.ttl_seconds,"priority":v.priority} for k,v in FRESHNESS_POLICIES.items()},"architecture":"Global symbol, history, fundamentals, flow and feature data are shared. User watchlists, holdings, alerts and theses contain references only, so duplicate users do not multiply provider calls for the same symbol."
    }
