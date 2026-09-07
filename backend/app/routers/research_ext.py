from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from .security_intelligence_v5 import security_intelligence

router=APIRouter(prefix="/api/v1",tags=["research"])


@router.get("/security/{symbol}/catalysts")
def security_catalysts(symbol:str,db:Session=Depends(get_db)):
    """Compatibility route backed by the same cache used by Opportunities/Research.

    This prevents the catalyst surfaces from independently re-pulling news/company
    calendars. The richer `/security/{symbol}/intelligence` route remains canonical.
    """
    data=security_intelligence(symbol,refresh_missing=True,force=False,history_days=365,db=db)
    return {
        "symbol":data.get("symbol"),
        "news":(data.get("news") or {}).get("articles") or [],
        "upcoming":(data.get("catalysts") or {}).get("upcoming") or [],
        "source":"shared security intelligence cache",
        "provider_calls":"cache-policy controlled",
        "cache_policy":data.get("cache_policy") or {},
    }
