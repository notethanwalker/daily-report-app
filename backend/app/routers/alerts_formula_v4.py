from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AlertRule
from ..services.opportunity_formula_alerts_v4 import FORMULA_ALERT_KINDS, evaluate_formula_alert_values
from ..v2_models import AlertDeliveryPreference
from ..v4_models import AlertEvaluationStateV4, OpportunityFormulaAlertBindingV4, OpportunityFormulaPresetV4
from .intelligence import current_user
from .portfolio_access import _require

router=APIRouter(prefix="/api/v1/alerts/v4",tags=["alerts-formula-v4"])


class FormulaAlertIn(BaseModel):
    formula_id:int=Field(gt=0)
    symbol:str=Field(min_length=1,max_length=20)
    mode:Literal["score","rank"]
    threshold:float=Field(gt=0)
    label:str=Field(min_length=1,max_length=256)
    channels:dict[str,bool]=Field(default_factory=lambda:{"in_app":True,"push":False})
    cooldown_minutes:int=Field(default=360,ge=15,le=10080)


def _formula_or_404(db:Session,user:str,formula_id:int):
    row=db.query(OpportunityFormulaPresetV4).filter(OpportunityFormulaPresetV4.id==formula_id,OpportunityFormulaPresetV4.user_id==user).first()
    if not row:raise HTTPException(404,"Saved Opportunity formula not found")
    return row


def _kind(mode:str)->str:return "opportunity_formula_score" if mode=="score" else "opportunity_formula_rank"


def _validate_threshold(mode:str,value:float)->float:
    number=float(value)
    if mode=="score" and not 0<number<=100:raise HTTPException(400,"Formula score threshold must be greater than 0 and no more than 100")
    if mode=="rank" and not 1<=number<=1000:raise HTTPException(400,"Formula rank threshold must be between 1 and 1000")
    return number


@router.get("/formulas")
def list_formula_alerts(user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts")
    rules=db.query(AlertRule).filter(AlertRule.user_email==user,AlertRule.kind.in_(FORMULA_ALERT_KINDS)).order_by(AlertRule.created_at.desc()).all()
    values=evaluate_formula_alert_values(db,rules);ids=[r.id for r in rules]
    bindings={b.alert_id:b for b in db.query(OpportunityFormulaAlertBindingV4).filter(OpportunityFormulaAlertBindingV4.alert_id.in_(ids)).all()} if ids else {}
    rows=[]
    for rule in rules:
        binding=bindings.get(rule.id);value,meta=values.get(rule.id,(None,{"state":"unavailable"}));pref=db.query(AlertDeliveryPreference).filter(AlertDeliveryPreference.alert_id==rule.id).first()
        rows.append({"id":rule.id,"symbol":rule.symbol,"kind":rule.kind,"mode":binding.mode if binding else None,"formula_id":binding.formula_id if binding else None,"formula_name":meta.get("formula_name"),"threshold":rule.threshold,"label":rule.label,"enabled":rule.enabled,"current_value":value,"current_score":meta.get("score"),"current_rank":meta.get("rank"),"current_state":meta.get("state"),"last_cache_update":meta.get("last_cache_update"),"delivery":{"channels":pref.channels if pref else {"in_app":True,"push":False},"cooldown_minutes":pref.cooldown_minutes if pref else 360}})
    return {"alerts":rows,"policy":"Saved-formula alerts are evaluated cache-only every scheduler cycle. Active alerts are grouped by formula so each saved formula is scanned once per cycle, regardless of how many symbols are bound to it."}


@router.post("/formulas",status_code=201)
def create_formula_alert(body:FormulaAlertIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts");formula=_formula_or_404(db,user,body.formula_id);symbol=body.symbol.strip().upper();threshold=_validate_threshold(body.mode,body.threshold);kind=_kind(body.mode)
    if not symbol:raise HTTPException(400,"Ticker is required")
    existing=(db.query(OpportunityFormulaAlertBindingV4).join(AlertRule,AlertRule.id==OpportunityFormulaAlertBindingV4.alert_id).filter(OpportunityFormulaAlertBindingV4.user_id==user,OpportunityFormulaAlertBindingV4.formula_id==formula.id,OpportunityFormulaAlertBindingV4.symbol==symbol,OpportunityFormulaAlertBindingV4.mode==body.mode,AlertRule.enabled.is_(True)).first())
    if existing:
        rule=db.get(AlertRule,existing.alert_id);return {"id":rule.id,"status":"already_exists","formula_id":formula.id,"formula_name":formula.name,"symbol":symbol,"mode":body.mode,"threshold":rule.threshold}
    rule=AlertRule(user_email=user,symbol=symbol,kind=kind,operator="changed",threshold=threshold,label=body.label,enabled=True);db.add(rule);db.flush();db.add(OpportunityFormulaAlertBindingV4(alert_id=rule.id,user_id=user,formula_id=formula.id,symbol=symbol,mode=body.mode,config={}));db.add(AlertDeliveryPreference(alert_id=rule.id,user_email=user,channels={"in_app":bool(body.channels.get("in_app",True)),"push":bool(body.channels.get("push",False))},cooldown_minutes=body.cooldown_minutes));db.commit()
    value,meta=evaluate_formula_alert_values(db,[rule]).get(rule.id,(None,{"state":"unavailable"}))
    return {"id":rule.id,"status":"created","formula_id":formula.id,"formula_name":formula.name,"symbol":symbol,"mode":body.mode,"threshold":threshold,"current_value":value,"current_score":meta.get("score"),"current_rank":meta.get("rank"),"current_state":meta.get("state"),"note":"The first evaluation establishes baseline state; delivery begins on a later qualifying transition."}


@router.delete("/formulas/{alert_id}")
def delete_formula_alert(alert_id:int,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts");rule=db.query(AlertRule).filter(AlertRule.id==alert_id,AlertRule.user_email==user,AlertRule.kind.in_(FORMULA_ALERT_KINDS)).first()
    if not rule:raise HTTPException(404,"Saved-formula alert not found")
    binding=db.get(OpportunityFormulaAlertBindingV4,rule.id);state=db.get(AlertEvaluationStateV4,rule.id);pref=db.query(AlertDeliveryPreference).filter(AlertDeliveryPreference.alert_id==rule.id).first()
    if binding:db.delete(binding)
    if state:db.delete(state)
    if pref:db.delete(pref)
    db.delete(rule);db.commit();return {"status":"removed"}
