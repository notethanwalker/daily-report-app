from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean, pstdev

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AlertEvent, FeatureSnapshot, FlowEvent, FundamentalCache, HistoricalDailyBar, MarketSnapshot, SymbolRegistry, UserWatchlistItem
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from ..services.macro_universe import MACRO_CATEGORIES, TRACKING_RATIONALE
from ..services.provider_orchestrator import FRESHNESS_POLICIES, PROVIDER_POLICY
from ..services.rotation import SECTORS
from ..v3_models import PortfolioValueSnapshot
from .events_v3 import build_event_payload
from .intelligence import _latest_market, _opportunity_components, current_user

router=APIRouter(prefix="/api/v1",tags=["decision-support"])


def _user_symbols(db:Session,user:str)->list[str]:
    symbols={x.symbol for x in db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email==user).all()}
    pids=[x.id for x in db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email==user).all()]
    if pids:symbols|={x.symbol for x in db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id.in_(pids)).all()}
    return sorted(symbols)


def _f(v,default=0.0):
    try:return float(v) if v is not None else default
    except (TypeError,ValueError):return default


def _latest_features(db:Session,symbol:str,limit:int=2)->list[FeatureSnapshot]:
    return db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==symbol).order_by(FeatureSnapshot.as_of.desc(),FeatureSnapshot.created_at.desc()).limit(limit).all()


def _feature_changes(db:Session,symbols:list[str])->list[dict]:
    out=[]
    for s in symbols:
        rows=_latest_features(db,s,2)
        if not rows:continue
        cur=rows[0].payload or {};prev=rows[1].payload or {} if len(rows)>1 else {}
        buy=_f(cur.get("buy_score"),50);sell=_f(cur.get("sell_score"),50);pb=prev.get("buy_score");ps=prev.get("sell_score")
        buy_change=round(buy-_f(pb,buy),1);sell_change=round(sell-_f(ps,sell),1)
        flags=[];will=cur.get("williams_r");pwill=prev.get("williams_r")
        if will is not None and float(will)<=-80 and (pwill is None or float(pwill)>-80):flags.append("Williams %R entered oversold zone")
        if will is not None and float(will)>=-20 and (pwill is None or float(pwill)<-20):flags.append("Williams %R entered overbought zone")
        for key,label in [("ma100_distance","100MA"),("ma200_distance","200MA")]:
            now=cur.get(key);old=prev.get(key)
            if now is not None and abs(float(now))<=10 and (old is None or abs(float(old))>10):flags.append(f"Entered 10% {label} proximity")
        if abs(buy_change)>=5 or abs(sell_change)>=5 or flags:
            out.append({"symbol":s,"as_of":rows[0].as_of,"buy_score":buy,"sell_score":sell,"buy_change":buy_change,"sell_change":sell_change,"new_flags":flags})
    return sorted(out,key=lambda x:max(abs(x["buy_change"]),abs(x["sell_change"]),3*len(x["new_flags"])),reverse=True)


def _flow_bias(payload:dict)->str:
    side=str(payload.get("side") or payload.get("option_type") or "").lower();agg=str(payload.get("aggression") or payload.get("execution") or payload.get("direction") or "").lower()
    buy=any(x in agg for x in ["buy","ask","lift"]);sell=any(x in agg for x in ["sell","bid","hit"])
    if (side=="call" and buy) or (side=="put" and sell):return "bull"
    if (side=="call" and sell) or (side=="put" and buy):return "bear"
    return "neutral"


def _flow_rows(db:Session,hours:int=72)->list[FlowEvent]:
    cutoff=datetime.now(timezone.utc)-timedelta(hours=hours)
    return db.query(FlowEvent).filter(FlowEvent.occurred_at>=cutoff).order_by(FlowEvent.occurred_at.desc()).all()


