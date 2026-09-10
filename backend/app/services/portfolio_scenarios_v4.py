from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from math import sqrt

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import MarketSnapshot, SymbolRegistry
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from ..normalized_market_models import NormalizedDailyBar
from .opportunity_model import SECTOR_PROXY

MODEL_VERSION = "portfolio-scenarios-v4.1"
HISTORY_DAYS = 260
MIN_OBSERVATIONS = 40
HEDGE_PROXIES = ("SPY", "QQQ")


def _latest_market_map(db:Session,symbols:list[str])->dict[str,dict]:
    symbols=sorted({str(x).upper() for x in symbols if x})
    if not symbols:return {}
    sub=db.query(MarketSnapshot.symbol,func.max(MarketSnapshot.id).label("max_id")).filter(MarketSnapshot.symbol.in_(symbols)).group_by(MarketSnapshot.symbol).subquery()
    rows=db.query(MarketSnapshot).join(sub,MarketSnapshot.id==sub.c.max_id).all()
    return {r.symbol.upper():dict(r.payload or {}) for r in rows}


def _returns(db:Session,symbols:list[str])->dict[str,dict[str,float]]:
    cutoff=(date.today()-timedelta(days=HISTORY_DAYS)).isoformat();symbols=sorted(set(symbols))
    rows=db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol.in_(symbols),NormalizedDailyBar.bar_date>=cutoff).order_by(NormalizedDailyBar.symbol,NormalizedDailyBar.bar_date).all()
    closes=defaultdict(list)
    for r in rows:closes[r.symbol.upper()].append((r.bar_date,float(r.close)))
    out={}
    for s,series in closes.items():
        prev=None;d={}
        for day,close in series:
            if prev not in (None,0):d[day]=close/prev-1
            prev=close
        out[s]=d
    return out


def _weighted(returns:dict[str,dict[str,float]],weights:dict[str,float])->dict[str,float]:
    dates=sorted({d for s in weights for d in returns.get(s,{})});out={}
    for day in dates:
        present=[(w,returns.get(s,{}).get(day)) for s,w in weights.items() if returns.get(s,{}).get(day) is not None]
        represented=sum(w for w,_ in present)
        if represented<.60:continue
        out[day]=sum((w/represented)*r for w,r in present)
    return out


def _corr(a:dict[str,float],b:dict[str,float]):
    common=sorted(set(a)&set(b))
    if len(common)<MIN_OBSERVATIONS:return None,len(common)
    x=[a[d] for d in common];y=[b[d] for d in common];mx=sum(x)/len(x);my=sum(y)/len(y)
    num=sum((u-mx)*(v-my) for u,v in zip(x,y));dx=sqrt(sum((u-mx)**2 for u in x));dy=sqrt(sum((v-my)**2 for v in y))
    return ((max(-1,min(1,num/(dx*dy)))) if dx and dy else None),len(common)


def _vol(r:dict[str,float]):
    vals=list(r.values())
    if len(vals)<MIN_OBSERVATIONS:return None
    m=sum(vals)/len(vals);sd=sqrt(sum((x-m)**2 for x in vals)/(len(vals)-1));return sd*sqrt(252)*100


def _max_dd(r:dict[str,float]):
    vals=[r[d] for d in sorted(r)]
    if not vals:return None
    equity=peak=1.0;worst=0.0
    for x in vals:
        equity*=1+x;peak=max(peak,equity);worst=min(worst,equity/peak-1)
    return worst*100


def _beta(a:dict[str,float],b:dict[str,float]):
    common=sorted(set(a)&set(b))
    if len(common)<MIN_OBSERVATIONS:return None,len(common)
    x=[a[d] for d in common];y=[b[d] for d in common];mx=sum(x)/len(x);my=sum(y)/len(y)
    cov=sum((u-mx)*(v-my) for u,v in zip(x,y))/(len(x)-1);var=sum((v-my)**2 for v in y)/(len(y)-1)
    return (cov/var if var else None),len(common)


def _themes(reg:SymbolRegistry|None)->set[str]:
    value=reg.themes if reg else None
    if isinstance(value,dict):return {str(k) for k,v in value.items() if v}
    if isinstance(value,(list,tuple,set)):return {str(x) for x in value if x}
    return set()


