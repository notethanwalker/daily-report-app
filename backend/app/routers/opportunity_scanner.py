from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import UserWatchlistItem
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from ..models import PortfolioHolding
from ..services.opportunity_scanner import scan_cached_market
from .intelligence import _opportunity_components, current_user

router = APIRouter(prefix="/api/v1/opportunities", tags=["opportunity-scanner"])


def _tracked_symbols(db: Session, user: str) -> list[str]:
    symbols = {
        r.symbol.upper()
        for r in db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email == user).all()
        if r.symbol and r.symbol != "__INITIALIZED__"
    }
    symbols |= {
        r.symbol.upper()
        for r in db.query(PortfolioHolding).filter(PortfolioHolding.user_email == user).all()
        if r.symbol
    }
    portfolio_ids = [r.id for r in db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email == user).all()]
    if portfolio_ids:
        symbols |= {
            r.symbol.upper()
            for r in db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id.in_(portfolio_ids)).all()
            if r.symbol
        }
    return sorted(symbols)


def _signal(buy: float | None, sell: float | None) -> str:
    b = float(buy or 0)
    s = float(sell or 0)
    if b >= 80 and b >= s + 10:
        return "strong_buy"
    if b >= 65 and b > s:
        return "buy"
    if s >= 80 and s >= b + 10:
        return "strong_sell"
    if s >= 65 and s > b:
        return "sell"
    return "neutral"


@router.get("/tracked")
def tracked_opportunities(
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    rows = []
    for symbol in _tracked_symbols(db, user):
        opportunity = _opportunity_components(db, symbol)
        if not opportunity:
            continue
        market = opportunity.get("market") or {}
        rows.append({
            "symbol": symbol,
            "signal": _signal(opportunity.get("buy_score"), opportunity.get("sell_score")),
            "buy_score": opportunity.get("buy_score"),
            "sell_score": opportunity.get("sell_score"),
            "components": opportunity.get("components") or {},
            "flow": opportunity.get("flow") or {},
            "sector_score": opportunity.get("sector_score"),
            "williams_r_14": market.get("williams_r_14"),
            "price_vs_ma100_percent": market.get("price_vs_ma100_percent"),
            "price_vs_ma200_percent": market.get("price_vs_ma200_percent"),
            "price": market.get("price"),
            "change_percent": market.get("change_percent"),
            "as_of": market.get("as_of"),
            "retrieved_at": market.get("retrieved_at"),
        })
    rows.sort(key=lambda x: max(float(x.get("buy_score") or 0), float(x.get("sell_score") or 0)), reverse=True)
    counts = {k: sum(1 for r in rows if r["signal"] == k) for k in ("strong_buy", "buy", "neutral", "sell", "strong_sell")}
    return {
        "rows": rows,
        "counts": counts,
        "universe": "Authenticated user's Markets watchlist union Portfolio holdings; symbols are deduplicated before scoring.",
        "methodology": "Uses the existing auditable multi-factor buy/sell formula and shared cached symbol data. No additional provider request is made by this endpoint.",
    }


@router.get("/market-scan")
def market_opportunities(
    include_near: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    # user dependency intentionally enforces Opportunities access/account scope,
    # while the normalized market cache itself remains safely shared by symbol.
    _ = user
    return scan_cached_market(db, include_near=include_near, limit_per_bucket=limit)
