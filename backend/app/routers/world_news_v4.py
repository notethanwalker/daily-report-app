from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import main as stable
from ..services.world_news_synthesis_v4 import synthesize_world_news

router=APIRouter(prefix="/api/v1",tags=["world-news-v4"])


@router.get("/news/world")
def world_news_v4(limit:int=Query(default=25,ge=1,le=50),topic:str|None=None,hours:int=Query(default=48,ge=1,le=168)):
    selected=topic if topic in stable.WORLD_NEWS_TOPIC_QUERIES else None
    key=f"world-v4:{limit}:{selected or 'all'}:{hours}h"
    try:
        return stable._cached_shared(
            key,
            stable.NEWS_CACHE_TTL_SECONDS,
            lambda:synthesize_world_news(stable._load_world_news(selected,limit,hours)),
        )
    except Exception as exc:
        raise HTTPException(502,f"World news unavailable: {exc}") from exc
