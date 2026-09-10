from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.system_data_quality_v4 import system_quality
from .intelligence import current_user
from .portfolio_access import _require

router=APIRouter(prefix="/api/v1/system",tags=["data-quality-v4"])


@router.get("/data-quality/v4")
def data_quality_v4(user:str=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,user,"can_view_settings")
    return system_quality(db,user)
