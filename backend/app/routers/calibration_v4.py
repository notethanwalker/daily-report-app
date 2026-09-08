from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.calibration_v4 import candidate_calibration_summary
from .intelligence import current_user

router=APIRouter(prefix="/api/v1/stack/candidates",tags=["decision-stack-v4"])

@router.get("/calibration")
def candidate_calibration(horizon:int=Query(20,ge=5,le=60),db:Session=Depends(get_db),user:str=Depends(current_user)):
    _=user
    return candidate_calibration_summary(db,horizon)
