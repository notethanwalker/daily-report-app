from __future__ import annotations


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalized_growth(value):
    value = _number(value)
    if value is None:
        return None
    return value * 100.0 if abs(value) <= 5 else value


def _bounded(value, low=0.0, high=100.0):
    return round(max(low, min(high, value)), 1)


def build_fundamental_score(payload: dict | None) -> dict:
    """Informational 0-100 fundamental context. Never alters technical ranking/allocation."""
    p = dict(payload or {})
    components = []

    revenue_growth = _normalized_growth(p.get("quarterly_revenue_growth_yoy") or p.get("revenue_growth"))
    earnings_growth = _normalized_growth(p.get("quarterly_earnings_growth_yoy") or p.get("earnings_growth"))
    growth_values = [x for x in (revenue_growth, earnings_growth) if x is not None]
    if growth_values:
        avg = sum(growth_values) / len(growth_values)
        components.append({"factor":"growth","score":_bounded(50 + avg * 1.25),"inputs":{"revenue_growth_yoy_percent":revenue_growth,"earnings_growth_yoy_percent":earnings_growth}})

    margin = _normalized_growth(p.get("profit_margin") or p.get("net_margin"))
    roe = _normalized_growth(p.get("return_on_equity") or p.get("roe"))
    profitability_values = []
    if margin is not None:
        profitability_values.append(_bounded(50 + margin * 1.5))
    if roe is not None:
        profitability_values.append(_bounded(50 + roe))
    if profitability_values:
        components.append({"factor":"profitability","score":round(sum(profitability_values)/len(profitability_values),1),"inputs":{"profit_margin_percent":margin,"return_on_equity_percent":roe}})

    pe = _number(p.get("pe_ratio"))
    ps = _number(p.get("price_to_sales_ratio"))
    peg = _number(p.get("peg_ratio"))
    valuation_values = []
    if pe is not None and pe > 0:
        valuation_values.append(_bounded(80 - max(0.0, pe - 15.0) * 1.5))
    if ps is not None and ps >= 0:
        valuation_values.append(_bounded(80 - max(0.0, ps - 3.0) * 6.0))
    if peg is not None and peg > 0:
        valuation_values.append(_bounded(90 - max(0.0, peg - 1.0) * 25.0))
    if valuation_values:
        components.append({"factor":"valuation","score":round(sum(valuation_values)/len(valuation_values),1),"inputs":{"pe_ratio":pe,"price_to_sales_ratio":ps,"peg_ratio":peg}})

    debt_to_equity = _number(p.get("debt_to_equity") or p.get("debt_equity"))
    if debt_to_equity is not None and debt_to_equity >= 0:
        dte = debt_to_equity / 100.0 if debt_to_equity > 10 else debt_to_equity
        components.append({"factor":"balance_sheet","score":_bounded(85 - max(0.0, dte - 0.5) * 35.0),"inputs":{"debt_to_equity":debt_to_equity}})

    free_cash_flow = _number(p.get("free_cash_flow") or p.get("free_cashflow"))
    operating_cash_flow = _number(p.get("operating_cash_flow") or p.get("operating_cashflow"))
    if free_cash_flow is not None or operating_cash_flow is not None:
        cash_score = 50.0
        if free_cash_flow is not None:
            cash_score += 25 if free_cash_flow > 0 else -25
        if operating_cash_flow is not None:
            cash_score += 20 if operating_cash_flow > 0 else -20
        components.append({"factor":"cash_flow","score":_bounded(cash_score),"inputs":{"free_cash_flow":free_cash_flow,"operating_cash_flow":operating_cash_flow}})

    if not components:
        return {"score":None,"grade":"insufficient data","coverage":0.0,"components":[],"informational_only":True,"affects_allocation":False}

    score = round(sum(x["score"] for x in components) / len(components), 1)
    coverage = round(len(components) / 5.0, 2)
    if coverage < 0.4:
        grade = "limited data"
    elif score >= 75:
        grade = "strong"
    elif score >= 60:
        grade = "above average"
    elif score >= 45:
        grade = "mixed"
    else:
        grade = "weak"
    return {"score":score,"grade":grade,"coverage":coverage,"components":components,"informational_only":True,"affects_allocation":False}
