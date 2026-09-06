import math
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    AlertRule,
    FeatureSnapshot,
    FlowEvent,
    FundamentalCache,
    HistoricalDailyBar,
    MarketSnapshot,
    PortfolioHolding,
    RefreshQueueItem,
    SymbolRegistry,
    Thesis,
    UserProfile,
    UserWatchlistItem,
    WatchlistItem,
)
from ..providers.macroradar import macro_calendar
from ..providers.twelve_data import TwelveDataProvider
from ..services.calculations import build_market_snapshot
from ..services.provider_orchestrator import FRESHNESS_POLICIES, ProviderOrchestrator, is_stale
from ..services.rotation import SECTORS

router = APIRouter(prefix="/api/v1", tags=["intelligence"])

SECTOR_PROXY = {
    "Technology": "XLK", "Financials": "XLF", "Energy": "XLE", "Healthcare": "XLV",
    "Industrials": "XLI", "Materials": "XLB", "Utilities": "XLU", "Real Estate": "XLRE",
    "Communication Services": "XLC", "Consumer Discretionary": "XLY", "Consumer Staples": "XLP",
}
CROSS_ASSET = {
    "SPY": "US equities", "QQQ": "Growth / duration", "IWM": "Small caps", "TLT": "Long Treasuries",
    "HYG": "High-yield credit", "UUP": "US dollar", "GLD": "Gold", "USO": "Crude oil", "SMH": "Semiconductors",
}


def _allowed_users():
    return {x.strip().lower() for x in os.getenv("ALLOWED_USER_EMAILS", "").split(",") if x.strip()}


def current_user(x_user_email: str | None = Header(default=None, alias="X-User-Email"), db: Session = Depends(get_db)) -> str:
    allowed = _allowed_users()
    if not allowed:
        email = (x_user_email or os.getenv("OWNER_EMAIL") or "owner@local").lower()
    else:
        if not x_user_email:
            raise HTTPException(401, "User verification required")
        email = x_user_email.lower()
        if email not in allowed:
            raise HTTPException(403, "User is not on the approved allowlist")
    profile = db.query(UserProfile).filter(UserProfile.email == email).first()
    if profile and not profile.enabled:
        raise HTTPException(403, "User access is disabled")
    if not profile:
        profile = UserProfile(email=email, role="owner" if email == (os.getenv("OWNER_EMAIL") or "owner@local").lower() else "approved_user")
        db.add(profile); db.commit()
    return email


def _latest_market(db: Session, symbol: str):
    row = db.query(MarketSnapshot).filter(MarketSnapshot.symbol == symbol.upper()).order_by(MarketSnapshot.retrieved_at.desc()).first()
    if not row:
        return None
    payload = {**(row.payload or {})}
    payload.setdefault("symbol", symbol.upper())
    payload["retrieved_at"] = row.retrieved_at.isoformat()
    f = db.get(FundamentalCache, symbol.upper())
    if f:
        payload.update(f.payload or {})
        payload["fundamentals_retrieved_at"] = f.retrieved_at.isoformat()
    return payload


def _all_symbols(db: Session):
    symbols = {r.symbol for r in db.query(WatchlistItem).all()}
    symbols |= {r.symbol for r in db.query(UserWatchlistItem).all()}
    symbols |= {r.symbol for r in db.query(PortfolioHolding).all()}
    return sorted(symbols)


def _flow_bias(payload: dict):
    side = str(payload.get("side") or "").lower()
    aggression = str(payload.get("aggression") or payload.get("execution") or "").lower()
    buy = any(x in aggression for x in ["buy", "ask", "lift"])
    sell = any(x in aggression for x in ["sell", "bid", "hit"])
    if (side == "call" and buy) or (side == "put" and sell): return "bull"
    if (side == "call" and sell) or (side == "put" and buy): return "bear"
    return "neutral"


