import json
import os
from datetime import datetime, timedelta, timezone

from ..models import AlertEvent, AlertRule, FeatureSnapshot, MarketSnapshot
from ..v2_models import AlertDeliveryPreference, PushSubscription


def _latest_market(db, symbol):
    if not symbol:return None
    row=db.query(MarketSnapshot).filter(MarketSnapshot.symbol==symbol.upper()).order_by(MarketSnapshot.retrieved_at.desc()).first()
    return {**(row.payload or {})} if row else None


def _latest_features(db, symbol):
    if not symbol:return None
    row=db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol==symbol.upper()).order_by(FeatureSnapshot.created_at.desc()).first()
    return {**(row.payload or {})} if row else None


def _value(rule, market, features):
    market=market or {};features=features or {}
    return {
        "price":market.get("price"),
        "change_1d":market.get("change_percent"),
        "change_7d":market.get("seven_day_percent"),
        "change_30d":market.get("thirty_day_percent"),
        "williams":market.get("williams_r_14"),
        "relative_volume":market.get("relative_volume"),
        "ma50_distance":market.get("price_vs_ma50_percent"),
        "ma100_distance":market.get("price_vs_ma100_percent"),
        "ma200_distance":market.get("price_vs_ma200_percent"),
        "ath_distance":market.get("price_vs_ath_percent"),
        "pe":market.get("pe_ratio") or features.get("pe"),
        "ps":market.get("price_to_sales_ratio") or features.get("ps"),
        "peg":market.get("peg_ratio") or features.get("peg"),
        "buy_score":features.get("buy_score"),
        "sell_score":features.get("sell_score"),
        "sector_score":features.get("sector_score"),
        "bullish_flow":features.get("bullish_flow"),
        "bearish_flow":features.get("bearish_flow"),
    }.get(rule.kind)


def _triggered(value, operator, threshold):
    if value is None or threshold is None:return False
    return {">=":value>=threshold,"<=":value<=threshold,">":value>threshold,"<":value<threshold,"==":value==threshold}.get(operator,False)


def _send_pushes(db, event: AlertEvent, rule: AlertRule, pref: AlertDeliveryPreference | None):
    channels=(pref.channels if pref else {}) or {}
    if not channels.get("push"):return
    private=os.getenv("VAPID_PRIVATE_KEY");subject=os.getenv("VAPID_SUBJECT","mailto:admin@daily-report.local")
    if not private or not os.getenv("VAPID_PUBLIC_KEY"):return
    try:
        from pywebpush import WebPushException, webpush
    except Exception:
        return
    payload=json.dumps({"title":f"{rule.symbol or 'Market'} alert","body":f"{rule.label}: {event.value if event.value is not None else 'condition met'}","url":"/?tab=Alerts","tag":f"daily-report-alert-{rule.id}","alert_id":rule.id})
    stale=[]
    for sub in db.query(PushSubscription).filter(PushSubscription.user_email==rule.user_email,PushSubscription.enabled.is_(True)).all():
        try:webpush(subscription_info=sub.subscription,data=payload,vapid_private_key=private,vapid_claims={"sub":subject},ttl=300)
        except Exception as exc:
            status=getattr(getattr(exc,"response",None),"status_code",None)
            if status in {404,410}:stale.append(sub)
    for sub in stale:db.delete(sub)


def evaluate_alerts(db):
    now=datetime.now(timezone.utc);created=[]
    for rule in db.query(AlertRule).filter(AlertRule.enabled.is_(True)).all():
        market=_latest_market(db,rule.symbol);features=_latest_features(db,rule.symbol);value=_value(rule,market,features)
        if not _triggered(value,rule.operator,rule.threshold):continue
        pref=db.query(AlertDeliveryPreference).filter(AlertDeliveryPreference.alert_id==rule.id).first();cooldown=max(15,int(pref.cooldown_minutes if pref else 360))
        last=db.query(AlertEvent).filter(AlertEvent.alert_id==rule.id).order_by(AlertEvent.created_at.desc()).first()
        if last:
            at=last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=timezone.utc)
            if now-at<timedelta(minutes=cooldown):continue
        event=AlertEvent(alert_id=rule.id,user_email=rule.user_email,symbol=rule.symbol,label=rule.label,value=float(value) if value is not None else None,payload={"kind":rule.kind,"operator":rule.operator,"threshold":rule.threshold,"observed":value,"channels":pref.channels if pref else {"in_app":True}})
        db.add(event);db.flush();created.append(rule.id)
        _send_pushes(db,event,rule,pref)
    if created:db.commit()
    return created
