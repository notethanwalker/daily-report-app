from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import httpx

TICKERS_URL="https://www.sec.gov/files/company_tickers.json"
FACTS_ROOT="https://data.sec.gov/api/xbrl/companyfacts"
SOURCE_ROOT="https://www.sec.gov/edgar/browse/"
_CACHE:dict[str,tuple[float,dict]]={}
_TICKERS:tuple[float,dict[str,str]]|None=None


def _headers():
    return {"User-Agent":os.getenv("SEC_USER_AGENT","DailyReportApp/1.9 market-research"),"Accept-Encoding":"gzip, deflate"}


def _ticker_map():
    global _TICKERS
    if _TICKERS and time.time()-_TICKERS[0]<86400:return _TICKERS[1]
    with httpx.Client(timeout=20,follow_redirects=True) as client:
        r=client.get(TICKERS_URL,headers=_headers());r.raise_for_status();raw=r.json()
    out={}
    for item in raw.values() if isinstance(raw,dict) else []:
        ticker=str(item.get("ticker") or "").upper();cik=item.get("cik_str")
        if ticker and cik is not None:out[ticker]=str(cik).zfill(10)
    _TICKERS=(time.time(),out);return out


def _entries(facts:dict,taxonomy:str,tag:str,unit:str):
    try:return list(facts["facts"][taxonomy][tag]["units"][unit])
    except Exception:return []


def _annual_values(entries:list[dict]):
    by_period={}
    for e in entries:
        if e.get("form") not in {"10-K","10-K/A","20-F","20-F/A"}:continue
        val=e.get("val");end=str(e.get("end") or "")[:10]
        if val is None or not end:continue
        # Prefer calendrical annual frames when supplied; otherwise use the latest filed value for an end date.
        frame=str(e.get("frame") or "")
        if frame and ("Q" in frame or frame.endswith("I")):continue
        old=by_period.get(end)
        if old is None or str(e.get("filed") or "")>str(old.get("filed") or ""):by_period[end]=e
    return sorted(by_period.values(),key=lambda x:str(x.get("end") or ""),reverse=True)


def _latest_instant(entries:list[dict]):
    usable=[e for e in entries if e.get("val") is not None and e.get("form") in {"10-Q","10-Q/A","10-K","10-K/A","20-F","20-F/A"}]
    usable.sort(key=lambda x:(str(x.get("end") or ""),str(x.get("filed") or "")),reverse=True)
    return usable[0] if usable else None


def _first_annual(facts:dict,tags:list[str],unit:str):
    for tag in tags:
        vals=_annual_values(_entries(facts,"us-gaap",tag,unit))
        if vals:return vals,tag
    return [],None


class SecCompanyFactsProvider:
    name="SEC EDGAR"
    def overview(self,symbol:str)->dict:
        s=symbol.strip().upper();cached=_CACHE.get(s)
        if cached and time.time()-cached[0]<21600:return {**cached[1]}
        cik=_ticker_map().get(s)
        if not cik:raise RuntimeError(f"SEC ticker mapping unavailable for {s}")
        with httpx.Client(timeout=25,follow_redirects=True) as client:
            r=client.get(f"{FACTS_ROOT}/CIK{cik}.json",headers=_headers());r.raise_for_status();facts=r.json()
        revenue_rows,revenue_tag=_first_annual(facts,["RevenueFromContractWithCustomerExcludingAssessedTax","Revenues","SalesRevenueNet","SalesRevenueGoodsNet"],"USD")
        eps_rows,eps_tag=_first_annual(facts,["EarningsPerShareDiluted","EarningsPerShareBasicAndDiluted","EarningsPerShareBasic"],"USD/shares")
        share_entry=None;share_tag=None
        for taxonomy,tag in [("dei","EntityCommonStockSharesOutstanding"),("us-gaap","CommonStockSharesOutstanding")]:
            row=_latest_instant(_entries(facts,taxonomy,tag,"shares"))
            if row:share_entry=row;share_tag=tag;break
        revenue=float(revenue_rows[0]["val"]) if revenue_rows else None
        eps=float(eps_rows[0]["val"]) if eps_rows else None
        shares=float(share_entry["val"]) if share_entry else None
        earnings_growth=None
        if len(eps_rows)>=2:
            prev=float(eps_rows[1]["val"] or 0);cur=float(eps_rows[0]["val"] or 0)
            if prev!=0:earnings_growth=(cur-prev)/abs(prev)
        revenue_growth=None
        if len(revenue_rows)>=2:
            prev=float(revenue_rows[1]["val"] or 0);cur=float(revenue_rows[0]["val"] or 0)
            if prev!=0:revenue_growth=(cur-prev)/abs(prev)
        payload={
            "symbol":s,"pe_ratio":None,"forward_pe":None,"peg_ratio":None,"price_to_sales_ratio":None,
            "eps":eps,"revenue_ttm":revenue,"shares_outstanding":shares,"quarterly_revenue_growth_yoy":revenue_growth,
            "quarterly_earnings_growth_yoy":earnings_growth,"market_cap":None,"earnings_date":None,"sector":None,"industry":None,
            "provider":self.name,"source_url":f"{SOURCE_ROOT}?CIK={int(cik)}","retrieved_at":datetime.now(timezone.utc).isoformat(),
            "valuation_refresh_version":4,"sec_cik":cik,"sec_fact_tags":{"revenue":revenue_tag,"eps":eps_tag,"shares":share_tag},
            "sec_measurement_note":"SEC fallback uses the most recent annual standardized XBRL revenue/EPS facts and latest reported shares. Ratios are derived from the shared market price; this is a fallback when richer trailing fundamentals are unavailable.",
        }
        if all(payload.get(k) is None for k in ["eps","revenue_ttm","shares_outstanding"]):raise RuntimeError(f"SEC Company Facts returned no usable valuation facts for {s}")
        _CACHE[s]=(time.time(),payload);return {**payload}
