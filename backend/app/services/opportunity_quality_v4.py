from __future__ import annotations

from datetime import datetime, timezone

from .data_quality_v4 import build_quality_summary, confidence_adjusted_score
from .provider_orchestrator import is_stale


def _dt(value):
    if isinstance(value,datetime):return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:return datetime.fromisoformat(str(value or "").replace("Z","+00:00"))
    except Exception:return None


def attach_opportunity_quality(rows:list[dict],now:datetime|None=None)->None:
    now=now or datetime.now(timezone.utc)
    for item in rows:
        retrieved=_dt(item.get("retrieved_at"));available=retrieved is not None
        fresh=bool(available and not is_stale(retrieved,"market",now))
        q=build_quality_summary(
            sections={"market":{"available":available,"fresh":fresh,"degrade_reason":None if fresh else "cached market snapshot exceeds freshness policy"}},
            required_sections=["market"],
            verification_status=item.get("verification_status"),
            feature_status="available",
            source_rows=[{"provider":item.get("provider"),"retrieved_at":item.get("retrieved_at"),"source_url":item.get("source_url")}],
            now=now,
        )
        item["data_quality"]=q
        item["quality_confidence"]=q["confidence"]
        item["quality_adjusted_score"]=confidence_adjusted_score(item.get("score"),q["confidence"])
    ranked=sorted((x for x in rows if x.get("quality_adjusted_score") is not None),key=lambda x:(float(x["quality_adjusted_score"]),float(x.get("score") or 0),x.get("symbol") or ""),reverse=True)
    for rank,item in enumerate(ranked,1):item["quality_adjusted_rank"]=rank
