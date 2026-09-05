SECTORS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
    "SMH": "Semiconductors",
    "EUV": "Photonics",
    "DRAM": "Memory",
    "NCLD": "Neocloud",
    "IGV": "Software",
    "CIBR": "Cybersecurity",
    "ARKX": "Space / Defense",
    "NLR": "Nuclear",
    "QTUM": "Quantum",
    "BOTZ": "Robotics & AI",
    "GLD": "Gold",
}


def _number(value):
    return value if isinstance(value, (int, float)) else None


def build_rotation_snapshot(market_by_symbol: dict[str, dict], currencies: dict | None = None, news: list[dict] | None = None) -> dict:
    rows = []
    for symbol, name in SECTORS.items():
        item = market_by_symbol.get(symbol)
        if not item:
            continue
        day = _number(item.get("change_percent"))
        week = _number(item.get("seven_day_percent"))
        month = _number(item.get("thirty_day_percent"))
        rel_vol = _number(item.get("relative_volume"))
        score = (day or 0) * 0.25 + (week or 0) * 0.45 + (month or 0) * 0.30
        if rel_vol and rel_vol > 1:
            score *= min(rel_vol, 2.0)
        rows.append({
            "symbol": symbol,
            "name": name,
            "day_percent": day,
            "seven_day_percent": week,
            "thirty_day_percent": month,
            "relative_volume": rel_vol,
            "rotation_score": round(score, 2),
            "source_url": item.get("source_url"),
            "as_of": item.get("as_of"),
        })

    rows.sort(key=lambda row: row["rotation_score"], reverse=True)
    leaders = rows[:5]
    laggards = list(reversed(rows[-5:])) if rows else []
    spread = None
    if leaders and laggards:
        spread = round(leaders[0]["rotation_score"] - laggards[0]["rotation_score"], 2)

    evidence = []
    if leaders:
        evidence.append(f"Leadership: {', '.join(row['name'] for row in leaders[:3])}.")
    if laggards:
        evidence.append(f"Weakness: {', '.join(row['name'] for row in laggards[:3])}.")
    if spread is not None:
        evidence.append(f"Leader-laggard rotation spread: {spread:.2f} points.")

    reasons = []
    for article in (news or [])[:20]:
        sectors = article.get("sectors") or []
        if sectors and any(sector.lower() in " ".join(row["name"].lower() for row in leaders) for sector in sectors):
            reasons.append({
                "title": article.get("title"),
                "url": article.get("url"),
                "inference": article.get("why_it_matters"),
                "confidence": "medium",
            })
        if len(reasons) >= 4:
            break

    return {
        "methodology": "Rotation score combines 1-day, 7-day and 30-day performance, amplified by relative volume when above normal. It is evidence of relative momentum, not direct fund-flow measurement.",
        "sectors": rows,
        "leaders": leaders,
        "laggards": laggards,
        "spread": spread,
        "evidence": evidence,
        "possible_reasons": reasons,
        "currency_context": (currencies or {}).get("rates", []),
    }
