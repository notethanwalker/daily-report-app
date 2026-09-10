from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AlertRule
from ..services.opportunity_formula_alerts_v4 import FORMULA_ALERT_KINDS, evaluate_formula_alert_values
from ..services.typed_alerts import evaluate_typed_value, typed_trigger
from ..v2_models import AlertDeliveryPreference, PushSubscription
from ..v4_models import AlertEvaluationStateV4, OpportunityFormulaAlertBindingV4
from .alerts_v2 import SUPPORTED_VARIABLES, TRANSITION_NATIVE_KINDS, TYPED_VARIABLES, _legacy_value
from .intelligence import current_user
from .portfolio_access import _require

router=APIRouter(prefix="/api/v1",tags=["alerts-consistency-v4"])


@router.get("/alerts/v2")
def alerts_v2_consistent(user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts")
    rows=db.query(AlertRule).filter(AlertRule.user_email==user).order_by(AlertRule.created_at.desc()).all()
    formula_values=evaluate_formula_alert_values(db,rows)
    out=[]
    for rule in rows:
        pref=db.query(AlertDeliveryPreference).filter(AlertDeliveryPreference.alert_id==rule.id).first()
        if rule.kind in FORMULA_ALERT_KINDS:
            value,meta=formula_values.get(rule.id,(None,{"state":"unavailable","reason":"formula_value_missing"}));triggered=False;typed=True;transition_native=True
        elif rule.kind in TYPED_VARIABLES:
            value,meta=evaluate_typed_value(db,rule.user_email,rule.kind,rule.symbol);triggered=typed_trigger(rule.kind,value,rule.operator,rule.threshold);typed=True;transition_native=rule.kind in TRANSITION_NATIVE_KINDS or rule.kind=="opportunity_convergence"
        else:
            value=_legacy_value(db,rule);meta={};triggered=value is not None and rule.threshold is not None and {">=":value>=rule.threshold,"<=":value<=rule.threshold,">":value>rule.threshold,"<":value<rule.threshold,"==":value==rule.threshold}.get(rule.operator,False);typed=False;transition_native=False
        state=db.get(AlertEvaluationStateV4,rule.id) if transition_native else None
        out.append({"id":rule.id,"symbol":rule.symbol,"kind":rule.kind,"operator":rule.operator,"threshold":rule.threshold,"label":rule.label,"enabled":rule.enabled,"current_value":value,"current_meta":meta,"current_state":state.state if state else meta.get("state"),"triggered":triggered,"typed":typed,"transition_native":transition_native,"formula_alert":rule.kind in FORMULA_ALERT_KINDS,"delivery":{"channels":pref.channels if pref else {"in_app":True,"push":False},"cooldown_minutes":pref.cooldown_minutes if pref else 360}})
    return {"alerts":out,"variables":SUPPORTED_VARIABLES,"typed_variables":TYPED_VARIABLES,"push":{"configured":bool(os.getenv("VAPID_PUBLIC_KEY") and os.getenv("VAPID_PRIVATE_KEY")),"subscriptions":db.query(PushSubscription).filter(PushSubscription.user_email==user,PushSubscription.enabled.is_(True)).count()},"consistency_version":"alerts-v4"}


@router.delete("/alerts/v2/{alert_id}")
def delete_alert_v2_consistent(alert_id:int,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts")
    rule=db.query(AlertRule).filter(AlertRule.id==alert_id,AlertRule.user_email==user).first()
    if not rule:raise HTTPException(404,"Alert not found")
    binding=db.get(OpportunityFormulaAlertBindingV4,rule.id);state=db.get(AlertEvaluationStateV4,rule.id);pref=db.query(AlertDeliveryPreference).filter(AlertDeliveryPreference.alert_id==rule.id).first()
    if binding:
        if binding.user_id!=user:raise HTTPException(403,"Formula alert ownership mismatch")
        db.delete(binding)
    if state:db.delete(state)
    if pref:db.delete(pref)
    db.delete(rule);db.commit()
    return {"status":"removed","formula_binding_removed":bool(binding),"evaluation_state_removed":bool(state)}
