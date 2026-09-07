import asyncio
import hmac
import os
import re

from starlette.responses import JSONResponse

from .database import Base, SessionLocal, engine
from . import main as stable
from .main import app
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
from .routers import portfolio_access as access_policy
from .routers.portfolio_access import _permissions, router as portfolio_access_router, verify_db_token
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

# Force the on-demand-hydrating Research workspace to be authoritative even if a
# legacy router later reintroduces the same path.
app.router.routes=[r for r in app.router.routes if not _is_get_route(r,"/api/v1/security/{symbol}/workspace")]
app.add_api_route("/api/v1/security/{symbol}/workspace",security_workspace_v4,methods=["GET"],tags=["research-v4"],name="security_workspace_v4_authoritative")
app.router.routes.insert(0,app.router.routes.pop())

# Keep the expanded event catalog authoritative over older event handlers.
app.router.routes=[r for r in app.router.routes if not _is_get_route(r,"/api/v1/events")]
app.add_api_route("/api/v1/events",events_v3_handler,methods=["GET"],tags=["events-v3"],name="events_v3_authoritative")
app.router.routes.insert(0,app.router.routes.pop())

# Reconciled routes supersede legacy primary-only market refreshes and the raw
# unusual-options feed. Specific market subroutes remain untouched.
app.router.routes=[r for r in app.router.routes if not _is_get_route(r,"/api/v1/markets/{symbol}","/api/v1/flow/recent")]
app.include_router(reconciliation_router)


def _allowed():return {x.strip().lower() for x in os.getenv("ALLOWED_USER_EMAILS","").split(",") if x.strip()}
def _tokens():
    raw=os.getenv("USER_ACCESS_TOKENS","");out={}
    for item in re.split(r"[;,]",raw):
        if "=" in item:
            email,token=item.split("=",1);out[email.strip().lower()]=token.strip()
    return out
def _auth_enabled():return os.getenv("USER_AUTH_ENABLED","").strip().lower() in {"1","true","yes","on"} or bool(_allowed())

USER_PATH_PREFIXES=("/api/v1/user/","/api/v1/portfolio","/api/v1/portfolios","/api/v1/opportunities","/api/v1/events","/api/v1/alerts","/api/v1/push","/api/v1/theses","/api/v1/users/me","/api/v1/admin/","/api/v1/flow","/api/v1/macro","/api/v1/security","/api/v1/system/","/api/v1/command-center","/api/v1/analytics/")
PERMISSION_PATHS=(("/api/v1/command-center","can_view_command_center"),("/api/v1/portfolios","can_manage_portfolios"),("/api/v1/opportunities","can_view_opportunities"),("/api/v1/events","can_view_events"),("/api/v1/flow","can_view_flow"),("/api/v1/macro","can_view_macro"),("/api/v1/analytics/","can_view_macro"),("/api/v1/security","can_view_research"),("/api/v1/alerts","can_manage_alerts"),("/api/v1/push","can_manage_alerts"),("/api/v1/theses","can_manage_theses"),("/api/v1/system/","can_view_settings"))

@app.middleware("http")
async def selected_user_gate(request,call_next):
    if _auth_enabled() and request.url.path.startswith(USER_PATH_PREFIXES):
        email=(request.headers.get("X-User-Email") or "").strip().lower();token=request.headers.get("X-User-Token") or ""
        if not email or not token:return JSONResponse({"detail":"Approved user verification required"},status_code=401)
        env_allowed=_allowed();env_expected=_tokens().get(email);env_ok=bool((not env_allowed or email in env_allowed) and env_expected and hmac.compare_digest(token,env_expected));db_ok=False
        db=SessionLocal()
        try:
            if not env_ok:db_ok=verify_db_token(db,email,token)
            if not env_ok and not db_ok:return JSONResponse({"detail":"Invalid or disabled user access token"},status_code=403)
            for prefix,permission in PERMISSION_PATHS:
                if request.url.path.startswith(prefix):
                    perms,_,cfg=_permissions(db,email)
                    if cfg and not cfg.enabled:return JSONResponse({"detail":"User access is disabled"},status_code=403)
                    if not perms.get(permission,False):return JSONResponse({"detail":f"Permission required: {permission}"},status_code=403)
                    break
        finally:db.close()
    return await call_next(request)

@app.on_event("startup")
async def start_refresh_scheduler():asyncio.create_task(scheduler_loop())
