from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from math import sqrt

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import MarketSnapshot, SymbolRegistry
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from ..normalized_market_models import NormalizedDailyBar

PORTFOLIO_FIT_MODEL_VERSION = "portfolio-fit-v4.1"
HISTORY_DAYS = 140
MIN_CORRELATION_OBSERVATIONS = 20
ASSET_WEIGHT = 0.80
FIT_WEIGHT = 0.20


def _clip(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _themes(value) -> set[str]:
    if isinstance(value, dict):
        return {str(k) for k, v in value.items() if v}
    if isinstance(value, (list, tuple, set)):
        return {str(x) for x in value if x}
    return set()


def _latest_market_map(db: Session, symbols: list[str]) -> dict[str, dict]:
    symbols = sorted({str(x).upper() for x in symbols if x})
    if not symbols:
        return {}
    sub = db.query(MarketSnapshot.symbol, func.max(MarketSnapshot.id).label("max_id")).filter(MarketSnapshot.symbol.in_(symbols)).group_by(MarketSnapshot.symbol).subquery()
    rows = db.query(MarketSnapshot).join(sub, MarketSnapshot.id == sub.c.max_id).all()
    return {row.symbol.upper(): dict(row.payload or {}) for row in rows}


def _daily_returns_map(db: Session, symbols: list[str], *, today: date | None = None) -> dict[str, dict[str, float]]:
    today = today or date.today()
    cutoff = (today - timedelta(days=HISTORY_DAYS)).isoformat()
    symbols = sorted({str(x).upper() for x in symbols if x})
    if not symbols:
        return {}
    rows = db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol.in_(symbols), NormalizedDailyBar.bar_date >= cutoff).order_by(NormalizedDailyBar.symbol, NormalizedDailyBar.bar_date).all()
    closes: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in rows:
        if row.close is not None:
            closes[str(row.symbol).upper()].append((str(row.bar_date)[:10], float(row.close)))
    out: dict[str, dict[str, float]] = {}
    for symbol, series in closes.items():
        returns: dict[str, float] = {}
        previous = None
        for day, close in series:
            if previous not in (None, 0):
                returns[day] = close / previous - 1.0
            previous = close
        out[symbol] = returns
    return out


def _weighted_portfolio_returns(returns: dict[str, dict[str, float]], weights: dict[str, float]) -> dict[str, float]:
    dates = sorted({d for symbol in weights for d in returns.get(symbol, {})})
    out = {}
    for day in dates:
        pairs = [(weight, returns.get(symbol, {}).get(day)) for symbol, weight in weights.items()]
        present = [(w, r) for w, r in pairs if r is not None]
        represented = sum(w for w, _ in present)
        if represented < 0.60:
            continue
        out[day] = sum((w / represented) * r for w, r in present)
    return out


def _correlation(a: dict[str, float], b: dict[str, float]) -> tuple[float | None, int]:
    common = sorted(set(a) & set(b))
    if len(common) < MIN_CORRELATION_OBSERVATIONS:
        return None, len(common)
    x = [a[d] for d in common]; y = [b[d] for d in common]
    mx = sum(x) / len(x); my = sum(y) / len(y)
    numerator = sum((vx - mx) * (vy - my) for vx, vy in zip(x, y))
    dx = sqrt(sum((vx - mx) ** 2 for vx in x)); dy = sqrt(sum((vy - my) ** 2 for vy in y))
    if dx == 0 or dy == 0:
        return None, len(common)
    return max(-1.0, min(1.0, numerator / (dx * dy))), len(common)


def _fit_score(components: dict[str, dict]) -> tuple[float | None, float]:
    weights = {"existing_position": 0.25, "sector_concentration": 0.30, "theme_overlap": 0.20, "correlation": 0.25}
    available = [(name, weights[name], data) for name, data in components.items() if name in weights and data.get("score") is not None]
    denom = sum(weight for _, weight, _ in available)
    if denom <= 0:
        return None, 0.0
    score = sum(float(data["score"]) * weight for _, weight, data in available) / denom
    return round(_clip(score), 2), round(denom, 2)


