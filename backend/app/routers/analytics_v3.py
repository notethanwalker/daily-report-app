from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from .decision_support import _aligned_returns, _bars, _beta, _returns, _user_symbols
from .events_v3 import build_event_payload
from .intelligence import _latest_market, current_user

router=APIRouter(prefix="/api/v1",tags=["analytics-v3"])


@router.get("/analytics/catalyst-density")
def catalyst_density(user:str=Depends(current_user),db:Session=Depends(get_db)):
    events=build_event_payload(db,user,30,"all").get("events",[]);today=date.today();d7=(today+timedelta(days=7)).isoformat();d30=(today+timedelta(days=30)).isoformat();rows=defaultdict(lambda:{"count_7d":0,"count_30d":0,"high_impact_30d":0,"events":[]})
    for e in events:
        symbol=e.get("symbol")
        if not symbol:continue
        d=str(e.get("event_date") or "")[:10]
        if d<=d30:
            x=rows[symbol];x["count_30d"]+=1;x["high_impact_30d"]+=str(e.get("impact"))=="high";x["events"].append({"date":d,"title":e.get("title"),"impact":e.get("impact"),"category":e.get("category")})
            if d<=d7:x["count_7d"]+=1
    symbols=_user_symbols(db,user)
    return {"rows":[{"symbol":s,**rows[s]} for s in symbols if rows[s]["count_30d"]],"market_wide_events_30d":sum(1 for e in events if not e.get("symbol")),"methodology":"Ticker catalyst density counts scheduled symbol-specific events in the merged Events calendar. Market-wide macro events are reported separately rather than pretending every macro release is equally relevant to every ticker."}


def _period_return(rows,days):
    if len(rows)<2:return None
    end=rows[-1].close;idx=max(0,len(rows)-1-days);start=rows[idx].close
    return (end/start-1)*100 if start else None


@router.get("/portfolios/{portfolio_id}/performance")
def portfolio_performance(portfolio_id:int,user:str=Depends(current_user),db:Session=Depends(get_db)):
    p=db.query(PortfolioDefinition).filter(PortfolioDefinition.id==portfolio_id,PortfolioDefinition.user_email==user).first()
    if not p:raise HTTPException(404,"Portfolio not found")
    positions=db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==p.id).all();current=[]
    for pos in positions:
        m=_latest_market(db,pos.symbol) or {};px=m.get("price") if m.get("price") is not None else pos.imported_last_price;current.append((pos,float(px or 0)*pos.shares))
    invested=sum(v for _,v in current);weights={p.symbol:(v/invested if invested else 0) for p,v in current};benchmarks={}
    for bench in ["SPY","QQQ"]:
        br=_bars(db,bench,400);benchmarks[bench]={"30d":_period_return(br,30),"90d":_period_return(br,90),"252d":_period_return(br,252)}
    periods={"30d":30,"90d":90,"252d":252};portfolio={}
    for label,days in periods.items():
        total=0.0;used=0.0
        for pos,_ in current:
            r=_period_return(_bars(db,pos.symbol,max(300,days+10)),days)
            if r is not None:total+=weights[pos.symbol]*r;used+=weights[pos.symbol]
        portfolio[label]=total/used if used else None
    position_beta=[]
    for pos,_ in current:
        x,y=_aligned_returns(db,pos.symbol,"SPY",260);b=_beta(x,y);position_beta.append({"symbol":pos.symbol,"beta_spy":round(b,2) if b is not None else None,"weight":round(weights[pos.symbol]*100,2)})
    relative={bench:{period:(portfolio[period]-ret if portfolio[period] is not None and ret is not None else None) for period,ret in vals.items()} for bench,vals in benchmarks.items()}
    return {"portfolio":portfolio,"benchmarks":benchmarks,"relative":relative,"position_beta":position_beta,"methodology":"Portfolio period returns are a current-weight historical approximation from stored daily closes; they are not a transaction-aware time-weighted return. Benchmark spreads compare the same stored windows. Position beta uses aligned daily returns versus SPY."}