def _recent_flow(db: Session, symbol: str, hours: int = 72):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = db.query(FlowEvent).filter(FlowEvent.symbol == symbol.upper(), FlowEvent.occurred_at >= since).order_by(FlowEvent.occurred_at.desc()).limit(100).all()
    out = {"bullish_premium": 0.0, "bearish_premium": 0.0, "events": 0}
    for r in rows:
        p = r.payload or {}; premium = float(p.get("premium") or 0)
        bias = _flow_bias(p)
        if bias == "bull": out["bullish_premium"] += premium
        elif bias == "bear": out["bearish_premium"] += premium
        out["events"] += 1
    return out


def _sector_score(db: Session, market: dict):
    sector = market.get("sector")
    proxy = SECTOR_PROXY.get(str(sector)) if sector else None
    if not proxy: return None
    p = _latest_market(db, proxy)
    if not p: return None
    d = float(p.get("change_percent") or 0); w = float(p.get("seven_day_percent") or 0); m = float(p.get("thirty_day_percent") or 0)
    return round(d * .25 + w * .45 + m * .30, 3)


def _opportunity_components(db: Session, symbol: str, market: dict | None = None):
    m = market or _latest_market(db, symbol)
    if not m: return None
    will = m.get("williams_r_14"); pe = m.get("pe_ratio"); ps = m.get("price_to_sales_ratio"); peg = m.get("peg_ratio")
    ma100 = m.get("price_vs_ma100_percent"); ma200 = m.get("price_vs_ma200_percent"); ath = m.get("price_vs_ath_percent")
    d7 = float(m.get("seven_day_percent") or 0); d30 = float(m.get("thirty_day_percent") or 0); rv = float(m.get("relative_volume") or 0)
    technical = 50.0
    if will is not None: technical += max(-20, min(20, (-50 - float(will)) * .5))
    if ma100 is not None and abs(float(ma100)) <= 10: technical += 8
    if ma200 is not None and abs(float(ma200)) <= 10: technical += 10
    technical += max(-12, min(12, d7 * .6 + d30 * .2))
    valuation = 50.0
    if pe is not None and float(pe) > 0: valuation += max(-20, min(20, (30 - float(pe)) * .8))
    if ps is not None: valuation += max(-15, min(15, (6 - float(ps)) * 2.5))
    if peg is not None and float(peg) > 0: valuation += max(-15, min(15, (2 - float(peg)) * 8))
    flow = _recent_flow(db, symbol)
    cap = float(m.get("market_cap") or 0)
    net_flow = flow["bullish_premium"] - flow["bearish_premium"]
    flow_score = 50 + max(-30, min(30, (net_flow / max(cap, 1)) * 100000)) if cap else 50
    sector = _sector_score(db, m)
    sector_component = 50 + max(-25, min(25, (sector or 0) * 4))
    risk = 50.0
    if ath is not None and float(ath) > -5: risk -= 10
    if rv > 1.5: risk += 8
    momentum = 50 + max(-30, min(30, d7 * 2 + d30 * .5))
    components = {
        "technical": round(max(0,min(100,technical)),1),
        "valuation": round(max(0,min(100,valuation)),1),
        "sector": round(max(0,min(100,sector_component)),1),
        "flow": round(max(0,min(100,flow_score)),1),
        "momentum": round(max(0,min(100,momentum)),1),
        "risk": round(max(0,min(100,risk)),1),
    }
    total = components["technical"]*.25 + components["valuation"]*.20 + components["sector"]*.15 + components["flow"]*.15 + components["momentum"]*.15 + components["risk"]*.10
    sell = 100-total
    return {"symbol":symbol.upper(),"buy_score":round(total,1),"sell_score":round(sell,1),"components":components,"flow":flow,"sector_score":sector,"market":m}


def _feature_payload(db: Session, symbol: str):
    o = _opportunity_components(db, symbol)
    if not o: return None
    m=o["market"]
    return {
        "return_1d":m.get("change_percent"),"return_7d":m.get("seven_day_percent"),"return_30d":m.get("thirty_day_percent"),
        "ma100_distance":m.get("price_vs_ma100_percent"),"ma200_distance":m.get("price_vs_ma200_percent"),"williams_r":m.get("williams_r_14"),
        "relative_volume":m.get("relative_volume"),"pe":m.get("pe_ratio"),"ps":m.get("price_to_sales_ratio"),"peg":m.get("peg_ratio"),
        "sector_score":o.get("sector_score"),"bullish_flow":o["flow"]["bullish_premium"],"bearish_flow":o["flow"]["bearish_premium"],
        "buy_score":o["buy_score"],"sell_score":o["sell_score"],"components":o["components"],
    }


