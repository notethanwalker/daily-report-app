import asyncio
import os
from http.cookies import SimpleCookie

from starlette.responses import JSONResponse

from .database import Base, SessionLocal, engine
from . import main as stable
from .main import app
from . import auth_models as _auth_models
from .auth_models import AuthAccount
from . import v2_models as _v2_models
from . import v3_models as _v3_models
from .routers.overrides import router as override_router
from .routers.health_override import router as health_router
from .routers.events_v3 import events as events_v3_handler, router as events_v3_router
from .routers.events_v4 import router as events_v4_router
from .routers.fundamentals_v2 import router as fundamentals_v2_router
from .routers.alerts_v2 import router as alerts_v2_router
from .routers.portfolio_live import router as portfolio_live_router
from .routers.intelligence import router as intelligence_router
from .routers.user_state import router as user_state_router
from .routers.lifecycle import router as lifecycle_router
from .routers.research_ext import router as research_router
from .routers.research_v4 import security_workspace_v4, router as research_v4_router
from .routers.decision_support import router as decision_support_router
from .routers.analytics_v3 import router as analytics_v3_router
from .routers.macro_v3 import router as macro_v3_router
from .routers.reconciliation import router as reconciliation_router
from .routers.auth import router as auth_router
from .routers import portfolio_access as access_policy
from .routers.portfolio_access import _permissions, router as portfolio_access_router
from .services.auth_security import SESSION_COOKIE, account_from_session, bootstrap_admin
from .services.refresh_scheduler import scheduler_loop
from .services.rotation import SECTORS
from .services.macro_universe import EXPANDED_MACRO

SECTORS.update(EXPANDED_MACRO)
for symbol in EXPANDED_MACRO:
    if symbol not in stable.MACRO_BACKFILL_PRIORITY:
        stable.MACRO_BACKFILL_PRIORITY.append(symbol)

if "Command Center" not in access_policy.ALL_TABS:
    access_policy.ALL_TABS.insert(0,"Command Center")
access_policy.DEFAULT_PERMISSIONS["can_view_command_center"]=True
access_policy.OWNER_PERMISSIONS["can_view_command_center"]=True
access_policy.TAB_PERMISSION["Command Center"]="can_view_command_center"


def _is_get_route(route, *paths):
    return getattr(route, "path", None) in paths and "GET" in (getattr(route, "methods", set()) or set())

app.router.routes=[r for r in app.router.routes if not _is_get_route(r,"/api/v1/markets/{symbol}/fundamentals")]
intelligence_router.routes=[r for r in intelligence_router.routes if not _is_get_route(r,"/events","/api/v1/events","/security/{symbol}/workspace","/api/v1/security/{symbol}/workspace")]

Base.metadata.create_all(bind=engine)

# Bootstrap uses only encrypted/HMAC/password-hash values. The plaintext admin
# email/password never live in source control or a deployment environment variable.
_bootstrap_db=SessionLocal()
try:
    _owner=bootstrap_admin(_bootstrap_db)
    if not _owner:
        _owner=_bootstrap_db.query(AuthAccount).filter(
            AuthAccount.role=="owner",AuthAccount.status=="approved",AuthAccount.enabled.is_(True)
        ).order_by(AuthAccount.created_at.asc()).first()
    if _owner:
        # Existing authorization code uses OWNER_EMAIL as its subject key. From this
        # point forward that value is an opaque user ID, not an email address.
        os.environ["OWNER_EMAIL"]=_owner.id
finally:
    _bootstrap_db.close()

# Disable legacy allowlist/bearer-token behavior inside older route dependencies.
# Session middleware below injects a trusted opaque subject instead.
os.environ["ALLOWED_USER_EMAILS"]=""
os.environ["USER_ACCESS_TOKENS"]=""
os.environ["USER_AUTH_ENABLED"]=""

