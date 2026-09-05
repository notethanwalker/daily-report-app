import re
from datetime import datetime, timezone

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

ETF_SUGGESTIONS = [
    {"symbol": "ITA", "name": "iShares U.S. Aerospace & Defense ETF", "theme": "Defense", "why": "Cleaner defense exposure than the broader ARKX basket."},
    {"symbol": "PAVE", "name": "Global X U.S. Infrastructure Development ETF", "theme": "Infrastructure", "why": "Useful for industrial capex, grid, construction, and reshoring rotation."},
    {"symbol": "KRE", "name": "SPDR S&P Regional Banking ETF", "theme": "Regional Banks", "why": "Adds rate/credit sensitivity that broad XLF can dilute."},
    {"symbol": "XBI", "name": "SPDR S&P Biotech ETF", "theme": "Biotech", "why": "High-beta healthcare risk appetite and financing-cycle proxy."},
    {"symbol": "IYT", "name": "iShares Transportation Average ETF", "theme": "Transports", "why": "Cyclical demand and goods-movement confirmation signal."},
    {"symbol": "URA", "name": "Global X Uranium ETF", "theme": "Uranium", "why": "Separates uranium/mining sensitivity from the broader NLR nuclear basket."},
    {"symbol": "COPX", "name": "Global X Copper Miners ETF", "theme": "Copper", "why": "Industrial growth, electrification, and commodity-cycle proxy."},
    {"symbol": "XME", "name": "SPDR S&P Metals & Mining ETF", "theme": "Metals & Mining", "why": "Adds materials-cycle breadth beyond broad XLB."},
]


def _number(value):
    return value if isinstance(value, (int, float)) else None


def _tokens(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "from", "into", "market", "markets", "stock", "stocks", "etf"}
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= 3 and w not in stop}


def _technical_reasons(symbol: str, name: str, item: dict, rank_kind: str) -> list[dict]:
    out = []
    price = _number(item.get("price"))
    vs50 = _number(item.get("price_vs_ma50_percent"))
    vs100 = _number(item.get("price_vs_ma100_percent"))
    vs200 = _number(item.get("price_vs_ma200_percent"))
    rel_vol = _number(item.get("relative_volume"))
    day = _number(item.get("change_percent"))
    week = _number(item.get("seven_day_percent"))
    month = _number(item.get("thirty_day_percent"))
    vs_ath = _number(item.get("price_vs_ath_percent"))
    hi52 = _number(item.get("high_52_week"))
    lo52 = _number(item.get("low_52_week"))

    trend_parts = []
    if vs50 is not None: trend_parts.append(f"50DMA {vs50:+.1f}%")
    if vs100 is not None: trend_parts.append(f"100DMA {vs100:+.1f}%")
    if vs200 is not None: trend_parts.append(f"200DMA {vs200:+.1f}%")
    aligned_up = all(v is not None and v > 0 for v in [vs50, vs100, vs200])
    aligned_down = all(v is not None and v < 0 for v in [vs50, vs100, vs200])
    if aligned_up or aligned_down:
        direction = "above" if aligned_up else "below"
        out.append({
            "reason_type": "technical",
            "title": f"{symbol}: moving-average trend alignment",
            "matched_symbol": symbol,
            "inference": f"Price is {direction} all tracked moving averages ({', '.join(trend_parts)}), which can reinforce trend-following positioning.",
            "evidence": trend_parts,
            "confidence": "medium",
            "move_context": rank_kind,
        })

    if rel_vol is not None and rel_vol >= 1.35:
        out.append({
            "reason_type": "technical",
            "title": f"{symbol}: elevated participation",
            "matched_symbol": symbol,
            "inference": f"Relative volume is {rel_vol:.2f}x normal, increasing confidence that the observed move has participation behind it rather than being a low-volume drift.",
            "evidence": [f"relative volume {rel_vol:.2f}x", f"day {day:+.2f}%" if day is not None else ""],
            "confidence": "medium",
            "move_context": rank_kind,
        })

    if week is not None and month is not None and abs(week) >= 3 and abs(month) >= 5 and week * month > 0:
        out.append({
            "reason_type": "technical",
            "title": f"{symbol}: multi-timeframe momentum",
            "matched_symbol": symbol,
            "inference": f"The 7-day ({week:+.1f}%) and 30-day ({month:+.1f}%) moves point in the same direction, consistent with persistent momentum rather than a one-day reversal.",
            "evidence": [f"7D {week:+.1f}%", f"30D {month:+.1f}%"],
            "confidence": "medium",
            "move_context": rank_kind,
        })

    if price is not None and hi52 not in (None, 0):
        from_high = ((price / hi52) - 1) * 100
        if from_high >= -2.5:
            out.append({
                "reason_type": "technical",
                "title": f"{symbol}: near 52-week resistance/high",
                "matched_symbol": symbol,
                "inference": f"Price is only {abs(from_high):.1f}% below its 52-week high, so breakout/continuation behavior or resistance reactions may be contributing to the move.",
                "evidence": [f"vs 52-week high {from_high:+.1f}%"],
                "confidence": "low",
                "move_context": rank_kind,
            })
    if price is not None and lo52 not in (None, 0):
        from_low = ((price / lo52) - 1) * 100
        if from_low <= 5:
            out.append({
                "reason_type": "technical",
                "title": f"{symbol}: near 52-week support/low",
                "matched_symbol": symbol,
                "inference": f"Price is only {from_low:.1f}% above its 52-week low, leaving the group in a technically weak zone where support tests can amplify moves.",
                "evidence": [f"vs 52-week low {from_low:+.1f}%"],
                "confidence": "low",
                "move_context": rank_kind,
            })
    if vs_ath is not None and vs_ath > -3:
        out.append({
            "reason_type": "technical",
            "title": f"{symbol}: close to provider-history all-time high",
            "matched_symbol": symbol,
            "inference": f"Price is {vs_ath:+.1f}% from the provider-history all-time high, a zone where breakout demand, profit-taking, or resistance can influence short-term movement.",
            "evidence": [f"vs ATH {vs_ath:+.1f}%"],
            "confidence": "low",
            "move_context": rank_kind,
        })
    return out[:3]