def _exposure(values:dict[str,float],registry:dict[str,SymbolRegistry],total:float):
    sectors=defaultdict(float);themes=defaultdict(float)
    if total<=0:return {},{}
    for symbol,value in values.items():
        reg=registry.get(symbol)
        if reg and reg.sector:sectors[str(reg.sector)]+=value/total*100
        for theme in _themes(reg):themes[theme]+=value/total*100
    return dict(sectors),dict(themes)


def _hedge_reference(candidate:str,sector:str|None,returns:dict[str,dict[str,float]])->dict:
    proxies=list(HEDGE_PROXIES)
    sector_proxy=SECTOR_PROXY.get(sector or "")
    if sector_proxy and sector_proxy not in proxies:proxies.append(sector_proxy)
    candidates=[]
    for proxy in proxies:
        corr,n=_corr(returns.get(candidate,{}),returns.get(proxy,{}));beta,bn=_beta(returns.get(candidate,{}),returns.get(proxy,{}))
        if corr is not None:candidates.append({"symbol":proxy,"correlation":round(corr,3),"beta":round(beta,3) if beta is not None else None,"observations":min(n,bn)})
    if not candidates:return {"available":False,"reason":"Insufficient overlapping stored return history for hedge proxies."}
    best=max(candidates,key=lambda x:abs(x["correlation"]))
    return {"available":True,"reference":best,"alternatives":sorted(candidates,key=lambda x:abs(x["correlation"]),reverse=True),"interpretation":"A positively correlated proxy could be used as a directional hedge reference; beta is a historical sensitivity estimate, not a recommended hedge size.","policy":"Reference only. The engine does not place trades or assume short/option availability."}


