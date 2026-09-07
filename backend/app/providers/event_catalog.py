from __future__ import annotations

import calendar
import re
import time
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser

import httpx

from .fred_calendar import fred_bls_events
from .macroradar import macro_calendar

BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_SOURCE = "https://www.bls.gov/schedule/"
BEA_SOURCE = "https://www.bea.gov/news/schedule"
FED_SOURCE = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_SECONDS = 6 * 60 * 60

HIGH_IMPACT = (
    "fomc", "consumer price index", "cpi", "employment situation", "payroll", "gross domestic product",
    "gdp", "personal income and outlays", "pce", "producer price index", "ppi", "job openings",
    "jolts", "employment cost index", "eci", "federal funds", "interest rate",
)
MEDIUM_IMPACT = (
    "productivity", "import and export price", "trade", "personal income", "retail", "industrial production",
    "consumer credit", "beige book", "international transactions", "corporate profits", "unemployment",
)


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__();self.in_tr=False;self.in_td=False;self.current_cell=[];self.current_row=[];self.rows=[]
    def handle_starttag(self,tag,attrs):
        if tag=="tr":self.in_tr=True;self.current_row=[]
        elif tag in {"td","th"} and self.in_tr:self.in_td=True;self.current_cell=[]
    def handle_data(self,data):
        if self.in_td:
            text=" ".join(data.split())
            if text:self.current_cell.append(text)
    def handle_endtag(self,tag):
        if tag in {"td","th"} and self.in_td:self.current_row.append(" ".join(self.current_cell).strip());self.current_cell=[];self.in_td=False
        elif tag=="tr" and self.in_tr:
            if any(self.current_row):self.rows.append(self.current_row)
            self.current_row=[];self.in_tr=False


def _impact(title:str):
    t=title.lower()
    if any(k in t for k in HIGH_IMPACT):return "high",3
    if any(k in t for k in MEDIUM_IMPACT):return "medium",2
    return "low",1


def _category(title:str,source:str):
    t=title.lower()
    if "fomc" in t or "federal reserve" in t or "beige book" in t or "interest rate" in t:return "Central banks"
    if any(k in t for k in ["consumer price","producer price","inflation","pce","price index"]):return "Inflation"
    if any(k in t for k in ["employment","job openings","jolts","unemployment","earnings","wages"]):return "Labor"
    if any(k in t for k in ["gdp","personal income","corporate profits","productivity"]):return "Growth"
    if "trade" in t or "international" in t:return "Trade"
    if source=="Earnings cache":return "Earnings"
    return "Economic data"


def _event(event_date,title,source,source_url,*,event_time=None,symbol=None,detail=None):
    impact,score=_impact(title)
    return {"event_date":event_date,"time":event_time,"title":title,"category":_category(title,source),"impact":impact,"impact_score":score,"source":source,"source_url":source_url,"symbol":symbol,"description":detail}


def _unfold_ics(text):
    out=[]
    for raw in text.replace("\r\n","\n").split("\n"):
        if raw.startswith((" ","\t")) and out:out[-1]+=raw[1:]
        else:out.append(raw)
    return out


def bls_events(start,end):
    with httpx.Client(timeout=20,follow_redirects=True) as client:
        r=client.get(BLS_ICS,headers={"User-Agent":"DailyReportApp/2.1"});r.raise_for_status()
    blocks=[];current=None
    for line in _unfold_ics(r.text):
        if line=="BEGIN:VEVENT":current={}
        elif line=="END:VEVENT" and current is not None:blocks.append(current);current=None
        elif current is not None and ":" in line:
            key,value=line.split(":",1);current[key.split(";",1)[0]]=value.replace("\\,",",").replace("\\n"," ").strip()
    out=[]
    for item in blocks:
        digits=re.sub(r"\D","",str(item.get("DTSTART") or ""))
        if len(digits)<8:continue
        try:d=datetime.strptime(digits[:8],"%Y%m%d").date()
        except ValueError:continue
        if not start<=d<=end:continue
        event_time=f"{digits[8:10]}:{digits[10:12]}" if len(digits)>=12 else None
        title=str(item.get("SUMMARY") or "BLS release").strip()
        out.append(_event(d.isoformat(),title,"BLS",BLS_SOURCE,event_time=event_time,detail="Official Bureau of Labor Statistics scheduled release."))
    return out


