from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import HistoricalDailyBar
from ..multiuser_models import PortfolioPosition
from .intelligence import _latest_market, current_user
from .portfolio_access import _portfolio_or_404

router=APIRouter(prefix="/api/v1/future",tags=["next-intelligence"])

FACTOR_PROXIES={
    "market":{"symbol":"SPY","label":"US market"},
    "growth_duration":{"symbol":"QQQ","label":"Growth / duration"},
    "semiconductors":{"symbol":"SMH","label":"Semiconductors"},
    "small_caps":{"symbol":"IWM","label":"Small caps"},
    "momentum":{"symbol":"MTUM","label":"Momentum"},
    "quality":{"symbol":"QUAL","label":"Quality"},
    "low_volatility":{"symbol":"SPLV","label":"Low volatility"},
    "rates_duration":{"symbol":"TLT","label":"Long rates duration"},
    "dollar":{"symbol":"UUP","label":"US dollar"},
    "gold":{"symbol":"GLD","label":"Gold"},
}

REGIME_DIMENSIONS={
    "risk_appetite":{"label":"Risk appetite","weights":{"SPY":1.0,"QQQ":0.8,"IWM":0.8,"HYG":0.9,"TLT":-0.35}},
    "growth":{"label":"Growth / cyclicality","weights":{"QQQ":0.9,"SMH":1.0,"IWM":0.65,"SPY":0.45}},
    "inflation_pressure":{"label":"Inflation / commodity pressure","weights":{"USO":1.0,"GLD":0.35,"TLT":-0.75,"UUP":0.25}},
    "liquidity":{"label":"Liquidity / financial conditions","weights":{"HYG":1.0,"SPY":0.55,"QQQ":0.45,"UUP":-0.75,"TLT":0.25}},
    "rates_dollar_pressure":{"label":"Rates / dollar pressure","weights":{"UUP":0.9,"TLT":-1.0,"QQQ":-0.35,"GLD":0.25}},
}


def _bars(db:Session,symbol:str,days:int=260):
    rows=db.query(HistoricalDailyBar).filter(HistoricalDailyBar.symbol==symbol.upper()).order_by(HistoricalDailyBar.bar_date.desc()).limit(days+5).all()
    rows=list(reversed(rows))
    return {r.bar_date:float(r.close) for r in rows if r.close is not None}


def _returns(closes:dict[str,float]):
    dates=sorted(closes);out={}
    for a,b in zip(dates,dates[1:]):
        if closes[a]:out[b]=closes[b]/closes[a]-1
    return out


def _corr_beta(x:list[float],y:list[float]):
    if len(x)<20 or len(y)!=len(x):return None,None
    mx=sum(x)/len(x);my=sum(y)/len(y)
    cov=sum((a-mx)*(b-my) for a,b in zip(x,y))/(len(x)-1)
    vx=sum((a-mx)**2 for a in x)/(len(x)-1);vy=sum((b-my)**2 for b in y)/(len(y)-1)
    corr=cov/math.sqrt(vx*vy) if vx>0 and vy>0 else None
    beta=cov/vy if vy>0 else None
    return corr,beta


def _current_weights(db:Session,portfolio_id:int):
    positions=db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==portfolio_id).all();values=[]
    for pos in positions:
        m=_latest_market(db,pos.symbol) or {};px=m.get("price")
        if px is None:px=pos.imported_last_price
        val=float(px or 0)*float(pos.shares) if px is not None else float(pos.imported_market_value or 0)
        values.append((pos.symbol,val))
    total=sum(v for _,v in values)
    return [(s,v/total) for s,v in values if total>0 and v>0]


def _portfolio_return_series(db:Session,portfolio_id:int,days:int):
    weights=_current_weights(db,portfolio_id);by_symbol={s:_returns(_bars(db,s,days+10)) for s,_ in weights}
    all_dates=sorted(set().union(*(set(r) for r in by_symbol.values()))) if by_symbol else []
    out={}
    for d in all_dates:
        present=[(w,by_symbol[s].get(d)) for s,w in weights if by_symbol[s].get(d) is not None]
        covered=sum(w for w,_ in present)
        if covered<0.65:continue
        out[d]=sum(w*r for w,r in present)/covered
    return out,weights


