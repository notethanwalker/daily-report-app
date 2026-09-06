import hashlib
import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import RefreshQueueItem, UserProfile
from ..multiuser_models import PortfolioDefinition, PortfolioPosition, UserAccessConfig, UserPreferences
from ..services.provider_orchestrator import FRESHNESS_POLICIES
from .intelligence import _latest_market, _opportunity_components, current_user

router = APIRouter(prefix="/api/v1", tags=["portfolio-access"])

ALL_TABS = ["Report","Markets","Portfolio","Opportunities","World News","Events","Large Flow","Macro","Regime","Research","Alerts","Theses","Settings"]
DEFAULT_INFO_MODULES = {
    "context_bar": True,
    "market_flags": True,
    "portfolio_risk": True,
    "report_outliers": True,
    "data_health": True,
}
DEFAULT_PERMISSIONS = {
    "can_customize_tabs": False,
    "can_customize_information": False,
    "can_manage_portfolios": True,
    "can_manage_alerts": True,
    "can_manage_theses": True,
    "can_view_flow": True,
    "can_view_macro": True,
    "can_view_research": True,
    "can_view_opportunities": True,
    "can_view_events": True,
    "can_view_regime": True,
    "can_view_settings": True,
    "can_admin_users": False,
}
OWNER_PERMISSIONS = {**DEFAULT_PERMISSIONS, "can_customize_tabs": True, "can_customize_information": True, "can_admin_users": True}
TAB_PERMISSION = {
    "Opportunities": "can_view_opportunities",
    "Events": "can_view_events",
    "Large Flow": "can_view_flow",
    "Macro": "can_view_macro",
    "Regime": "can_view_regime",
    "Research": "can_view_research",
    "Alerts": "can_manage_alerts",
    "Theses": "can_manage_theses",
    "Settings": "can_view_settings",
}

JOINT_FIDELITY = {
    "cash": 2979.57,
    "positions": [
        {"symbol":"AAOI","shares":7,"average_cost":148.19,"last":105.19,"value":736.33,"day_gain":33.67,"day_pct":4.79,"total_gain":-301.00,"total_pct":-29.02,"account_pct":4.75},
        {"symbol":"GLD","shares":3.098,"average_cost":215.97,"last":406.945,"value":1260.71,"day_gain":-10.15,"day_pct":-0.80,"total_gain":591.65,"total_pct":88.43,"account_pct":8.13},
        {"symbol":"IONQ","shares":15,"average_cost":46.89,"last":39.16,"value":587.40,"day_gain":2.10,"day_pct":0.35,"total_gain":-115.95,"total_pct":-16.49,"account_pct":3.79},
        {"symbol":"MU","shares":3,"average_cost":1003.82,"last":1003.92,"value":3011.76,"day_gain":0.30,"day_pct":0.00,"total_gain":0.30,"total_pct":0.00,"account_pct":19.43},
        {"symbol":"NBIS","shares":14,"average_cost":227.11,"last":217.215,"value":3041.01,"day_gain":30.99,"day_pct":1.02,"total_gain":-138.49,"total_pct":-4.36,"account_pct":19.62},
        {"symbol":"NVDA","shares":8,"average_cost":231.46,"last":231.465,"value":1851.72,"day_gain":0.08,"day_pct":0.00,"total_gain":0.08,"total_pct":0.00,"account_pct":11.94},
        {"symbol":"OKLO","shares":25,"average_cost":45.32,"last":41.07,"value":1026.75,"day_gain":30.75,"day_pct":3.08,"total_gain":-106.25,"total_pct":-9.38,"account_pct":6.62},
        {"symbol":"SCHD","shares":24.155,"average_cost":25.08,"last":34.8958,"value":842.90,"day_gain":-4.45,"day_pct":-0.53,"total_gain":237.02,"total_pct":39.12,"account_pct":5.44},
        {"symbol":"SMH","shares":5.193,"average_cost":141.62,"last":566.70,"value":2942.87,"day_gain":73.22,"day_pct":2.55,"total_gain":2207.46,"total_pct":300.16,"account_pct":18.98},
    ],
}


