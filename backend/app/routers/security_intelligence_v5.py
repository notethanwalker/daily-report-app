from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.security_intelligence_service import refresh_security_intelligence

router = APIRouter(prefix="/api/v1", tags=["security-intelligence-v5"])


@router.get("/security/{symbol}/intelligence")
def security_intelligence(
    symbol: str,
    refresh_missing: bool = Query(default=True),
    force: bool = Query(default=False),
    history_days: int = Query(default=365, ge=30, le=730),
    db: Session = Depends(get_db),
):
    return refresh_security_intelligence(
        db,
        symbol,
        refresh_missing=refresh_missing,
        force=force,
        history_days=history_days,
    )
