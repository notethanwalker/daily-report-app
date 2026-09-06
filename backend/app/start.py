from .database import Base, engine
from .main import app
from .routers.intelligence import router as intelligence_router

# The intelligence router imports the expanded ORM model set before create_all runs here.
Base.metadata.create_all(bind=engine)
app.include_router(intelligence_router)
