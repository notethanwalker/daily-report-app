from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..future_models import RegimeSnapshot
from ..models import FeatureSnapshot, FlowEvent, HistoricalDailyBar, MarketSnapshot, ReportSnapshot, SymbolRegistry, UserWatchlistItem
from ..multiuser_models import PortfolioDefinition, PortfolioPosition, UserPreferences
from ..v3_models import PortfolioValueSnapshot, UserCustomEvent
from .intelligence import CROSS_ASSET, _latest_market, current_user
from .portfolio_access import _portfolio_or_404

router = APIRouter(prefix="/api/v1/future", tags=["future-release"])


THEME_FALLBACK = {
    "AAOI": ["Photonics", "AI infrastructure"],
    "AXTI": ["Photonics", "Compound semiconductors"],
    "SNDK": ["Memory", "Storage"],
    "MU": ["Memory", "Semiconductors"],
    "NBIS": ["AI infrastructure", "Cloud"],
    "NVDA": ["AI compute", "Semiconductors"],
    "SMH": ["Semiconductors", "ETF"],
    "IONQ": ["Quantum"],
    "OKLO": ["Nuclear", "Power"],
    "GLD": ["Gold", "Commodity"],
}

ALERT_TEMPLATES = [
    {"id":"ma100_proximity","name":"100MA proximity","kind":"ma100_distance","operator":"<=","threshold":3.0,"unit":"% distance","scope":"ticker","description":"Alert when absolute price distance to the 100-day moving average is at or below the selected percentage."},
    {"id":"ma200_proximity","name":"200MA proximity","kind":"ma200_distance","operator":"<=","threshold":3.0,"unit":"% distance","scope":"ticker","description":"Alert when absolute price distance to the 200-day moving average is at or below the selected percentage."},
    {"id":"relative_volume","name":"Unusual relative volume","kind":"relative_volume","operator":">=","threshold":1.75,"unit":"x normal","scope":"ticker","description":"Alert when relative volume exceeds the selected multiple."},
    {"id":"earnings_catalyst","name":"Upcoming earnings/catalyst","kind":"catalyst_days","operator":"<=","threshold":7.0,"unit":"days","scope":"ticker","description":"Alert when a tracked company catalyst falls inside the selected look-ahead window."},
    {"id":"persistent_flow","name":"Persistent options flow","kind":"persistent_flow","operator":">=","threshold":3.0,"unit":"cluster observations","scope":"ticker","description":"Alert when repeated same-direction option observations cluster for a tracked ticker. This does not identify a participant."},
    {"id":"portfolio_concentration","name":"Portfolio concentration","kind":"portfolio_position_weight","operator":">=","threshold":20.0,"unit":"% portfolio","scope":"portfolio","description":"Alert when a single position exceeds the selected portfolio weight."},
    {"id":"regime_change","name":"Market regime change","kind":"regime_transition","operator":"!=","threshold":None,"unit":"state","scope":"global","description":"Alert when the confidence-weighted regime state differs from the prior stored daily state."},
]


class LayoutProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    cards: list[str] = Field(default_factory=list)
    hidden: list[str] = Field(default_factory=list)
    density: str = Field(default="comfortable", pattern="^(comfortable|compact)$")
    columns: int = Field(default=2, ge=1, le=4)
    make_active: bool = True


class ActiveLayoutIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _utc(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _market_value(db: Session, pos: PortfolioPosition) -> float:
    m = _latest_market(db, pos.symbol) or {}
    px = m.get("price")
    if px is None:
        px = pos.imported_last_price
    if px is None:
        return float(pos.imported_market_value or 0)
    return float(px) * float(pos.shares)


def _themes(db: Session, symbol: str) -> list[str]:
    row = db.get(SymbolRegistry, symbol)
    raw = (row.themes or {}) if row else {}
    out = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            if value is True or (isinstance(value, (int, float)) and value > 0):
                out.append(str(key))
            elif isinstance(value, str) and value:
                out.append(value)
    elif isinstance(raw, list):
        out.extend(str(x) for x in raw if x)
    if not out:
        out = THEME_FALLBACK.get(symbol, [])
    return sorted(set(out))


def _historical_return(db: Session, symbol: str, start_date: str, end_date: str):
    rows = db.query(HistoricalDailyBar).filter(
        HistoricalDailyBar.symbol == symbol,
        HistoricalDailyBar.bar_date >= start_date,
        HistoricalDailyBar.bar_date <= end_date,
    ).order_by(HistoricalDailyBar.bar_date.asc()).all()
    if len(rows) < 2 or not rows[0].close:
        return None
    return (rows[-1].close / rows[0].close - 1) * 100


def _report_summary(payload: dict):
    markets = payload.get("markets") or payload.get("market_rows") or []
    if isinstance(markets, dict):
        markets = list(markets.values())
    by_symbol = {}
    for row in markets if isinstance(markets, list) else []:
        if isinstance(row, dict) and row.get("symbol"):
            by_symbol[str(row["symbol"]).upper()] = row
    return {
        "market_count": len(by_symbol),
        "verified": (payload.get("verification_summary") or {}).get("verified"),
        "primary_only": (payload.get("verification_summary") or {}).get("primary_only"),
        "top_news": [x.get("title") for x in (payload.get("top_market_news") or [])[:5] if isinstance(x, dict)],
        "symbols": by_symbol,
    }


def _feature_flags(payload: dict):
    flags = set()
    buy = payload.get("buy_score")
    sell = payload.get("sell_score")
    will = payload.get("williams_r")
    rv = payload.get("relative_volume")
    ma100 = payload.get("ma100_distance")
    ma200 = payload.get("ma200_distance")
    if isinstance(buy, (int, float)) and buy >= 65: flags.add("buy_score_65+")
    if isinstance(sell, (int, float)) and sell >= 65: flags.add("sell_score_65+")
    if isinstance(will, (int, float)) and will <= -80: flags.add("williams_oversold")
    if isinstance(will, (int, float)) and will >= -20: flags.add("williams_overbought")
    if isinstance(rv, (int, float)) and rv >= 1.5: flags.add("relative_volume_1.5x+")
    if isinstance(ma100, (int, float)) and abs(ma100) <= 5: flags.add("within_5pct_100ma")
    if isinstance(ma200, (int, float)) and abs(ma200) <= 5: flags.add("within_5pct_200ma")
    return flags


@router.get("/portfolio/{portfolio_id}/intelligence")
def portfolio_intelligence(portfolio_id: int, user: str = Depends(current_user), db: Session = Depends(get_db)):
    p = _portfolio_or_404(db, user, portfolio_id)
    positions = db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id == p.id).all()
    values = {pos.symbol: _market_value(db, pos) for pos in positions}
    invested = sum(values.values())
    total = invested + float(p.cash or 0)
    sector = defaultdict(float); theme = defaultdict(float); geography = defaultdict(float); currency = defaultdict(float)
    rows = []
    for pos in positions:
        value = values[pos.symbol]
        m = _latest_market(db, pos.symbol) or {}
        reg = db.get(SymbolRegistry, pos.symbol)
        s = str(m.get("sector") or (reg.sector if reg else None) or "Unclassified")
        sector[s] += value
        themes = _themes(db, pos.symbol) or ["Unclassified"]
        split = value / max(len(themes), 1)
        for t in themes: theme[t] += split
        exch = str((reg.exchange if reg else None) or m.get("exchange") or "Unknown")
        geo = "US-listed" if any(x in exch.upper() for x in ["NYSE", "NASDAQ", "AMEX", "ARCA", "BATS"]) else "Other/unknown listing"
        geography[geo] += value
        curr = str(m.get("currency") or "USD/unknown")
        currency[curr] += value
        rows.append({"symbol": pos.symbol, "market_value": round(value,2), "weight": round(value/total*100,2) if total else 0, "sector": s, "themes": themes, "currency": curr, "listing_group": geo})
    def exposure(d):
        return [{"name": k, "value": round(v,2), "weight": round(v/total*100,2) if total else 0} for k,v in sorted(d.items(), key=lambda x:x[1], reverse=True)]
    weights = sorted((r["weight"] for r in rows), reverse=True)
    hhi = sum((w/100)**2 for w in weights)
    scenarios = [
        {"id":"broad_market_down_10","label":"Broad holdings -10%","estimated_change":round(-0.10*invested,2),"estimated_portfolio_percent":round((-0.10*invested/total)*100,2) if total else 0,"assumption":"Every invested holding changes -10%; cash is unchanged."},
        {"id":"top_position_down_20","label":"Largest position -20%","estimated_change":round(-0.20*(max(values.values()) if values else 0),2),"estimated_portfolio_percent":round((-0.20*(max(values.values()) if values else 0)/total)*100,2) if total else 0,"assumption":"Only the current largest position changes -20%."},
        {"id":"largest_sector_down_15","label":"Largest sector -15%","estimated_change":round(-0.15*(max(sector.values()) if sector else 0),2),"estimated_portfolio_percent":round((-0.15*(max(sector.values()) if sector else 0)/total)*100,2) if total else 0,"assumption":"Only holdings in the largest classified sector change -15%."},
    ]
    hist = db.query(PortfolioValueSnapshot).filter(PortfolioValueSnapshot.portfolio_id == p.id).order_by(PortfolioValueSnapshot.as_of.asc()).all()
    benchmark = {"symbol":"SPY","portfolio_return":None,"benchmark_return":None,"relative_return":None,"start":None,"end":None,"note":"Needs at least two stored portfolio snapshots on distinct dates."}
    if len(hist) >= 2 and hist[0].market_value:
        start, end = hist[0].as_of, hist[-1].as_of
        port_ret = (hist[-1].market_value / hist[0].market_value - 1) * 100
        spy_ret = _historical_return(db, "SPY", start, end)
        benchmark.update({"portfolio_return":round(port_ret,2),"benchmark_return":round(spy_ret,2) if spy_ret is not None else None,"relative_return":round(port_ret-spy_ret,2) if spy_ret is not None else None,"start":start,"end":end})
    return {
        "portfolio_id": p.id, "name": p.name, "market_value": round(total,2), "invested_value": round(invested,2), "cash": round(float(p.cash or 0),2),
        "positions": sorted(rows,key=lambda x:x["market_value"],reverse=True),
        "exposures": {"sector":exposure(sector),"theme":exposure(theme),"geography":exposure(geography),"currency":exposure(currency)},
        "concentration": {"top1_weight":round(weights[0],2) if weights else 0,"top3_weight":round(sum(weights[:3]),2),"hhi":round(hhi,4),"effective_positions":round(1/hhi,2) if hhi else 0,"interpretation":"higher HHI means more concentration"},
        "scenarios": scenarios,
        "benchmark": benchmark,
        "methodology":"Exposure uses current position market values and cached symbol metadata. Theme weights split equally when a symbol has multiple tags. Geography is listing-location proxy, not issuer revenue geography. Scenarios are mechanical shocks, not forecasts.",
    }