def _upsert_registry(db: Session, symbol: str, market: dict):
    row = db.get(SymbolRegistry, symbol)
    if not row:
        row = SymbolRegistry(symbol=symbol, themes={}, provider_ids={}); db.add(row)
    row.name = market.get("name") or row.name
    row.asset_type = market.get("type") or market.get("asset_type") or row.asset_type
    row.exchange = market.get("exchange") or row.exchange
    row.sector = market.get("sector") or row.sector
    row.industry = market.get("industry") or row.industry
    return row


def _refresh_feature(db: Session, symbol: str):
    m = _latest_market(db, symbol)
    if not m: return None
    payload = _feature_payload(db, symbol)
    if payload is None:return None
    as_of = str(m.get("as_of") or date.today().isoformat())[:10]
    row = db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==symbol, FeatureSnapshot.as_of==as_of).first()
    if row: row.payload=payload
    else: db.add(FeatureSnapshot(symbol=symbol,as_of=as_of,payload=payload))
    _upsert_registry(db,symbol,m); db.commit()
    return payload


class HoldingIn(BaseModel):
    symbol: str
    shares: float = Field(ge=0)
    average_cost: float = Field(ge=0)

class AlertIn(BaseModel):
    symbol: str | None = None
    kind: str
    operator: str = ">="
    threshold: float | None = None
    label: str

class ThesisIn(BaseModel):
    title: str
    statement: str
    symbols: list[str]

class RefreshIn(BaseModel):
    symbol: str
    data_class: str = "market"
    priority: int = Field(default=50, ge=1, le=100)


@router.get("/users/me")
def me(user: str = Depends(current_user), db: Session = Depends(get_db)):
    p=db.query(UserProfile).filter(UserProfile.email==user).first();return {"email":user,"role":p.role if p else "approved_user","allowlist_enabled":bool(_allowed_users())}

@router.get("/portfolio")
def portfolio(user: str = Depends(current_user), db: Session = Depends(get_db)):
    rows=db.query(PortfolioHolding).filter(PortfolioHolding.user_email==user).order_by(PortfolioHolding.symbol).all();holdings=[];sector_value=defaultdict(float);total=0.0;cost=0.0
    for r in rows:
        m=_latest_market(db,r.symbol) or {};price=float(m.get("price") or 0);value=price*r.shares;basis=r.average_cost*r.shares;total+=value;cost+=basis
        sector=str(m.get("sector") or "Unclassified");sector_value[sector]+=value
        o=_opportunity_components(db,r.symbol,m)
        holdings.append({"id":r.id,"symbol":r.symbol,"shares":r.shares,"average_cost":r.average_cost,"price":price or None,"market_value":round(value,2),"cost_basis":round(basis,2),"unrealized_pl":round(value-basis,2),"unrealized_percent":round((value/basis-1)*100,2) if basis else None,"sector":sector,"buy_score":o["buy_score"] if o else None,"sell_score":o["sell_score"] if o else None})
    exposures=[{"sector":k,"value":round(v,2),"weight":round(v/total*100,2) if total else 0} for k,v in sorted(sector_value.items(),key=lambda x:x[1],reverse=True)]
    concentration=max([x["weight"] for x in exposures],default=0)
    return {"holdings":holdings,"market_value":round(total,2),"cost_basis":round(cost,2),"unrealized_pl":round(total-cost,2),"cash":None,"sector_exposure":exposures,"concentration_risk":"high" if concentration>=50 else "moderate" if concentration>=30 else "diversified"}