def _flow_analytics(db:Session,hours:int=72)->dict:
    grouped=defaultdict(lambda:{"bullish_premium":0.0,"bearish_premium":0.0,"neutral_premium":0.0,"events":0,"contracts":set(),"hour1":0.0,"day1":0.0,"day3":0.0})
    now=datetime.now(timezone.utc)
    for r in _flow_rows(db,hours):
        p=r.payload or {};g=grouped[r.symbol];premium=_f(p.get("premium"));bias=_flow_bias(p);g[f"{bias}ish_premium" if bias in {"bull","bear"} else "neutral_premium"]+=premium;g["events"]+=1
        g["contracts"].add((p.get("side"),p.get("strike"),p.get("expiration")))
        age=(now-(r.occurred_at if r.occurred_at.tzinfo else r.occurred_at.replace(tzinfo=timezone.utc))).total_seconds()/3600
        if age<=1:g["hour1"]+=premium
        if age<=24:g["day1"]+=premium
        if age<=72:g["day3"]+=premium
    out=[]
    for s,g in grouped.items():
        m=_latest_market(db,s) or {};cap=_f(m.get("market_cap"));price=_f(m.get("price"));vol=_f(m.get("volume"));adv=price*vol if price and vol else 0;bull=g["bullish_premium"];bear=g["bearish_premium"];total=bull+bear+g["neutral_premium"]
        out.append({"symbol":s,"bullish_premium":round(bull,2),"bearish_premium":round(bear,2),"net_premium":round(bull-bear,2),"total_premium":round(total,2),"events":g["events"],"unique_contracts":len(g["contracts"]),"flow_to_market_cap":total/cap if cap else None,"flow_to_daily_dollar_volume":total/adv if adv else None,"premium_1h":round(g["hour1"],2),"premium_24h":round(g["day1"],2),"premium_72h":round(g["day3"],2),"market_cap":cap or None,"average_daily_dollar_volume_proxy":adv or None})
    out.sort(key=lambda x:(x["flow_to_market_cap"] or 0,x["total_premium"]),reverse=True)
    return {"rows":out,"methodology":"Uses stored unusual-options observations only. Relative flow = observed premium / cached market cap; liquidity-adjusted flow = observed premium / latest daily dollar-volume proxy. 1h/24h/72h totals expose persistence without additional provider calls."}


def _macro_rows(db:Session)->list[dict]:
    rows=[]
    for s,name in SECTORS.items():
        m=_latest_market(db,s)
        if not m:continue
        score=_f(m.get("change_percent"))*.25+_f(m.get("seven_day_percent"))*.45+_f(m.get("thirty_day_percent"))*.30
        rv=m.get("relative_volume")
        if rv is not None and float(rv)>1:score*=min(float(rv),2)
        rows.append({"symbol":s,"name":name,"category":MACRO_CATEGORIES.get(s,"Other"),"rotation_score":round(score,2),"day":m.get("change_percent"),"seven_day":m.get("seven_day_percent"),"thirty_day":m.get("thirty_day_percent"),"relative_volume":rv,"as_of":m.get("as_of")})
    return sorted(rows,key=lambda x:x["rotation_score"],reverse=True)


def _breadth(db:Session,symbols:list[str])->dict:
    rows=[]
    for s in symbols:
        m=_latest_market(db,s)
        if not m:continue
        rows.append(m)
    n=len(rows)
    def share(fn):return round(sum(1 for x in rows if fn(x))/n*100,1) if n else None
    return {"count":n,"above_50ma":share(lambda x:x.get("price_vs_ma50_percent") is not None and float(x["price_vs_ma50_percent"])>0),"above_100ma":share(lambda x:x.get("price_vs_ma100_percent") is not None and float(x["price_vs_ma100_percent"])>0),"above_200ma":share(lambda x:x.get("price_vs_ma200_percent") is not None and float(x["price_vs_ma200_percent"])>0),"positive_1d":share(lambda x:_f(x.get("change_percent"))>0),"positive_7d":share(lambda x:_f(x.get("seven_day_percent"))>0),"near_52w_high":share(lambda x:x.get("price") is not None and x.get("high_52_week") not in (None,0) and float(x["price"])/float(x["high_52_week"])-1>=-.05),"near_52w_low":share(lambda x:x.get("price") is not None and x.get("low_52_week") not in (None,0) and float(x["price"])/float(x["low_52_week"])-1<=.05),"methodology":"Breadth is calculated from the existing shared symbol cache. No provider call is made by this endpoint."}


def _bars(db:Session,symbol:str,limit:int=260)->list[HistoricalDailyBar]:
    rows=db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol==symbol).order_by(HistoricalDailyBar.bar_date.desc()).limit(limit).all();return list(reversed(rows))


def _returns(rows:list[HistoricalDailyBar])->dict[str,float]:
    out={}
    for a,b in zip(rows,rows[1:]):
        if a.close and b.close:out[b.bar_date]=b.close/a.close-1
    return out