def owner_email() -> str:
    return (os.getenv("OWNER_EMAIL") or "owner@local").strip().lower()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_db_token(db: Session, email: str, token: str) -> bool:
    row = db.get(UserAccessConfig, email.lower())
    return bool(row and row.enabled and row.token_hash and secrets.compare_digest(row.token_hash, token_digest(token)))


def _permissions(db: Session, email: str) -> tuple[dict, list[str], UserAccessConfig | None]:
    email = email.lower()
    row = db.get(UserAccessConfig, email)
    perms = dict(OWNER_PERMISSIONS if email == owner_email() else DEFAULT_PERMISSIONS)
    if row:
        perms.update(row.permissions or {})
        allowed = row.allowed_tabs or list(ALL_TABS)
    else:
        allowed = list(ALL_TABS)
    effective = [t for t in allowed if t in ALL_TABS and (TAB_PERMISSION.get(t) is None or perms.get(TAB_PERMISSION[t], False))]
    return perms, effective, row


def _require_owner(user: str):
    if user.lower() != owner_email():
        raise HTTPException(403, "Owner permission required")


def _require(db: Session, user: str, permission: str):
    perms, _, row = _permissions(db, user)
    if row and not row.enabled:
        raise HTTPException(403, "User access is disabled")
    if not perms.get(permission, False):
        raise HTTPException(403, f"Permission required: {permission}")


def _enqueue(db: Session, symbol: str, data_class: str, priority: int, requested_by: str):
    exists = db.query(RefreshQueueItem).filter(
        RefreshQueueItem.symbol == symbol,
        RefreshQueueItem.data_class == data_class,
        RefreshQueueItem.status.in_(["queued", "running"]),
    ).first()
    if not exists:
        db.add(RefreshQueueItem(symbol=symbol, data_class=data_class, priority=priority, requested_by=requested_by))


def _queue_symbol(db: Session, symbol: str, user: str):
    _enqueue(db, symbol, "market", FRESHNESS_POLICIES["market"].priority, user)
    _enqueue(db, symbol, "history", FRESHNESS_POLICIES["history"].priority, user)
    _enqueue(db, symbol, "fundamentals", FRESHNESS_POLICIES["fundamentals"].priority, user)


def _ensure_joint_fidelity(db: Session, user: str):
    if user.lower() != owner_email():
        return
    existing = db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email == user, PortfolioDefinition.name == "Joint Fidelity").first()
    if existing:
        return
    p = PortfolioDefinition(
        user_email=user,
        name="Joint Fidelity",
        brokerage="Fidelity",
        account_type="Joint",
        cash=JOINT_FIDELITY["cash"],
        is_default=True,
        source_note="Imported from Fidelity portfolio screenshot supplied 2026-09-06. Imported price/P&L fields preserve the screenshot; shared market data is displayed separately when available.",
    )
    db.add(p); db.flush()
    imported_at = datetime(2026, 9, 6, 18, 23, tzinfo=timezone.utc)
    for item in JOINT_FIDELITY["positions"]:
        db.add(PortfolioPosition(
            portfolio_id=p.id,
            symbol=item["symbol"], shares=item["shares"], average_cost=item["average_cost"],
            imported_last_price=item["last"], imported_market_value=item["value"],
            imported_day_gain=item["day_gain"], imported_day_gain_percent=item["day_pct"],
            imported_total_gain=item["total_gain"], imported_total_gain_percent=item["total_pct"],
            imported_account_percent=item["account_pct"], imported_at=imported_at,
        ))
        _queue_symbol(db, item["symbol"], user)
    db.commit()


def _portfolio_or_404(db: Session, user: str, portfolio_id: int) -> PortfolioDefinition:
    p = db.query(PortfolioDefinition).filter(PortfolioDefinition.id == portfolio_id, PortfolioDefinition.user_email == user).first()
    if not p:
        raise HTTPException(404, "Portfolio not found")
    return p


