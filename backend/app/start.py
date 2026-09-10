import asyncio
import os
import urllib.request
from http.cookies import SimpleCookie

from starlette.responses import JSONResponse

from .database import Base, SessionLocal, engine
from . import main as stable
from .main import app
from . import auth_models as _auth_models
from .auth_models import AuthAccount
from . import v2_models as _v2_models
from . import v3_models as _v3_models
from . import future_models as _future_models
from . import intelligence_cache_models as _intelligence_cache_models
from . import normalized_market_models as _normalized_market_models
from . import v4_models as _v4_models
from .routers.overrides import router as override_router
from .routers.health_override import router as health_router
from .routers.data_quality_v4 import router as data_quality_v4_router
from .routers.events_v3 import events as events_v3_handler, router as events_v3_router
from .routers.events_v4 import router as events_v4_router
from .routers.fundamentals_v2 import router as fundamentals_v2_router
from .routers.alerts_consistency_v4 import router as alerts_consistency_v4_router
from .routers.alerts_context_v4 import router as alerts_context_v4_router
from .routers.alerts_v2 import router as alerts_v2_router
from .routers.alerts_formula_v4 import router as alerts_formula_v4_router
from .routers.portfolio_live import router as portfolio_live_router
from .routers.intelligence import router as intelligence_router
from .routers.user_state import router as user_state_router
from .routers.lifecycle import router as lifecycle_router
from .routers.research_ext import router as research_router
from .routers.research_v4 import security_workspace_v4, router as research_v4_router
from .routers.security_intelligence_v5 import router as security_intelligence_v5_router
from .routers.decision_support import router as decision_support_router
from .routers.opportunity_scanner import router as opportunity_scanner_router
from .routers.opportunity_formula_v4 import router as opportunity_formula_v4_router
from .routers.stack_v4 import router as stack_v4_router
from .routers.calibration_v4 import router as calibration_v4_router
from .routers.stooq_internal import router as stooq_internal_router
from .routers.analytics_v3 import router as analytics_v3_router
from .routers.macro_v3 import router as macro_v3_router
from .routers.reconciliation import router as reconciliation_router
from .routers.future_release import router as future_release_router
from .routers.next_intelligence import router as next_intelligence_router
from .routers.world_news_v4 import router as world_news_v4_router
from .routers.auth import router as auth_router
from .routers import portfolio_access as access_policy
from .routers.portfolio_access import _permissions, router as portfolio_access_router
from .services.auth_security import SESSION_COOKIE, account_from_session, bootstrap_admin
from .services.calibration_v4 import calibration_loop
from .services.feature_model_v4 import feature_version_loop
from .services import refresh_scheduler as _refresh_scheduler
from .services.refresh_scheduler import bulk_market_loop, scheduler_loop, yahoo_bootstrap_loop
from .services.tracked_market_fallback import refresh_tracked_market_snapshot_with_fallback
from .services.opportunity_incremental import opportunity_incremental_loop
from .services.candidate_funnel_v4 import candidate_snapshot_loop
from .services.stooq_worker import stooq_import_loop
from .services.rotation import SECTORS
from .services.macro_universe import EXPANDED_MACRO

SECTORS.update(EXPANDED_MACRO)
stable.DEFAULT_WATCHLIST=["CBRS" if symbol=="CRBS" else symbol for symbol in stable.DEFAULT_WATCHLIST]
_refresh_scheduler.refresh_tracked_market_snapshot=refresh_tracked_market_snapshot_with_fallback
for symbol in EXPANDED_MACRO:
    if symbol not in stable.MACRO_BACKFILL_PRIORITY:stable.MACRO_BACKFILL_PRIORITY.append(symbol)
if "Command Center" not in access_policy.ALL_TABS:access_policy.ALL_TABS.insert(0,"Command Center")
access_policy.DEFAULT_PERMISSIONS["can_view_command_center"]=True;access_policy.OWNER_PERMISSIONS["can_view_command_center"]=True;access_policy.TAB_PERMISSION["Command Center"]="can_view_command_center"
def _is_get_route(route,*paths):return getattr(route,"path",None) in paths and "GET" in (getattr(route,"methods",set()) or set())
app.router.routes=[r for r in app.router.routes if not _is_get_route(r,"/api/v1/markets/{symbol}/fundamentals","/api/v1/news/world")]
intelligence_router.routes=[r for r in intelligence_router.routes if not _is_get_route(r,"/events","/api/v1/events","/security/{symbol}/workspace","/api/v1/security/{symbol}/workspace")]
Base.metadata.create_all(bind=engine)
_bootstrap_db=SessionLocal()
try:
    _owner=bootstrap_admin(_bootstrap_db)
    if not _owner:_owner=_bootstrap_db.query(AuthAccount).filter(AuthAccount.role=="owner",AuthAccount.status=="approved",AuthAccount.enabled.is_(True)).order_by(AuthAccount.created_at.asc()).first()
    if _owner:os.environ["OWNER_EMAIL"]=_owner.id
