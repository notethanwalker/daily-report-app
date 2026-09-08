from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import FeatureSnapshot, FlowEvent, FundamentalCache, MarketSnapshot, SymbolRegistry
from .feature_model_v4 import version_payload

COMPONENT_WEIGHTS={"technical":.25,"valuation":.20,"sector":.15,"flow":.15,"momentum":.15,"risk":.10}
SECTOR_PROXY={"Technology":"XLK","Financials":"XLF","Energy":"XLE","Healthcare":"XLV","Industrials":"XLI","Materials":"XLB","Utilities":"XLU","Real Estate":"XLRE","Communication Services":"XLC","Consumer Discretionary":"XLY","Consumer Staples":"XLP"}


def _latest_market(db:Session,symbol:str)->dict|None:
    row=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol.upper()).order_by(MarketSnapshot.retrieved_at.desc()).first()
    if not row:return None
    p=dict(row.payload or {});p.setdefault("symbol",symbol.upper());p["retrieved_at"]=row.retrieved_at.isoformat()
    f=db.get(FundamentalCache,symbol.upper())
    if f:p.update(f.payload or {});p["fundamentals_retrieved_at"]=f.retrieved_at.isoformat()
    return p


def _flow_bias(payload:dict)->str:
    side=str(payload.get("side") or "").lower();ag=str(payload.get("aggression") or payload.get("execution") or "").lower()
    buy=any(x in ag for x in ("buy","ask","lift"));sell=any(x in ag for x in ("sell","bid","hit"))
    if (side=="call" and buy) or (side=="put" and sell):return "bull"
    if (side=="call" and sell) or (side=="put" and buy):return "bear"
    return "neutral"


def recent_flow(db:Session,symbol:str,hours:int=72)->dict:
    since=datetime.now(timezone.utc)-timedelta(hours=hours)
    rows=db.query(FlowEvent).filter(FlowEvent.symbol==symbol.upper(),FlowEvent.occurred_at>=since).order_by(FlowEvent.occurred_at.desc()).limit(100).all()
    out={"bullish_premium":0.0,"bearish_premium":0.0,"events":0}
    for r in rows:
        p=r.payload or {};premium=float(p.get("premium") or 0);bias=_flow_bias(p)
        if bias=="bull":out["bullish_premium"]+=premium
        elif bias=="bear":out["bearish_premium"]+=premium
        out["events"]+=1
    return out


def _sector_score(db:Session,market:dict):
    proxy=SECTOR_PROXY.get(str(market.get("sector"))) if market.get("sector") else None
    if not proxy:return None
    p=_latest_market(db,proxy)
    if not p:return None
    return round(float(p.get("change_percent") or 0)*.25+float(p.get("seven_day_percent") or 0)*.45+float(p.get("thirty_day_percent") or 0)*.30,3)


def opportunity_components(db:Session,symbol:str,market:dict|None=None)->dict|None:
    m=market or _latest_market(db,symbol)
    if not m:return None
    will=m.get("williams_r_14");pe=m.get("pe_ratio");ps=m.get("price_to_sales_ratio");peg=m.get("peg_ratio")
    ma100=m.get("price_vs_ma100_percent");ma200=m.get("price_vs_ma200_percent");ath=m.get("price_vs_ath_percent")
    d7=float(m.get("seven_day_percent") or 0);d30=float(m.get("thirty_day_percent") or 0);rv=float(m.get("relative_volume") or 0)
    technical=50.0
    if will is not None:technical+=max(-20,min(20,(-50-float(will))*.5))
    if ma100 is not None and abs(float(ma100))<=10:technical+=8
    if ma200 is not None and abs(float(ma200))<=10:technical+=10
    technical+=max(-12,min(12,d7*.6+d30*.2))
    valuation=50.0
    if pe is not None and float(pe)>0:valuation+=max(-20,min(20,(30-float(pe))*.8))
    if ps is not None:valuation+=max(-15,min(15,(6-float(ps))*2.5))
    if peg is not None and float(peg)>0:valuation+=max(-15,min(15,(2-float(peg))*8))
    flow=recent_flow(db,symbol);cap=float(m.get("market_cap") or 0);net=flow["bullish_premium"]-flow["bearish_premium"]
    flow_score=50+max(-30,min(30,(net/max(cap,1))*100000)) if cap else 50
    sector=_sector_score(db,m);sector_component=50+max(-25,min(25,(sector or 0)*4))
    risk=50.0
    if ath is not None and float(ath)>-5:risk-=10
    if rv>1.5:risk+=8
    momentum=50+max(-30,min(30,d7*2+d30*.5))
    components={"technical":round(max(0,min(100,technical)),1),"valuation":round(max(0,min(100,valuation)),1),"sector":round(max(0,min(100,sector_component)),1),"flow":round(max(0,min(100,flow_score)),1),"momentum":round(max(0,min(100,momentum)),1),"risk":round(max(0,min(100,risk)),1)}
    total=sum(components[k]*w for k,w in COMPONENT_WEIGHTS.items())
    return {"symbol":symbol.upper(),"buy_score":round(total,1),"sell_score":round(100-total,1),"components":components,"flow":flow,"sector_score":sector,"market":m}


def feature_payload(db:Session,symbol:str)->dict|None:
    o=opportunity_components(db,symbol)
    if not o:return None
    m=o["market"]
    return version_payload({"return_1d":m.get("change_percent"),"return_7d":m.get("seven_day_percent"),"return_30d":m.get("thirty_day_percent"),"ma100_distance":m.get("price_vs_ma100_percent"),"ma200_distance":m.get("price_vs_ma200_percent"),"williams_r":m.get("williams_r_14"),"relative_volume":m.get("relative_volume"),"pe":m.get("pe_ratio"),"ps":m.get("price_to_sales_ratio"),"peg":m.get("peg_ratio"),"sector_score":o.get("sector_score"),"bullish_flow":o["flow"]["bullish_premium"],"bearish_flow":o["flow"]["bearish_premium"],"buy_score":o["buy_score"],"sell_score":o["sell_score"],"components":o["components"]})


def refresh_feature(db:Session,symbol:str)->dict|None:
    s=symbol.upper();m=_latest_market(db,s)
    if not m:return None
    payload=feature_payload(db,s)
    if payload is None:return None
    as_of=str(m.get("as_of") or date.today().isoformat())[:10]
    row=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==s,FeatureSnapshot.as_of==as_of).first()
    if row:row.payload=payload
    else:db.add(FeatureSnapshot(symbol=s,as_of=as_of,payload=payload))
    reg=db.get(SymbolRegistry,s)
    if not reg:reg=SymbolRegistry(symbol=s,themes={},provider_ids={});db.add(reg)
    reg.name=m.get("name") or reg.name;reg.asset_type=m.get("type") or m.get("asset_type") or reg.asset_type;reg.exchange=m.get("exchange") or reg.exchange;reg.sector=m.get("sector") or reg.sector;reg.industry=m.get("industry") or reg.industry
    db.commit();return payload
