from __future__ import annotations
import os
from datetime import datetime, timezone
import httpx

ALPACA_BASE="https://data.alpaca.markets"
TIINGO_BASE="https://api.tiingo.com"

class IntradayProviderError(RuntimeError):pass

def _iso(value):
    if isinstance(value,datetime):
        if value.tzinfo is None:value=value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)

class AlpacaIntradayProvider:
    name="Alpaca"
    def __init__(self):
        self.key=os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
        self.secret=os.getenv("ALPACA_API_SECRET") or os.getenv("APCA_API_SECRET_KEY")
        if not self.key or not self.secret:raise IntradayProviderError("Alpaca credentials are not configured")
    @property
    def headers(self):return {"APCA-API-KEY-ID":self.key,"APCA-API-SECRET-KEY":self.secret}
    def stock_bars(self,symbol,start,end,timeframe="1Min",feed="iex",limit=10000):
        rows=[];token=None
        with httpx.Client(timeout=45.0) as client:
            while True:
                params={"timeframe":timeframe,"start":_iso(start),"end":_iso(end),"feed":feed,"limit":limit,"sort":"asc"}
                if token:params["page_token"]=token
                r=client.get(f"{ALPACA_BASE}/v2/stocks/{symbol.upper()}/bars",headers=self.headers,params=params);r.raise_for_status();data=r.json()
                rows.extend(data.get("bars") or []);token=data.get("next_page_token")
                if not token:break
        return {"provider":self.name,"feed":feed,"source_url":"https://docs.alpaca.markets/us/reference/stockbarsingle-1","bars":rows}
    def option_bars(self,contracts,start,end,timeframe="1Min",feed="indicative",limit=10000):
        symbols=",".join(contracts);rows=[];token=None
        with httpx.Client(timeout=45.0) as client:
            while True:
                params={"symbols":symbols,"timeframe":timeframe,"start":_iso(start),"end":_iso(end),"feed":feed,"limit":limit,"sort":"asc"}
                if token:params["page_token"]=token
                r=client.get(f"{ALPACA_BASE}/v1beta1/options/bars",headers=self.headers,params=params);r.raise_for_status();data=r.json()
                for contract,bars in (data.get("bars") or {}).items():
                    for bar in bars:rows.append((contract,bar))
                token=data.get("next_page_token")
                if not token:break
        return {"provider":self.name,"feed":feed,"source_url":"https://docs.alpaca.markets/us/reference/optionbars","bars":rows}

class TiingoIntradayProvider:
    name="Tiingo"
    def __init__(self):
        self.token=os.getenv("TIINGO_API_TOKEN")
        if not self.token:raise IntradayProviderError("TIINGO_API_TOKEN is not configured")
    def stock_bars(self,symbol,start,end,resample="1min",derived=True):
        path="tiingo/equity/intraday" if derived else "iex"
        url=f"{TIINGO_BASE}/{path}/{symbol.upper()}/prices"
        params={"startDate":str(start)[:10],"endDate":str(end)[:10],"resampleFreq":resample,"token":self.token,"columns":"open,high,low,close,volume"}
        with httpx.Client(timeout=45.0) as client:r=client.get(url,params=params);r.raise_for_status();rows=r.json()
        return {"provider":self.name,"feed":"derived_multi_venue" if derived else "iex","source_url":"https://www.tiingo.com/documentation/equity-realtime-stock-data","bars":rows}