app.include_router(auth_router)
app.include_router(override_router)
app.include_router(health_router)
app.include_router(fundamentals_v2_router)
app.include_router(alerts_v2_router)
app.include_router(portfolio_live_router)
app.include_router(portfolio_access_router)
app.include_router(intelligence_router)
app.include_router(user_state_router)
app.include_router(lifecycle_router)
app.include_router(research_router)
app.include_router(research_v4_router)
app.include_router(decision_support_router)
app.include_router(analytics_v3_router)
app.include_router(macro_v3_router)
app.include_router(events_v3_router)
app.include_router(events_v4_router)

app.router.routes=[r for r in app.router.routes if not _is_get_route(r,"/api/v1/security/{symbol}/workspace")]
app.add_api_route("/api/v1/security/{symbol}/workspace",security_workspace_v4,methods=["GET"],tags=["research-v4"],name="security_workspace_v4_authoritative")
app.router.routes.insert(0,app.router.routes.pop())

app.router.routes=[r for r in app.router.routes if not _is_get_route(r,"/api/v1/events")]
app.add_api_route("/api/v1/events",events_v3_handler,methods=["GET"],tags=["events-v3"],name="events_v3_authoritative")
app.router.routes.insert(0,app.router.routes.pop())

app.router.routes=[r for r in app.router.routes if not _is_get_route(r,"/api/v1/markets/{symbol}","/api/v1/flow/recent")]
app.include_router(reconciliation_router)

PERMISSION_PATHS=(("/api/v1/command-center","can_view_command_center"),("/api/v1/portfolios","can_manage_portfolios"),("/api/v1/opportunities","can_view_opportunities"),("/api/v1/events","can_view_events"),("/api/v1/flow","can_view_flow"),("/api/v1/macro","can_view_macro"),("/api/v1/analytics/","can_view_macro"),("/api/v1/security","can_view_research"),("/api/v1/alerts","can_manage_alerts"),("/api/v1/push","can_manage_alerts"),("/api/v1/theses","can_manage_theses"),("/api/v1/system/","can_view_settings"))
PUBLIC_API_PATHS={"/api/v1/health"}


def _cookie_from_scope(scope,name):
    raw=""
    for key,value in scope.get("headers",[]):
        if key.lower()==b"cookie":
            raw=value.decode("latin-1");break
    if not raw:return None
    jar=SimpleCookie();jar.load(raw);item=jar.get(name);return item.value if item else None


def _inject_subject(scope,user_id):
    clean=[]
    for key,value in scope.get("headers",[]):
        if key.lower() in {b"x-user-email",b"x-user-token",b"x-auth-user-id"}:
            continue
        clean.append((key,value))
    clean.append((b"x-user-email",user_id.encode("utf-8")))
    clean.append((b"x-auth-user-id",user_id.encode("utf-8")))
    scope["headers"]=clean


@app.middleware("http")
async def authenticated_session_gate(request,call_next):
    path=request.url.path
    if path=="/" or path in PUBLIC_API_PATHS or path.startswith("/api/v1/auth/") or not path.startswith("/api/v1"):
        return await call_next(request)
    token=_cookie_from_scope(request.scope,SESSION_COOKIE)
    db=SessionLocal()
    try:
        account=account_from_session(db,token)
        if not account:
            return JSONResponse({"detail":"Authentication required"},status_code=401)
        _inject_subject(request.scope,account.id)
        for prefix,permission in PERMISSION_PATHS:
            if path.startswith(prefix):
                perms,_,cfg=_permissions(db,account.id)
                if cfg and not cfg.enabled:
                    return JSONResponse({"detail":"User access is disabled"},status_code=403)
                if not perms.get(permission,False):
                    return JSONResponse({"detail":f"Permission required: {permission}"},status_code=403)
                break
    finally:
        db.close()
    return await call_next(request)


@app.on_event("startup")
async def start_refresh_scheduler():asyncio.create_task(scheduler_loop())
