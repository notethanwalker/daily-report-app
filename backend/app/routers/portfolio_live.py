from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from ..v2_models import PortfolioBaseline, PortfolioPositionBaseline, PortfolioPositionRevision
from ..v3_models import PortfolioValueSnapshot
from .intelligence import _latest_market, _opportunity_components, current_user
from .portfolio_access import _ensure_joint_fidelity, _portfolio_or_404, _queue_symbol, _require

router=APIRouter(prefix="/api/v1",tags=["portfolio-live"])


class LivePositionIn(BaseModel):
    symbol:str
    shares:float=Field(ge=0)
    average_cost:float=Field(ge=0)
    note:str|None=Field(default=None,max_length=256)


def _ensure_position_baseline(db:Session,pos:PortfolioPosition,market:dict|None=None):
    baseline=db.get(PortfolioPositionBaseline,pos.id)
    if baseline:return baseline
    market=market or _latest_market(db,pos.symbol) or {}
    initial_price=pos.imported_last_price if pos.imported_last_price is not None else market.get("price")
    initial_value=pos.imported_market_value if pos.imported_market_value is not None else ((float(initial_price)*pos.shares) if initial_price is not None else None)
    baseline=PortfolioPositionBaseline(
        position_id=pos.id,
        initial_shares=pos.shares,
        initial_average_cost=pos.average_cost,
        initial_cost_basis=pos.shares*pos.average_cost,
        initial_market_price=float(initial_price) if initial_price is not None else None,
        initial_market_value=float(initial_value) if initial_value is not None else None,
        recorded_at=pos.imported_at or pos.created_at or datetime.now(timezone.utc),
    )
    db.add(baseline);db.flush();return baseline


def _ensure_portfolio_baseline(db:Session,p:PortfolioDefinition,positions:list[PortfolioPosition]):
    row=db.get(PortfolioBaseline,p.id)
    if row:return row
    invested=0.0
    for pos in positions:
        b=_ensure_position_baseline(db,pos)
        invested+=float(b.initial_market_value if b.initial_market_value is not None else b.initial_cost_basis)
    row=PortfolioBaseline(portfolio_id=p.id,initial_cash=p.cash,initial_invested_value=invested,initial_total_value=invested+p.cash)
    db.add(row);db.flush();return row


def _position_payload(db:Session,pos:PortfolioPosition,total_live:float):
    market=_latest_market(db,pos.symbol) or {}
    live_price=market.get("price")
    if live_price is None:live_price=pos.imported_last_price
    live_price=float(live_price) if live_price is not None else None
    live_value=live_price*pos.shares if live_price is not None else float(pos.imported_market_value or 0)
    cost_basis=pos.average_cost*pos.shares
    baseline=_ensure_position_baseline(db,pos,market)
    opportunity=_opportunity_components(db,pos.symbol,market) if market else None
    return {
        "id":pos.id,"symbol":pos.symbol,"shares":pos.shares,"average_cost":pos.average_cost,"cost_basis":round(cost_basis,2),
        "price":round(live_price,6) if live_price is not None else None,"market_value":round(live_value,2),
        "account_percent":round(live_value/total_live*100,2) if total_live else 0,
        "unrealized_pl":round(live_value-cost_basis,2),"unrealized_percent":round((live_value/cost_basis-1)*100,2) if cost_basis else None,
        "buy_score":opportunity.get("buy_score") if opportunity else None,"sell_score":opportunity.get("sell_score") if opportunity else None,
        "market":market,
        "live":{"price":live_price,"market_value":round(live_value,2),"account_percent":round(live_value/total_live*100,2) if total_live else 0,"as_of":market.get("as_of"),"retrieved_at":market.get("retrieved_at"),"provider":market.get("provider")},
        "baseline":{"shares":baseline.initial_shares,"average_cost":baseline.initial_average_cost,"cost_basis":round(baseline.initial_cost_basis,2),"market_price":baseline.initial_market_price,"market_value":baseline.initial_market_value,"recorded_at":baseline.recorded_at.isoformat() if baseline.recorded_at else None},
        "imported_snapshot":{"last_price":pos.imported_last_price,"market_value":pos.imported_market_value,"day_gain":pos.imported_day_gain,"day_gain_percent":pos.imported_day_gain_percent,"total_gain":pos.imported_total_gain,"total_gain_percent":pos.imported_total_gain_percent,"account_percent":pos.imported_account_percent,"imported_at":pos.imported_at.isoformat() if pos.imported_at else None},
    }


