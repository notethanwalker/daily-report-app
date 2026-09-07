from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..future_models import RegimeSnapshot
from ..models import FundamentalCache, FlowEvent, MarketSnapshot
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from ..v3_models import UserCustomEvent

PORTFOLIO_PREFIX = "PORTFOLIO:"


def _utc(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _latest_market(db: Session, symbol: str | None):
    if not symbol or symbol.startswith(PORTFOLIO_PREFIX):
        return {}
    row = db.query(MarketSnapshot).filter(MarketSnapshot.symbol == symbol.upper()).order_by(MarketSnapshot.retrieved_at.desc()).first()
    return {**(row.payload or {})} if row else {}


def _days_until(raw) -> int | None:
    if not raw:
        return None
    try:
        d = date.fromisoformat(str(raw)[:10])
    except Exception:
        return None
    delta = (d - date.today()).days
    return delta if delta >= 0 else None


def _catalyst_days(db: Session, user: str, symbol: str):
    candidates: list[tuple[int, str]] = []
    f = db.get(FundamentalCache, symbol)
    payload = {**(f.payload or {})} if f else {}
    for field in ("earnings_date", "earnings_date_estimate", "ex_dividend_date", "dividend_date"):
        days = _days_until(payload.get(field))
        if days is not None:
            candidates.append((days, field))
    custom = db.query(UserCustomEvent).filter(
        UserCustomEvent.user_email == user,
        UserCustomEvent.symbol == symbol,
        UserCustomEvent.event_date >= date.today().isoformat(),
    ).order_by(UserCustomEvent.event_date.asc()).limit(20).all()
    for row in custom:
        days = _days_until(row.event_date)
        if days is not None:
            candidates.append((days, f"custom:{row.id}"))
    if not candidates:
        return None, {"event": None}
    days, source = min(candidates, key=lambda x: x[0])
    return float(days), {"event": source, "days": days}


def _flow_cluster_count(db: Session, symbol: str, hours: int = 72):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = db.query(FlowEvent).filter(
        FlowEvent.symbol == symbol,
        FlowEvent.occurred_at >= since,
    ).order_by(FlowEvent.occurred_at.desc()).limit(500).all()
    groups: dict[tuple, dict] = {}
    for row in rows:
        p = row.payload or {}
        side = str(p.get("side") or "unknown").lower()
        expiry = str(p.get("expiration") or p.get("expiry") or "")
        strike = p.get("strike")
        aggression = str(p.get("aggression") or p.get("execution") or p.get("direction") or "unknown").lower()
        key = (side, expiry, str(strike), aggression)
        g = groups.setdefault(key, {"count": 0, "premium": 0.0, "key": key})
        g["count"] += 1
        try:
            g["premium"] += float(p.get("premium") or 0)
        except Exception:
            pass
    if not groups:
        return 0.0, {"cluster": None, "hours": hours}
    best = max(groups.values(), key=lambda x: (x["count"], x["premium"]))
    return float(best["count"]), {
        "cluster": {"side": best["key"][0], "expiration": best["key"][1], "strike": best["key"][2], "direction": best["key"][3], "premium": round(best["premium"], 2)},
        "hours": hours,
    }


def _portfolio_weight(db: Session, user: str, encoded: str | None):
    if not encoded or not encoded.startswith(PORTFOLIO_PREFIX):
        return None, {"portfolio_id": None}
    try:
        portfolio_id = int(encoded[len(PORTFOLIO_PREFIX):])
    except Exception:
        return None, {"portfolio_id": None}
    p = db.query(PortfolioDefinition).filter(PortfolioDefinition.id == portfolio_id, PortfolioDefinition.user_email == user).first()
    if not p:
        return None, {"portfolio_id": portfolio_id, "missing": True}
    positions = db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id == p.id).all()
    values = []
    for pos in positions:
        m = _latest_market(db, pos.symbol)
        px = m.get("price")
        if px is None:
            px = pos.imported_last_price
        value = float(px or 0) * float(pos.shares) if px is not None else float(pos.imported_market_value or 0)
        values.append((pos.symbol, value))
    total = float(p.cash or 0) + sum(v for _, v in values)
    if total <= 0 or not values:
        return 0.0, {"portfolio_id": p.id, "portfolio": p.name, "largest_symbol": None}
    symbol, largest = max(values, key=lambda x: x[1])
    weight = largest / total * 100
    return round(weight, 4), {"portfolio_id": p.id, "portfolio": p.name, "largest_symbol": symbol, "largest_value": round(largest, 2)}


def _regime_transition(db: Session):
    rows = db.query(RegimeSnapshot).order_by(RegimeSnapshot.as_of.desc(), RegimeSnapshot.created_at.desc()).limit(2).all()
    if len(rows) < 2:
        return None, {"transition": None, "event_key": None}
    current, previous = rows[0], rows[1]
    changed = current.regime != previous.regime
    event_key = f"{previous.as_of}:{previous.regime}->{current.as_of}:{current.regime}"
    return (1.0 if changed else 0.0), {
        "transition": {"from": previous.regime, "to": current.regime, "from_as_of": previous.as_of, "to_as_of": current.as_of},
        "event_key": event_key if changed else None,
    }


def evaluate_typed_value(db: Session, user: str, kind: str, symbol: str | None):
    market = _latest_market(db, symbol)
    if kind == "ma100_proximity":
        raw = market.get("price_vs_ma100_percent")
        return (abs(float(raw)) if raw is not None else None), {"signed_distance": raw, "metric": "100MA"}
    if kind == "ma200_proximity":
        raw = market.get("price_vs_ma200_percent")
        return (abs(float(raw)) if raw is not None else None), {"signed_distance": raw, "metric": "200MA"}
    if kind == "catalyst_days" and symbol:
        return _catalyst_days(db, user, symbol)
    if kind == "persistent_flow" and symbol:
        return _flow_cluster_count(db, symbol)
    if kind == "portfolio_position_weight":
        return _portfolio_weight(db, user, symbol)
    if kind == "regime_transition":
        return _regime_transition(db)
    return None, {}


def typed_trigger(kind: str, value, operator: str, threshold):
    if kind == "regime_transition":
        return bool(value == 1.0)
    if value is None or threshold is None:
        return False
    return {
        ">=": value >= threshold,
        "<=": value <= threshold,
        ">": value > threshold,
        "<": value < threshold,
        "==": value == threshold,
    }.get(operator, False)
