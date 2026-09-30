from __future__ import annotations
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.intraday_warehouse import backfill_stock,backfill_options_alpaca,coverage
from ..services.net_drift_research import run_net_drift_proxy

router=APIRouter(prefix="/api/v1/research/intraday",tags=["intraday-research"])

class StockBackfillRequest(BaseModel):
    symbol:str
    start:str
    end:str
    provider:str="twelve_data"
    interval:str="1min"
    feed:str|None=None

class OptionContract(BaseModel):
    contract:str
    underlying:str
    expiration:str
    option_type:str
    strike:float

class OptionBackfillRequest(BaseModel):
    contracts:list[OptionContract]=Field(min_length=1,max_length=100)
    start:str
    end:str
    interval:str="1min"
    feed:str="indicative"

class NetDriftTestRequest(BaseModel):
    symbol:str="QQQ"
    start_date:str
    end_date:str
    stock_provider:str|None=None
    option_provider:str|None=None
    signal_time:str="10:30"
    horizon_time:str="11:30"
    min_abs_pressure:float=0.0
    save:bool=True

@router.get("/coverage")
def intraday_coverage(symbol:str|None=None,db:Session=Depends(get_db)):
    return coverage(db,symbol)

@router.post("/backfill/stocks")
def intraday_stock_backfill(req:StockBackfillRequest,db:Session=Depends(get_db)):
    try:return backfill_stock(db,req.symbol,req.start,req.end,req.provider,req.interval,req.feed)
    except Exception as exc:raise HTTPException(status_code=502,detail=f"Intraday backfill failed: {str(exc)[:240]}")

@router.post("/backfill/options/alpaca")
def intraday_option_backfill(req:OptionBackfillRequest,db:Session=Depends(get_db)):
    try:return backfill_options_alpaca(db,[x.model_dump() for x in req.contracts],req.start,req.end,req.interval,req.feed)
    except Exception as exc:raise HTTPException(status_code=502,detail=f"Option backfill failed: {str(exc)[:240]}")

@router.post("/tests/net-drift")
def net_drift_test(req:NetDriftTestRequest,db:Session=Depends(get_db)):
    try:return run_net_drift_proxy(db,**req.model_dump())
    except Exception as exc:raise HTTPException(status_code=400,detail=f"Net Drift test failed: {str(exc)[:240]}")