@router.get("/opportunities/{symbol}/why-changed")
def why_opportunity_changed(symbol: str, db: Session = Depends(get_db), user: str = Depends(current_user)):
    s = symbol.strip().upper()
    allowed = {r.symbol for r in db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email == user).all()}
    if s not in allowed:
        raise HTTPException(404, "Ticker is not in this user's watchlist")
    rows = db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol == s).order_by(FeatureSnapshot.as_of.desc()).limit(2).all()
    if not rows:
        return {"symbol":s,"current":None,"previous":None,"component_deltas":[],"new_flags":[],"removed_flags":[],"note":"No stored opportunity feature snapshots yet."}
    cur = rows[0]; prev = rows[1] if len(rows)>1 else None
    cp = cur.payload or {}; pp = (prev.payload or {}) if prev else {}
    keys = sorted(set((cp.get("components") or {}).keys()) | set((pp.get("components") or {}).keys()))
    deltas=[]
    for k in keys:
        a=(cp.get("components") or {}).get(k); b=(pp.get("components") or {}).get(k)
        deltas.append({"component":k,"current":a,"previous":b,"delta":round(float(a)-float(b),2) if isinstance(a,(int,float)) and isinstance(b,(int,float)) else None})
    cf=_feature_flags(cp); pf=_feature_flags(pp)
    market = db.query(MarketSnapshot).filter(MarketSnapshot.symbol==s).order_by(MarketSnapshot.retrieved_at.desc()).first()
    age = None
    if market:
        age = round((datetime.now(timezone.utc)-_utc(market.retrieved_at)).total_seconds()/60,1)
    return {"symbol":s,"current":{"as_of":cur.as_of,"buy_score":cp.get("buy_score"),"sell_score":cp.get("sell_score")},"previous":{"as_of":prev.as_of,"buy_score":pp.get("buy_score"),"sell_score":pp.get("sell_score")} if prev else None,"score_delta":round(float(cp.get("buy_score") or 0)-float(pp.get("buy_score") or 0),2) if prev else None,"component_deltas":deltas,"new_flags":sorted(cf-pf),"removed_flags":sorted(pf-cf),"source_age":{"market_minutes":age,"historical_source_age_delta":None},"note":"Component deltas compare the two latest stored daily feature snapshots. Historical provider-age deltas were not previously persisted, so they are left unavailable rather than inferred."}


