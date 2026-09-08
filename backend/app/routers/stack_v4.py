from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FeatureSnapshot, FundamentalCache, MarketSnapshot, SymbolRegistry, Thesis, UserWatchlistItem
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from ..normalized_market_models import MarketPipelineState
from ..providers.alpaca_market_data import AlpacaMarketDataProvider
from ..services.candidate_funnel_v4 import build_candidate_funnel, enqueue_deep_enrichment
from ..services.classification_v4 import rotation_proxy_name
from ..services.feature_model_v4 import presentation_payload
from ..services.monthly_priority import deployment_plan
from ..services.provider_orchestrator import ProviderOrchestrator
from ..services.rotation_model_v4 import ROTATION_HISTORY_KEY, build_rotation_model
from ..services.score_history_v4 import build_score_history
from .intelligence import _recent_flow, current_user

router = APIRouter(prefix="/api/v1/stack", tags=["decision-stack-v4"])
AI_BUILDOUT_BASKET = ["NBIS", "MU", "AAOI", "NVDA", "SMH"]


def _user_symbols(db: Session, user: str) -> list[str]:
    symbols = {x.symbol for x in db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email == user).all() if x.symbol != "__INITIALIZED__"}
    pids = [x.id for x in db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email == user).all()]
    if pids:
        symbols |= {x.symbol for x in db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id.in_(pids)).all()}
    return sorted(symbols)


def _latest_feature(db: Session, symbol: str) -> dict:
    row = db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol == symbol).order_by(FeatureSnapshot.as_of.desc(), FeatureSnapshot.created_at.desc()).first()
    return {**presentation_payload(row.payload or {}, row.as_of), "as_of": row.as_of} if row else {}


def _latest_market(db: Session, symbol: str) -> dict:
    row = db.query(MarketSnapshot).filter(MarketSnapshot.symbol == symbol).order_by(MarketSnapshot.retrieved_at.desc()).first()
    return {**(row.payload or {}), "retrieved_at": row.retrieved_at.isoformat()} if row else {}


def _source_registry() -> list[dict]:
    return [
        {"provider": "Twelve Data", "role": "shared market snapshots/history", "configured": bool(os.getenv("TWELVE_DATA_API_KEY")), "authoritative": "shared snapshot when configured"},
        {"provider": "Alpaca IEX", "role": "independent OHLC/history and Williams research", "configured": AlpacaMarketDataProvider.configured(), "authoritative": False, "notes": "Free IEX feed is not consolidated SIP."},
        {"provider": "Yahoo Finance", "role": "quota-free OHLC fallback and valuation coverage", "configured": True, "authoritative": False},
        {"provider": "SEC EDGAR", "role": "public fundamental history", "configured": True, "authoritative": "fundamental-history source where taxonomy coverage exists"},
        {"provider": "Alpha Vantage", "role": "quota-aware independent check / missing fundamentals", "configured": bool(os.getenv("ALPHA_VANTAGE_API_KEY")), "authoritative": False},
        {"provider": "GDELT + Google News RSS", "role": "news intelligence", "configured": True, "authoritative": False},
        {"provider": "Frankfurter / ECB", "role": "FX and currency context", "configured": True, "authoritative": "FX layer"},
        {"provider": "Public economic calendars + Nasdaq", "role": "macro/company events", "configured": True, "authoritative": "event-specific public source"},
        {"provider": "SquawkFlow observations", "role": "unusual options / large-flow observations", "configured": True, "authoritative": False},
    ]


def _macro_for_security(rotation: dict, symbol: str, market: dict, registry: SymbolRegistry | None) -> tuple[dict, str | None, str]:
    by_name = {str(x.get("name") or ""): x for x in rotation.get("rows", [])}
    sector = (registry.sector if registry else None) or market.get("sector")
    industry = (registry.industry if registry else None) or market.get("industry")
    themes = (registry.themes if registry else None) or market.get("themes")
    proxy, basis = rotation_proxy_name(symbol, sector, industry, themes)
    return by_name.get(str(proxy)) or by_name.get(str(sector)) or {}, proxy, basis


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: str = Depends(current_user)):
    symbols = _user_symbols(db, user)
    feature_count = db.query(FeatureSnapshot).count()
    market_count = db.query(MarketSnapshot).count()
    rotation_state = db.get(MarketPipelineState, ROTATION_HISTORY_KEY)
    rotation_history_days = len((rotation_state.payload or {}).get("daily", [])) if rotation_state else 0
    return {
        "version": "4.4-dev",
        "pipeline": ["research", "macro", "opportunity", "deployment"],
        "provider_policy": ProviderOrchestrator().describe(),
        "sources": _source_registry(),
        "layers": {
            "research": {"tracked_symbols": len(symbols), "stored_market_snapshots": market_count, "stored_feature_snapshots": feature_count, "status": "active-v4", "capabilities": ["markets", "portfolios", "security research", "fundamentals", "world news", "events", "large flow", "theses", "alerts", "versioned score history"]},
            "macro": {"status": "active-v4", "rotation_history_days": rotation_history_days, "capabilities": ["sector/theme strength", "rotation acceleration/deceleration", "transition states", "persisted state history", "breadth", "regime", "currencies", "liquidity proxies"]},
            "opportunity": {"status": "active-v4", "tracked_symbols": len(symbols), "methodology": "Detailed candidate data is permission-isolated. Broad-market ranking is cache-first/read-only; enrichment is a separate bounded action."},
            "deployment": {"status": "phase-1", "models": ["Williams Priority — new capital only"], "named_baskets": {"AI Buildout Basket": AI_BUILDOUT_BASKET}, "manual_quality_gate": True, "rebalancing_default": False},
        },
        "overview_policy": "Summary metadata only. Detailed Research/Macro/Opportunity/Deployment data must be fetched from the layer-specific endpoint and pass that layer's permission check.",
    }


