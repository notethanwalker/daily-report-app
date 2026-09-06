from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import main as stable
from ..database import get_db
from ..models import FeatureSnapshot, FundamentalCache, MarketSnapshot, RefreshQueueItem, SymbolRegistry, UserWatchlistItem, WatchlistItem
from ..services.provider_orchestrator import FRESHNESS_POLICIES, ProviderOrchestrator, is_stale

router=APIRouter(prefix="/api/v1",tags=["health"])

@router.get("/system/data-health")
def data_health_override(db:Session=Depends(get_db)):
    symbols={r.symbol for r in db.query(WatchlistItem).all()};symbols|={r.symbol for r in db.query(UserWatchlistItem).all() if r.symbol!="__INITIALIZED__"};now=datetime.now(timezone.utc);market_fresh=0;fund_fresh=0;stale=[];coverage=[]
    for s in sorted(symbols):
        m=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==s).order_by(MarketSnapshot.retrieved_at.desc()).first();f=db.get(FundamentalCache,s);ms="missing";fs="missing"
        if m:ms="stale" if is_stale(m.retrieved_at,"market",now) else "fresh";market_fresh+=int(ms=="fresh")
        if f:fs="stale" if is_stale(f.retrieved_at,"fundamentals",now) else "fresh";fund_fresh+=int(fs=="fresh")
        if ms!="fresh":stale.append({"symbol":s,"data_class":"market","state":ms,"retrieved_at":m.retrieved_at.isoformat() if m else None})
        coverage.append({"symbol":s,"market":ms,"fundamentals":fs})
    queue={status:db.query(RefreshQueueItem).filter(RefreshQueueItem.status==status).count() for status in ["queued","running","failed","complete"]}
    alpha_used=stable._alpha_requests_used_today(db) if hasattr(stable,"_alpha_requests_used_today") else None
    return {"symbols":len(symbols),"market_fresh":market_fresh,"fundamentals_fresh":fund_fresh,"feature_snapshots":db.query(FeatureSnapshot).count(),"registry_symbols":db.query(SymbolRegistry).count(),"queue":queue,"stale":stale[:100],"coverage":coverage,"provider_status":{"twelve_data":{"configured":bool(__import__('os').getenv('TWELVE_DATA_API_KEY'))},"alpha_vantage":{"configured":bool(__import__('os').getenv('ALPHA_VANTAGE_API_KEY')),"budget":20,"used_today":alpha_used,"remaining":max(20-alpha_used,0) if alpha_used is not None else None},"yahoo_finance":{"configured":True,"role":"fundamentals fallback"},"squawkflow":{"configured":True,"cache_seconds":30},"frankfurter":{"configured":True},"gdelt":{"configured":True},"macroradar":{"configured":True}},"cache_state":{"market_memory_entries":len(getattr(stable,'_market_cache',{})),"shared_memory_entries":len(getattr(stable,'_shared_cache',{}))},"provider_policy":ProviderOrchestrator().describe(),"freshness_policies":{k:{"ttl_seconds":v.ttl_seconds,"priority":v.priority} for k,v in FRESHNESS_POLICIES.items()},"architecture":"Global symbol, history, fundamentals, flow and feature data are shared. User watchlists, holdings, alerts and theses contain references only, so duplicate users do not multiply provider calls for the same symbol."}
