from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FeatureSnapshot, MarketSnapshot, UserWatchlistItem
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from ..providers.alpaca_market_data import AlpacaMarketDataProvider
from ..services.monthly_priority import deployment_plan
from ..services.provider_orchestrator import ProviderOrchestrator
from .decision_support import _macro_rows
from .intelligence import current_user

router = APIRouter(prefix="/api/v1/stack", tags=["decision-stack-v4"])
AI_BUILDOUT_BASKET = ["NBIS", "MU", "AAOI", "NVDA", "SMH"]


def _user_symbols(db: Session, user: str) -> list[str]:
    symbols = {x.symbol for x in db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email == user).all()}
    pids = [x.id for x in db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email == user).all()]
    if pids:
        symbols |= {x.symbol for x in db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id.in_(pids)).all()}
    return sorted(symbols)


def _latest_feature(db: Session, symbol: str) -> dict:
    row = db.query(FeatureSnapshot).filter(FeatureSnapshot.symbol == symbol).order_by(FeatureSnapshot.as_of.desc(), FeatureSnapshot.created_at.desc()).first()
    return {**(row.payload or {}), "as_of": row.as_of} if row else {}


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


def _opportunities(db: Session, symbols: list[str], macro: list[dict]) -> list[dict]:
    sector_score = {x["name"]: x["rotation_score"] for x in macro}
    rows = []
    for s in symbols:
        f = _latest_feature(db, s)
        m = _latest_market(db, s)
        buy = float(f.get("buy_score") or 0)
        will = f.get("williams_r")
        ma100 = f.get("ma100_distance")
        sector = m.get("sector")
        macro_score = float(sector_score.get(sector, 0))
        composite = buy + max(-10.0, min(10.0, macro_score)) * 0.75
        rows.append({
            "symbol": s,
            "score": round(composite, 2),
            "base_buy_score": round(buy, 2),
            "sector": sector,
            "sector_rotation_score": round(macro_score, 2),
            "williams_feature": will,
            "ma100_distance": ma100,
            "as_of": f.get("as_of") or m.get("as_of"),
            "price": m.get("price"),
            "provider": m.get("provider"),
        })
    return sorted(rows, key=lambda x: x["score"], reverse=True)


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: str = Depends(current_user)):
    symbols = _user_symbols(db, user)
    macro = _macro_rows(db)
    opportunities = _opportunities(db, symbols, macro)
    feature_count = db.query(FeatureSnapshot).count()
    market_count = db.query(MarketSnapshot).count()
    return {
        "version": "4.0-dev",
        "pipeline": ["research", "macro", "opportunity", "deployment"],
        "provider_policy": ProviderOrchestrator().describe(),
        "sources": _source_registry(),
        "layers": {
            "research": {
                "symbols": len(symbols),
                "stored_market_snapshots": market_count,
                "stored_feature_snapshots": feature_count,
                "status": "active",
                "capabilities": ["markets", "portfolios", "security research", "fundamentals", "world news", "events", "large flow", "theses", "alerts"],
            },
            "macro": {
                "status": "active",
                "sector_rows": len(macro),
                "leaders": macro[:5],
                "laggards": list(reversed(macro[-5:])),
                "capabilities": ["sector strength", "breadth", "regime", "rotation", "currencies", "liquidity proxies"],
            },
            "opportunity": {
                "status": "active",
                "candidates": opportunities[:10],
                "candidate_count": len(opportunities),
                "methodology": "Candidate-first scoring from cached user/watchlist/portfolio symbols. Base opportunity score is combined with bounded sector-rotation context; expensive refreshes remain incremental.",
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
