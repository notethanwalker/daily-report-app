import asyncio
import hmac
import os
import re

from starlette.responses import JSONResponse

from .database import Base, SessionLocal, engine
from . import main as stable
from .main import app
from .routers.overrides import router as override_router
from .routers.health_override import router as health_router
from .routers.intelligence import router as intelligence_router
from .routers.user_state import router as user_state_router
from .routers.lifecycle import router as lifecycle_router
from .routers.research_ext import router as research_router
from .routers.portfolio_access import router as portfolio_access_router, verify_db_token
from .services.refresh_scheduler import scheduler_loop
from .services.rotation import SECTORS

# Broaden the shared macro universe without creating a second data-pull path.
# ETF proxies keep the free market-data path uniform and avoid adding another provider/quota surface.
CROSS_ASSET = {
    "IWM": "Small Caps",
    "TLT": "Long Treasuries",
    "SHY": "Short Treasuries",
    "HYG": "High-Yield Credit",
    "UUP": "US Dollar",
    "USO": "Crude Oil",
    "CPER": "Copper",
    "IBIT": "Bitcoin",
}
SECTORS.update(CROSS_ASSET)
for symbol in CROSS_ASSET:
    if symbol not in stable.MACRO_BACKFILL_PRIORITY:
        stable.MACRO_BACKFILL_PRIORITY.append(symbol)

# All router/model modules are imported before create_all so new additive tables are provisioned safely.
Base.metadata.create_all(bind=engine)
# Mount overrides before the stable intelligence routes when the same path is intentionally upgraded.
app.include_router(override_router)
app.include_router(health_router)
app.include_router(portfolio_access_router)
app.include_router(intelligence_router)
app.include_router(user_state_router)
app.include_router(lifecycle_router)
app.include_router(research_router)


def _allowed():
    return {x.strip().lower() for x in os.getenv("ALLOWED_USER_EMAILS", "").split(",") if x.strip()}


def _tokens():
    raw=os.getenv("USER_ACCESS_TOKENS","");out={}
    for item in re.split(r"[;,]",raw):
        if "=" in item:
            email,token=item.split("=",1);out[email.strip().lower()]=token.strip()
    return out


def _auth_enabled():
    return os.getenv("USER_AUTH_ENABLED","").strip().lower() in {"1","true","yes","on"} or bool(_allowed())


USER_PATH_PREFIXES=(
    "/api/v1/user/",
    "/api/v1/portfolio",
    "/api/v1/portfolios",
    "/api/v1/opportunities",
    "/api/v1/events",
    "/api/v1/alerts",
    "/api/v1/theses",
    "/api/v1/users/me",
    "/api/v1/admin/",
)

@app.middleware("http")
async def selected_user_gate(request,call_next):
    if _auth_enabled() and request.url.path.startswith(USER_PATH_PREFIXES):
        email=(request.headers.get("X-User-Email") or "").strip().lower()
        token=request.headers.get("X-User-Token") or ""
        if not email or not token:
            return JSONResponse({"detail":"Approved user verification required"},status_code=401)
        env_allowed=_allowed();env_tokens=_tokens();env_expected=env_tokens.get(email)
        env_ok=bool((not env_allowed or email in env_allowed) and env_expected and hmac.compare_digest(token,env_expected))
        db_ok=False
        if not env_ok:
            db=SessionLocal()
            try:db_ok=verify_db_token(db,email,token)
            finally:db.close()
        if not env_ok and not db_ok:
            return JSONResponse({"detail":"Invalid or disabled user access token"},status_code=403)
    return await call_next(request)


@app.on_event("startup")
async def start_refresh_scheduler():
    # Refreshes are globally shared and rate-aware; user count does not multiply provider calls.
    asyncio.create_task(scheduler_loop())
