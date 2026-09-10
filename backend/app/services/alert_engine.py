import json
import os
from datetime import datetime, timedelta, timezone

from ..models import AlertEvent, AlertRule, FeatureSnapshot, MarketSnapshot
from ..v2_models import AlertDeliveryPreference, PushSubscription
from ..v4_models import AlertEvaluationStateV4
from .alert_transition_logic_v4 import transition_entered
from .opportunity_formula_alerts_v4 import FORMULA_ALERT_KINDS, evaluate_formula_alert_values
from .typed_alerts import evaluate_typed_value, typed_trigger

TRANSITION_KINDS={"opportunity_convergence","williams_oversold_entry","williams_oversold_recovery","ma100_approach_from_above","williams_ma100_trigger","opportunity_invalidated",*FORMULA_ALERT_KINDS}
TYPED_KINDS={"ma100_proximity","ma200_proximity","catalyst_days","persistent_flow","portfolio_position_weight","regime_transition",*TRANSITION_KINDS}


def _latest_market(db,symbol):
    if not symbol:return None
    row=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol.upper()).order_by(MarketSnapshot.retrieved_at.desc()).first();return {**(row.payload or {})} if row else None

def _latest_features(db,symbol):
    if not symbol:return None
    row=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==symbol.upper()).order_by(FeatureSnapshot.created_at.desc()).first();return {**(row.payload or {})} if row else None

def _legacy_value(rule,market,features):
    market=market or {};features=features or {}
    return {"price":market.get("price"),"change_1d":market.get("change_percent"),"change_7d":market.get("seven_day_percent"),"change_30d":market.get("thirty_day_percent"),"williams":market.get("williams_r_14"),"relative_volume":market.get("relative_volume"),"ma50_distance":market.get("price_vs_ma50_percent"),"ma100_distance":market.get("price_vs_ma100_percent"),"ma200_distance":market.get("price_vs_ma200_percent"),"ath_distance":market.get("price_vs_ath_percent"),"pe":market.get("pe_ratio") or features.get("pe"),"ps":market.get("price_to_sales_ratio") or features.get("ps"),"peg":market.get("peg_ratio") or features.get("peg"),"buy_score":features.get("buy_score"),"sell_score":features.get("sell_score"),"sector_score":features.get("sector_score"),"bullish_flow":features.get("bullish_flow"),"bearish_flow":features.get("bearish_flow")}.get(rule.kind)
def _legacy_triggered(value,operator,threshold):
    if value is None or threshold is None:return False
    return {">=":value>=threshold,"<=":value<=threshold,">":value>threshold,"<":value<threshold,"==":value==threshold}.get(operator,False)


def _transition_trigger(db,rule,meta,default_triggered):
    if rule.kind not in TRANSITION_KINDS:return default_triggered,False
    meta=meta or {};current=str(meta.get("state") or "unavailable");row=db.get(AlertEvaluationStateV4,rule.id);previous=row.state if row else None;entered=transition_entered(rule.kind,previous,current,meta)
    payload={"previous_state":previous,"current_state":current,"model_version":meta.get("model_version"),"model_config_hash":meta.get("model_config_hash"),"score":meta.get("score"),"rank":meta.get("rank"),"formula_id":meta.get("formula_id")}
    if row:
        row.kind=rule.kind;row.symbol=rule.symbol;row.state=current;row.state_as_of=meta.get("as_of") or meta.get("last_cache_update");row.payload=payload
    else:
        db.add(AlertEvaluationStateV4(alert_id=rule.id,kind=rule.kind,symbol=rule.symbol,state=current,state_as_of=meta.get("as_of") or meta.get("last_cache_update"),payload=payload))
    meta["previous_state"]=previous;meta["transition_entered"]=entered;meta["event_key"]=f"{rule.kind}:{rule.id}:{meta.get('as_of') or meta.get('last_cache_update')}:{previous}->{current}" if entered else None
    return entered,True

