from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import FeatureSnapshot, MarketSnapshot, RefreshQueueItem, SymbolRegistry
from .classification_v4 import blend_rotation_context
from .opportunity_scanner import scan_cached_market
from .provider_orchestrator import FRESHNESS_POLICIES

DEEP_ENRICHMENT_LIMIT=25


def _f(v,default=0.0):
    try:return float(v) if v is not None else default
    except (TypeError,ValueError):return default

def _latest_feature(db,symbol):
    row=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==symbol).order_by(FeatureSnapshot.as_of.desc(),FeatureSnapshot.created_at.desc()).first();return dict(row.payload or {}) if row else {}
def _latest_market(db,symbol):
    row=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol).order_by(MarketSnapshot.retrieved_at.desc()).first();return dict(row.payload or {}) if row else {}
def _setup_type(macro):
    state=macro.get("state")
    if state in {"leading_accelerating","leading_stable"}:return "macro_confirmed"
    if state in {"lagging_improving","recovering"}:return "early_rotation"
    if state in {"lagging_deteriorating","leading_weakening"}:return "counter_trend_mean_reversion"
    return "technical_only"

def enqueue_deep_enrichment(db:Session,symbols:list[str])->int:
    added=0
    for symbol in symbols[:DEEP_ENRICHMENT_LIMIT]:
        exists=db.query(RefreshQueueItem).filter(RefreshQueueItem.symbol==symbol,RefreshQueueItem.data_class=="fundamentals",RefreshQueueItem.status.in_(["queued","running"])).first()
        if exists:continue
        db.add(RefreshQueueItem(symbol=symbol,data_class="fundamentals",priority=max(70,FRESHNESS_POLICIES["fundamentals"].priority),requested_by="v4_candidate_funnel"));added+=1
    if added:db.commit()
    return added

def build_candidate_funnel(db:Session,rotation:dict,limit:int=50,enqueue_enrichment:bool=False)->dict:
    scan=scan_cached_market(db,include_near=True,limit_per_bucket=max(limit*4,200),include_etfs=False);source=[]
    for bucket,bonus in (("strong",8.0),("weak",4.0),("near",0.0)):
        for row in scan.get(bucket,[]):source.append((row,bonus))
    registry={x.symbol.upper():x for x in db.query(SymbolRegistry).all()};ranked=[]
    for row,bucket_bonus in source:
        symbol=row["symbol"];reg=registry.get(symbol);market=_latest_market(db,symbol);feature=_latest_feature(db,symbol)
        sector=(reg.sector if reg else None) or market.get("sector") or row.get("sector");industry=(reg.industry if reg else None) or market.get("industry");themes=(reg.themes if reg else None) or market.get("themes")
        macro=blend_rotation_context(rotation,symbol,sector,industry,themes);pressure=_f(macro.get("rotation_pressure"));conviction=max(0,min(100,_f(macro.get("conviction"))))
        confidence=conviction/100 if macro.get("transition_ready") else min(conviction/100,.45);macro_fit=max(-15,min(15,pressure*3))*confidence
        technical=_f(row.get("score"))
        if feature:base_buy=_f(feature.get("buy_score"),50);base_source="persisted_opportunity_model";enrichment="full"
        else:base_buy=50;base_source="neutral_pending_enrichment";enrichment="scanner_only"
        liquidity=_f(row.get("average_dollar_volume_20d"));liq=min(5,max(0,liquidity/100_000_000*5));raw=technical*.55+base_buy*.25+(50+macro_fit)*.15+liq+bucket_bonus;final=max(0,min(100,raw))
        ranked.append({"symbol":symbol,"name":row.get("name") or (reg.name if reg else None),"sector":sector,"industry":industry,"rotation_proxy":macro.get("dominant_proxy"),"rotation_proxy_basis":macro.get("basis"),"rotation_exposures":macro.get("exposures"),"rotation_components":macro.get("components"),"bucket":row.get("bucket"),"setup_type":_setup_type(macro),"funnel_score":round(final,2),"raw_rank_score":round(raw,2),"technical_score":round(technical,1),"base_buy_score":round(base_buy,1),"base_buy_source":base_source,"rotation_pressure":round(pressure,3),"rotation_state":macro.get("state"),"rotation_conviction":round(conviction,1),"macro_confidence_factor":round(confidence,3),"williams_r_14":row.get("williams_r_14"),"price_vs_ma100_percent":row.get("price_vs_ma100_percent"),"average_dollar_volume_20d":row.get("average_dollar_volume_20d"),"price":row.get("price"),"as_of":row.get("as_of"),"provider":row.get("provider"),"enrichment_status":enrichment,"needs_deep_enrichment":enrichment!="full","explain":{"stage_1_universe":"Broad cached stock universe after price/liquidity filters","stage_2_technical":f"{row.get('bucket')} Williams/100MA setup","stage_3_macro":f"Weighted rotation context: {macro.get('exposures') or 'unmapped'}; confidence factor {confidence:.2f}","stage_4_score":"Technical setup remains dominant; persisted opportunity score is used only when available, otherwise neutral 50 until enrichment."}})
    ranked.sort(key=lambda x:x["raw_rank_score"],reverse=True);short=ranked[:limit];deep=[x["symbol"] for x in short if x["needs_deep_enrichment"]][:DEEP_ENRICHMENT_LIMIT];queued=enqueue_deep_enrichment(db,deep) if enqueue_enrichment and deep else 0
    return {"stages":[{"name":"Universe","input":scan.get("counts",{}).get("cached_symbols_scanned",0),"output":scan.get("counts",{}).get("technically_eligible",0),"rule":"Cached equities only; minimum price and average-dollar-volume filters."},{"name":"Technical setup","input":scan.get("counts",{}).get("technically_eligible",0),"output":len(source),"rule":"Williams %R + approach to 100MA, preserving strong/weak/near buckets."},{"name":"Macro fit","input":len(source),"output":len(source),"rule":"Blend weighted sector/industry/theme rotation exposures; contribution is confidence-weighted."},{"name":"Rank","input":len(source),"output":len(short),"rule":"55% scanner technical, 25% persisted buy score, 15% confidence-weighted macro, plus bounded liquidity/setup bonuses."},{"name":"Deep enrichment shortlist","input":len(short),"output":len(deep),"rule":f"At most {DEEP_ENRICHMENT_LIMIT} scanner-only finalists are eligible for explicit fundamentals enrichment."}],"candidates":short,"deep_enrichment_symbols":deep,"deep_enrichment_jobs_added":queued,"source_scan_counts":scan.get("counts",{}),"methodology":"Candidate-first/cache-first. Weighted theme exposure replaces one-proxy classification where configured. Scanner-only names receive a neutral nontechnical prior and GET ranking remains read-only.","generated_at":datetime.now(timezone.utc).isoformat()}