@router.post("/portfolio")
def set_holding(body: HoldingIn, user: str = Depends(current_user), db: Session = Depends(get_db)):
    s=body.symbol.strip().upper();row=db.query(PortfolioHolding).filter(PortfolioHolding.user_email==user,PortfolioHolding.symbol==s).first()
    if row:row.shares=body.shares;row.average_cost=body.average_cost
    else:db.add(PortfolioHolding(user_email=user,symbol=s,shares=body.shares,average_cost=body.average_cost))
    db.commit();return {"status":"saved","symbol":s}

@router.delete("/portfolio/{symbol}")
def delete_holding(symbol: str, user: str = Depends(current_user), db: Session = Depends(get_db)):
    row=db.query(PortfolioHolding).filter(PortfolioHolding.user_email==user,PortfolioHolding.symbol==symbol.upper()).first()
    if not row:raise HTTPException(404,"Holding not found")
    db.delete(row);db.commit();return {"status":"removed"}

@router.get("/opportunities")
def opportunities(db: Session = Depends(get_db), user: str = Depends(current_user), limit: int = Query(default=50,ge=1,le=200)):
    symbols=_all_symbols(db);rows=[]
    for s in symbols:
        o=_opportunity_components(db,s)
        if o:
            rows.append({k:v for k,v in o.items() if k!="market"});_refresh_feature(db,s)
    rows.sort(key=lambda x:x["buy_score"],reverse=True)
    return {"opportunities":rows[:limit],"methodology":"Transparent 0-100 composite: technical 25%, valuation 20%, sector 15%, flow 15%, momentum 15%, risk 10%. Components remain visible so the score is auditable; it is a screening model, not a recommendation."}

@router.get("/regime")
def regime(db: Session = Depends(get_db)):
    signals=[]
    for symbol,label in CROSS_ASSET.items():
        m=_latest_market(db,symbol)
        if not m:continue
        signals.append({"symbol":symbol,"label":label,"day":m.get("change_percent"),"seven_day":m.get("seven_day_percent"),"thirty_day":m.get("thirty_day_percent"),"as_of":m.get("as_of")})
    lookup={x["symbol"]:x for x in signals}
    qqq=float((lookup.get("QQQ") or {}).get("seven_day") or 0);spy=float((lookup.get("SPY") or {}).get("seven_day") or 0);tlt=float((lookup.get("TLT") or {}).get("seven_day") or 0);hyg=float((lookup.get("HYG") or {}).get("seven_day") or 0);uup=float((lookup.get("UUP") or {}).get("seven_day") or 0);iwm=float((lookup.get("IWM") or {}).get("seven_day") or 0)
    factors=[
        {"factor":"Risk appetite","score":round(spy+hyg,2),"state":"risk-on" if spy+hyg>1 else "risk-off" if spy+hyg<-1 else "neutral"},
        {"factor":"Growth leadership","score":round(qqq-spy,2),"state":"growth" if qqq-spy>.5 else "value/broad" if qqq-spy<-.5 else "balanced"},
        {"factor":"Rate pressure","score":round(-tlt,2),"state":"rising-yield pressure" if tlt<-1 else "falling-yield support" if tlt>1 else "neutral"},
        {"factor":"Dollar pressure","score":round(uup,2),"state":"stronger dollar" if uup>.5 else "weaker dollar" if uup<-.5 else "neutral"},
        {"factor":"Breadth","score":round(iwm-spy,2),"state":"broadening" if iwm-spy>.5 else "narrowing" if iwm-spy<-.5 else "neutral"},
    ]
    return {"factors":factors,"cross_asset":signals,"methodology":"Regime state is inferred from stored cross-asset ETF returns; it does not add new real-time provider calls when cached snapshots exist."}

@router.get("/events")
def events(days: int = Query(default=60,ge=7,le=180), db: Session = Depends(get_db)):
    start=date.today();end=start+timedelta(days=days);items=[];source=None
    try:
        cal=macro_calendar(start.isoformat(),end.isoformat());items=[{**e,"kind":"macro"} for e in cal.get("events",[])];source={"provider":cal.get("provider"),"source_url":cal.get("source_url")}
    except Exception as exc: source={"provider":"unavailable","error":str(exc)}
    for f in db.query(FundamentalCache).all():
        dt=(f.payload or {}).get("earnings_date")
        if dt and start.isoformat()<=str(dt)[:10]<=end.isoformat():items.append({"event_date":str(dt)[:10],"title":f"{f.symbol} earnings","symbol":f.symbol,"kind":"earnings","provider":f.provider})
    items.sort(key=lambda x:str(x.get("event_date") or x.get("date") or ""))
    return {"events":items,"source":source,"window":{"start":start.isoformat(),"end":end.isoformat()}}