def attach_portfolio_fit(db: Session, user: str, candidates: list[dict]) -> dict:
    """Attach user-scoped diversification/capacity context without changing asset Opportunity scores."""
    portfolio = db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email == user).order_by(PortfolioDefinition.is_default.desc(), PortfolioDefinition.id.asc()).first()
    if not portfolio:
        for candidate in candidates:
            candidate["portfolio_fit"] = {"available": False, "reason": "No portfolio is configured for the authenticated user.", "model_version": PORTFOLIO_FIT_MODEL_VERSION}
            candidate["portfolio_adjusted_score"] = candidate.get("formula_score")
            candidate["portfolio_adjusted_rank"] = candidate.get("formula_rank")
        return {"available": False, "model_version": PORTFOLIO_FIT_MODEL_VERSION, "reason": "No user portfolio configured."}

    positions = db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id == portfolio.id, PortfolioPosition.shares > 0).all()
    holding_symbols = [str(p.symbol).upper() for p in positions]
    candidate_symbols = [str(c.get("symbol") or "").upper() for c in candidates if c.get("symbol")]
    all_symbols = sorted(set(holding_symbols + candidate_symbols))
    registry_rows = db.query(SymbolRegistry).filter(SymbolRegistry.symbol.in_(all_symbols)).all() if all_symbols else []
    registry = {str(row.symbol).upper(): row for row in registry_rows}
    markets = _latest_market_map(db, holding_symbols)

    values = {}
    for pos in positions:
        symbol = str(pos.symbol).upper()
        price = (markets.get(symbol) or {}).get("price")
        if price is not None:
            value = float(price) * float(pos.shares)
        elif pos.imported_market_value is not None:
            value = float(pos.imported_market_value)
        else:
            value = float(pos.average_cost or 0) * float(pos.shares)
        values[symbol] = max(0.0, value)
    invested = sum(values.values())
    total = invested + float(portfolio.cash or 0)
    holding_weights = {symbol: value / invested for symbol, value in values.items() if invested > 0 and value > 0}
    account_weights = {symbol: value / total for symbol, value in values.items() if total > 0 and value > 0}

    sector_exposure: dict[str, float] = defaultdict(float)
    theme_exposure: dict[str, float] = defaultdict(float)
    for symbol, weight in account_weights.items():
        reg = registry.get(symbol)
        sector = str(reg.sector).strip() if reg and reg.sector else ""
        if sector:
            sector_exposure[sector] += weight
        for theme in _themes(reg.themes if reg else None):
            theme_exposure[theme] += weight

    returns = _daily_returns_map(db, all_symbols)
    portfolio_returns = _weighted_portfolio_returns(returns, holding_weights) if holding_weights else {}

    for candidate in candidates:
        symbol = str(candidate.get("symbol") or "").upper()
        reg = registry.get(symbol)
        sector = str(reg.sector).strip() if reg and reg.sector else str(candidate.get("sector") or "").strip()
        candidate_themes = _themes(reg.themes if reg else None)
        current_symbol_pct = account_weights.get(symbol, 0.0) * 100.0
        sector_pct = sector_exposure.get(sector, 0.0) * 100.0 if sector else None
        theme_pairs = sorted(((theme, theme_exposure.get(theme, 0.0) * 100.0) for theme in candidate_themes), key=lambda x: x[1], reverse=True)
        max_theme_pct = theme_pairs[0][1] if theme_pairs else None
        corr, corr_n = _correlation(returns.get(symbol, {}), portfolio_returns) if portfolio_returns else (None, 0)

        components = {
            "existing_position": {"score": round(_clip(100.0 - current_symbol_pct * 4.0), 2), "current_exposure_pct": round(current_symbol_pct, 2)},
            "sector_concentration": {"score": round(_clip(100.0 - sector_pct * 2.5), 2) if sector_pct is not None else None, "sector": sector or None, "current_exposure_pct": round(sector_pct, 2) if sector_pct is not None else None},
            "theme_overlap": {"score": round(_clip(100.0 - max_theme_pct * 2.0), 2) if max_theme_pct is not None else None, "highest_overlap_theme": theme_pairs[0][0] if theme_pairs else None, "current_exposure_pct": round(max_theme_pct, 2) if max_theme_pct is not None else None},
            "correlation": {"score": round(_clip((1.0 - corr) * 100.0), 2) if corr is not None else None, "correlation": round(corr, 3) if corr is not None else None, "observations": corr_n},
        }
        fit_score, coverage = _fit_score(components)
        formula_score = float(candidate.get("formula_score") or 0.0)
        adjusted = formula_score if fit_score is None else ASSET_WEIGHT * formula_score + FIT_WEIGHT * fit_score
        confidence = "high" if coverage >= 0.90 else "medium" if coverage >= 0.65 else "low" if coverage > 0 else "none"
        candidate["portfolio_fit"] = {
            "available": fit_score is not None,
            "score": fit_score,
            "confidence": confidence,
            "component_weight_coverage": coverage,
            "components": components,
            "cash_percent": round((float(portfolio.cash or 0) / total * 100.0), 2) if total else None,
            "portfolio_name": portfolio.name,
            "model_version": PORTFOLIO_FIT_MODEL_VERSION,
            "status": "experimental",
            "policy": "Portfolio Fit measures diversification/capacity context, not expected return. Missing components are omitted and remaining component weights are renormalized.",
        }
        candidate["portfolio_adjusted_score"] = round(adjusted, 2)

    ordered = sorted(candidates, key=lambda c: (float(c.get("portfolio_adjusted_score") or 0), float(c.get("formula_score") or 0)), reverse=True)
    for rank, candidate in enumerate(ordered, start=1):
        candidate["portfolio_adjusted_rank"] = rank

    best_absolute = min(candidates, key=lambda c: c.get("formula_rank") or 10**9, default=None)
    best_portfolio = ordered[0] if ordered else None
    return {
        "available": True,
        "model_version": PORTFOLIO_FIT_MODEL_VERSION,
        "status": "experimental",
        "portfolio": {"id": portfolio.id, "name": portfolio.name, "cash_percent": round(float(portfolio.cash or 0) / total * 100.0, 2) if total else None, "holding_count": len(positions)},
        "best_absolute": {"symbol": best_absolute.get("symbol"), "formula_rank": best_absolute.get("formula_rank"), "formula_score": best_absolute.get("formula_score")} if best_absolute else None,
        "best_for_portfolio": {"symbol": best_portfolio.get("symbol"), "portfolio_adjusted_rank": best_portfolio.get("portfolio_adjusted_rank"), "portfolio_adjusted_score": best_portfolio.get("portfolio_adjusted_score"), "formula_rank": best_portfolio.get("formula_rank")} if best_portfolio else None,
        "blend": {"asset_opportunity_weight": ASSET_WEIGHT, "portfolio_fit_weight": FIT_WEIGHT},
        "policy": "Asset Opportunity and Portfolio Fit remain separate. The provisional portfolio-aware rank is an explicitly experimental 80/20 blend and must not be interpreted as calibrated return probability.",
    }
