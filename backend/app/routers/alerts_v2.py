from __future__ import annotations

import hashlib
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AlertRule
from ..v2_models import AlertDeliveryPreference, PushSubscription
from ..services.typed_alerts import PORTFOLIO_PREFIX, evaluate_typed_value, typed_trigger
from .intelligence import _latest_market, _opportunity_components, current_user
from .portfolio_access import _portfolio_or_404, _require

router=APIRouter(prefix="/api/v1",tags=["alerts-v2"])

SUPPORTED_VARIABLES={
    "price":{"label":"Price","unit":"USD","source":"Markets","description":"Latest shared market price."},
    "change_1d":{"label":"1D change","unit":"%","source":"Markets","description":"Change versus the previous completed daily close."},
    "change_7d":{"label":"7D change","unit":"%","source":"Markets","description":"Return across the stored 7-day comparison window."},
    "change_30d":{"label":"30D change","unit":"%","source":"Markets","description":"Return across the stored 30-day comparison window."},
    "williams":{"label":"Williams %R","unit":"index","source":"Markets / Research","description":"14-period Williams %R derived from shared daily history."},
    "relative_volume":{"label":"Relative volume","unit":"x","source":"Markets","description":"Current daily volume divided by the 20-day average volume."},
    "ma50_distance":{"label":"50MA distance","unit":"%","source":"Markets / Research","description":"Signed price distance from the 50-day moving average."},
    "ma100_distance":{"label":"100MA distance","unit":"%","source":"Markets / Research","description":"Signed price distance from the 100-day moving average."},
    "ma200_distance":{"label":"200MA distance","unit":"%","source":"Markets / Research","description":"Signed price distance from the 200-day moving average."},
    "ath_distance":{"label":"ATH distance","unit":"%","source":"Markets / Research","description":"Price distance from the stored all-time high."},
    "pe":{"label":"P/E","unit":"ratio","source":"Markets / Research","description":"Trailing or derived price-to-earnings ratio from cached fundamentals."},
    "ps":{"label":"P/S","unit":"ratio","source":"Markets / Research","description":"Price-to-sales ratio from cached fundamentals."},
    "peg":{"label":"PEG","unit":"ratio","source":"Markets / Research","description":"P/E divided by available earnings-growth estimate."},
    "buy_score":{"label":"Buy score","unit":"0-100","source":"Opportunities","description":"Auditable composite opportunity score."},
    "sell_score":{"label":"Sell score","unit":"0-100","source":"Opportunities","description":"Inverse opportunity / trim score."},
    "sector_score":{"label":"Sector score","unit":"score","source":"Macro / Opportunities","description":"Weighted 1D/7D/30D performance of the related sector proxy."},
    "bullish_flow":{"label":"Bullish flow premium","unit":"USD","source":"Large Flow","description":"Recent bullish unusual-options premium stored for the symbol."},
    "bearish_flow":{"label":"Bearish flow premium","unit":"USD","source":"Large Flow","description":"Recent bearish unusual-options premium stored for the symbol."},
}

TYPED_VARIABLES={
    "ma100_proximity":{"label":"100MA proximity","unit":"absolute % distance","scope":"ticker","description":"Absolute price distance from the 100-day moving average; unlike signed distance this does not fire simply because price is far below the average."},
    "ma200_proximity":{"label":"200MA proximity","unit":"absolute % distance","scope":"ticker","description":"Absolute price distance from the 200-day moving average."},
    "catalyst_days":{"label":"Days to next catalyst","unit":"days","scope":"ticker","description":"Minimum non-negative days to cached earnings/dividend dates or a user custom event for the ticker."},
    "persistent_flow":{"label":"Persistent options-flow cluster","unit":"observations","scope":"ticker","description":"Largest repeated stored contract-signature cluster in the trailing 72 hours; does not identify a participant."},
    "portfolio_position_weight":{"label":"Largest portfolio position","unit":"% portfolio","scope":"portfolio","description":"Current largest single-position weight in the selected private portfolio."},
    "regime_transition":{"label":"Regime transition","unit":"state change","scope":"global","description":"Fires once for each newly stored change in the confidence-weighted regime state."},
}