@router.get("/security/{symbol}/workspace")
def security_workspace(symbol: str, db: Session = Depends(get_db)):
    s=symbol.upper();m=_latest_market(db,s)
    if not m:raise HTTPException(404,"No stored market data for symbol")
    o=_opportunity_components(db,s,m);flow=_recent_flow(db,s);reg=db.get(SymbolRegistry,s);feature=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==s).order_by(FeatureSnapshot.created_at.desc()).first()
    return {"symbol":s,"market":m,"opportunity":{k:v for k,v in (o or {}).items() if k!="market"},"flow":flow,"registry":{"name":reg.name,"asset_type":reg.asset_type,"exchange":reg.exchange,"sector":reg.sector,"industry":reg.industry,"themes":reg.themes} if reg else None,"features":feature.payload if feature else _refresh_feature(db,s)}

@router.get("/security/{symbol}/analogs")
def analogs(symbol: str, db: Session = Depends(get_db), limit: int = Query(default=5,ge=1,le=20)):
    s=symbol.upper();rows=db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol==s).order_by(HistoricalDailyBar.bar_date).all()
    data=[{"date":r.bar_date,"close":r.close,"volume":r.volume} for r in rows]
    if len(data)<30:return {"symbol":s,"analogs":[],"note":"At least 30 stored daily bars are required."}
    def ret(i,n):return (data[i]["close"]/data[i-n]["close"]-1)*100 if i>=n and data[i-n]["close"] else None
    i=len(data)-1;target=[ret(i,1),ret(i,5),ret(i,21)];avg=sum(x["volume"] for x in data[max(0,i-20):i])/max(1,len(data[max(0,i-20):i]));target.append(data[i]["volume"]/avg if avg else 1)
    matches=[]
    for j in range(21,len(data)-5):
        vals=[ret(j,1),ret(j,5),ret(j,21)];av=sum(x["volume"] for x in data[max(0,j-20):j])/max(1,len(data[max(0,j-20):j]));vals.append(data[j]["volume"]/av if av else 1)
        if any(x is None for x in vals+target):continue
        distance=math.sqrt(sum(((a-b)/scale)**2 for a,b,scale in zip(vals,target,[3,8,15,1])))
        next5=ret(j+5,5)
        matches.append({"date":data[j]["date"],"distance":round(distance,3),"return_1d":round(vals[0],2),"return_5d":round(vals[1],2),"return_21d":round(vals[2],2),"relative_volume":round(vals[3],2),"following_5d":round(next5,2) if next5 is not None else None})
    matches.sort(key=lambda x:x["distance"])
    return {"symbol":s,"analogs":matches[:limit],"methodology":"Nearest historical patterns use normalized 1D/5D/21D returns and relative volume. Similarity is descriptive, not predictive."}

@router.get("/alerts")
def list_alerts(user: str = Depends(current_user), db: Session = Depends(get_db)):
    rows=db.query(AlertRule).filter(AlertRule.user_email==user).order_by(AlertRule.created_at.desc()).all();out=[]
    for r in rows:
        m=_latest_market(db,r.symbol) if r.symbol else None;value=None
        if m:
            mapping={"price":m.get("price"),"williams":m.get("williams_r_14"),"buy_score":(_opportunity_components(db,r.symbol,m) or {}).get("buy_score"),"sell_score":(_opportunity_components(db,r.symbol,m) or {}).get("sell_score"),"ma100_distance":m.get("price_vs_ma100_percent"),"ma200_distance":m.get("price_vs_ma200_percent")}
            value=mapping.get(r.kind)
        triggered=False
        if value is not None and r.threshold is not None:
            triggered={">=":value>=r.threshold,"<=":value<=r.threshold,">":value>r.threshold,"<":value<r.threshold}.get(r.operator,False)
        out.append({"id":r.id,"symbol":r.symbol,"kind":r.kind,"operator":r.operator,"threshold":r.threshold,"label":r.label,"enabled":r.enabled,"current_value":value,"triggered":triggered})
    return {"alerts":out}