@router.get("/portfolio/{portfolio_id}/factor-proxies")
def factor_proxies(portfolio_id:int,benchmark:str=Query(default="SPY",min_length=1,max_length=12),days:int=Query(default=126,ge=30,le=504),user:str=Depends(current_user),db:Session=Depends(get_db)):
    p=_portfolio_or_404(db,user,portfolio_id);portfolio_returns,weights=_portfolio_return_series(db,p.id,days)
    proxies={**FACTOR_PROXIES,"custom_benchmark":{"symbol":benchmark.strip().upper(),"label":f"Custom benchmark · {benchmark.strip().upper()}"}}
    rows=[]
    for key,meta in proxies.items():
        pr=_returns(_bars(db,meta["symbol"],days+10));common=sorted(set(portfolio_returns)&set(pr))
        x=[portfolio_returns[d] for d in common];y=[pr[d] for d in common];corr,beta=_corr_beta(x,y)
        port_total=(math.prod(1+r for r in x)-1)*100 if x else None;proxy_total=(math.prod(1+r for r in y)-1)*100 if y else None
        rows.append({"factor":key,"label":meta["label"],"symbol":meta["symbol"],"observations":len(common),"correlation":round(corr,3) if corr is not None else None,"beta":round(beta,3) if beta is not None else None,"portfolio_return_percent":round(port_total,2) if port_total is not None else None,"proxy_return_percent":round(proxy_total,2) if proxy_total is not None else None,"relative_return_percent":round(port_total-proxy_total,2) if port_total is not None and proxy_total is not None else None})
    return {"portfolio_id":p.id,"portfolio":p.name,"window_days":days,"weights":[{"symbol":s,"weight":round(w*100,2)} for s,w in weights],"proxies":rows,"methodology":"Proxy sensitivities use current portfolio weights applied to stored daily holding returns, then compare that reconstructed portfolio return series with liquid ETF proxies. Correlation and beta are descriptive sensitivities, not institutional multi-factor-model loadings. Missing history reduces observations rather than being imputed."}


def _signal(m:dict):
    d7=m.get("seven_day_percent");d30=m.get("thirty_day_percent")
    if d7 is None and d30 is None:return None
    a=float(d7 or 0);b=float(d30 or 0)
    return max(-10.0,min(10.0,a*0.65+b*0.20))


@router.get("/regime/dimensions")
def regime_dimensions(db:Session=Depends(get_db)):
    dimensions=[]
    for key,spec in REGIME_DIMENSIONS.items():
        evidence=[];weighted=0.0;abs_weight=0.0;signs=[]
        for symbol,weight in spec["weights"].items():
            m=_latest_market(db,symbol) or {};sig=_signal(m)
            if sig is None:continue
            contribution=sig*weight;weighted+=contribution;abs_weight+=abs(weight);signs.append(1 if contribution>0 else -1 if contribution<0 else 0)
            evidence.append({"symbol":symbol,"weight":weight,"signal":round(sig,2),"contribution":round(contribution,2),"as_of":m.get("as_of"),"retrieved_at":m.get("retrieved_at")})
        score=weighted/abs_weight if abs_weight else 0.0;coverage=abs_weight/sum(abs(w) for w in spec["weights"].values()) if spec["weights"] else 0
        nonzero=[s for s in signs if s];agreement=abs(sum(nonzero))/len(nonzero) if nonzero else 0
        confidence=coverage*0.55+agreement*0.45
        if coverage<0.55 or confidence<0.42:state="uncertain"
        elif score>=1.25:state="positive"
        elif score<=-1.25:state="negative"
        else:state="neutral"
        dimensions.append({"dimension":key,"label":spec["label"],"score":round(score,2),"state":state,"coverage_percent":round(coverage*100,1),"agreement_percent":round(agreement*100,1),"confidence_percent":round(confidence*100,1),"evidence":evidence})
    headline_votes=[1 if d["state"]=="positive" else -1 if d["state"]=="negative" else 0 for d in dimensions if d["state"]!="uncertain"]
    headline_score=sum(headline_votes)
    headline="uncertain" if len(headline_votes)<3 else "risk-supportive" if headline_score>=2 else "risk-restrictive" if headline_score<=-2 else "mixed"
    return {"headline":headline,"headline_vote":headline_score,"dimensions":dimensions,"methodology":"Each dimension combines bounded 7D/30D moves from transparent cross-asset proxies. Coverage and directional agreement determine confidence. Low coverage or weak agreement produces an explicit uncertain state rather than forcing a directional regime label."}
