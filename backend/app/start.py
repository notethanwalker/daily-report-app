import asyncio
import hmac
import os
import re

from starlette.responses import JSONResponse

from .database import Base, engine
from . import main as stable
from .main import app
from .routers.overrides import router as override_router
from .routers.intelligence import router as intelligence_router
from .routers.user_state import router as user_state_router
from .routers.lifecycle import router as lifecycle_router
from .routers.research_ext import router as research_router
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

# The intelligence routers import the expanded ORM model set before create_all runs here.
Base.metadata.create_all(bind=engine)
# Mount the enhanced scorer first so /opportunities resolves to the catalyst-aware implementation.
app.include_router(override_router)
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


USER_PATH_PREFIXES=("/api/v1/user/","/api/v1/portfolio","/api/v1/opportunities","/api/v1/alerts","/api/v1/theses","/api/v1/users/me")

@app.middleware("http")
async def selected_user_gate(request,call_next):
    allowed=_allowed()
    if allowed and request.url.path.startswith(USER_PATH_PREFIXES):
        email=(request.headers.get("X-User-Email") or "").lower();token=request.headers.get("X-User-Token") or "";tokens=_tokens()
        if not email or email not in allowed:
            return JSONResponse({"detail":"Approved user verification required"},status_code=401)
        expected=tokens.get(email)
        if not expected:
            return JSONResponse({"detail":"Access token is not configured for this approved user"},status_code=503)
        if not hmac.compare_digest(token,expected):
            return JSONResponse({"detail":"Invalid user access token"},status_code=403)
    return await call_next(request)


@app.on_event("startup")
async def start_refresh_scheduler():
    # Refreshes are globally shared and rate-aware; user count does not multiply provider calls.
    asyncio.create_task(scheduler_loop())