def build_buy_scenario(db:Session,user:str,portfolio_id:int,symbol:str,amount:float,funding_source:str="cash")->dict:
    symbol=symbol.upper();funding_source=str(funding_source or "cash").lower()
    if amount<=0:raise ValueError("Scenario amount must be greater than zero")
    if funding_source not in {"cash","external"}:raise ValueError("funding_source must be cash or external")
    portfolio=db.query(PortfolioDefinition).filter(PortfolioDefinition.id==portfolio_id,PortfolioDefinition.user_email==user).first()
    if not portfolio:raise ValueError("Portfolio not found")
    positions=db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==portfolio.id,PortfolioPosition.shares>0).all()
    symbols=[p.symbol.upper() for p in positions];all_market_symbols=sorted(set(symbols+[symbol]+list(HEDGE_PROXIES)))
    registry_rows=db.query(SymbolRegistry).filter(SymbolRegistry.symbol.in_(all_market_symbols)).all();registry={r.symbol.upper():r for r in registry_rows}
    candidate_reg=registry.get(symbol);sector=str(candidate_reg.sector) if candidate_reg and candidate_reg.sector else None
    sector_proxy=SECTOR_PROXY.get(sector or "")
    if sector_proxy and sector_proxy not in all_market_symbols:all_market_symbols.append(sector_proxy)
    markets=_latest_market_map(db,all_market_symbols)
    values={}
    for p in positions:
        px=(markets.get(p.symbol.upper()) or {}).get("price")
        value=float(px)*p.shares if px is not None else float(p.imported_market_value or p.average_cost*p.shares)
        values[p.symbol.upper()]=max(0.0,value)
    invested=sum(values.values());cash=float(portfolio.cash or 0);before_total=invested+cash
    if funding_source=="cash" and amount>cash:raise ValueError(f"Scenario exceeds available cash (${cash:,.2f})")
    candidate_price=(markets.get(symbol) or {}).get("price")
    if candidate_price is None or float(candidate_price)<=0:raise ValueError("Candidate has no current stored market price")
    after_values=dict(values);after_values[symbol]=after_values.get(symbol,0)+amount
    after_cash=cash-amount if funding_source=="cash" else cash
    after_total=before_total if funding_source=="cash" else before_total+amount
    all_symbols=sorted(set(after_values)|set(HEDGE_PROXIES)|({sector_proxy} if sector_proxy else set()))
    if symbol not in registry:
        row=db.get(SymbolRegistry,symbol)
        if row:registry[symbol]=row
    before_sector,before_theme=_exposure(values,registry,before_total);after_sector,after_theme=_exposure(after_values,registry,after_total)
    returns=_returns(db,all_symbols)
    before_weights={s:v/before_total for s,v in values.items() if before_total>0 and v>0};after_weights={s:v/after_total for s,v in after_values.items() if after_total>0 and v>0}
    before_r=_weighted(returns,before_weights);after_r=_weighted(returns,after_weights);candidate_r=returns.get(symbol,{})
    corr,n=_corr(candidate_r,before_r);candidate_vol=_vol(candidate_r);before_vol=_vol(before_r);after_vol=_vol(after_r);before_dd=_max_dd(before_r);after_dd=_max_dd(after_r)
    candidate_dd=_max_dd(candidate_r);candidate_weight=amount/after_total*100 if after_total else 0
    current_symbol=values.get(symbol,0)/before_total*100 if before_total else 0;after_symbol=after_values.get(symbol,0)/after_total*100 if after_total else 0
    sector_before=before_sector.get(sector,0) if sector else None;sector_after=after_sector.get(sector,0) if sector else None
    theme_changes=[]
    for theme in sorted(_themes(candidate_reg)):
        b=before_theme.get(theme,0);a=after_theme.get(theme,0);theme_changes.append({"theme":theme,"before_percent":round(b,2),"after_percent":round(a,2),"delta_points":round(a-b,2)})
    hedge=_hedge_reference(symbol,sector,returns)
    return {
        "model_version":MODEL_VERSION,"scenario":"buy","portfolio":{"id":portfolio.id,"name":portfolio.name},"symbol":symbol,"amount":round(amount,2),"funding_source":funding_source,"candidate_price":round(float(candidate_price),4),"estimated_shares":round(amount/float(candidate_price),6),
        "before":{"total_value":round(before_total,2),"cash":round(cash,2),"cash_percent":round(cash/before_total*100,2) if before_total else None,"symbol_exposure_percent":round(current_symbol,2),"sector":sector,"sector_exposure_percent":round(sector_before,2) if sector_before is not None else None,"annualized_volatility_percent":round(before_vol,2) if before_vol is not None else None,"historical_max_drawdown_percent":round(before_dd,2) if before_dd is not None else None},
        "after":{"total_value":round(after_total,2),"cash":round(after_cash,2),"cash_percent":round(after_cash/after_total*100,2) if after_total else None,"symbol_exposure_percent":round(after_symbol,2),"sector":sector,"sector_exposure_percent":round(sector_after,2) if sector_after is not None else None,"annualized_volatility_percent":round(after_vol,2) if after_vol is not None else None,"historical_max_drawdown_percent":round(after_dd,2) if after_dd is not None else None},
        "changes":{"cash_percent_points":round(after_cash/after_total*100-cash/before_total*100,2) if before_total and after_total else None,"symbol_exposure_points":round(after_symbol-current_symbol,2),"sector_exposure_points":round(sector_after-sector_before,2) if sector_before is not None and sector_after is not None else None,"annualized_volatility_points":round(after_vol-before_vol,2) if before_vol is not None and after_vol is not None else None,"historical_max_drawdown_points":round(after_dd-before_dd,2) if before_dd is not None and after_dd is not None else None},
        "candidate_risk":{"portfolio_correlation":round(corr,3) if corr is not None else None,"correlation_observations":n,"standalone_annualized_volatility_percent":round(candidate_vol,2) if candidate_vol is not None else None,"standalone_max_drawdown_percent":round(candidate_dd,2) if candidate_dd is not None else None,"approx_drawdown_contribution_points":round(abs(candidate_dd)*candidate_weight/100,2) if candidate_dd is not None else None,"scenario_weight_percent":round(candidate_weight,2)},
        "theme_changes":theme_changes,"hedge_reference":hedge,
        "policy":"Read-only scenario analysis. No holdings or cash are mutated. Historical volatility, correlation and drawdown are descriptive estimates from stored daily returns; they are not forecasts, expected-return scores, or automatic sizing recommendations."
    }
