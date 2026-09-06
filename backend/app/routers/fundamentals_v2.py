from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import main as stable
from ..database import get_db
from ..models import FundamentalCache
from ..providers.alpha_vantage import AlphaVantageProvider
from ..providers.sec_companyfacts import SecCompanyFactsProvider
from ..providers.yahoo_finance import YahooFinanceProvider

router=APIRouter(prefix="/api/v1",tags=["fundamentals-v2"])

FIELDS=("pe_ratio","price_to_sales_ratio","peg_ratio")


def _complete(p:dict)->bool:
    ps=p.get("price_to_sales_ratio");pe=p.get("pe_ratio");peg=p.get("peg_ratio");eps=p.get("eps");growth=p.get("quarterly_earnings_growth_yoy")
    pe_ok=pe is not None or (isinstance(eps,(int,float)) and eps<=0)
    peg_ok=peg is not None or pe is None or not (isinstance(growth,(int,float)) and growth>0)
    return ps is not None and pe_ok and peg_ok


def _merge(base:dict,extra:dict,source_name:str)->dict:
    out={**base};field_sources=dict(out.get("field_sources") or {})
    for k,v in extra.items():
        if k in {"provider","source_url","retrieved_at","valuation_refresh_version"}:continue
        if out.get(k) is None and v is not None:
            out[k]=v;field_sources[k]=source_name
    sources=list(out.get("valuation_sources") or [])
    if source_name not in sources:sources.append(source_name)
    out["valuation_sources"]=sources;out["field_sources"]=field_sources
    return out


def _load_sources(symbol:str,db:Session,market:dict)->tuple[dict,list[str]]:
    errors=[];merged={"symbol":symbol,"valuation_sources":[],"field_sources":{}}
    # Yahoo is the primary no-key enrichment path. SEC fills standardized company facts.
    for name,loader in [("Yahoo Finance",lambda:YahooFinanceProvider().overview(symbol)),("SEC EDGAR",lambda:SecCompanyFactsProvider().overview(symbol))]:
        try:
            p=loader();merged=_merge(merged,p,name)
            if name=="Yahoo Finance":
                merged["provider"]="Yahoo Finance";merged["source_url"]=p.get("source_url")
            if _complete(stable._enrich_fundamental_ratios(merged,market)):break
        except Exception as exc:errors.append(f"{name}: {exc}")
    # Use Alpha Vantage only when still incomplete and quota remains; this protects the free daily allowance.
    if not _complete(stable._enrich_fundamental_ratios(merged,market)) and os.getenv("ALPHA_VANTAGE_API_KEY") and stable._alpha_requests_used_today(db)<stable.ALPHA_VANTAGE_DAILY_BUDGET:
        try:
            p=AlphaVantageProvider().overview(symbol);merged=_merge(merged,p,"Alpha Vantage")
            if not merged.get("provider"):merged["provider"]="Alpha Vantage";merged["source_url"]=p.get("source_url")
        except Exception as exc:errors.append(f"Alpha Vantage: {exc}")
    merged["provider"]=merged.get("provider") or "Composite fundamentals"
    merged["retrieved_at"]=datetime.now(timezone.utc).isoformat();merged["valuation_refresh_version"]=5
    merged=stable._enrich_fundamental_ratios(merged,market)
    if "SEC EDGAR" in merged.get("valuation_sources",[]):merged["valuation_note"]="SEC EDGAR is used to fill missing standardized revenue, EPS or share-count facts; Yahoo/Alpha fields are preferred when available."
    return merged,errors


@router.get("/markets/{symbol}/fundamentals")
def fundamentals(symbol:str,db:Session=Depends(get_db)):
    s=symbol.strip().upper();market=stable._latest_market_payload(db,s) or {};cached=db.get(FundamentalCache,s)
    if cached:
        age=(datetime.now(timezone.utc)-(cached.retrieved_at if cached.retrieved_at.tzinfo else cached.retrieved_at.replace(tzinfo=timezone.utc))).total_seconds();p=stable._enrich_fundamental_ratios(cached.payload,market)
        if age<stable.FUNDAMENTAL_CACHE_TTL_SECONDS and int((cached.payload or {}).get("valuation_refresh_version") or 0)>=5 and _complete(p):
            return {**p,"fundamentals_cache":"fresh","coverage":{"pe":p.get("pe_ratio") is not None,"ps":p.get("price_to_sales_ratio") is not None,"peg":p.get("peg_ratio") is not None},"quality":{"pe":"not_applicable" if p.get("pe_ratio") is None and isinstance(p.get("eps"),(int,float)) and p.get("eps")<=0 else ("available" if p.get("pe_ratio") is not None else "unavailable"),"ps":"available" if p.get("price_to_sales_ratio") is not None else "unavailable","peg":"available" if p.get("peg_ratio") is not None else "not_applicable_or_unavailable"}}
    fresh,errors=_load_sources(s,db,market)
    if not any(fresh.get(k) is not None for k in ["eps","revenue_ttm","shares_outstanding","pe_ratio","price_to_sales_ratio","peg_ratio"]):
        if cached:return {**stable._enrich_fundamental_ratios(cached.payload,market),"fundamentals_cache":"stale","fundamentals_errors":errors}
        raise HTTPException(502,"Fundamentals unavailable from Yahoo Finance, SEC EDGAR and Alpha Vantage")
    provider=str(fresh.get("provider") or "Composite fundamentals")
    if cached:cached.provider=provider;cached.payload=fresh;cached.retrieved_at=datetime.now(timezone.utc)
    else:db.add(FundamentalCache(symbol=s,provider=provider,payload=fresh,retrieved_at=datetime.now(timezone.utc)))
    db.commit()
    return {**fresh,"fundamentals_cache":"fresh","fundamentals_errors":errors,"coverage":{"pe":fresh.get("pe_ratio") is not None,"ps":fresh.get("price_to_sales_ratio") is not None,"peg":fresh.get("peg_ratio") is not None},"quality":{"pe":"not_applicable" if fresh.get("pe_ratio") is None and isinstance(fresh.get("eps"),(int,float)) and fresh.get("eps")<=0 else ("available" if fresh.get("pe_ratio") is not None else "unavailable"),"ps":"available" if fresh.get("price_to_sales_ratio") is not None else "unavailable","peg":"available" if fresh.get("peg_ratio") is not None else "not_applicable_or_unavailable"}}