def _enriched_position(db: Session, position: PortfolioPosition, total_account_value: float):
    market = _latest_market(db, position.symbol) or {}
    market_price = market.get("price")
    price = float(market_price) if market_price is not None else float(position.imported_last_price or 0)
    market_value = price * position.shares if price else float(position.imported_market_value or 0)
    cost_basis = position.average_cost * position.shares
    pnl = market_value - cost_basis
    account_pct = market_value / total_account_value * 100 if total_account_value else 0
    opportunity = _opportunity_components(db, position.symbol, market) if market else None
    return {
        "id": position.id,
        "symbol": position.symbol,
        "shares": position.shares,
        "average_cost": position.average_cost,
        "cost_basis": round(cost_basis, 2),
        "price": round(price, 6) if price else None,
        "market_value": round(market_value, 2),
        "account_percent": round(account_pct, 2),
        "unrealized_pl": round(pnl, 2),
        "unrealized_percent": round((market_value / cost_basis - 1) * 100, 2) if cost_basis else None,
        "buy_score": opportunity.get("buy_score") if opportunity else None,
        "sell_score": opportunity.get("sell_score") if opportunity else None,
        "market": market,
        "imported_snapshot": {
            "last_price": position.imported_last_price,
            "market_value": position.imported_market_value,
            "day_gain": position.imported_day_gain,
            "day_gain_percent": position.imported_day_gain_percent,
            "total_gain": position.imported_total_gain,
            "total_gain_percent": position.imported_total_gain_percent,
            "account_percent": position.imported_account_percent,
            "imported_at": position.imported_at.isoformat() if position.imported_at else None,
        },
    }


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    brokerage: str | None = Field(default=None, max_length=80)
    account_type: str | None = Field(default=None, max_length=80)
    cash: float = Field(default=0, ge=0)


class PortfolioUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    brokerage: str | None = Field(default=None, max_length=80)
    account_type: str | None = Field(default=None, max_length=80)
    cash: float | None = Field(default=None, ge=0)
    is_default: bool | None = None


class PositionIn(BaseModel):
    symbol: str
    shares: float = Field(ge=0)
    average_cost: float = Field(ge=0)


class PreferencesIn(BaseModel):
    visible_tabs: list[str] | None = None
    information_modules: dict[str, bool] | None = None
    settings: dict | None = None


class UserAdminIn(BaseModel):
    enabled: bool | None = None
    role: str | None = None
    permissions: dict[str, bool] | None = None
    allowed_tabs: list[str] | None = None


@router.get("/portfolios")
def portfolios(user: str = Depends(current_user), db: Session = Depends(get_db)):
    _ensure_joint_fidelity(db, user)
    rows = db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email == user).order_by(PortfolioDefinition.is_default.desc(), PortfolioDefinition.created_at).all()
    out=[]
    for p in rows:
        positions=db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==p.id).all()
        invested=sum(((_latest_market(db,x.symbol) or {}).get("price") or x.imported_last_price or 0)*x.shares for x in positions)
        out.append({"id":p.id,"name":p.name,"brokerage":p.brokerage,"account_type":p.account_type,"cash":p.cash,"is_default":p.is_default,"position_count":len(positions),"estimated_value":round(invested+p.cash,2)})
    return {"portfolios":out,"multi_portfolio":True}


@router.post("/portfolios")
def create_portfolio(body: PortfolioCreate, user: str = Depends(current_user), db: Session = Depends(get_db)):
    _require(db,user,"can_manage_portfolios")
    has_any=db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email==user).first() is not None
    p=PortfolioDefinition(user_email=user,name=body.name.strip(),brokerage=body.brokerage,account_type=body.account_type,cash=body.cash,is_default=not has_any)
    db.add(p);db.commit();db.refresh(p)
    return {"id":p.id,"status":"created"}