def _persist_value_snapshot(db:Session,p:PortfolioDefinition,holdings:list[dict],invested:float,total:float):
    # One end-state snapshot per calendar day is enough for portfolio history while
    # keeping database churn and provider demand negligible. Repeated live requests
    # update the same row instead of creating minute-by-minute noise.
    as_of=date.today().isoformat()
    row=db.query(PortfolioValueSnapshot).filter(PortfolioValueSnapshot.portfolio_id==p.id,PortfolioValueSnapshot.as_of==as_of).first()
    payload={"positions":[{"symbol":h["symbol"],"shares":h["shares"],"price":h["price"],"market_value":h["market_value"],"account_percent":h["account_percent"]} for h in holdings]}
    if row:
        row.market_value=total;row.invested_value=invested;row.cash=p.cash;row.payload=payload
    else:
        db.add(PortfolioValueSnapshot(portfolio_id=p.id,as_of=as_of,market_value=total,invested_value=invested,cash=p.cash,payload=payload))


@router.get("/portfolios/{portfolio_id}")
def portfolio_live(portfolio_id:int,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _ensure_joint_fidelity(db,user);p=_portfolio_or_404(db,user,portfolio_id)
    positions=db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==p.id).order_by(PortfolioPosition.symbol).all()
    baseline=_ensure_portfolio_baseline(db,p,positions)
    live_values=[]
    for pos in positions:
        m=_latest_market(db,pos.symbol) or {};px=m.get("price") if m.get("price") is not None else pos.imported_last_price
        live_values.append(float(px or 0)*pos.shares if px is not None else float(pos.imported_market_value or 0))
    invested=sum(live_values);total=invested+p.cash
    holdings=[_position_payload(db,pos,total) for pos in positions]
    _persist_value_snapshot(db,p,holdings,invested,total)
    db.commit()
    cost=sum(x["cost_basis"] for x in holdings);pnl=invested-cost
    return {
        "portfolio":{"id":p.id,"name":p.name,"brokerage":p.brokerage,"account_type":p.account_type,"cash":p.cash,"is_default":p.is_default,"source_note":p.source_note,"updated_at":p.updated_at.isoformat() if p.updated_at else None},
        "holdings":holdings,"invested_value":round(invested,2),"market_value":round(total,2),"cost_basis":round(cost,2),"unrealized_pl":round(pnl,2),"unrealized_percent":round((invested/cost-1)*100,2) if cost else None,"cash_percent":round(p.cash/total*100,2) if total else 0,
        "baseline":{"initial_cash":round(baseline.initial_cash,2),"initial_invested_value":round(baseline.initial_invested_value,2),"initial_total_value":round(baseline.initial_total_value,2),"recorded_at":baseline.recorded_at.isoformat() if baseline.recorded_at else None},
        "live_note":"Current prices, account percentages, portfolio value and unrealized P/L are recalculated from the latest shared market snapshot on every request. Original position metrics remain preserved in the baseline/imported snapshot. One portfolio-value history point is persisted per day.",
    }


@router.post("/portfolios/{portfolio_id}/positions/live")
def set_live_position(portfolio_id:int,body:LivePositionIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_portfolios");p=_portfolio_or_404(db,user,portfolio_id);symbol=body.symbol.strip().upper()
    row=db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==p.id,PortfolioPosition.symbol==symbol).first()
    if row:
        _ensure_position_baseline(db,row)
        db.add(PortfolioPositionRevision(position_id=row.id,shares=row.shares,average_cost=row.average_cost,cost_basis=row.shares*row.average_cost,note=body.note or "Position updated"))
        row.shares=body.shares;row.average_cost=body.average_cost
    else:
        row=PortfolioPosition(portfolio_id=p.id,symbol=symbol,shares=body.shares,average_cost=body.average_cost);db.add(row);db.flush();_ensure_position_baseline(db,row)
        db.add(PortfolioPositionRevision(position_id=row.id,shares=body.shares,average_cost=body.average_cost,cost_basis=body.shares*body.average_cost,note=body.note or "Position created"))
    _queue_symbol(db,symbol,user);db.commit();return {"status":"saved","symbol":symbol,"position_id":row.id,"baseline_preserved":True}


@router.get("/portfolios/{portfolio_id}/revisions")
def position_revisions(portfolio_id:int,user:str=Depends(current_user),db:Session=Depends(get_db)):
    p=_portfolio_or_404(db,user,portfolio_id);positions=db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==p.id).all();ids=[x.id for x in positions]
    if not ids:return {"revisions":[]}
    rows=db.query(PortfolioPositionRevision).filter(PortfolioPositionRevision.position_id.in_(ids)).order_by(PortfolioPositionRevision.created_at.desc()).limit(500).all();symbols={x.id:x.symbol for x in positions}
    return {"revisions":[{"id":r.id,"position_id":r.position_id,"symbol":symbols.get(r.position_id),"shares":r.shares,"average_cost":r.average_cost,"cost_basis":r.cost_basis,"note":r.note,"created_at":r.created_at.isoformat()} for r in rows]}
