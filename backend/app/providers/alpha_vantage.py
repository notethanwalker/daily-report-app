import os
from datetime import datetime, timezone

import httpx

from .yahoo_finance import YahooFinanceProvider

BASE_URL = "https://www.alphavantage.co/query"
SOURCE_URL = "https://www.alphavantage.co/documentation/"

class AlphaVantageError(RuntimeError):
    pass

class AlphaVantageProvider:
    name = "Alpha Vantage"
    def __init__(self):
        self.api_key=os.getenv("ALPHA_VANTAGE_API_KEY")
        if not self.api_key: raise AlphaVantageError("ALPHA_VANTAGE_API_KEY is not configured")
    def _get(self,params:dict)->dict:
        request_params={**params,"apikey":self.api_key}
        try:
            with httpx.Client(timeout=20.0) as client:
                response=client.get(BASE_URL,params=request_params);response.raise_for_status();data=response.json()
        except Exception as exc:
            raise AlphaVantageError("Alpha Vantage request failed") from exc
        error=data.get("Error Message") or data.get("Information") or data.get("Note")
        if error: raise AlphaVantageError("Alpha Vantage provider unavailable or quota reached")
        return data
    def daily_history(self,symbol:str)->dict:
        data=self._get({"function":"TIME_SERIES_DAILY","symbol":symbol,"outputsize":"compact"})
        series=data.get("Time Series (Daily)") or {}
        if not series: raise AlphaVantageError(f"No Alpha Vantage daily history returned for {symbol}")
        rows=[]
        for day,item in series.items():
            try: rows.append({"date":day,"open":float(item["1. open"]),"high":float(item["2. high"]),"low":float(item["3. low"]),"close":float(item["4. close"]),"volume":float(item["5. volume"])})
            except (KeyError,TypeError,ValueError): continue
        rows.sort(key=lambda row:row["date"])
        if not rows: raise AlphaVantageError(f"No usable Alpha Vantage rows returned for {symbol}")
        return {"symbol":symbol.upper(),"rows":rows,"provider":self.name,"source_url":SOURCE_URL,"retrieved_at":datetime.now(timezone.utc).isoformat()}
    def overview(self,symbol:str)->dict:
        try:
            data=self._get({"function":"OVERVIEW","symbol":symbol})
            if not data or not data.get("Symbol"): raise AlphaVantageError("No company overview available")
            def num(key):
                try:
                    v=data.get(key)
                    return None if v in (None,"","None","-") else float(v)
                except (TypeError,ValueError): return None
            return {
                "symbol":symbol.upper(),
                "name":data.get("Name"),
                "sector":data.get("Sector"),
                "industry":data.get("Industry"),
                "pe_ratio":num("PERatio"),
                "forward_pe":num("ForwardPE"),
                "peg_ratio":num("PEGRatio"),
                "price_to_sales_ratio":num("PriceToSalesRatioTTM"),
                "eps":num("EPS"),
                "revenue_ttm":num("RevenueTTM"),
                "quarterly_revenue_growth_yoy":num("QuarterlyRevenueGrowthYOY"),
                "quarterly_earnings_growth_yoy":num("QuarterlyEarningsGrowthYOY"),
                "market_cap":num("MarketCapitalization"),
                "provider":self.name,
                "source_url":SOURCE_URL,
                "retrieved_at":datetime.now(timezone.utc).isoformat()
            }
        except Exception as alpha_exc:
            try:
                payload=YahooFinanceProvider().overview(symbol)
                payload["fallback_reason"]="Alpha Vantage OVERVIEW unavailable"
                payload["fallback_from"]="Alpha Vantage"
                return payload
            except Exception as yahoo_exc:
                raise AlphaVantageError(f"Fundamentals unavailable from Alpha Vantage and Yahoo Finance for {symbol}") from yahoo_exc