finally:_bootstrap_db.close()
os.environ["ALLOWED_USER_EMAILS"]="";os.environ["USER_ACCESS_TOKENS"]="";os.environ["USER_AUTH_ENABLED"]=""
app.include_router(auth_router);app.include_router(override_router);app.include_router(health_router);app.include_router(data_quality_v4_router);app.include_router(fundamentals_v2_router);app.include_router(alerts_consistency_v4_router);app.include_router(alerts_context_v4_router);app.include_router(alerts_v2_router);app.include_router(alerts_formula_v4_router);app.include_router(portfolio_live_router);app.include_router(portfolio_access_router);app.include_router(intelligence_router);app.include_router(user_state_router);app.include_router(lifecycle_router);app.include_router(research_router);app.include_router(research_v4_router);app.include_router(security_intelligence_v5_router);app.include_router(decision_support_router);app.include_router(opportunity_scanner_router);app.include_router(opportunity_formula_v4_router);app.include_router(stack_v4_router);app.include_router(calibration_v4_router);app.include_router(stooq_internal_router);app.include_router(analytics_v3_router);app.include_router(macro_v3_router);app.include_router(events_v3_router);app.include_router(events_v4_router);app.include_router(future_release_router);app.include_router(next_intelligence_router);app.include_router(world_news_v4_router)
app.router.routes=[r for r in app.router.routes if not _is_get_route(r,"/api/v1/security/{symbol}/workspace")]
app.add_api_route("/api/v1/security/{symbol}/workspace",security_workspace_v4,methods=["GET"],tags=["research-v4"],name="security_workspace_v4_authoritative");app.router.routes.insert(0,app.router.routes.pop())
app.router.routes=[r for r in app.router.routes if not _is_get_route(r,"/api/v1/events")]
app.add_api_route("/api/v1/events",events_v3_handler,methods=["GET"],tags=["events-v3"],name="events_v3_authoritative");app.router.routes.insert(0,app.router.routes.pop())
app.router.routes=[r for r in app.router.routes if not _is_get_route(r,"/api/v1/markets/{symbol}","/api/v1/flow/recent")];app.include_router(reconciliation_router)
PERMISSION_PATHS=(("/api/v1/stack/research","can_view_research"),("/api/v1/stack/scores","can_view_research"),("/api/v1/stack/rotation","can_view_macro"),("/api/v1/stack/candidates","can_view_opportunities"),("/api/v1/stack/deployment","can_manage_portfolios"),("/api/v1/stack","can_view_command_center"),("/api/v1/command-center","can_view_command_center"),("/api/v1/portfolios","can_manage_portfolios"),("/api/v1/opportunities","can_view_opportunities"),("/api/v1/events","can_view_events"),("/api/v1/flow","can_view_flow"),("/api/v1/macro","can_view_macro"),("/api/v1/analytics/","can_view_macro"),("/api/v1/security","can_view_research"),("/api/v1/alerts","can_manage_alerts"),("/api/v1/push","can_manage_alerts"),("/api/v1/theses","can_manage_theses"),("/api/v1/system/","can_view_settings"))
PUBLIC_API_PATHS={
    "/api/v1/health",
    "/api/v1/opportunities/bulk-missing",
    "/api/v1/opportunities/bulk-ingest",
}
def _cookie_from_scope(scope,name):
    raw=""
    for key,value in scope.get("headers",[]):
        if key.lower()==b"cookie":raw=value.decode("latin-1");break
    if not raw:return None
    jar=SimpleCookie();jar.load(raw);item=jar.get(name);return item.value if item else None
def _inject_subject(scope,user_id):
    clean=[]
    for key,value in scope.get("headers",[]):
        if key.lower() in {b"x-user-email",b"x-user-token",b"x-auth-user-id"}:continue
        clean.append((key,value))
    clean.append((b"x-user-email",user_id.encode("utf-8")));clean.append((b"x-auth-user-id",user_id.encode("utf-8")));scope["headers"]=clean
@app.middleware("http")
async def authenticated_session_gate(request,call_next):
    path=request.url.path
    if path=="/" or path in PUBLIC_API_PATHS or path.startswith("/api/v1/auth/") or not path.startswith("/api/v1"):return await call_next(request)
    token=_cookie_from_scope(request.scope,SESSION_COOKIE);db=SessionLocal()
    try:
        account=account_from_session(db,token)
        if not account:return JSONResponse({"detail":"Authentication required"},status_code=401)
        _inject_subject(request.scope,account.id)
        for prefix,permission in PERMISSION_PATHS:
            if path.startswith(prefix):
                perms,_,cfg=_permissions(db,account.id)
                if cfg and not cfg.enabled:return JSONResponse({"detail":"User access is disabled"},status_code=403)
                if not perms.get(permission,False):return JSONResponse({"detail":f"Permission required: {permission}"},status_code=403)
                break
    finally:db.close()
    return await call_next(request)
def _self_keepalive_request():
    url=os.getenv("RENDER_EXTERNAL_URL") or "https://daily-report-api-ero2.onrender.com";req=urllib.request.Request(url.rstrip("/")+"/",headers={"User-Agent":"daily-report-self-keepalive"})
    with urllib.request.urlopen(req,timeout=30) as response:response.read(1)
async def self_keepalive_loop():
    while True:
        await asyncio.sleep(8*60)
        try:await asyncio.to_thread(_self_keepalive_request)
        except Exception:pass
@app.on_event("startup")
async def start_refresh_scheduler():
    asyncio.create_task(scheduler_loop());asyncio.create_task(bulk_market_loop());asyncio.create_task(yahoo_bootstrap_loop());asyncio.create_task(opportunity_incremental_loop());asyncio.create_task(candidate_snapshot_loop());asyncio.create_task(stooq_import_loop());asyncio.create_task(calibration_loop());asyncio.create_task(feature_version_loop());asyncio.create_task(self_keepalive_loop())