@router.get("/flow/clusters")
def flow_clusters(days: int = Query(default=7, ge=1, le=30), limit: int = Query(default=80, ge=1, le=200), db: Session = Depends(get_db), user: str = Depends(current_user)):
    tracked = {r.symbol for r in db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email == user).all()}
    since = datetime.now(timezone.utc)-timedelta(days=days)
    q = db.query(FlowEvent).filter(FlowEvent.occurred_at >= since)
    if tracked:q=q.filter(FlowEvent.symbol.in_(tracked))
    rows=q.order_by(FlowEvent.occurred_at.desc()).limit(2000).all()
    groups={}
    for row in rows:
        p=row.payload or {}; side=str(p.get("side") or "unknown").lower(); expiry=str(p.get("expiration") or "unknown"); strike=p.get("strike"); direction=str(p.get("direction") or p.get("aggression") or p.get("execution") or "unknown").lower()
        key=(row.symbol,side,expiry,strike,direction)
        g=groups.setdefault(key,{"symbol":row.symbol,"side":side,"expiration":expiry,"strike":strike,"direction":direction,"observations":0,"premium":0.0,"contracts":0.0,"first_seen":row.occurred_at,"last_seen":row.occurred_at,"providers":set(),"outlier_max":0.0})
        g["observations"]+=1;g["premium"]+=float(p.get("premium") or 0);g["contracts"]+=float(p.get("contracts") or p.get("volume") or 0);g["first_seen"]=min(g["first_seen"],row.occurred_at);g["last_seen"]=max(g["last_seen"],row.occurred_at);g["providers"].add(row.provider);g["outlier_max"]=max(g["outlier_max"],float(row.outlier_score or 0))
    out=[]
    for g in groups.values():
        explicit=g["direction"] not in {"","unknown","none"}
        confidence=min(95,35+g["observations"]*10+(20 if explicit else 0))
        out.append({**g,"premium":round(g["premium"],2),"contracts":round(g["contracts"],2),"first_seen":g["first_seen"].isoformat(),"last_seen":g["last_seen"].isoformat(),"providers":sorted(g["providers"]),"confidence":confidence,"inference":"Repeated contract-signature observations. This does not identify a participant or prove opening/closing activity.","participant_behavior_supported":False,"opening_closing_supported":False})
    out.sort(key=lambda x:(x["observations"],x["premium"],x["outlier_max"]),reverse=True)
    return {"clusters":out[:limit],"window_days":days,"methodology":"Groups stored flow observations by ticker, side, expiration, strike and reported direction/aggression. Repetition can indicate persistent activity, but participant identity and open/close intent are unavailable from the current feed."}


