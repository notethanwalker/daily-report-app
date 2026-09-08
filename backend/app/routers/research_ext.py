from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..providers.stooq import StooqError, StooqProvider
from .security_intelligence_v5 import security_intelligence

router = APIRouter(prefix="/api/v1", tags=["research"])


def _history(symbol: str) -> dict:
    try:
        return StooqProvider().daily_history(symbol)
    except StooqError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _iso(value: str | None, fallback: str) -> str:
    raw = value or fallback
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date: {raw}") from exc


def _williams(rows: list[dict], window: int = 14) -> list[dict]:
    out = []
    for i, row in enumerate(rows):
        wr = None
        if i >= window - 1:
            lookback = rows[i - window + 1 : i + 1]
            highs = [x.get("high") for x in lookback if x.get("high") is not None]
            lows = [x.get("low") for x in lookback if x.get("low") is not None]
            close = row.get("close")
            if len(highs) == window and len(lows) == window and close is not None:
                hh, ll = max(highs), min(lows)
                if hh != ll:
                    wr = -100.0 * (hh - close) / (hh - ll)
        out.append({**row, "williams_r": wr})
    return out


def _summary(contributions: float, invested: float, cash: float, shares: float, price: float) -> dict:
    market_value = shares * price
    total_value = market_value + cash
    profit = total_value - contributions
    return {
        "total_contributions": round(contributions, 2),
        "total_invested": round(invested, 2),
        "remaining_cash": round(cash, 2),
        "shares": round(shares, 8),
        "effective_cost_basis": round(invested / shares, 6) if shares else None,
        "stock_market_value": round(market_value, 2),
        "total_portfolio_value": round(total_value, 2),
        "profit": round(profit, 2),
        "return_pct": round((profit / contributions) * 100.0, 4) if contributions else None,
    }


@router.get("/security/{symbol}/catalysts")
def security_catalysts(symbol: str, db: Session = Depends(get_db)):
    data = security_intelligence(symbol, refresh_missing=True, force=False, history_days=365, db=db)
    return {
        "symbol": data.get("symbol"),
        "news": (data.get("news") or {}).get("articles") or [],
        "upcoming": (data.get("catalysts") or {}).get("upcoming") or [],
        "source": "shared security intelligence cache",
        "provider_calls": "cache-policy controlled",
        "cache_policy": data.get("cache_policy") or {},
    }


@router.get("/market/history/{symbol}")
def market_history(
    symbol: str,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    data = _history(symbol)
    rows = data.get("rows") or []
    if not rows:
        raise HTTPException(status_code=404, detail="No history returned")
    start_date = _iso(start, rows[0]["date"])
    end_date = _iso(end, rows[-1]["date"])
    selected = [r for r in rows if start_date <= r["date"] <= end_date]
    return {
        "symbol": data.get("symbol"),
        "provider": data.get("provider"),
        "source_url": data.get("source_url"),
        "retrieved_at": data.get("retrieved_at"),
        "start_date": selected[0]["date"] if selected else None,
        "end_date": selected[-1]["date"] if selected else None,
        "row_count": len(selected),
        "rows": selected,
    }


@router.get("/backtests/williams-timeline/{symbol}")
def williams_timeline_backtest(
    symbol: str,
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str | None = Query(default=None, description="YYYY-MM-DD; defaults to latest available bar"),
    monthly_contribution: float = Query(default=1000.0, gt=0),
    threshold: float = Query(default=-80.0, ge=-100.0, le=0.0),
    window: int = Query(default=14, ge=2, le=252),
):
    data = _history(symbol)
    raw = data.get("rows") or []
    if len(raw) < window:
        raise HTTPException(status_code=422, detail="Insufficient history")
    start_date = _iso(start, raw[0]["date"])
    end_date = _iso(end, raw[-1]["date"])
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end must be on or after start")

    series = _williams(raw, window=window)
    eligible = [r for r in series if start_date <= r["date"] <= end_date]
    if not eligible:
        raise HTTPException(status_code=404, detail="No trading days in requested range")

    first_by_month: dict[str, dict] = {}
    for row in eligible:
        first_by_month.setdefault(row["date"][:7], row)
    contribution_dates = {row["date"]: row for row in first_by_month.values()}

    dca_shares = 0.0
    dca_invested = 0.0
    dca_ledger = []
    for row in first_by_month.values():
        amount = float(monthly_contribution)
        close = float(row["close"])
        shares = amount / close
        dca_shares += shares
        dca_invested += amount
        dca_ledger.append({"date": row["date"], "amount": amount, "close": close, "shares_bought": shares})

    cash = 0.0
    wr_shares = 0.0
    wr_invested = 0.0
    trigger_ledger = []
    contribution_ledger = []
    previous = None
    for row in series:
        if row["date"] > end_date:
            break
        if row["date"] < start_date:
            previous = row
            continue
        if row["date"] in contribution_dates:
            cash += float(monthly_contribution)
            contribution_ledger.append({"date": row["date"], "amount": float(monthly_contribution), "cash_after_contribution": cash})
        current_wr = row.get("williams_r")
        previous_wr = previous.get("williams_r") if previous else None
        fresh_cross = (
            current_wr is not None
            and previous_wr is not None
            and current_wr <= threshold
            and previous_wr > threshold
        )
        if fresh_cross and cash > 0:
            amount = cash
            close = float(row["close"])
            shares = amount / close
            wr_shares += shares
            wr_invested += amount
            cash = 0.0
            trigger_ledger.append({
                "date": row["date"],
                "prior_williams_r": previous_wr,
                "williams_r": current_wr,
                "close": close,
                "amount_invested": amount,
                "shares_bought": shares,
            })
        previous = row

    contributions = len(first_by_month) * float(monthly_contribution)
    valuation_row = eligible[-1]
    valuation_price = float(valuation_row["close"])

    return {
        "test": "Williams Timeline Test",
        "symbol": data.get("symbol"),
        "provider": data.get("provider"),
        "source_url": data.get("source_url"),
        "retrieved_at": data.get("retrieved_at"),
        "parameters": {
            "start": eligible[0]["date"],
            "end": eligible[-1]["date"],
            "monthly_contribution": monthly_contribution,
            "threshold": threshold,
            "window": window,
            "execution": "trigger-day close",
            "contribution_timing": "first trading day of each month",
        },
        "valuation": {"date": valuation_row["date"], "close": valuation_price},
        "strategy_1_monthly_dca": {
            **_summary(contributions, dca_invested, 0.0, dca_shares, valuation_price),
            "transactions": dca_ledger,
        },
        "strategy_2_williams_timeline": {
            **_summary(contributions, wr_invested, cash, wr_shares, valuation_price),
            "contributions": contribution_ledger,
            "triggers": trigger_ledger,
        },
    }