@router.get("/portfolios/{portfolio_id}")
def portfolio_detail(portfolio_id: int, user: str = Depends(current_user), db: Session = Depends(get_db)):
    _ensure_joint_fidelity(db,user);p=_portfolio_or_404(db,user,portfolio_id)
    rows=db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==p.id).order_by(PortfolioPosition.symbol).all()
    preliminary=[]
    for r in rows:
        m=_latest_market(db,r.symbol) or {};px=m.get("price") if m.get("price") is not None else r.imported_last_price
        preliminary.append((r,float(px or 0)*r.shares if px else float(r.imported_market_value or 0)))
    invested=sum(v for _,v in preliminary);total=invested+p.cash
    holdings=[_enriched_position(db,r,total) for r,_ in preliminary]
    cost=sum(h["cost_basis"] for h in holdings);pnl=invested-cost
    return {"portfolio":{"id":p.id,"name":p.name,"brokerage":p.brokerage,"account_type":p.account_type,"cash":p.cash,"is_default":p.is_default,"source_note":p.source_note},"holdings":holdings,"invested_value":round(invested,2),"market_value":round(total,2),"cost_basis":round(cost,2),"unrealized_pl":round(pnl,2),"unrealized_percent":round((invested/cost-1)*100,2) if cost else None,"cash_percent":round(p.cash/total*100,2) if total else 0}


@router.put("/portfolios/{portfolio_id}")
def update_portfolio(portfolio_id:int,body:PortfolioUpdate,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_portfolios");p=_portfolio_or_404(db,user,portfolio_id)
    if body.name is not None:p.name=body.name.strip()
    if body.brokerage is not None:p.brokerage=body.brokerage
    if body.account_type is not None:p.account_type=body.account_type
    if body.cash is not None:p.cash=body.cash
    if body.is_default:
        for other in db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email==user).all():other.is_default=False
        p.is_default=True
    db.commit();return {"status":"saved","id":p.id}


@router.post("/portfolios/{portfolio_id}/positions")
def set_position(portfolio_id:int,body:PositionIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_portfolios");_portfolio_or_404(db,user,portfolio_id);s=body.symbol.strip().upper()
    row=db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==portfolio_id,PortfolioPosition.symbol==s).first()
    if row:row.shares=body.shares;row.average_cost=body.average_cost
    else:db.add(PortfolioPosition(portfolio_id=portfolio_id,symbol=s,shares=body.shares,average_cost=body.average_cost))
    _queue_symbol(db,s,user);db.commit();return {"status":"saved","symbol":s}


@router.delete("/portfolios/{portfolio_id}/positions/{symbol}")
def delete_position(portfolio_id:int,symbol:str,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_manage_portfolios");_portfolio_or_404(db,user,portfolio_id)
    row=db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==portfolio_id,PortfolioPosition.symbol==symbol.upper()).first()
    if not row:raise HTTPException(404,"Position not found")
    db.delete(row);db.commit();return {"status":"removed"}


@router.get("/user/access")
def user_access(user:str=Depends(current_user),db:Session=Depends(get_db)):
    perms,tabs,row=_permissions(db,user);prefs=db.get(UserPreferences,user)
    info={**DEFAULT_INFO_MODULES,**((prefs.information_modules or {}) if prefs else {})}
    visible=(prefs.visible_tabs or tabs) if prefs else tabs
    visible=[t for t in visible if t in tabs]
    return {"email":user,"role":row.role if row else ("owner" if user==owner_email() else "approved_user"),"enabled":row.enabled if row else True,"permissions":perms,"allowed_tabs":tabs,"preferences":{"visible_tabs":visible,"information_modules":info,"settings":prefs.settings if prefs else {}},"auth_enabled":os.getenv("USER_AUTH_ENABLED","").lower() in {"1","true","yes"} or bool(os.getenv("ALLOWED_USER_EMAILS",""))}