def _news_reasons(news: list[dict], focus_rows: list[dict]) -> list[dict]:
    candidates = []
    used_domains = set()
    for article in news or []:
        title = article.get("title") or ""
        article_tokens = _tokens(title + " " + " ".join(article.get("sectors") or []) + " " + " ".join(article.get("topics") or []))
        best = None
        for row in focus_rows:
            symbol = row["symbol"]
            name = row["name"]
            target = _tokens(f"{symbol} {name}")
            overlap = len(article_tokens & target)
            if symbol.lower() in title.lower(): overlap += 4
            if name.lower() in title.lower(): overlap += 4
            sector_hits = sum(1 for s in article.get("sectors") or [] if s.lower() in name.lower() or name.lower() in s.lower())
            score = overlap * 18 + sector_hits * 20 + min(int(article.get("relevance_score") or 0), 100) * 0.25
            if best is None or score > best[0]:
                best = (score, row)
        if not best or best[0] < 22:
            continue
        row = best[1]
        domain = article.get("domain") or "Unknown source"
        diversity_bonus = 8 if domain not in used_domains else 0
        score = best[0] + diversity_bonus
        candidates.append((score, article, row))

    candidates.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, article, row in candidates:
        domain = article.get("domain") or "Unknown source"
        if len(out) >= 6:
            break
        if domain in used_domains and len(used_domains) >= 3:
            continue
        used_domains.add(domain)
        confidence = "high" if score >= 75 else "medium" if score >= 45 else "low"
        out.append({
            "reason_type": "news",
            "title": article.get("title"),
            "url": article.get("url"),
            "domain": domain,
            "published_at": article.get("published_at"),
            "discovery_source": article.get("discovery_source"),
            "matched_symbol": row["symbol"],
            "matched_group": row["name"],
            "inference": article.get("why_it_matters") or f"Potential catalyst for {row['name']}.",
            "confidence": confidence,
            "match_score": round(score, 1),
            "move_context": "leader" if row.get("rotation_score", 0) >= 0 else "laggard",
        })
    return out


def build_rotation_snapshot(market_by_symbol: dict[str, dict], currencies: dict | None = None, news: list[dict] | None = None, news_meta: dict | None = None) -> dict:
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

    focus_rows = leaders[:3] + laggards[:3]
    reasons = _news_reasons(news or [], focus_rows)
    technical = []
    for row in focus_rows:
        item = market_by_symbol.get(row["symbol"], {})
        technical.extend(_technical_reasons(row["symbol"], row["name"], item, "leader" if row in leaders else "laggard"))
    technical = technical[:8]

    return {
        "methodology": "Rotation score combines 1-day, 7-day and 30-day performance, amplified by relative volume when above normal. It is evidence of relative momentum, not direct fund-flow measurement.",
        "sectors": rows,
        "leaders": leaders,
        "laggards": laggards,
        "spread": spread,
        "evidence": evidence,
        "possible_reasons": reasons,
        "technical_reasons": technical,
        "reasoning_methodology": "News catalysts are matched by ticker/theme token overlap, sector classification, relevance score, recency feed ordering, and source-domain diversity. Technical explanations use MA alignment, relative volume, multi-timeframe momentum, and proximity to 52-week/provider-history highs and lows. Neither is treated as proof of causality.",
        "news_context": news_meta or {},
        "etf_suggestions": ETF_SUGGESTIONS,
        "currency_context": (currencies or {}).get("rates", []),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