def _corr(xs:list[float],ys:list[float])->float|None:
    if len(xs)<10 or len(xs)!=len(ys):return None
    mx,my=mean(xs),mean(ys);sx=sum((x-mx)**2 for x in xs);sy=sum((y-my)**2 for y in ys)
    if sx<=0 or sy<=0:return None
    return sum((x-mx)*(y-my) for x,y in zip(xs,ys))/math.sqrt(sx*sy)


def _beta(xs:list[float],ys:list[float])->float|None:
    if len(xs)<10 or len(xs)!=len(ys):return None
    my=mean(ys);mx=mean(xs);var=sum((y-my)**2 for y in ys)
    return sum((x-mx)*(y-my) for x,y in zip(xs,ys))/var if var>0 else None


def _aligned_returns(db:Session,a:str,b:str,limit:int=260):
    ra,rb=_returns(_bars(db,a,limit)),_returns(_bars(db,b,limit));dates=sorted(set(ra)&set(rb));return [ra[d] for d in dates],[rb[d] for d in dates]


def _portfolio_analytics(db:Session,user:str,portfolio_id:int)->dict:
    p=db.query(PortfolioDefinition).filter(PortfolioDefinition.id==portfolio_id,PortfolioDefinition.user_email==user).first()
    if not p:raise HTTPException(404,"Portfolio not found")
    positions=db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==p.id).all();vals=[];total=p.cash
    for pos in positions:
        m=_latest_market(db,pos.symbol) or {};px=m.get("price") if m.get("price") is not None else pos.imported_last_price;value=float(px or 0)*pos.shares;total+=value;vals.append((pos,m,value))
    invested=sum(v for _,_,v in vals);weights={pos.symbol:(v/invested if invested else 0) for pos,_,v in vals}
    bench=_returns(_bars(db,"SPY",260));series={}
    for pos,_,_ in vals:series[pos.symbol]=_returns(_bars(db,pos.symbol,260))
    dates=sorted(set(bench).intersection(*[set(x) for x in series.values()])) if series else []
    port_returns=[sum(weights[s]*series[s][d] for s in series) for d in dates]
    spy_returns=[bench[d] for d in dates]
    beta=_beta(port_returns,spy_returns);vol=pstdev(port_returns)*math.sqrt(252)*100 if len(port_returns)>=10 else None
    equity=1.0;peak=1.0;maxdd=0.0
    for r in port_returns:equity*=1+r;peak=max(peak,equity);maxdd=min(maxdd,equity/peak-1)
    pairs=[]
    syms=list(series)
    for i,a in enumerate(syms):
        for b in syms[i+1:]:
            xa,xb=_aligned_returns(db,a,b,180);c=_corr(xa,xb)
            if c is not None and c>=.65:pairs.append({"a":a,"b":b,"correlation":round(c,2)})
    pairs.sort(key=lambda x:x["correlation"],reverse=True)
    risk_raw=[]
    for s,w in weights.items():
        r=list(series[s].values())[-126:];sv=pstdev(r)*math.sqrt(252) if len(r)>=10 else 0;risk_raw.append((s,w*sv))
    risk_total=sum(x[1] for x in risk_raw);risk_contribution=[{"symbol":s,"weight":round(weights[s]*100,2),"risk_contribution":round(v/risk_total*100,2) if risk_total else None} for s,v in sorted(risk_raw,key=lambda x:x[1],reverse=True)]
    sectors=defaultdict(float)
    for pos,m,v in vals:sectors[str(m.get("sector") or "Unclassified")]+=v
    sector_exposure=[{"sector":k,"weight":round(v/invested*100,2) if invested else 0} for k,v in sorted(sectors.items(),key=lambda x:x[1],reverse=True)]
    history=db.query(PortfolioValueSnapshot).filter(PortfolioValueSnapshot.portfolio_id==p.id).order_by(PortfolioValueSnapshot.as_of.desc()).limit(365).all()
    return {"portfolio_id":p.id,"portfolio":p.name,"portfolio_beta_spy":round(beta,2) if beta is not None else None,"annualized_volatility_percent":round(vol,2) if vol is not None else None,"historical_max_drawdown_percent":round(maxdd*100,2) if port_returns else None,"correlation_clusters":pairs[:20],"risk_contribution":risk_contribution,"sector_exposure":sector_exposure,"cash_weight":round(p.cash/total*100,2) if total else 0,"history":[{"as_of":x.as_of,"market_value":x.market_value,"invested_value":x.invested_value,"cash":x.cash} for x in reversed(history)],"methodology":"Beta, volatility and pairwise correlations use aligned stored daily returns. Risk contribution is a transparent approximation using current portfolio weight × each holding's annualized volatility; it is not a covariance risk model. Exact ETF constituent overlap is intentionally not estimated without a constituent source."}