@router.post("/alerts")
def create_alert(body: AlertIn, user: str = Depends(current_user), db: Session = Depends(get_db)):
    row=AlertRule(user_email=user,symbol=body.symbol.upper() if body.symbol else None,kind=body.kind,operator=body.operator,threshold=body.threshold,label=body.label);db.add(row);db.commit();db.refresh(row);return {"id":row.id,"status":"created"}

@router.delete("/alerts/{alert_id}")
def delete_alert(alert_id: int, user: str = Depends(current_user), db: Session = Depends(get_db)):
    row=db.query(AlertRule).filter(AlertRule.id==alert_id,AlertRule.user_email==user).first()
    if not row:raise HTTPException(404,"Alert not found")
    db.delete(row);db.commit();return {"status":"removed"}

@router.get("/theses")
def theses(user: str = Depends(current_user), db: Session = Depends(get_db)):
    rows=db.query(Thesis).filter(Thesis.user_email==user).order_by(Thesis.updated_at.desc()).all();out=[]
    for r in rows:
        symbols=(r.symbols or {}).get("items",[]);evidence=[];scores=[]
        for s in symbols:
            o=_opportunity_components(db,s)
            if not o:continue
            scores.append(o["buy_score"]);m=o["market"]
            evidence.append({"symbol":s,"direction":"supports" if o["buy_score"]>=58 else "challenges" if o["buy_score"]<=42 else "neutral","summary":f"Buy score {o['buy_score']}; 7D {float(m.get('seven_day_percent') or 0):+.1f}%; sector {o.get('sector_score') if o.get('sector_score') is not None else '—'}; bullish flow ${o['flow']['bullish_premium']:,.0f}."})
        avg=sum(scores)/len(scores) if scores else 50;health="strengthening" if avg>=60 else "weakening" if avg<=40 else "stable"
        out.append({"id":r.id,"title":r.title,"statement":r.statement,"symbols":symbols,"health":health,"score":round(avg,1),"evidence":evidence,"enabled":r.enabled})
    return {"theses":out}

@router.post("/theses")
def create_thesis(body: ThesisIn, user: str = Depends(current_user), db: Session = Depends(get_db)):
    row=Thesis(user_email=user,title=body.title,statement=body.statement,symbols={"items":[s.upper() for s in body.symbols]});db.add(row);db.commit();db.refresh(row);return {"id":row.id,"status":"created"}

@router.delete("/theses/{thesis_id}")
def delete_thesis(thesis_id: int, user: str = Depends(current_user), db: Session = Depends(get_db)):
    row=db.query(Thesis).filter(Thesis.id==thesis_id,Thesis.user_email==user).first()
    if not row:raise HTTPException(404,"Thesis not found")
    db.delete(row);db.commit();return {"status":"removed"}

@router.get("/features")
def features(db: Session = Depends(get_db), symbol: str | None = None):
    q=db.query(FeatureSnapshot)
    if symbol:q=q.filter(FeatureSnapshot.symbol==symbol.upper())
    rows=q.order_by(FeatureSnapshot.created_at.desc()).limit(300).all();return {"features":[{"symbol":r.symbol,"as_of":r.as_of,"data":r.payload,"created_at":r.created_at.isoformat()} for r in rows]}

@router.post("/features/refresh")
def refresh_features(db: Session = Depends(get_db), user: str = Depends(current_user)):
    done=[]
    for s in _all_symbols(db):
        if _refresh_feature(db,s) is not None:done.append(s)
    return {"refreshed":done}

