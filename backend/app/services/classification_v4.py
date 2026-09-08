from __future__ import annotations

SECTOR_PROXY_NAME = {
    "Technology": "Technology", "Financials": "Financials", "Energy": "Energy", "Healthcare": "Healthcare",
    "Industrials": "Industrials", "Consumer Discretionary": "Consumer Discretionary", "Consumer Staples": "Consumer Staples",
    "Materials": "Materials", "Utilities": "Utilities", "Real Estate": "Real Estate", "Communication Services": "Communication Services",
}

KEYWORD_PROXIES = [
    (("memory", "dram", "nand"), "Memory"),
    (("photonics", "optical", "optoelectronic", "fiber optic"), "Photonics"),
    (("cloud infrastructure", "neocloud", "gpu cloud"), "Neocloud"),
    (("semiconductor", "semiconductors", "chip", "foundry"), "Semiconductors"),
    (("cybersecurity", "security software"), "Cybersecurity"), (("software", "saas"), "Software"),
    (("nuclear", "uranium"), "Nuclear"), (("quantum",), "Quantum"),
    (("robotics", "automation", "artificial intelligence"), "Robotics & AI"),
    (("aerospace", "defense"), "Aerospace & Defense"), (("biotech", "biotechnology"), "Biotech"),
    (("copper",), "Copper Miners"), (("metals", "mining"), "Metals & Mining"),
]

# Explicit weights are intentionally auditable. They encode investment-theme exposure,
# not business-segment revenue accounting, and can later be learned from observed outcomes.
SYMBOL_EXPOSURES = {
    "MU": {"Memory": .75, "Semiconductors": .25},
    "NVDA": {"Semiconductors": .70, "Robotics & AI": .30},
    "AMD": {"Semiconductors": .80, "Robotics & AI": .20},
    "AVGO": {"Semiconductors": .65, "Technology": .35},
    "TSM": {"Semiconductors": 1.0}, "ASML": {"Semiconductors": 1.0}, "AMAT": {"Semiconductors": 1.0}, "LRCX": {"Semiconductors": 1.0}, "KLAC": {"Semiconductors": 1.0},
    "AAOI": {"Photonics": .85, "Technology": .15}, "AXTI": {"Photonics": .80, "Semiconductors": .20},
    "NBIS": {"Neocloud": .70, "Robotics & AI": .30},
    "AMZN": {"Consumer Discretionary": .55, "Neocloud": .25, "Technology": .20},
    "GOOGL": {"Communication Services": .55, "Robotics & AI": .25, "Technology": .20},
}


def _theme_text(themes) -> str:
    if isinstance(themes, dict):
        values=[]
        for k,v in themes.items():
            values.append(str(k))
            if isinstance(v,(str,int,float,bool)): values.append(str(v))
            elif isinstance(v,list): values.extend(map(str,v))
        return " ".join(values).lower()
    if isinstance(themes,list): return " ".join(map(str,themes)).lower()
    return str(themes or "").lower()


def rotation_exposures(symbol: str, sector: str | None, industry: str | None, themes=None) -> tuple[dict[str,float], str]:
    s=(symbol or "").upper()
    if s in SYMBOL_EXPOSURES:
        return dict(SYMBOL_EXPOSURES[s]), "symbol_weighted_override"
    text=" ".join([str(industry or ""),_theme_text(themes)]).lower()
    matched=[]
    for keywords,proxy in KEYWORD_PROXIES:
        if any(k in text for k in keywords): matched.append(proxy)
    if matched:
        uniq=list(dict.fromkeys(matched))[:2]
        if len(uniq)==1: return {uniq[0]:1.0}, "industry_or_theme"
        return {uniq[0]:.65,uniq[1]:.35}, "industry_or_theme_weighted"
    if sector in SECTOR_PROXY_NAME: return {SECTOR_PROXY_NAME[sector]:1.0}, "sector"
    return {}, "unmapped"


def rotation_proxy_name(symbol: str, sector: str | None, industry: str | None, themes=None) -> tuple[str | None,str]:
    exposures,basis=rotation_exposures(symbol,sector,industry,themes)
    if not exposures:return None,basis
    return max(exposures,key=exposures.get),basis


def blend_rotation_context(rotation: dict, symbol: str, sector: str | None, industry: str | None, themes=None) -> dict:
    exposures,basis=rotation_exposures(symbol,sector,industry,themes)
    by_name={str(x.get("name") or ""):x for x in rotation.get("rows",[])}
    used=[];weight_sum=0.0;pressure=0.0;conviction=0.0
    for name,w in exposures.items():
        row=by_name.get(name)
        if not row: continue
        used.append({"name":name,"weight":w,"state":row.get("state"),"pressure":row.get("rotation_pressure"),"conviction":row.get("conviction")})
        weight_sum+=w;pressure+=float(row.get("rotation_pressure") or 0)*w;conviction+=float(row.get("conviction") or 0)*w
    if not used:return {"basis":basis,"exposures":exposures,"components":[],"rotation_pressure":0.0,"conviction":0.0,"state":"unmapped","transition_ready":False}
    pressure/=weight_sum;conviction/=weight_sum
    dominant=max(used,key=lambda x:x["weight"])
    return {"basis":basis,"exposures":exposures,"components":used,"rotation_pressure":round(pressure,3),"conviction":round(conviction,1),"state":dominant.get("state"),"transition_ready":all((by_name.get(x["name"]) or {}).get("transition_ready",False) for x in used),"dominant_proxy":dominant["name"]}