def bea_events(start,end):
    with httpx.Client(timeout=20,follow_redirects=True) as client:
        r=client.get(BEA_SOURCE,headers={"User-Agent":"DailyReportApp/2.1"});r.raise_for_status()
    p=_TableParser();p.feed(r.text);out=[];month_names="|".join(calendar.month_name[1:]);rx=re.compile(rf"({month_names})\s+(\d{{1,2}})(?:\s+(\d{{1,2}}:\d{{2}}\s*[AP]M))?",re.I)
    for row in p.rows:
        joined=" | ".join(row);m=rx.search(joined)
        if not m:continue
        year_match=re.search(r"\b(20\d{2})\b",joined);year=int(year_match.group(1)) if year_match else start.year
        try:d=datetime.strptime(f"{m.group(1)} {m.group(2)} {year}","%B %d %Y").date()
        except ValueError:continue
        if not start<=d<=end:continue
        title=next((c for c in reversed(row) if len(c)>12 and not rx.search(c)),"BEA economic release")
        out.append(_event(d.isoformat(),title,"BEA",BEA_SOURCE,event_time=m.group(3),detail="Official Bureau of Economic Analysis scheduled release."))
    return out


_FOMC={2026:[(9,15,16,True),(10,27,28,False),(12,8,9,True)],2027:[(1,26,27,False),(3,16,17,True),(4,27,28,False),(6,8,9,True),(7,27,28,False),(9,14,15,True),(10,26,27,False),(12,7,8,True)]}

def fed_events(start,end):
    out=[]
    for year,meetings in _FOMC.items():
        for month,day1,day2,sep in meetings:
            d=date(year,month,day2)
            if start<=d<=end:
                detail=f"FOMC two-day meeting {calendar.month_name[month]} {day1}-{day2}. Policy statement and press conference are normally on the second day."+(" Meeting includes Summary of Economic Projections." if sep else "")
                out.append(_event(d.isoformat(),"FOMC policy decision","Federal Reserve",FED_SOURCE,event_time="14:00",detail=detail));out.append(_event(d.isoformat(),"FOMC press conference","Federal Reserve",FED_SOURCE,event_time="14:30",detail="Federal Reserve Chair press conference following the policy decision."))
                minutes=d+timedelta(days=21)
                if start<=minutes<=end:out.append(_event(minutes.isoformat(),"FOMC meeting minutes","Federal Reserve",FED_SOURCE,event_time="14:00",detail="Minutes are generally released three weeks after a scheduled FOMC meeting."))
    return out


def macroradar_events(start,end):
    try:payload=macro_calendar(start.isoformat(),end.isoformat())
    except Exception:return []
    out=[]
    for x in payload.get("events",[]):
        d=str(x.get("event_date") or "")[:10]
        if not d:continue
        title=str(x.get("title") or "Macro event")
        out.append(_event(d,title,"MacroRadar",x.get("source_url") or payload.get("source_url") or "https://www.macroradar.io/developers",detail="MacroRadar calendar event."))
    return out


def _fred_fallback(start,end):
    payload=fred_bls_events(start,end);out=[]
    for row in payload.get("events",[]):
        out.append(_event(row["event_date"],row["title"],"FRED / BLS schedule",row["source_url"],event_time=row.get("time"),detail="BLS release date mirrored by the Federal Reserve Bank of St. Louis FRED release calendar because direct BLS calendar requests may block hosted servers."))
    return out,payload.get("errors") or []


def catalog(start,end):
    key=f"{start.isoformat()}:{end.isoformat()}";cached=_CACHE.get(key)
    if cached and time.time()-cached[0]<CACHE_SECONDS:return cached[1]
    providers=[];events=[];errors=[];bls_ok=False
    for name,loader in [("BLS",bls_events),("BEA",bea_events),("Federal Reserve",fed_events),("MacroRadar",macroradar_events)]:
        try:
            rows=loader(start,end);events.extend(rows);providers.append({"provider":name,"count":len(rows),"status":"ok"});bls_ok=bls_ok or (name=="BLS" and bool(rows))
        except Exception as exc:
            errors.append(f"{name}: {exc}");providers.append({"provider":name,"count":0,"status":"unavailable"})
    if not bls_ok:
        try:
            rows,fred_errors=_fred_fallback(start,end);events.extend(rows);providers.append({"provider":"FRED BLS calendar fallback","count":len(rows),"status":"ok" if rows else "empty"});errors.extend([f"FRED fallback: {x}" for x in fred_errors])
        except Exception as exc:
            errors.append(f"FRED BLS calendar fallback: {exc}");providers.append({"provider":"FRED BLS calendar fallback","count":0,"status":"unavailable"})
    dedup={}
    for e in events:
        key2=(e.get("event_date"),str(e.get("title") or "").lower(),e.get("symbol"));old=dedup.get(key2)
        if old is None or int(e.get("impact_score") or 0)>int(old.get("impact_score") or 0):dedup[key2]=e
    result={"events":list(dedup.values()),"providers":providers,"errors":errors,"retrieved_at":datetime.now(timezone.utc).isoformat()};_CACHE[key]=(time.time(),result);return result