def _legacy_value(db:Session,rule:AlertRule):
    if not rule.symbol:return None
    m=_latest_market(db,rule.symbol) or {};o=_opportunity_components(db,rule.symbol,m) if m else None
    flow=(o or {}).get("flow") or {}
    mapping={
        "price":m.get("price"),"change_1d":m.get("change_percent"),"change_7d":m.get("seven_day_percent"),"change_30d":m.get("thirty_day_percent"),
        "williams":m.get("williams_r_14"),"relative_volume":m.get("relative_volume"),"ma50_distance":m.get("price_vs_ma50_percent"),
        "ma100_distance":m.get("price_vs_ma100_percent"),"ma200_distance":m.get("price_vs_ma200_percent"),"ath_distance":m.get("price_vs_ath_percent"),
        "pe":m.get("pe_ratio"),"ps":m.get("price_to_sales_ratio"),"peg":m.get("peg_ratio"),"buy_score":(o or {}).get("buy_score"),
        "sell_score":(o or {}).get("sell_score"),"sector_score":(o or {}).get("sector_score"),"bullish_flow":flow.get("bullish_premium"),"bearish_flow":flow.get("bearish_premium"),
    }
    return mapping.get(rule.kind)


def current_value(db:Session,rule:AlertRule):
    if rule.kind in TYPED_VARIABLES:
        value,meta=evaluate_typed_value(db,rule.user_email,rule.kind,rule.symbol)
        return value,meta
    return _legacy_value(db,rule),{}


class AlertBatchIn(BaseModel):
    symbols:list[str]=Field(min_length=1,max_length=100)
    kind:str
    operator:Literal[">=","<=",">","<","=="]="<="
    threshold:float
    label:str=Field(min_length=1,max_length=256)
    channels:dict[str,bool]=Field(default_factory=lambda:{"in_app":True,"push":True})
    cooldown_minutes:int=Field(default=360,ge=15,le=10080)

class TypedAlertIn(BaseModel):
    kind:str
    symbol:str|None=None
    portfolio_id:int|None=None
    operator:Literal[">=","<=",">","<","==","changed"]="<="
    threshold:float|None=None
    label:str=Field(min_length=1,max_length=256)
    channels:dict[str,bool]=Field(default_factory=lambda:{"in_app":True,"push":False})
    cooldown_minutes:int=Field(default=360,ge=15,le=10080)

class SubscriptionIn(BaseModel):
    subscription:dict
    platform:str|None=None

class SubscriptionDelete(BaseModel):
    endpoint:str


def _typed_target(db:Session,user:str,body:TypedAlertIn):
    meta=TYPED_VARIABLES.get(body.kind)
    if not meta:raise HTTPException(400,"Unsupported typed alert variable")
    scope=meta["scope"]
    if scope=="ticker":
        symbol=(body.symbol or "").strip().upper()
        if not symbol:raise HTTPException(400,"Ticker is required for this alert")
        return symbol
    if scope=="portfolio":
        if body.portfolio_id is None:raise HTTPException(400,"Portfolio is required for this alert")
        _portfolio_or_404(db,user,body.portfolio_id)
        return f"{PORTFOLIO_PREFIX}{body.portfolio_id}"
    return None


