from datetime import datetime, timedelta, timezone

from ..models import AlertEvent, AlertRule, FeatureSnapshot, MarketSnapshot


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
        "williams":market.get("williams_r_14"),
        "ma100_distance":market.get("price_vs_ma100_percent"),
        "ma200_distance":market.get("price_vs_ma200_percent"),
        "buy_score":features.get("buy_score"),
        "sell_score":features.get("sell_score"),
    }.get(rule.kind)


def _triggered(value, operator, threshold):
    if value is None or threshold is None:return False
    return {">=":value>=threshold,"<=":value<=threshold,">":value>threshold,"<":value<threshold,"==":value==threshold}.get(operator,False)


def evaluate_alerts(db):
    now=datetime.now(timezone.utc);created=[]
    for rule in db.query(AlertRule).filter(AlertRule.enabled.is_(True)).all():
        market=_latest_market(db,rule.symbol);features=_latest_features(db,rule.symbol);value=_value(rule,market,features)
        if not _triggered(value,rule.operator,rule.threshold):continue
        last=db.query(AlertEvent).filter(AlertEvent.alert_id==rule.id).order_by(AlertEvent.created_at.desc()).first()
        if last:
            at=last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=timezone.utc)
            # Avoid notification spam while a condition remains continuously true.
            if now-at<timedelta(hours=6):continue
        event=AlertEvent(alert_id=rule.id,user_email=rule.user_email,symbol=rule.symbol,label=rule.label,value=float(value) if value is not None else None,payload={"kind":rule.kind,"operator":rule.operator,"threshold":rule.threshold,"observed":value})
        db.add(event);created.append(rule.id)
    if created:db.commit()
    return created
