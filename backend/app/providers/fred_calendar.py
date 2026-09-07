from __future__ import annotations

import re
from datetime import date, datetime
from html.parser import HTMLParser

import httpx

SOURCE_ROOT="https://fred.stlouisfed.org/releases/calendar"
RELEASES={
    10:"Consumer Price Index",
    46:"Producer Price Index",
    50:"Employment Situation",
    192:"Job Openings and Labor Turnover Survey",
    11:"Employment Cost Index",
}


class _Rows(HTMLParser):
    def __init__(self):
        super().__init__();self.in_row=False;self.in_cell=False;self.cell=[];self.row=[];self.rows=[]
    def handle_starttag(self,tag,attrs):
        if tag=="tr":self.in_row=True;self.row=[]
        elif self.in_row and tag in {"td","th"}:self.in_cell=True;self.cell=[]
    def handle_data(self,data):
        if self.in_cell:
            t=" ".join(data.split())
            if t:self.cell.append(t)
    def handle_endtag(self,tag):
        if tag in {"td","th"} and self.in_cell:self.row.append(" ".join(self.cell));self.in_cell=False
        elif tag=="tr" and self.in_row:
            if self.row:self.rows.append(self.row)
            self.in_row=False


def _parse_date(text):
    clean=re.sub(r"\s+Updated\s*$","",str(text or "").strip(),flags=re.I)
    for fmt in ("%A %B %d, %Y","%B %d, %Y"):
        try:return datetime.strptime(clean,fmt).date()
        except ValueError:pass
    m=re.search(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})",clean,re.I)
    if m:
        try:return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}","%B %d %Y").date()
        except ValueError:return None
    return None


def fred_bls_events(start:date,end:date):
    out=[];errors=[]
    headers={"User-Agent":"DailyReportApp/2.1","Accept":"text/html,application/xhtml+xml"}
    with httpx.Client(timeout=20,follow_redirects=True,headers=headers) as client:
        for rid,default_title in RELEASES.items():
            url=f"{SOURCE_ROOT}?rid={rid}&vs={start.isoformat()}&ve={end.isoformat()}&od=asc"
            try:
                r=client.get(url);r.raise_for_status();p=_Rows();p.feed(r.text)
                for row in p.rows:
                    d=next((_parse_date(c) for c in row if _parse_date(c)),None)
                    if not d or not start<=d<=end:continue
                    event_time=next((c for c in row if re.fullmatch(r"\d{1,2}:\d{2}\s*[ap]m",c,re.I)),None)
                    title=next((c for c in reversed(row) if default_title.lower() in c.lower()),default_title)
                    out.append({"event_date":d.isoformat(),"time":event_time,"title":title,"source_url":url})
            except Exception as exc:errors.append(f"{default_title}: {str(exc)[:160]}")
    dedup={(e["event_date"],e["title"]):e for e in out}
    return {"events":sorted(dedup.values(),key=lambda e:e["event_date"]),"errors":errors,"provider":"FRED release calendar"}