def _liquidity(db:Session)->dict:
    tickers={s:_latest_market(db,s) for s in ["VIX","HYG","LQD","UUP","TLT","IEF","IWM","RSP","SPY","QQQ"]};signals=[]
    def add(label,sym,field="seven_day_percent",invert=False):
        m=tickers.get(sym) or {};v=m.get(field)
        if v is not None:signals.append({"label":label,"symbol":sym,"value":v,"risk_direction":"worse" if (float(v)>0 if invert else float(v)<0) else "better"})
    add("High-yield credit","HYG");add("Investment-grade credit","LQD");add("Dollar pressure","UUP",invert=True);add("Long-duration rates proxy","TLT");add("Small-cap breadth","IWM");add("Equal-weight breadth","RSP")
    vix=(tickers.get("VIX") or {}).get("price");stress=0
    if vix is not None:stress+=max(0,min(40,(float(vix)-15)*2))
    stress+=sum(10 for x in signals if x["risk_direction"]=="worse")
    return {"stress_score":round(min(100,stress),1),"signals":signals,"snapshots":tickers,"methodology":"Risk/liquidity context uses shared VIX, credit, dollar, duration and breadth proxies. It is a dashboard heuristic, not a direct liquidity measurement."}


@router.get("/command-center")
def command_center(user:str=Depends(current_user),db:Session=Depends(get_db)):
    symbols=_user_symbols(db,user);markets=[]
    for s in symbols:
        m=_latest_market(db,s)
        if m:markets.append({"symbol":s,"day":m.get("change_percent"),"seven_day":m.get("seven_day_percent"),"thirty_day":m.get("thirty_day_percent"),"williams":m.get("williams_r_14"),"as_of":m.get("as_of")})
    movers=sorted(markets,key=lambda x:abs(_f(x.get("day"))),reverse=True)[:10];changes=_feature_changes(db,symbols)[:12];macro=_macro_rows(db);flow=_flow_analytics(db,72)["rows"][:10]
    try:events=sorted(build_event_payload(db,user,30,"all")["events"],key=lambda e:str(e.get("event_date") or ""))[:16]
    except Exception:events=[]
    alerts=db.query(AlertEvent).filter(AlertEvent.user_email==user,AlertEvent.acknowledged==False).order_by(AlertEvent.created_at.desc()).limit(20).all()  # noqa: E712
    portfolios=db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email==user).all();portfolio_risk=[]
    for p in portfolios:
        positions=db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==p.id).all();vals=[]
        for pos in positions:
            m=_latest_market(db,pos.symbol) or {};px=m.get("price") if m.get("price") is not None else pos.imported_last_price;vals.append((pos.symbol,float(px or 0)*pos.shares))
        invested=sum(v for _,v in vals);top=max(vals,key=lambda x:x[1]) if vals else None
        portfolio_risk.append({"id":p.id,"name":p.name,"largest_position":top[0] if top else None,"largest_position_weight":round(top[1]/invested*100,1) if top and invested else None,"cash":p.cash})
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"tracked_symbols":len(symbols),"movers":movers,"score_changes":changes,"new_flag_count":sum(len(x["new_flags"]) for x in changes),"macro":{"leaders":macro[:6],"weakness":list(reversed(macro[-6:])) if macro else []},"relative_flow":flow,"upcoming_events":events,"unacknowledged_alerts":[{"id":a.id,"symbol":a.symbol,"label":a.label,"value":a.value,"created_at":a.created_at.isoformat()} for a in alerts],"portfolio_risk":portfolio_risk,"breadth":_breadth(db,symbols),"liquidity":_liquidity(db),"methodology":"Command Center is change-first: it reuses stored market/features/flow/portfolio data and cached event catalogs. It does not independently refetch each tab."}


@router.get("/analytics/breadth")
def breadth(scope:str=Query("macro",pattern="^(macro|user)$"),user:str=Depends(current_user),db:Session=Depends(get_db)):
    symbols=list(SECTORS) if scope=="macro" else _user_symbols(db,user);return {"scope":scope,**_breadth(db,symbols)}


