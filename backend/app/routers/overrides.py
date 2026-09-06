from datetime import date, timedelta
from functools import lru_cache

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FundamentalCache
from ..providers.macroradar import macro_calendar
from .intelligence import _latest_market, current_user
from .user_state import _symbols, enhanced_opportunities

router=APIRouter(prefix="/api/v1",tags=["intelligence-overrides"])

@router.get("/opportunities")
def opportunities_override(user:str=Depends(current_user),db:Session=Depends(get_db)):
    return enhanced_opportunities(user=user,db=db)

@router.get("/regime")
def regime_override(db:Session=Depends(get_db)):
    roles={"SPY":"US equities","QQQ":"Growth / duration","IWM":"Small caps","TLT":"Long Treasuries","SHY":"Short Treasuries","HYG":"High-yield credit","UUP":"US dollar","GLD":"Gold","USO":"Crude oil","CPER":"Copper","IBIT":"Bitcoin","SMH":"Semiconductors"};signals=[]
    for symbol,label in roles.items():
        m=_latest_market(db,symbol)
        if m:signals.append({"symbol":symbol,"label":label,"day":m.get("change_percent"),"seven_day":m.get("seven_day_percent"),"thirty_day":m.get("thirty_day_percent"),"as_of":m.get("as_of")})
    x={r["symbol"]:r for r in signals};v=lambda s,k="seven_day":float((x.get(s) or {}).get(k) or 0)
    spy,qqq,iwm,tlt,shy,hyg,uup,uso,cper,ibit=v("SPY"),v("QQQ"),v("IWM"),v("TLT"),v("SHY"),v("HYG"),v("UUP"),v("USO"),v("CPER"),v("IBIT")
    factors=[
        {"factor":"Risk appetite","score":round(spy+hyg,2),"state":"risk-on" if spy+hyg>1 else "risk-off" if spy+hyg<-1 else "neutral"},
        {"factor":"Growth leadership","score":round(qqq-spy,2),"state":"growth" if qqq-spy>.5 else "value/broad" if qqq-spy<-.5 else "balanced"},
        {"factor":"Rate pressure","score":round(-tlt,2),"state":"rising-yield pressure" if tlt<-1 else "falling-yield support" if tlt>1 else "neutral"},
        {"factor":"Curve proxy","score":round(tlt-shy,2),"state":"long-duration outperforming" if tlt-shy>.5 else "short-duration outperforming" if tlt-shy<-.5 else "balanced"},
        {"factor":"Dollar pressure","score":round(uup,2),"state":"stronger dollar" if uup>.5 else "weaker dollar" if uup<-.5 else "neutral"},
        {"factor":"Breadth","score":round(iwm-spy,2),"state":"broadening" if iwm-spy>.5 else "narrowing" if iwm-spy<-.5 else "neutral"},
        {"factor":"Industrial commodities","score":round((uso+cper)/2,2),"state":"firm" if (uso+cper)/2>1 else "weak" if (uso+cper)/2<-1 else "neutral"},
        {"factor":"Crypto risk appetite","score":round(ibit,2),"state":"firm" if ibit>2 else "weak" if ibit<-2 else "neutral"},
    ]
    return {"factors":factors,"cross_asset":signals,"methodology":"Regime state uses stored ETF proxies for equities, duration, curve shape, credit, dollar, oil, copper and Bitcoin. It reuses the shared Twelve Data cache and does not create a second provider path."}

@lru_cache(maxsize=8)
def _macro_window(start:str,end:str):
    return macro_calendar(start,end)


def _sensitivity(title:str,symbols:list[str],db:Session):
    text=title.lower();sector_targets=set();explicit=set();reason="Broad macro exposure"
    if any(k in text for k in ["fed","fomc","interest rate","inflation","cpi","pce","yield","treasury"]):
        sector_targets.update(["Technology","Financials","Real Estate","Utilities"]);explicit.update(["QQQ","TLT","SHY"]);reason="Rates/inflation sensitivity"
    elif any(k in text for k in ["oil","crude","energy","opec"]):sector_targets.add("Energy");explicit.add("USO");reason="Energy-price sensitivity"
    elif any(k in text for k in ["manufacturing","pmi","gdp","industrial"]):sector_targets.update(["Industrials","Materials","Technology"]);explicit.update(["IWM","SMH","CPER"]);reason="Growth/industrial-cycle sensitivity"
    elif any(k in text for k in ["jobs","employment","payroll","unemployment"]):explicit.update(["SPY","QQQ","IWM"]);reason="Broad growth/rates sensitivity"
    out=[]
    for s in symbols:
        m=_latest_market(db,s) or {};sector=str(m.get("sector") or "")
        if s in explicit or sector in sector_targets:out.append(s)
    return out[:10],reason

@router.get("/events")
def events_override(days:int=Query(default=60,ge=7,le=180),user:str=Depends(current_user),db:Session=Depends(get_db)):
    start=date.today();end=start+timedelta(days=days);symbols=_symbols(db,user);items=[];source={}
    try:
        cal=_macro_window(start.isoformat(),end.isoformat());source={"provider":cal.get("provider"),"source_url":cal.get("source_url")}
        for e in cal.get("events",[]):
            title=str(e.get("title") or e.get("event") or e.get("name") or "Macro event");sensitive,reason=_sensitivity(title,symbols,db);items.append({**e,"kind":"macro","sensitive_symbols":sensitive,"sensitivity_reason":reason,"description":f"{reason}. Tracked symbols potentially exposed: {', '.join(sensitive) if sensitive else 'none identified from cached sector mappings'}."})
    except Exception as exc:source={"provider":"unavailable","error":str(exc)}
    for f in db.query(FundamentalCache).filter(FundamentalCache.symbol.in_(symbols)).all() if symbols else []:
        dt=(f.payload or {}).get("earnings_date")
        if dt and start.isoformat()<=str(dt)[:10]<=end.isoformat():items.append({"event_date":str(dt)[:10],"title":f"{f.symbol} earnings","symbol":f.symbol,"kind":"earnings","provider":f.provider,"sensitive_symbols":[f.symbol],"sensitivity_reason":"Direct company catalyst","description":f"Direct earnings catalyst for {f.symbol}."})
    items.sort(key=lambda x:str(x.get("event_date") or x.get("date") or ""))
    return {"events":items,"source":source,"window":{"start":start.isoformat(),"end":end.isoformat()},"watchlist_context":symbols,"provider_calls":"Macro calendar is process-cached by date window; sensitivity uses stored symbol metadata."}
