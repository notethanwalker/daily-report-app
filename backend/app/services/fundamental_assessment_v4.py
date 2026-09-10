from __future__ import annotations

from typing import Any

MODEL_VERSION = "fundamental-assessment-v4.2"


def _num(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _pct(value):
    value = _num(value)
    if value is None:
        return None
    return value * 100.0 if abs(value) <= 5 else value


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def assess_fundamentals(payload: dict | None) -> dict[str, Any]:
    """Transparent fundamental/valuation context.

    This is not an expected-return model. It explicitly separates business quality
    from valuation so a low multiple cannot hide deteriorating fundamentals.
    """
    p = dict(payload or {})
    eps = _num(p.get("eps"))
    revenue_growth = _pct(p.get("quarterly_revenue_growth_yoy") or p.get("revenue_growth"))
    earnings_growth = _pct(p.get("quarterly_earnings_growth_yoy") or p.get("earnings_growth"))
    margin = _pct(p.get("profit_margin") or p.get("net_margin"))
    margin_change = _num(p.get("profit_margin_change_yoy_points"))
    operating_margin_change = _num(p.get("operating_margin_change_yoy_points"))
    roe = _pct(p.get("return_on_equity") or p.get("roe"))
    debt_to_equity = _num(p.get("debt_to_equity") or p.get("debt_equity"))
    current_ratio = _num(p.get("current_ratio"))
    free_cash_flow = _num(p.get("free_cash_flow") or p.get("free_cashflow"))
    operating_cash_flow = _num(p.get("operating_cash_flow") or p.get("operating_cashflow"))
    total_cash = _num(p.get("total_cash"))
    total_debt = _num(p.get("total_debt"))
    pe = _num(p.get("pe_ratio"))
    forward_pe = _num(p.get("forward_pe"))
    ps = _num(p.get("price_to_sales_ratio"))
    peg = _num(p.get("peg_ratio"))

    scores: dict[str, float | None] = {}

    growth_parts = []
    if revenue_growth is not None:
        growth_parts.append(_clamp(50 + revenue_growth * 1.15))
    if earnings_growth is not None:
        growth_parts.append(_clamp(50 + earnings_growth * 0.85))
    scores["growth"] = round(sum(growth_parts) / len(growth_parts), 1) if growth_parts else None

    profit_parts = []
    if margin is not None:
        profit_parts.append(_clamp(50 + margin * 1.5))
    if roe is not None:
        profit_parts.append(_clamp(50 + roe))
    if margin_change is not None:
        profit_parts.append(_clamp(50 + margin_change * 5.0))
    elif operating_margin_change is not None:
        profit_parts.append(_clamp(50 + operating_margin_change * 5.0))
    scores["profitability"] = round(sum(profit_parts) / len(profit_parts), 1) if profit_parts else None

    balance_parts = []
    if debt_to_equity is not None and debt_to_equity >= 0:
        dte = debt_to_equity / 100.0 if debt_to_equity > 10 else debt_to_equity
        balance_parts.append(_clamp(85 - max(0.0, dte - 0.5) * 35.0))
    if current_ratio is not None and current_ratio >= 0:
        balance_parts.append(_clamp(35 + min(current_ratio, 3.0) * 25.0))
    if total_cash is not None and total_debt is not None and max(total_cash,total_debt)>0:
        balance_parts.append(_clamp(50 + ((total_cash-total_debt)/max(total_cash,total_debt))*35.0))
    scores["balance_sheet"] = round(sum(balance_parts) / len(balance_parts), 1) if balance_parts else None

    cash_parts = []
    if free_cash_flow is not None:
        cash_parts.append(80.0 if free_cash_flow > 0 else 20.0)
    if operating_cash_flow is not None:
        cash_parts.append(80.0 if operating_cash_flow > 0 else 20.0)
    scores["cash_flow"] = round(sum(cash_parts) / len(cash_parts), 1) if cash_parts else None

    pe_applicable = bool(pe is not None and pe > 0 and (eps is None or eps > 0))
    valuation_parts = []
    if pe_applicable:
        valuation_parts.append(_clamp(82 - max(0.0, pe - 15.0) * 1.5))
    if forward_pe is not None and forward_pe > 0:
        valuation_parts.append(_clamp(82 - max(0.0, forward_pe - 15.0) * 1.35))
    if ps is not None and ps >= 0:
        valuation_parts.append(_clamp(82 - max(0.0, ps - 3.0) * 6.0))
    if peg is not None and peg > 0:
        valuation_parts.append(_clamp(90 - max(0.0, peg - 1.0) * 25.0))
    scores["valuation"] = round(sum(valuation_parts) / len(valuation_parts), 1) if valuation_parts else None

    quality_parts = [scores[k] for k in ("growth", "profitability", "balance_sheet", "cash_flow") if scores[k] is not None]
    quality_score = round(sum(quality_parts) / len(quality_parts), 1) if quality_parts else None
    valuation_score = scores["valuation"]

    flags = []
    deterioration = 0
    if revenue_growth is not None and revenue_growth < 0:
        deterioration += 1; flags.append({"code":"revenue_contraction","severity":"warning","detail":f"Revenue growth is {revenue_growth:.1f}% YoY."})
    if earnings_growth is not None and earnings_growth < 0:
        deterioration += 1; flags.append({"code":"earnings_contraction","severity":"warning","detail":f"Earnings growth is {earnings_growth:.1f}% YoY."})
    if margin is not None and margin < 0:
        deterioration += 1; flags.append({"code":"negative_margin","severity":"warning","detail":f"Net margin is {margin:.1f}%."})
    if margin_change is not None and margin_change <= -3:
        deterioration += 1; flags.append({"code":"margin_compression","severity":"warning","detail":f"Net margin contracted {abs(margin_change):.1f} percentage points YoY."})
    elif operating_margin_change is not None and operating_margin_change <= -3:
        deterioration += 1; flags.append({"code":"operating_margin_compression","severity":"warning","detail":f"Operating margin contracted {abs(operating_margin_change):.1f} percentage points YoY."})
    if free_cash_flow is not None and free_cash_flow < 0:
        deterioration += 1; flags.append({"code":"negative_free_cash_flow","severity":"warning","detail":"Free cash flow is negative."})
    if debt_to_equity is not None:
        dte = debt_to_equity / 100.0 if debt_to_equity > 10 else debt_to_equity
        if dte > 2.0:
            flags.append({"code":"high_leverage","severity":"warning","detail":f"Debt/equity is {dte:.2f}x."})
    if total_cash is not None and total_debt is not None and total_debt > total_cash*2 and total_debt>0:
        flags.append({"code":"net_debt_pressure","severity":"warning","detail":"Total debt exceeds twice total cash in the latest cached fundamentals."})

    if not pe_applicable:
        reason = "negative/non-positive earnings" if eps is not None and eps <= 0 else "P/E unavailable or non-positive"
        flags.append({"code":"pe_not_meaningful","severity":"info","detail":f"P/E is not treated as a cheapness signal because {reason}."})

    anomaly = "neutral"
    if valuation_score is not None and valuation_score >= 70 and (quality_score is not None and quality_score < 45 or deterioration >= 2):
        anomaly = "value_trap_risk"
        flags.append({"code":"value_trap_risk","severity":"warning","detail":"Low/attractive valuation is paired with weak or deteriorating business quality."})
    elif valuation_score is not None and valuation_score <= 35 and quality_score is not None and quality_score >= 70:
        anomaly = "expensive_quality"
    elif valuation_score is not None and valuation_score >= 60 and quality_score is not None and quality_score >= 65:
        anomaly = "quality_at_reasonable_value"
    elif valuation_score is not None and valuation_score <= 35 and (quality_score is None or quality_score < 55):
        anomaly = "expensive_weak_quality"

    observed = sum(v is not None for v in scores.values())
    coverage = round(observed / len(scores), 2)
    confidence = "high" if coverage >= .8 else "medium" if coverage >= .5 else "low"

    return {
        "model_version": MODEL_VERSION,
        "quality_score": quality_score,
        "valuation_score": valuation_score,
        "anomaly": anomaly,
        "confidence": confidence,
        "coverage": coverage,
        "scores": scores,
        "flags": flags,
        "valuation_applicability": {
            "pe_meaningful": pe_applicable,
            "pe_reason": "positive trailing earnings and positive P/E" if pe_applicable else "P/E cannot be interpreted as cheapness",
        },
        "inputs": {
            "revenue_growth_yoy_percent": revenue_growth,
            "earnings_growth_yoy_percent": earnings_growth,
            "profit_margin_percent": margin,
            "profit_margin_change_yoy_points": margin_change,
            "operating_margin_change_yoy_points": operating_margin_change,
            "return_on_equity_percent": roe,
            "debt_to_equity": debt_to_equity,
            "current_ratio": current_ratio,
            "total_cash": total_cash,
            "total_debt": total_debt,
            "free_cash_flow": free_cash_flow,
            "operating_cash_flow": operating_cash_flow,
            "pe_ratio": pe,
            "forward_pe": forward_pe,
            "price_to_sales_ratio": ps,
            "peg_ratio": peg,
        },
        "policy": "Quality and valuation are reported separately. A low multiple does not override deteriorating fundamentals, profitability trajectory is evaluated when comparable quarterly data exists, and this assessment is not a return forecast.",
    }