@router.get("/alerts/v2")
def alerts_v2(user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts")
    rows=db.query(AlertRule).filter(AlertRule.user_email==user).order_by(AlertRule.created_at.desc()).all();out=[]
    for r in rows:
        pref=db.query(AlertDeliveryPreference).filter(AlertDeliveryPreference.alert_id==r.id).first();value,meta=current_value(db,r)
        if r.kind in TYPED_VARIABLES:triggered=typed_trigger(r.kind,value,r.operator,r.threshold)
        else:triggered=value is not None and r.threshold is not None and {">=":value>=r.threshold,"<=":value<=r.threshold,">":value>r.threshold,"<":value<r.threshold,"==":value==r.threshold}.get(r.operator,False)
        out.append({"id":r.id,"symbol":r.symbol,"kind":r.kind,"operator":r.operator,"threshold":r.threshold,"label":r.label,"enabled":r.enabled,"current_value":value,"current_meta":meta,"triggered":triggered,"typed":r.kind in TYPED_VARIABLES,"delivery":{"channels":(pref.channels if pref else {"in_app":True,"push":False}),"cooldown_minutes":pref.cooldown_minutes if pref else 360}})
    return {"alerts":out,"variables":SUPPORTED_VARIABLES,"typed_variables":TYPED_VARIABLES,"push":{"configured":bool(os.getenv("VAPID_PUBLIC_KEY") and os.getenv("VAPID_PRIVATE_KEY")),"subscriptions":db.query(PushSubscription).filter(PushSubscription.user_email==user,PushSubscription.enabled.is_(True)).count()}}


@router.post("/alerts/v2")
def create_alerts(body:AlertBatchIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts")
    if body.kind not in SUPPORTED_VARIABLES:raise HTTPException(400,"Unsupported alert variable")
    created=[]
    for raw in body.symbols:
        symbol=raw.strip().upper()
        if not symbol:continue
        row=AlertRule(user_email=user,symbol=symbol,kind=body.kind,operator=body.operator,threshold=body.threshold,label=body.label,enabled=True);db.add(row);db.flush()
        db.add(AlertDeliveryPreference(alert_id=row.id,user_email=user,channels={"in_app":bool(body.channels.get("in_app",True)),"push":bool(body.channels.get("push",False))},cooldown_minutes=body.cooldown_minutes));created.append({"id":row.id,"symbol":symbol})
    db.commit();return {"created":created,"count":len(created)}


@router.post("/alerts/v3/preview")
def preview_typed_alert(body:TypedAlertIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts");target=_typed_target(db,user,body)
    value,meta=evaluate_typed_value(db,user,body.kind,target)
    return {"kind":body.kind,"scope":TYPED_VARIABLES[body.kind]["scope"],"target":target,"current_value":value,"current_meta":meta,"would_trigger":typed_trigger(body.kind,value,body.operator,body.threshold)}


@router.post("/alerts/v3")
def create_typed_alert(body:TypedAlertIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts");target=_typed_target(db,user,body)
    if body.kind=="regime_transition":operator="changed";threshold=None
    else:
        operator=body.operator
        if body.threshold is None:raise HTTPException(400,"Threshold is required for this alert")
        threshold=body.threshold
    row=AlertRule(user_email=user,symbol=target,kind=body.kind,operator=operator,threshold=threshold,label=body.label,enabled=True);db.add(row);db.flush()
    db.add(AlertDeliveryPreference(alert_id=row.id,user_email=user,channels={"in_app":bool(body.channels.get("in_app",True)),"push":bool(body.channels.get("push",False))},cooldown_minutes=body.cooldown_minutes));db.commit()
    value,meta=evaluate_typed_value(db,user,row.kind,row.symbol)
    return {"id":row.id,"status":"created","kind":row.kind,"target":row.symbol,"current_value":value,"current_meta":meta}


@router.delete("/alerts/v2/{alert_id}")
def delete_alert_v2(alert_id:int,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts");row=db.query(AlertRule).filter(AlertRule.id==alert_id,AlertRule.user_email==user).first()
    if not row:raise HTTPException(404,"Alert not found")
    pref=db.query(AlertDeliveryPreference).filter(AlertDeliveryPreference.alert_id==row.id).first()
    if pref:db.delete(pref)
    db.delete(row);db.commit();return {"status":"removed"}


@router.get("/push/config")
def push_config(user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts");public=os.getenv("VAPID_PUBLIC_KEY","")
    return {"configured":bool(public and os.getenv("VAPID_PRIVATE_KEY")),"public_key":public or None,"subscriptions":db.query(PushSubscription).filter(PushSubscription.user_email==user,PushSubscription.enabled.is_(True)).count(),"note":"Web Push works on installed iOS/iPadOS PWAs and compatible desktop/mobile browsers after notification permission is granted."}


@router.post("/push/subscriptions")
def save_subscription(body:SubscriptionIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_alerts");endpoint=str((body.subscription or {}).get("endpoint") or "")
    if not endpoint:raise HTTPException(400,"Push subscription endpoint is required")
    digest=hashlib.sha256(endpoint.encode()).hexdigest();row=db.query(PushSubscription).filter(PushSubscription.endpoint_hash==digest).first()
    if row:row.user_email=user;row.subscription=body.subscription;row.platform=body.platform;row.enabled=True
    else:db.add(PushSubscription(user_email=user,endpoint_hash=digest,subscription=body.subscription,platform=body.platform,enabled=True))
    db.commit();return {"status":"subscribed"}


@router.delete("/push/subscriptions")
def delete_subscription(body:SubscriptionDelete,user:str=Depends(current_user),db:Session=Depends(get_db)):
    digest=hashlib.sha256(body.endpoint.encode()).hexdigest();row=db.query(PushSubscription).filter(PushSubscription.endpoint_hash==digest,PushSubscription.user_email==user).first()
    if row:db.delete(row);db.commit()
    return {"status":"unsubscribed"}
