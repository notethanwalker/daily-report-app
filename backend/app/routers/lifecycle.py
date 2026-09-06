from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AlertEvent, PortfolioAccount
from ..services.alert_engine import evaluate_alerts
from .intelligence import current_user

router=APIRouter(prefix="/api/v1",tags=["lifecycle"])

class CashIn(BaseModel):
    cash:float=Field(ge=0)

@router.get("/portfolio/account")
def portfolio_account(user:str=Depends(current_user),db:Session=Depends(get_db)):
    row=db.get(PortfolioAccount,user)
    return {"cash":row.cash if row else 0.0,"user":user}

@router.put("/portfolio/account")
def update_portfolio_account(body:CashIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    row=db.get(PortfolioAccount,user)
    if row:row.cash=body.cash
    else:db.add(PortfolioAccount(user_email=user,cash=body.cash))
    db.commit();return {"cash":body.cash,"status":"saved"}

@router.post("/alerts/evaluate")
def evaluate(user:str=Depends(current_user),db:Session=Depends(get_db)):
    created=evaluate_alerts(db);return {"created":len(created),"alert_ids":created}

@router.get("/alerts/events")
def alert_events(unacknowledged:bool=Query(default=True),user:str=Depends(current_user),db:Session=Depends(get_db)):
    q=db.query(AlertEvent).filter(AlertEvent.user_email==user)
    if unacknowledged:q=q.filter(AlertEvent.acknowledged.is_(False))
    rows=q.order_by(AlertEvent.created_at.desc()).limit(100).all()
    return {"events":[{"id":r.id,"alert_id":r.alert_id,"symbol":r.symbol,"label":r.label,"value":r.value,"data":r.payload,"acknowledged":r.acknowledged,"created_at":r.created_at.isoformat()} for r in rows]}

@router.post("/alerts/events/{event_id}/acknowledge")
def acknowledge_alert(event_id:int,user:str=Depends(current_user),db:Session=Depends(get_db)):
    row=db.query(AlertEvent).filter(AlertEvent.id==event_id,AlertEvent.user_email==user).first()
    if not row:raise HTTPException(404,"Alert event not found")
    row.acknowledged=True;db.commit();return {"status":"acknowledged","id":event_id}