def _send_pushes(db,event:AlertEvent,rule:AlertRule,pref:AlertDeliveryPreference|None):
    channels=(pref.channels if pref else {}) or {}
    if not channels.get("push"):return
    private=os.getenv("VAPID_PRIVATE_KEY");subject=os.getenv("VAPID_SUBJECT","mailto:admin@daily-report.local")
    if not private or not os.getenv("VAPID_PUBLIC_KEY"):return
    try:from pywebpush import webpush
    except Exception:return
    meta=(event.payload or {}).get("meta") or {}
    transition_bodies={
        "opportunity_convergence":f"{rule.symbol} entered Triggered · convergence {meta.get('convergence_score') if meta.get('convergence_score') is not None else '—'}",
        "williams_oversold_entry":f"{rule.symbol} Williams %R entered oversold · {meta.get('williams_r','—')}",
        "williams_oversold_recovery":f"{rule.symbol} Williams %R recovered above -80 · {meta.get('williams_r','—')}",
        "ma100_approach_from_above":f"{rule.symbol} approached the 100MA from above · {meta.get('signed_distance','—')}%",
        "williams_ma100_trigger":f"{rule.symbol} hit the combined Williams + 100MA trigger",
        "opportunity_invalidated":f"{rule.symbol} Opportunity convergence became Invalidated",
        "opportunity_formula_score":f"{rule.symbol} crossed the {meta.get('formula_name','saved formula')} score threshold · {meta.get('score','—')}",
        "opportunity_formula_rank":f"{rule.symbol} entered top {meta.get('top_n','—')} for {meta.get('formula_name','saved formula')} · rank #{meta.get('rank','—')}",
    }
    body=transition_bodies.get(rule.kind) or f"{rule.label}: {event.value if event.value is not None else 'condition met'}"
    payload=json.dumps({"title":f"{rule.symbol or 'Market'} alert","body":body,"url":"/?tab=Alerts","tag":f"daily-report-alert-{rule.id}","alert_id":rule.id});stale=[]
    for sub in db.query(PushSubscription).filter(PushSubscription.user_email==rule.user_email,PushSubscription.enabled.is_(True)).all():
        try:webpush(subscription_info=sub.subscription,data=payload,vapid_private_key=private,vapid_claims={"sub":subject},ttl=300)
        except Exception as exc:
            status=getattr(getattr(exc,"response",None),"status_code",None)
            if status in {404,410}:stale.append(sub)
    for sub in stale:db.delete(sub)

def evaluate_alerts(db):
    now=datetime.now(timezone.utc);created=[];state_changed=False;rules=db.query(AlertRule).filter(AlertRule.enabled.is_(True)).all();formula_values=evaluate_formula_alert_values(db,rules)
    for rule in rules:
        typed=rule.kind in TYPED_KINDS;meta={}
        if rule.kind in FORMULA_ALERT_KINDS:
            value,meta=formula_values.get(rule.id,(None,{"state":"unavailable","reason":"formula_value_missing"}));triggered=False
        elif typed:
            value,meta=evaluate_typed_value(db,rule.user_email,rule.kind,rule.symbol);triggered=typed_trigger(rule.kind,value,rule.operator,rule.threshold)
        else:
            market=_latest_market(db,rule.symbol);features=_latest_features(db,rule.symbol);value=_legacy_value(rule,market,features);triggered=_legacy_triggered(value,rule.operator,rule.threshold)
        triggered,changed=_transition_trigger(db,rule,meta,triggered);state_changed=state_changed or changed
        if not triggered:continue
        pref=db.query(AlertDeliveryPreference).filter(AlertDeliveryPreference.alert_id==rule.id).first();cooldown=max(15,int(pref.cooldown_minutes if pref else 360));last=db.query(AlertEvent).filter(AlertEvent.alert_id==rule.id).order_by(AlertEvent.created_at.desc()).first();event_key=(meta or {}).get("event_key")
        if last:
            if event_key and (last.payload or {}).get("event_key")==event_key:continue
            at=last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=timezone.utc)
            if now-at<timedelta(minutes=cooldown):continue
        payload={"kind":rule.kind,"operator":rule.operator,"threshold":rule.threshold,"observed":value,"typed":typed,"meta":meta,"channels":pref.channels if pref else {"in_app":True}}
        if event_key:payload["event_key"]=event_key
        event=AlertEvent(alert_id=rule.id,user_email=rule.user_email,symbol=rule.symbol,label=rule.label,value=float(value) if value is not None else None,payload=payload);db.add(event);db.flush();created.append(rule.id);_send_pushes(db,event,rule,pref)
    if created or state_changed:db.commit()
    return created
