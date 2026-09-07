from __future__ import annotations

from datetime import date

SOURCE_ROOT="https://fred.stlouisfed.org/releases/calendar"

# FRED mirrors dates supplied by the underlying data agencies. Render currently
# cannot reliably reach either BLS or FRED, so keep the already-published 2026
# high-impact BLS schedule in-process rather than delaying every Events request.
# These dates were rechecked against the FRED release calendars on 2026-09-07.
# Only published dates are included; the app does not fabricate 2027 dates.
_PUBLISHED_2026={
    10:("Consumer Price Index","7:30 am",["2026-09-11","2026-10-14","2026-11-10","2026-12-10"]),
    46:("Producer Price Index","7:30 am",["2026-09-10","2026-10-15","2026-11-13","2026-12-15"]),
    50:("Employment Situation","7:30 am",["2026-10-02","2026-11-06","2026-12-04"]),
    192:("Job Openings and Labor Turnover Survey","9:00 am",["2026-09-29","2026-11-03","2026-12-01"]),
    11:("Employment Cost Index","7:30 am",["2026-10-30"]),
}


def fred_bls_events(start:date,end:date):
    out=[]
    for rid,(title,event_time,dates) in _PUBLISHED_2026.items():
        source=f"{SOURCE_ROOT}?rid={rid}&y=2026"
        for raw in dates:
            d=date.fromisoformat(raw)
            if start<=d<=end:
                out.append({"event_date":raw,"time":event_time,"title":title,"source_url":source,"calendar_status":"published","snapshot_verified":"2026-09-07"})
    out.sort(key=lambda e:(e["event_date"],e["title"]))
    return {"events":out,"errors":[],"provider":"FRED release calendar snapshot","snapshot_verified":"2026-09-07"}
