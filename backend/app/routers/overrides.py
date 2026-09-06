from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from .intelligence import current_user
from .user_state import enhanced_opportunities

router=APIRouter(prefix="/api/v1",tags=["intelligence-overrides"])

@router.get("/opportunities")
def opportunities_override(user:str=Depends(current_user),db:Session=Depends(get_db)):
    return enhanced_opportunities(user=user,db=db)
