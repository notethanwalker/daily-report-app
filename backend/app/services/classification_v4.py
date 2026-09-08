from __future__ import annotations

# Maps security metadata to the most decision-relevant rotation proxy. Broad GICS
# sector is the fallback; industry/theme matches take precedence.
SECTOR_PROXY_NAME = {
    "Technology": "Technology",
    "Financials": "Financials",
    "Energy": "Energy",
    "Healthcare": "Healthcare",
    "Industrials": "Industrials",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Materials": "Materials",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Communication Services": "Communication Services",
}

KEYWORD_PROXIES = [
    (("semiconductor", "semiconductors", "chip", "foundry"), "Semiconductors"),
    (("memory", "dram", "nand"), "Memory"),
    (("photonics", "optical", "optoelectronic", "fiber optic"), "Photonics"),
    (("cloud infrastructure", "neocloud", "gpu cloud"), "Neocloud"),
    (("cybersecurity", "security software"), "Cybersecurity"),
    (("software", "saas"), "Software"),
    (("nuclear", "uranium"), "Nuclear"),
    (("quantum",), "Quantum"),
    (("robotics", "automation", "artificial intelligence"), "Robotics & AI"),
    (("aerospace", "defense"), "Aerospace & Defense"),
    (("biotech", "biotechnology"), "Biotech"),
    (("copper",), "Copper Miners"),
    (("metals", "mining"), "Metals & Mining"),
]

# Explicit overrides are intentionally small and auditable. They are for cases
# where broad provider metadata obscures the investment theme we actively track.
SYMBOL_PROXY_OVERRIDES = {
    "MU": "Memory",
    "NVDA": "Semiconductors",
    "AMD": "Semiconductors",
    "AVGO": "Semiconductors",
    "TSM": "Semiconductors",
    "ASML": "Semiconductors",
    "AMAT": "Semiconductors",
    "LRCX": "Semiconductors",
    "KLAC": "Semiconductors",
    "AAOI": "Photonics",
    "AXTI": "Photonics",
    "NBIS": "Neocloud",
}


def _theme_text(themes) -> str:
    if isinstance(themes, dict):
        values = []
        for k, v in themes.items():
            values.append(str(k))
            if isinstance(v, (str, int, float, bool)):
                values.append(str(v))
            elif isinstance(v, list):
                values.extend(map(str, v))
        return " ".join(values).lower()
    if isinstance(themes, list):
        return " ".join(map(str, themes)).lower()
    return str(themes or "").lower()


def rotation_proxy_name(symbol: str, sector: str | None, industry: str | None, themes=None) -> tuple[str | None, str]:
    s = (symbol or "").upper()
    if s in SYMBOL_PROXY_OVERRIDES:
        return SYMBOL_PROXY_OVERRIDES[s], "symbol_override"
    text = " ".join([str(industry or ""), _theme_text(themes)]).lower()
    for keywords, proxy in KEYWORD_PROXIES:
        if any(k in text for k in keywords):
            return proxy, "industry_or_theme"
    if sector in SECTOR_PROXY_NAME:
        return SECTOR_PROXY_NAME[sector], "sector"
    return None, "unmapped"