@router.get("/refresh-queue")
def refresh_queue(db: Session = Depends(get_db)):
    rows=db.query(RefreshQueueItem).order_by(RefreshQueueItem.priority.desc(),RefreshQueueItem.created_at).limit(100).all();return {"items":[{"id":r.id,"symbol":r.symbol,"data_class":r.data_class,"priority":r.priority,"status":r.status,"error":r.error,"created_at":r.created_at.isoformat()} for r in rows]}

@router.post("/refresh-queue")
def enqueue_refresh(body: RefreshIn, user: str = Depends(current_user), db: Session = Depends(get_db)):
    s=body.symbol.upper();existing=db.query(RefreshQueueItem).filter(RefreshQueueItem.symbol==s,RefreshQueueItem.data_class==body.data_class,RefreshQueueItem.status=="queued").first()
    if existing:return {"id":existing.id,"status":"already_queued"}
    row=RefreshQueueItem(symbol=s,data_class=body.data_class,priority=body.priority,requested_by=user);db.add(row);db.commit();db.refresh(row);return {"id":row.id,"status":"queued"}

@router.post("/refresh-queue/process")
def process_refresh_queue(limit: int = Query(default=5,ge=1,le=20), db: Session = Depends(get_db), user: str = Depends(current_user)):
    rows=db.query(RefreshQueueItem).filter(RefreshQueueItem.status=="queued").order_by(RefreshQueueItem.priority.desc(),RefreshQueueItem.created_at).limit(limit).all();done=[];failed=[]
    for r in rows:
        r.status="running";db.commit()
        try:
            if r.data_class=="fundamentals":
                payload,_=ProviderOrchestrator().fundamentals(r.symbol,allow_alpha=False);f=db.get(FundamentalCache,r.symbol)
                if f:f.provider=str(payload.get("provider") or "Fundamentals");f.payload=payload;f.retrieved_at=datetime.now(timezone.utc)
                else:db.add(FundamentalCache(symbol=r.symbol,provider=str(payload.get("provider") or "Fundamentals"),payload=payload,retrieved_at=datetime.now(timezone.utc)))
            else:
                snap=build_market_snapshot(TwelveDataProvider().market_snapshot_raw(r.symbol));db.add(MarketSnapshot(symbol=r.symbol,as_of=str(snap.get("as_of") or ""),provider=str(snap.get("provider") or "Twelve Data"),payload=snap))
            r.status="complete";r.error=None;done.append(r.symbol);db.commit();_refresh_feature(db,r.symbol)
        except Exception as exc:
            db.rollback();r=db.get(RefreshQueueItem,r.id);r.status="failed";r.error=str(exc)[:500];db.commit();failed.append({"symbol":r.symbol,"error":r.error})
    return {"complete":done,"failed":failed}

@router.get("/system/data-health")
def data_health(db: Session = Depends(get_db)):
    symbols=_all_symbols(db);now=datetime.now(timezone.utc);market_fresh=0;fund_fresh=0;stale=[]
    for s in symbols:
        m=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==s).order_by(MarketSnapshot.retrieved_at.desc()).first();f=db.get(FundamentalCache,s)
        if m and not is_stale(m.retrieved_at,"market",now):market_fresh+=1
        elif m:stale.append({"symbol":s,"data_class":"market","retrieved_at":m.retrieved_at.isoformat()})
        if f and not is_stale(f.retrieved_at,"fundamentals",now):fund_fresh+=1
    queues={status:db.query(RefreshQueueItem).filter(RefreshQueueItem.status==status).count() for status in ["queued","running","failed","complete"]}
    return {"symbols":len(symbols),"market_fresh":market_fresh,"fundamentals_fresh":fund_fresh,"feature_snapshots":db.query(FeatureSnapshot).count(),"registry_symbols":db.query(SymbolRegistry).count(),"queue":queues,"stale":stale[:50],"freshness_policies":{k:{"ttl_seconds":v.ttl_seconds,"priority":v.priority} for k,v in FRESHNESS_POLICIES.items()},"architecture":"Global symbol/fundamental/feature state is shared; user watchlists, holdings, alerts and theses are user-specific references. This prevents duplicate provider pulls for the same symbol across approved users."}
