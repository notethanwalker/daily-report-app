from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AlertRule
from ..services.candidate_alert_context_v4 import CONTEXT_ALERT_KINDS, PORTFOLIO_BREACH_KIND, V4_ALERT_DEFINITIONS, evaluate_candidate_context_alert
from ..services.typed_alerts import PORTFOLIO_PREFIX, evaluate_typed_value
from ..v2_models import AlertDeliveryPreference
from .intelligence import current_user
from .portfolio_access import _portfolio_or_404, _require

router=APIRouter(prefix="/api/v1/alerts/v4",tags=["alerts-context-v4"])


class ContextAlertIn(BaseModel):
    kind:str
    symbol:str|None=None
    portfolio_id:int|None=None
    threshold:float|None=Field(default=None,ge=0,le=100)
    label:str=Field(min_length=1,max_length=256)
    channels:dict[str,bool]=Field(default_factory=lambda:{"in_app":True,"push":False})
    cooldown_minutes:int=Field(default=360,ge=15,le=10080)


def _target(db:Session,user:str,body:ContextAlertIn):
    if body.kind in CONTEXT_ALERT_KINDS:
        symbol=(body.symbol or "").strip().upper()
        if not symbol:raise HTTPException(400,"Ticker is required for this alert")
        return symbol
    if body.kind==PORTFOLIO_BREACH_KIND:
        if body.portfolio_id is None:raise HTTPException(400,"Portfolio is required for this alert")
        _portfolio_or_404(db,user,body.portfolio_id)
        if body.threshold is None:raise HTTPException(400,"Threshold is required for portfolio concentration alerts")
        return f"{PORTFOLIO_PREFIX}{body.portfolio_id}"
    raise HTTPException(400,"Unsupported V4 semantic alert type")


def _current(db:Session,user:str,kind:str,target:str,threshold:float|None):
    if kind in CONTEXT_ALERT_KINDS:
        return evaluate_candidate_context_alert(db,kind,target)
    value,meta=evaluate_typed_value(db,user,"portfolio_position_weight",target)
    breached=bool(value is not None and threshold is not None and value>=threshold)
    return value,{**(meta or {}),"state":"breached" if breached else "within_limit"}


@router.get("/definitions")
def semantic_alert_definitions(user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts")
    return {"definitions":V4_ALERT_DEFINITIONS,"evaluation":"15-minute scheduler; cache-only; transition-native; first observation establishes baseline without notification"}


@router.post("/preview")
def preview_semantic_alert(body:ContextAlertIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts");target=_target(db,user,body);value,meta=_current(db,user,body.kind,target,body.threshold)
    return {"kind":body.kind,"target":target,"threshold":body.threshold,"current_value":value,"current_meta":meta,"transition_native":True,"would_notify_now":False,"note":"Creation establishes the current state as baseline. Delivery begins only after a qualifying subsequent transition."}


@router.post("")
def create_semantic_alert(body:ContextAlertIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts");target=_target(db,user,body)
    existing=db.query(AlertRule).filter(AlertRule.user_email==user,AlertRule.symbol==target,AlertRule.kind==body.kind,AlertRule.enabled.is_(True)).first()
    if existing:
        value,meta=_current(db,user,existing.kind,existing.symbol or "",existing.threshold)
        return {"id":existing.id,"status":"already_exists","kind":existing.kind,"target":existing.symbol,"current_value":value,"current_meta":meta}
    threshold=body.threshold if body.kind==PORTFOLIO_BREACH_KIND else None
    row=AlertRule(user_email=user,symbol=target,kind=body.kind,operator="changed",threshold=threshold,label=body.label,enabled=True);db.add(row);db.flush()
    db.add(AlertDeliveryPreference(alert_id=row.id,user_email=user,channels={"in_app":bool(body.channels.get("in_app",True)),"push":bool(body.channels.get("push",False))},cooldown_minutes=body.cooldown_minutes));db.commit()
    value,meta=_current(db,user,row.kind,row.symbol or "",row.threshold)
    return {"id":row.id,"status":"created","kind":row.kind,"target":row.symbol,"threshold":row.threshold,"current_value":value,"current_meta":meta,"transition_native":True}