@router.get("/sources")
def sources(user: str = Depends(current_user)):
    return {"sources": _source_registry(), "policy": ProviderOrchestrator().describe()}


@router.get("/rotation")
def rotation(db: Session = Depends(get_db), user: str = Depends(current_user)):
    _ = user
    return build_rotation_model(db)


@router.get("/rotation/history")
def rotation_history(days: int = Query(90, ge=1, le=400), db: Session = Depends(get_db), user: str = Depends(current_user)):
    _ = user
    state = db.get(MarketPipelineState, ROTATION_HISTORY_KEY)
    daily = list((state.payload or {}).get("daily", [])) if state else []
    return {"days": daily[-days:], "count": min(days, len(daily)), "methodology_version": (state.payload or {}).get("methodology_version") if state else None}


@router.get("/candidates")
def candidates(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user: str = Depends(current_user)):
    _ = user
    return build_candidate_funnel(db, build_rotation_model(db), limit=limit, enqueue_enrichment=False)


@router.post("/candidates/enrich")
def enrich_candidates(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user: str = Depends(current_user)):
    _ = user
    funnel = build_candidate_funnel(db, build_rotation_model(db), limit=limit, enqueue_enrichment=False)
    symbols = funnel.get("deep_enrichment_symbols", [])
    added = enqueue_deep_enrichment(db, symbols)
    return {"shortlist": symbols, "jobs_added": added, "limit": min(limit, 200), "policy": "Explicit mutation; at most 25 scanner-only finalists are queued and queued/running duplicates are suppressed."}


@router.get("/scores/{symbol}")
def score_history(symbol: str, limit: int = Query(90, ge=2, le=365), db: Session = Depends(get_db), user: str = Depends(current_user)):
    _ = user
    return build_score_history(db, symbol, limit=limit)


@router.get("/research/{symbol}")
def research_workspace(symbol: str, db: Session = Depends(get_db), user: str = Depends(current_user)):
    s = symbol.strip().upper()
    if not s:
        raise HTTPException(400, "Symbol is required")
    market = _latest_market(db, s)
    feature = _latest_feature(db, s)
    fundamentals_row = db.get(FundamentalCache, s)
    registry = db.get(SymbolRegistry, s)
    rotation_model = build_rotation_model(db)
    macro, proxy, basis = _macro_for_security(rotation_model, s, market, registry)
    theses = db.query(Thesis).filter(Thesis.user_email == user, Thesis.enabled.is_(True)).all()
    related_theses = []
    for t in theses:
        symbols = t.symbols if isinstance(t.symbols, list) else (t.symbols or {}).get("symbols", []) if isinstance(t.symbols, dict) else []
        if s in [str(x).upper() for x in symbols]:
            related_theses.append({"id": t.id, "title": t.title, "statement": t.statement})
    history = build_score_history(db, s, limit=90)
    return {
        "symbol": s,
        "registry": {"name": registry.name, "asset_type": registry.asset_type, "exchange": registry.exchange, "sector": registry.sector, "industry": registry.industry, "themes": registry.themes} if registry else None,
        "market": market,
        "fundamentals": {**(fundamentals_row.payload or {}), "retrieved_at": fundamentals_row.retrieved_at.isoformat()} if fundamentals_row else None,
        "latest_features": feature,
        "score_history": history,
        "flow_72h": _recent_flow(db, s),
        "rotation_context": {"proxy": proxy, "basis": basis, "state": macro},
        "theses": related_theses,
        "data_state": {"market": bool(market), "fundamentals": bool(fundamentals_row), "feature_history_points": len(history.get("history", [])), "registry": bool(registry)},
        "methodology": "Entity-centric workspace composes stored market, fundamentals, versioned feature history, flow, theses and the most-specific available sector/theme rotation context. It remains cache-first and read-only.",
    }


@router.get("/deployment")
def deployment(
    capital: float = Query(1000.0, ge=0, le=100000000),
    basket: str = Query("watchlist"),
    symbols: str | None = Query(None),
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    if symbols:
        selected = [x.strip().upper() for x in symbols.split(",") if x.strip()]
        basket_name = "Custom Basket"
    elif basket.lower() in {"ai", "ai-buildout", "ai_buildout", "ai buildout basket"}:
        selected = AI_BUILDOUT_BASKET
        basket_name = "AI Buildout Basket"
    else:
        selected = _user_symbols(db, user)
        basket_name = "Watchlist + Portfolio"
    result = deployment_plan(selected, capital)
    return {"model": "Williams Priority v1", "basket": basket_name, "symbols": selected, "capital": capital, "new_capital_only": True, "existing_holdings_rebalanced": False, "quality_gate": "manual", **result}