@router.get("/impact-map")
def impact_map(db: Session = Depends(get_db), user: str = Depends(current_user)):
    watch={r.symbol for r in db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email==user).all()}
    portfolios=db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email==user).all();pos=db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id.in_([p.id for p in portfolios])).all() if portfolios else []
    value_by_symbol=defaultdict(float)
    for p in pos:value_by_symbol[p.symbol]+=_market_value(db,p)
    total=sum(value_by_symbol.values())
    registry={s:db.get(SymbolRegistry,s) for s in watch|set(value_by_symbol)}
    latest=db.query(ReportSnapshot).order_by(ReportSnapshot.created_at.desc()).first();articles=(latest.payload or {}).get("top_market_news",[]) if latest else []
    items=[]
    for a in articles:
        text=f"{a.get('title','')} {a.get('why_it_matters','')}".upper();hits=[];rationales=[]
        for s in sorted(watch|set(value_by_symbol)):
            reg=registry.get(s);name=(reg.name if reg else "") or "";themes=_themes(db,s)
            matched=[]
            if s in text:matched.append("ticker mention")
            if name and name.upper() in text:matched.append("company-name mention")
            for t in themes:
                if len(t)>=4 and t.upper() in text:matched.append(f"theme: {t}")
            if matched:
                hits.append(s);rationales.append({"symbol":s,"matches":matched,"portfolio_exposure_percent":round(value_by_symbol[s]/total*100,2) if total else 0})
        if hits:items.append({"kind":"news","title":a.get("title"),"url":a.get("url"),"published_at":a.get("published_at"),"symbols":hits,"estimated_portfolio_exposure_percent":round(sum(value_by_symbol[s] for s in hits)/total*100,2) if total else 0,"rationale":rationales,"causal_confidence":"association_only"})
    today=date.today().isoformat();until=(date.today()+timedelta(days=30)).isoformat()
    custom=db.query(UserCustomEvent).filter(UserCustomEvent.user_email==user,UserCustomEvent.event_date>=today,UserCustomEvent.event_date<=until).order_by(UserCustomEvent.event_date).all()
    for e in custom:
        if e.symbol and e.symbol in watch|set(value_by_symbol):
            items.append({"kind":"event","title":e.title,"event_date":e.event_date,"symbols":[e.symbol],"estimated_portfolio_exposure_percent":round(value_by_symbol[e.symbol]/total*100,2) if total else 0,"rationale":[{"symbol":e.symbol,"matches":["explicit event ticker"],"portfolio_exposure_percent":round(value_by_symbol[e.symbol]/total*100,2) if total else 0}],"causal_confidence":"explicit_mapping"})
    return {"items":items,"watchlist_symbols":len(watch),"portfolio_market_value":round(total,2),"methodology":"News mapping uses explicit ticker/company/theme text matches and therefore shows association, not proven causality. Exposure is current portfolio market value linked to matched symbols. Custom events with an explicit ticker receive stronger mapping confidence."}


