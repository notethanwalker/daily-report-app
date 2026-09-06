from .database import Base, engine
from . import main as stable
from .main import app
from .routers.intelligence import router as intelligence_router
from .services.rotation import SECTORS

# Broaden the shared macro universe without creating a second data-pull path.
CROSS_ASSET = {
    "IWM": "Small Caps",
    "TLT": "Long Treasuries",
    "HYG": "High-Yield Credit",
    "UUP": "US Dollar",
    "USO": "Crude Oil",
}
SECTORS.update(CROSS_ASSET)
for symbol in CROSS_ASSET:
    if symbol not in stable.MACRO_BACKFILL_PRIORITY:
        stable.MACRO_BACKFILL_PRIORITY.append(symbol)

# The intelligence router imports the expanded ORM model set before create_all runs here.
Base.metadata.create_all(bind=engine)
app.include_router(intelligence_router)
