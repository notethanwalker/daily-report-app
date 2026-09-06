from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from .intelligence import _latest_market, current_user
from .user_state import enhanced_opportunities

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
