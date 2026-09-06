from dataclasses import dataclass
from datetime import datetime, timezone

from ..providers.alpha_vantage import AlphaVantageProvider
from ..providers.sec_companyfacts import SecCompanyFactsProvider
from ..providers.yahoo_finance import YahooFinanceProvider


@dataclass(frozen=True)
class FreshnessPolicy:
    ttl_seconds: int
    priority: int


FRESHNESS_POLICIES = {
    "market": FreshnessPolicy(15 * 60, 100),
    "flow": FreshnessPolicy(30, 95),
    "news": FreshnessPolicy(10 * 60, 80),
    "events": FreshnessPolicy(6 * 60 * 60, 78),
    "macro": FreshnessPolicy(30 * 60, 75),
    "fx": FreshnessPolicy(60 * 60, 65),
    "history": FreshnessPolicy(30 * 24 * 60 * 60, 55),
    "fundamentals": FreshnessPolicy(7 * 24 * 60 * 60, 40),
    "daily_features": FreshnessPolicy(24 * 60 * 60, 50),
}

PROVIDER_POLICY = {
    "market": {"primary":"Twelve Data","fallback":"latest validated shared snapshot","cache":"15m during market window","notes":"One shared symbol snapshot is reused across users and tabs."},
    "history": {"primary":"Twelve Data","fallback":"persistent historical_daily_bars","cache":"persistent daily bars"},
    "fundamentals": {"primary":"Yahoo Finance","fallback":"SEC EDGAR Company Facts -> quota-aware Alpha Vantage","cache":"7d global symbol cache","notes":"P/E and P/S may be derived from shared price plus source EPS/revenue/shares. PEG is only derived with positive earnings growth."},
    "flow": {"primary":"SquawkFlow public unusual options","fallback":"stored observations","cache":"30s global feed cache"},
    "news": {"primary":"GDELT","fallback":"Google News RSS","cache":"10m shared topic cache"},
    "fx": {"primary":"Frankfurter / ECB","fallback":None,"cache":"60m"},
    "events": {"primary":"BEA + Federal Reserve + BLS public schedules + U.S. Treasury","fallback":"MacroRadar + rule-based market calendar + cached company dates + private user events","cache":"provider-specific; official catalog 6h"},
}


def is_stale(retrieved_at, data_class: str, now=None) -> bool:
    if retrieved_at is None:return True
    now=now or datetime.now(timezone.utc)
    if retrieved_at.tzinfo is None:retrieved_at=retrieved_at.replace(tzinfo=timezone.utc)
    policy=FRESHNESS_POLICIES.get(data_class,FreshnessPolicy(3600,50))
    return (now-retrieved_at).total_seconds()>policy.ttl_seconds


def _merge_missing(base:dict,extra:dict,source:str)->dict:
    out={**base};field_sources=dict(out.get("field_sources") or {});sources=list(out.get("valuation_sources") or [])
    for k,v in extra.items():
        if k in {"provider","source_url","retrieved_at","valuation_refresh_version"}:continue
        if out.get(k) is None and v is not None:out[k]=v;field_sources[k]=source
    if source not in sources:sources.append(source)
    out["field_sources"]=field_sources;out["valuation_sources"]=sources
    return out


class ProviderOrchestrator:
    """Central no-duplicate provider policy used by the background refresh queue."""

    def fundamentals(self,symbol:str,allow_alpha:bool=True)->tuple[dict,list[str]]:
        s=symbol.strip().upper();errors=[];merged={"symbol":s,"valuation_sources":[],"field_sources":{}}
        try:
            y=YahooFinanceProvider().overview(s);merged=_merge_missing(merged,y,"Yahoo Finance");merged["provider"]="Yahoo Finance";merged["source_url"]=y.get("source_url")
        except Exception as exc:errors.append(f"Yahoo Finance: {exc}")
        try:
            sec=SecCompanyFactsProvider().overview(s);merged=_merge_missing(merged,sec,"SEC EDGAR")
        except Exception as exc:errors.append(f"SEC EDGAR: {exc}")
        if allow_alpha:
            need=any(merged.get(k) is None for k in ["price_to_sales_ratio","eps","revenue_ttm","market_cap"])
            if need:
                try:
                    a=AlphaVantageProvider().overview(s);merged=_merge_missing(merged,a,"Alpha Vantage")
                    if not merged.get("provider"):merged["provider"]="Alpha Vantage";merged["source_url"]=a.get("source_url")
                except Exception as exc:errors.append(f"Alpha Vantage: {exc}")
        if not any(merged.get(k) is not None for k in ["pe_ratio","price_to_sales_ratio","peg_ratio","eps","revenue_ttm","market_cap","shares_outstanding"]):
            raise RuntimeError("; ".join(errors) or "No fundamentals provider available")
        merged["provider"]=merged.get("provider") or "Composite fundamentals";merged["retrieved_at"]=datetime.now(timezone.utc).isoformat();merged["valuation_refresh_version"]=5
        return merged,errors

    def describe(self)->dict:return PROVIDER_POLICY
