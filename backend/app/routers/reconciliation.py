from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import main as stable
from ..database import get_db
from ..providers.squawkflow import SquawkFlowProvider
from ..providers.yahoo_finance import YahooFinanceProvider
from ..services.flow_pipeline import NormalizedFlowEvent, score_flow_event
from ..services.validation import build_secondary_metrics, cross_check_market_snapshot

router=APIRouter(prefix="/api/v1",tags=["reconciliation"])


def _parse_time(value):
    if isinstance(value,datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value or "").replace("Z","+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def _verification_error(primary,error):
    return {
        "verification_status":"primary_only",
        "verification":{
            "primary_provider":primary.get("provider"),
            "secondary_provider":"Yahoo Finance",
            "same_as_of":False,
            "verified_fields":[],
            "discrepancy_fields":[],
            "unavailable_fields":["price","previous_close","change_percent","seven_day_percent","thirty_day_percent","ma100"],
            "error":"secondary_provider_unavailable",
            "detail":str(error)[:200],
        },
    }


@router.get("/markets/{symbol}")
def verified_market(symbol:str,verify:bool=True,db:Session=Depends(get_db)):
    """Canonical on-demand market snapshot.

    Twelve Data remains primary. Yahoo Finance is always attempted as the normal
    secondary cross-check; Alpha Vantage remains available elsewhere as a tertiary,
    quota-aware source. The legacy verify=false flag no longer disables the normal
    secondary check because every displayed refresh should carry verification state.
    """
    primary=stable.get_market_snapshot(symbol,db,verify=False)
    try:
        secondary=build_secondary_metrics(YahooFinanceProvider().daily_history(symbol))
        primary.update(cross_check_market_snapshot(primary,secondary))
    except Exception as exc:
        primary.update(_verification_error(primary,exc))
    primary["verification_policy"]="Twelve Data primary; Yahoo Finance independent daily-history cross-check; provider disagreement is preserved rather than silently averaged."
    sym=(primary.get("symbol") or symbol).strip().upper()
    stable._persist_market_result(db,sym,primary);db.commit()
    return primary


def _contract_key(event):
    d=event.get("data") or {}
    return (str(event.get("symbol") or "").upper(),d.get("side"),d.get("strike"),d.get("expiration"))


def _flow_analysis(event,all_events):
    data=event.get("data") or {};key=_contract_key(event)
    peers=[x for x in all_events if x is not event and _contract_key(x)==key]
    providers=sorted({str(x.get("provider") or "unknown") for x in peers if x.get("provider")})
    market_cap=data.get("market_cap")
    rel_vol=data.get("underlying_relative_volume") or data.get("relative_volume")
    normalized=NormalizedFlowEvent(
        event_type=str(event.get("event_type") or "options"),
        symbol=str(event.get("symbol") or "").upper(),
        provider=str(event.get("provider") or "unknown"),
        occurred_at=_parse_time(event.get("occurred_at")),
        source_url=str(event.get("source_url") or ""),
        contract={"side":data.get("side"),"strike":data.get("strike"),"expiration":data.get("expiration")},
        execution={"premium":data.get("premium"),"contracts":data.get("contracts"),"volume":data.get("volume"),"open_interest":data.get("open_interest"),"aggression":data.get("aggression"),"trade_type":data.get("trade_type")},
        provider_score=event.get("outlier_score"),
        raw=data.get("raw") or {},
    )
    analysis=score_flow_event(normalized,corroboration_count=len(providers),underlying_relative_volume=rel_vol,market_cap=market_cap)
    return {
        "significance_score":analysis.significance_score,
        "direction":analysis.direction,
        "direction_confidence":analysis.direction_confidence,
        "analysis_reasons":analysis.reasons,
        "analysis_version":analysis.analysis_version,
        "corroborating_providers":providers,
        "corroboration_count":len(providers),
        "interpretation_warning":"Options activity can represent hedges, spreads, rolls, opening or closing trades. Direction is an inference, not a transaction label.",
    }


@router.get("/flow/recent")
def scored_flow(limit:int=Query(default=50,ge=1,le=100),symbol:str|None=None,event_type:str|None=None,db:Session=Depends(get_db)):
    stored=stable._enrich_flow_events(db,stable._stored_flow(db,limit,symbol,event_type))
    try:
        live=stable._cached_shared(f"flow:unusual:{limit}",stable.FLOW_CACHE_TTL_SECONDS,lambda:SquawkFlowProvider().unusual_options(limit))
        events=stable._enrich_flow_events(db,live.get("events",[]))
        if symbol:events=[e for e in events if str(e.get("symbol") or "").upper()==symbol.strip().upper()]
        if event_type:events=[e for e in events if str(e.get("event_type") or "").lower()==event_type.strip().lower()]
        universe=events+stored
        scored=[]
        for event in events:
            row={**event};row.update(_flow_analysis(row,universe));scored.append(row)
        scored.sort(key=lambda x:(x.get("significance_score") or 0,x.get("outlier_score") or 0),reverse=True)
        direction_counts=Counter(str(x.get("direction") or "ambiguous") for x in scored)
        return {
            **live,
            "events":scored,
            "stored_events":stored,
            "analysis":{
                "method":"flow-v2 significance/direction split",
                "ranked_by":"derived significance score, then provider unusualness score",
                "direction_counts":dict(direction_counts),
                "social_sources":"Public social accounts such as Flow God or Unusual Whales can be treated as corroborating discovery signals only when a licensed/API-accessible observation is available; this endpoint does not scrape X or fabricate observations.",
            },
            "enrichment":"Market cap/price/sector are reused from cached market fundamentals when the flow source omits them. Provider unusualness, premium size, volume/open-interest, execution classification, corroboration and market context feed the significance score.",
        }
    except Exception as exc:
        return {
            "provider":"SquawkFlow",
            "provider_configured":True,
            "events":stored,
            "stored_events":stored,
            "live_error":"Live unusual-options feed temporarily unavailable",
            "note":"Showing stored flow observations when available. No synthetic flow is generated.",
            "error_detail":str(exc),
            "analysis":{"method":"flow-v2","degraded":True},
        }