def _regime_now(db: Session):
    evidence=[]
    for symbol,label in CROSS_ASSET.items():
        m=_latest_market(db,symbol)
        if not m:continue
        r=float(m.get("seven_day_percent") or m.get("change_percent") or 0)
        evidence.append({"symbol":symbol,"label":label,"return":round(r,2),"as_of":m.get("as_of"),"retrieved_at":m.get("retrieved_at")})
    vix=_latest_market(db,"VIX")
    if vix:evidence.append({"symbol":"VIX","label":"Volatility","return":round(float(vix.get("seven_day_percent") or vix.get("change_percent") or 0),2),"as_of":vix.get("as_of"),"retrieved_at":vix.get("retrieved_at")})
    risk_on_syms={"SPY","QQQ","IWM","HYG","SMH"};defensive_syms={"TLT","GLD","UUP","VIX"}
    votes=[]
    for e in evidence:
        r=e["return"];s=e["symbol"]
        if s in risk_on_syms:votes.append(1 if r>0 else -1 if r<0 else 0)
        elif s in defensive_syms:votes.append(-1 if r>0 else 1 if r<0 else 0)
    score=(sum(votes)/max(len(votes),1))*100
    regime="risk-on" if score>=25 else "risk-off" if score<=-25 else "mixed"
    agreement=(sum(1 for v in votes if (score>0 and v>0) or (score<0 and v<0) or (score==0 and v==0))/max(len(votes),1)) if votes else 0
    expected=len(CROSS_ASSET)+1;completeness=len(evidence)/expected
    confidence=min(100,max(0,(agreement*.65+completeness*.35)*100))
    return regime,score,confidence,evidence,completeness


@router.get("/regime/confidence")
def regime_confidence(db: Session = Depends(get_db)):
    regime,score,confidence,evidence,completeness=_regime_now(db);today=date.today().isoformat();payload={"evidence":evidence,"completeness":round(completeness*100,1)}
    row=db.query(RegimeSnapshot).filter(RegimeSnapshot.as_of==today).first()
    if row:row.regime=regime;row.score=score;row.confidence=confidence;row.payload=payload
    else:db.add(RegimeSnapshot(as_of=today,regime=regime,score=score,confidence=confidence,payload=payload))
    db.commit();hist=db.query(RegimeSnapshot).order_by(RegimeSnapshot.as_of.desc()).limit(60).all();hist=list(reversed(hist));trans=[]
    prior=None
    for h in hist:
        if prior is None or h.regime!=prior:trans.append({"as_of":h.as_of,"regime":h.regime,"score":round(h.score,1),"confidence":round(h.confidence,1)})
        prior=h.regime
    return {"regime":regime,"score":round(score,1),"confidence":round(confidence,1),"evidence_completeness":round(completeness*100,1),"evidence":evidence,"transition_history":trans,"methodology":"Seven-day cross-asset direction is converted to risk-on/risk-off votes. Confidence combines evidence completeness and directional agreement. This is a transparent state classifier, not a forecast."}


@router.get("/dashboard-layouts")
def dashboard_layouts(user: str = Depends(current_user), db: Session = Depends(get_db)):
    row=db.get(UserPreferences,user);settings=(row.settings or {}) if row else {};layouts=settings.get("dashboard_layouts") or []
    if not layouts:layouts=[{"name":"Default","cards":["market_dashboard","sentiment","themes","daily_report","currencies","outliers","news"],"hidden":[],"density":"comfortable","columns":2}]
    active=settings.get("active_dashboard_layout") or layouts[0]["name"]
    return {"layouts":layouts,"active":active}


@router.put("/dashboard-layouts")
def save_dashboard_layout(body: LayoutProfileIn, user: str = Depends(current_user), db: Session = Depends(get_db)):
    row=db.get(UserPreferences,user)
    if not row:row=UserPreferences(user_email=user,visible_tabs=[],information_modules={},settings={});db.add(row)
    settings=dict(row.settings or {});layouts=list(settings.get("dashboard_layouts") or []);profile=body.model_dump(exclude={"make_active"});found=False
    for i,x in enumerate(layouts):
        if str(x.get("name"))==body.name:layouts[i]=profile;found=True;break
    if not found:layouts.append(profile)
    settings["dashboard_layouts"]=layouts
    if body.make_active:settings["active_dashboard_layout"]=body.name
    row.settings=settings;db.commit();return {"status":"saved","active":settings.get("active_dashboard_layout"),"layouts":layouts}


@router.put("/dashboard-layouts/active")
def set_active_layout(body: ActiveLayoutIn, user: str = Depends(current_user), db: Session = Depends(get_db)):
    row=db.get(UserPreferences,user)
    if not row:raise HTTPException(404,"No saved dashboard layouts")
    settings=dict(row.settings or {});layouts=settings.get("dashboard_layouts") or []
    if body.name not in [str(x.get("name")) for x in layouts]:raise HTTPException(404,"Layout not found")
    settings["active_dashboard_layout"]=body.name;row.settings=settings;db.commit();return {"status":"saved","active":body.name}