@router.put("/user/preferences")
def update_preferences(body:PreferencesIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    perms,tabs,_=_permissions(db,user);row=db.get(UserPreferences,user)
    if not row:row=UserPreferences(user_email=user,visible_tabs=tabs,information_modules=dict(DEFAULT_INFO_MODULES),settings={});db.add(row)
    if body.visible_tabs is not None:
        if not perms.get("can_customize_tabs"):raise HTTPException(403,"Tab customization is not enabled for this user")
        row.visible_tabs=[t for t in body.visible_tabs if t in tabs]
    if body.information_modules is not None:
        if not perms.get("can_customize_information"):raise HTTPException(403,"Information customization is not enabled for this user")
        row.information_modules={**DEFAULT_INFO_MODULES,**{k:bool(v) for k,v in body.information_modules.items() if k in DEFAULT_INFO_MODULES}}
    if body.settings is not None:row.settings=body.settings
    db.commit();return user_access(user=user,db=db)


@router.get("/admin/users")
def admin_users(user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require_owner(user)
    emails={owner_email()}|{x.email.lower() for x in db.query(UserProfile).all()}|{x.user_email.lower() for x in db.query(UserAccessConfig).all()}
    rows=[]
    for email in sorted(emails):
        perms,tabs,cfg=_permissions(db,email);prefs=db.get(UserPreferences,email)
        rows.append({"email":email,"role":cfg.role if cfg else ("owner" if email==owner_email() else "approved_user"),"enabled":cfg.enabled if cfg else True,"has_token":bool(cfg and cfg.token_hash),"permissions":perms,"allowed_tabs":tabs,"visible_tabs":prefs.visible_tabs if prefs else tabs})
    return {"users":rows,"permission_keys":sorted(DEFAULT_PERMISSIONS),"tabs":ALL_TABS,"auth_enabled":os.getenv("USER_AUTH_ENABLED","").lower() in {"1","true","yes"} or bool(os.getenv("ALLOWED_USER_EMAILS",""))}


@router.put("/admin/users/{email}")
def admin_update_user(email:str,body:UserAdminIn,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require_owner(user);email=email.strip().lower();row=db.get(UserAccessConfig,email)
    if not row:row=UserAccessConfig(user_email=email,enabled=True,role="approved_user",permissions={},allowed_tabs=list(ALL_TABS));db.add(row)
    if body.enabled is not None:row.enabled=body.enabled
    if body.role is not None:row.role=body.role
    if body.permissions is not None:row.permissions={**(row.permissions or {}),**{k:bool(v) for k,v in body.permissions.items() if k in DEFAULT_PERMISSIONS}}
    if body.allowed_tabs is not None:row.allowed_tabs=[t for t in body.allowed_tabs if t in ALL_TABS]
    db.commit();return {"status":"saved","email":email}


@router.post("/admin/users/{email}/issue-token")
def issue_token(email:str,user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require_owner(user);email=email.strip().lower();row=db.get(UserAccessConfig,email)
    if not row:row=UserAccessConfig(user_email=email,enabled=True,role="owner" if email==owner_email() else "approved_user",permissions={},allowed_tabs=list(ALL_TABS));db.add(row)
    token=secrets.token_urlsafe(32);row.token_hash=token_digest(token);db.commit()
    return {"email":email,"access_token":token,"note":"This token is returned only when issued. Store it securely and give it only to the intended user."}


@router.get("/admin/auth-readiness")
def auth_readiness(user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require_owner(user);owner=db.get(UserAccessConfig,owner_email())
    users=db.query(UserAccessConfig).all()
    return {"auth_enabled":os.getenv("USER_AUTH_ENABLED","").lower() in {"1","true","yes"} or bool(os.getenv("ALLOWED_USER_EMAILS","")),"owner_email":owner_email(),"owner_token_ready":bool(owner and owner.token_hash),"configured_users":len(users),"users_with_tokens":sum(1 for x in users if x.token_hash),"deployment_steps":["Issue an owner token","Create/permission approved users and issue their tokens","Set USER_AUTH_ENABLED=true on Render","Verify owner login before distributing user tokens"]}
