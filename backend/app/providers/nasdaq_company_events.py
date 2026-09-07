from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median

import httpx

API_ROOT="https://api.nasdaq.com/api"
SOURCE_ROOT="https://www.nasdaq.com/market-activity/stocks"
_HEADERS={
    "Accept":"application/json, text/plain, */*",
    "User-Agent":"Mozilla/5.0",
    "Origin":"https://www.nasdaq.com",
    "Referer":"https://www.nasdaq.com/",
}


def _parse_report_date(value):
    if not value:return None
    text=str(value).strip()
    for fmt in ("%m/%d/%Y","%m/%d/%y","%Y-%m-%d"):
        try:return datetime.strptime(text,fmt).date()
        except ValueError:pass
    return None


class NasdaqCompanyEventsProvider:
    name="Nasdaq"

    def _json(self,path):
        with httpx.Client(timeout=20,follow_redirects=True,headers=_HEADERS) as client:
            r=client.get(f"{API_ROOT}{path}");r.raise_for_status();data=r.json()
        status=data.get("status") or {}
        if status.get("rCode") not in (None,200):raise RuntimeError(f"Nasdaq API status {status.get('rCode')}")
        return data.get("data") or {}

    def earnings_estimate(self,symbol:str)->dict:
        s=symbol.strip().upper();data=self._json(f"/company/{s}/earnings-surprise")
        table=data.get("earningsSurpriseTable") or {};rows=table.get("rows") or []
        reports=sorted({d for d in (_parse_report_date(x.get("dateReported")) for x in rows) if d})
        today=date.today();past=[d for d in reports if d<=today]
        checked=datetime.now(timezone.utc).isoformat()
        base={"symbol":s,"provider":self.name,"source_url":f"{SOURCE_ROOT}/{s.lower()}/earnings","nasdaq_calendar_retrieved_at":checked}
        if not past:return base
        intervals=[(b-a).days for a,b in zip(past,past[1:]) if 60<=(b-a).days<=120]
        cadence=int(round(median(intervals[-4:]))) if intervals else 91
        cadence=max(70,min(110,cadence));last=past[-1];estimated=last+timedelta(days=cadence)
        while estimated<=today:estimated+=timedelta(days=cadence)
        spread=max(5,min(10,round(cadence*.08)))
        return {**base,"earnings_date_estimate":estimated.isoformat(),"earnings_date_estimate_start":(estimated-timedelta(days=spread)).isoformat(),"earnings_date_estimate_end":(estimated+timedelta(days=spread)).isoformat(),"earnings_estimate_cadence_days":cadence,"earnings_estimate_last_reported":last.isoformat(),"earnings_estimate_sample_count":len(past),"earnings_date_estimate_method":"estimated from median interval between recent Nasdaq-reported earnings dates; not a confirmed company announcement"}
