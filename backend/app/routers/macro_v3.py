from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import main as stable
from ..database import get_db
from ..models import FundamentalCache, RefreshQueueItem, SecondaryVerificationCache
from ..services.macro_universe import MACRO_CATEGORIES, TRACKING_RATIONALE
from ..services.rotation import SECTORS
from .decision_support import _breadth, _macro_rows

router=APIRouter(prefix="/api/v1",tags=["macro-v3"])


@router.get("/macro/expanded")
def expanded_macro(db:Session=Depends(get_db)):
    rows=_macro_rows(db);groups={}
    for row in rows:groups.setdefault(row.get("category") or "Other",[]).append(row)
    missing=[s for s in SECTORS if not stable._latest_market_payload(db,s)]
    return {"rows":rows,"groups":groups,"categories":TRACKING_RATIONALE,"breadth":_breadth(db,list(SECTORS)),"tracking":{"requested":len(SECTORS),"available":len(rows),"pending":missing},"methodology":"All macro groups use the same stored daily market snapshots and rotation formula. Categories are presentation metadata only; they do not create extra provider pulls."}


@router.get("/system/api-budget")
def api_budget(db:Session=Depends(get_db)):
    now=datetime.now(timezone.utc);day_start=now.replace(hour=0,minute=0,second=0,microsecond=0)
    alpha_secondary=db.query(SecondaryVerificationCache).filter(SecondaryVerificationCache.provider=="Alpha Vantage",SecondaryVerificationCache.retrieved_at>=day_start).count()
    alpha_fund=db.query(FundamentalCache).filter(FundamentalCache.provider=="Alpha Vantage",FundamentalCache.retrieved_at>=day_start).count()
    queued=db.query(RefreshQueueItem).filter(RefreshQueueItem.status=="queued").all();classes={}
    for row in queued:classes[row.data_class]=classes.get(row.data_class,0)+1
    twelve_demand=classes.get("market",0)+classes.get("history",0)
    alpha_used=alpha_secondary+alpha_fund
    return {"alpha_vantage":{"daily_app_budget":stable.ALPHA_VANTAGE_DAILY_BUDGET,"used_today":alpha_used,"remaining":max(stable.ALPHA_VANTAGE_DAILY_BUDGET-alpha_used,0)},"twelve_data":{"documented_plan_daily_credits":800,"documented_plan_per_minute":8,"queued_market_history_requests":twelve_demand,"scheduler_batch_size":4,"scheduler_spacing_seconds":8.2},"queue":classes,"forecast":{"twelve_data_queue_share_of_daily_cap_percent":round(twelve_demand/800*100,1),"alpha_budget_pressure":"high" if alpha_used>=16 else "moderate" if alpha_used>=10 else "low"},"note":"Forecast counts queued market/history requests, not future interactive searches. Shared symbol caching and queue deduplication prevent the same ticker from multiplying by user count."}