@router.get("/analytics/relative-strength")
def relative_strength(scope:str=Query("user",pattern="^(user|macro)$"),limit:int=Query(100,ge=1,le=200),user:str=Depends(current_user),db:Session=Depends(get_db)):
    symbols=_user_symbols(db,user) if scope=="user" else list(SECTORS);spy=_latest_market(db,"SPY") or {};qqq=_latest_market(db,"QQQ") or {};rows=[]
    for s in symbols[:limit]:
        m=_latest_market(db,s)
        if not m:continue
        rows.append({"symbol":s,"day":m.get("change_percent"),"seven_day":m.get("seven_day_percent"),"thirty_day":m.get("thirty_day_percent"),"vs_spy_7d":round(_f(m.get("seven_day_percent"))-_f(spy.get("seven_day_percent")),2),"vs_spy_30d":round(_f(m.get("thirty_day_percent"))-_f(spy.get("thirty_day_percent")),2),"vs_qqq_7d":round(_f(m.get("seven_day_percent"))-_f(qqq.get("seven_day_percent")),2),"vs_qqq_30d":round(_f(m.get("thirty_day_percent"))-_f(qqq.get("thirty_day_percent")),2),"category":MACRO_CATEGORIES.get(s)})
    rows.sort(key=lambda x:x["vs_spy_30d"],reverse=True);return {"rows":rows,"methodology":"Relative strength is return spread versus SPY or QQQ over the same stored 7D/30D windows, not RSI."}


@router.get("/analytics/liquidity")
def liquidity(db:Session=Depends(get_db)):return _liquidity(db)


@router.get("/flow/analytics")
def flow_analytics(hours:int=Query(72,ge=1,le=168),db:Session=Depends(get_db)):return _flow_analytics(db,hours)


@router.get("/opportunities/{symbol}/history")
def opportunity_history(symbol:str,days:int=Query(90,ge=7,le=730),db:Session=Depends(get_db)):
    s=symbol.strip().upper();cut=(date.today()-timedelta(days=days)).isoformat();rows=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==s,FeatureSnapshot.as_of>=cut).order_by(FeatureSnapshot.as_of).all();return {"symbol":s,"history":[{"as_of":r.as_of,"buy_score":(r.payload or {}).get("buy_score"),"sell_score":(r.payload or {}).get("sell_score"),"technical":((r.payload or {}).get("components") or {}).get("technical"),"valuation":((r.payload or {}).get("components") or {}).get("valuation"),"sector":((r.payload or {}).get("components") or {}).get("sector"),"flow":((r.payload or {}).get("components") or {}).get("flow"),"momentum":((r.payload or {}).get("components") or {}).get("momentum"),"risk":((r.payload or {}).get("components") or {}).get("risk")} for r in rows],"methodology":"Historical opportunity scores come from persisted daily feature snapshots; no historical score is reconstructed with future data."}


@router.get("/portfolios/{portfolio_id}/analytics")
def portfolio_analytics(portfolio_id:int,user:str=Depends(current_user),db:Session=Depends(get_db)):return _portfolio_analytics(db,user,portfolio_id)


@router.get("/system/data-lineage")
def data_lineage(db:Session=Depends(get_db)):
    fundamentals=db.query(FundamentalCache).all();coverage={"pe":0,"ps":0,"peg":0,"total":len(fundamentals)}
    for f in fundamentals:
        p=f.payload or {};coverage["pe"]+=p.get("pe_ratio") is not None;coverage["ps"]+=p.get("price_to_sales_ratio") is not None;coverage["peg"]+=p.get("peg_ratio") is not None
    return {"provider_policy":PROVIDER_POLICY,"freshness":{k:{"ttl_seconds":v.ttl_seconds,"priority":v.priority} for k,v in FRESHNESS_POLICIES.items()},"fundamental_coverage":coverage,"field_policy":{"pe_ratio":["Yahoo Finance direct/derived","SEC EDGAR EPS + shared price","Alpha Vantage fallback"],"price_to_sales_ratio":["Yahoo Finance direct/derived","SEC EDGAR revenue + market cap","Alpha Vantage fallback"],"peg_ratio":["Yahoo Finance direct","P/E ÷ positive earnings growth estimate","Alpha Vantage fallback"],"market_cap":["Yahoo Finance","shares outstanding × shared price","Alpha Vantage fallback"]},"quality_states":["live","cached","derived","stale","unavailable","not_applicable"],"macro_categories":TRACKING_RATIONALE}