@router.get("/reports/history")
def report_history(limit:int=Query(default=30,ge=2,le=100),db:Session=Depends(get_db)):
    rows=db.query(ReportSnapshot).order_by(ReportSnapshot.created_at.desc()).limit(limit).all()
    return {"reports":[{"id":r.id,"report_date":r.report_date,"created_at":r.created_at.isoformat(),"summary":_report_summary(r.payload or {})} for r in rows]}


@router.get("/reports/compare")
def compare_reports(left_id:int,right_id:int,db:Session=Depends(get_db)):
    left=db.get(ReportSnapshot,left_id);right=db.get(ReportSnapshot,right_id)
    if not left or not right:raise HTTPException(404,"Report snapshot not found")
    a=_report_summary(left.payload or {});b=_report_summary(right.payload or {});symbols=sorted(set(a["symbols"])|set(b["symbols"]));changes=[]
    for s in symbols:
        x=a["symbols"].get(s,{});y=b["symbols"].get(s,{});px=x.get("price");py=y.get("price")
        changes.append({"symbol":s,"left_price":px,"right_price":py,"price_change_percent":round((float(py)/float(px)-1)*100,2) if isinstance(px,(int,float)) and isinstance(py,(int,float)) and px else None,"left_verification":x.get("verification_status"),"right_verification":y.get("verification_status")})
    return {"left":{"id":left.id,"report_date":left.report_date,"created_at":left.created_at.isoformat()},"right":{"id":right.id,"report_date":right.report_date,"created_at":right.created_at.isoformat()},"symbol_changes":changes,"news_added":[x for x in b["top_news"] if x not in a["top_news"]],"news_removed":[x for x in a["top_news"] if x not in b["top_news"]],"verification":{"left_verified":a["verified"],"right_verified":b["verified"],"left_primary_only":a["primary_only"],"right_primary_only":b["primary_only"]},"methodology":"Comparison preserves each snapshot's stored values and timestamps; it does not silently refresh historical data."}


@router.get("/reports/{report_id}/export.json")
def export_report_json(report_id:int,db:Session=Depends(get_db)):
    row=db.get(ReportSnapshot,report_id)
    if not row:raise HTTPException(404,"Report snapshot not found")
    return {"id":row.id,"report_date":row.report_date,"created_at":row.created_at.isoformat(),"payload":row.payload}


@router.get("/reports/{report_id}/export.csv",response_class=PlainTextResponse)
def export_report_csv(report_id:int,db:Session=Depends(get_db)):
    row=db.get(ReportSnapshot,report_id)
    if not row:raise HTTPException(404,"Report snapshot not found")
    summary=_report_summary(row.payload or {});buf=io.StringIO();w=csv.writer(buf);w.writerow(["report_id",row.id]);w.writerow(["report_date",row.report_date]);w.writerow(["created_at",row.created_at.isoformat()]);w.writerow([]);w.writerow(["symbol","price","1d_percent","7d_percent","30d_percent","ma100","ma200","verification_status","as_of","retrieved_at"])
    for s,m in sorted(summary["symbols"].items()):w.writerow([s,m.get("price"),m.get("change_percent"),m.get("seven_day_percent"),m.get("thirty_day_percent"),m.get("ma100"),m.get("ma200"),m.get("verification_status"),m.get("as_of"),m.get("retrieved_at")])
    return PlainTextResponse(buf.getvalue(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="daily-report-{row.report_date}-{row.id}.csv"'})


@router.get("/alert-templates")
def alert_templates():
    return {"templates":ALERT_TEMPLATES,"methodology":"Templates prefill transparent rule types and thresholds; users can change thresholds before saving. Persistent-flow templates use repeated observation clusters and do not claim participant identity."}
