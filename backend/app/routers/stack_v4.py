from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FeatureSnapshot, FundamentalCache, MarketSnapshot, SymbolRegistry, Thesis, UserWatchlistItem
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from ..normalized_market_models import MarketPipelineState
from ..providers.alpaca_market_data import AlpacaMarketDataProvider
from ..services.candidate_funnel_v4 import build_candidate_funnel
from ..services.classification_v4 import rotation_proxy_name
from ..services.feature_model_v4 import version_payload
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
    if not row:
        return {}
    payload = version_payload(row.payload or {})
    if payload != (row.payload or {}):
        row.payload = payload
        db.commit()
    return {**payload, "as_of": row.as_of}


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


def _tracked_opportunities(db: Session, symbols: list[str], rotation: dict) -> list[dict]:
    rows = []
    for s in symbols:
        f = _latest_feature(db, s)
        m = _latest_market(db, s)
        reg = db.get(SymbolRegistry, s)
        buy = float(f.get("buy_score") or 0)
        macro, proxy, basis = _macro_for_security(rotation, s, m, reg)
        pressure = float(macro.get("rotation_pressure") or 0)
        raw_score = buy + max(-10.0, min(10.0, pressure * 2.5))
        rows.append({
            "symbol": s,
            "score": round(max(0.0, min(100.0, raw_score)), 2),
            "raw_rank_score": round(raw_score, 2),
            "base_buy_score": round(buy, 2),
            "sector": (reg.sector if reg else None) or m.get("sector"),
            "rotation_proxy": proxy,
            "rotation_proxy_basis": basis,
            "rotation_pressure": macro.get("rotation_pressure"),
            "rotation_state": macro.get("state"),
            "rotation_conviction": macro.get("conviction"),
            "williams_feature": f.get("williams_r"),
            "ma100_distance": f.get("ma100_distance"),
            "as_of": f.get("as_of") or m.get("as_of"),
            "price": m.get("price"),
            "provider": m.get("provider"),
            "model_version": f.get("model_version"),
            "model_config_hash": f.get("model_config_hash"),
        })
    return sorted(rows, key=lambda x: x["raw_rank_score"], reverse=True)


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: str = Depends(current_user)):
    symbols = _user_symbols(db, user)
    rotation = build_rotation_model(db)
    tracked = _tracked_opportunities(db, symbols, rotation)
    feature_count = db.query(FeatureSnapshot).count()
    market_count = db.query(MarketSnapshot).count()
    rotation_state = db.get(MarketPipelineState, ROTATION_HISTORY_KEY)
    rotation_history_days = len((rotation_state.payload or {}).get("daily", [])) if rotation_state else 0
    return {
        "version": "4.2-dev",
        "pipeline": ["research", "macro", "opportunity", "deployment"],
        "provider_policy": ProviderOrchestrator().describe(),
        "sources": _source_registry(),
        "layers": {
            "research": {
                "symbols": len(symbols),
                "stored_market_snapshots": market_count,
                "stored_feature_snapshots": feature_count,
                "status": "active-v4",
                "capabilities": ["markets", "portfolios", "security research", "fundamentals", "world news", "events", "large flow", "theses", "alerts", "versioned score history"],
            },
            "macro": {
                "status": "active-v4",
                "sector_rows": len(rotation.get("rows", [])),
                "leaders": rotation.get("leaders", [])[:5],
                "early_rotation": rotation.get("early_rotation", [])[:5],
                "outflow_risk": rotation.get("outflow_risk", [])[:5],
                "state_counts": rotation.get("state_counts", {}),
                "rotation_history_days": rotation_history_days,
                "history_policy": rotation.get("history_policy"),
                "methodology": rotation.get("methodology"),
                "capabilities": ["sector/theme strength", "rotation acceleration/deceleration", "transition states", "persisted state history", "breadth", "regime", "currencies", "liquidity proxies"],
            },
            "opportunity": {
                "status": "active-v4",
                "candidates": tracked[:10],
                "candidate_count": len(tracked),
                "methodology": "Tracked candidates combine versioned opportunity scores with bounded sector/theme-rotation pressure. The broad-market funnel is cache-first, then queues only shortlisted names for deeper enrichment.",
            },
            "deployment": {
                "status": "phase-1",
                "models": ["Williams Priority — new capital only"],
                "named_baskets": {"AI Buildout Basket": AI_BUILDOUT_BASKET},
                "manual_quality_gate": True,
                "rebalancing_default": False,
            },
        },
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
    rotation_model = build_rotation_model(db)
    return build_candidate_funnel(db, rotation_model, limit=limit)


@router.get("/scores/{symbol}")
def score_history(symbol: str, limit: int = Query(90, ge=2, le=365), db: Session = Depends(get_db), user: str = Depends(current_user)):
    _ = user
    _latest_feature(db, symbol.strip().upper())
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
        "methodology": "Entity-centric workspace composes stored market, fundamentals, versioned feature history, flow, theses and the most-specific available sector/theme rotation context. It remains cache-first.",
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
    return {
        "model": "Williams Priority v1",
        "basket": basket_name,
        "symbols": selected,
        "capital": capital,
        "new_capital_only": True,
        "existing_holdings_rebalanced": False,
        "quality_gate": "manual",
        **result,
    }
