from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Iterable

MODEL_VERSION = "world-news-synthesis-v4.1"

TAXONOMY = {
    "monetary_policy": ("fed", "federal reserve", "ecb", "boj", "central bank", "interest rate", "rate cut", "rate hike", "yield"),
    "inflation_growth": ("inflation", "cpi", "ppi", "gdp", "jobs", "employment", "recession", "economy", "consumer", "growth"),
    "geopolitics_security": ("war", "military", "conflict", "sanction", "russia", "ukraine", "iran", "israel", "taiwan", "defense"),
    "energy_commodities": ("oil", "crude", "natural gas", "energy", "opec", "gold", "copper", "uranium", "commodity", "commodities"),
    "trade_supply_chain": ("tariff", "trade", "export", "import", "supply chain", "shipping", "port", "restriction", "embargo"),
    "fiscal_regulatory": ("tax", "budget", "deficit", "fiscal", "regulation", "regulator", "antitrust", "subsidy", "government spending"),
    "technology_industrial_policy": ("artificial intelligence", " ai ", "semiconductor", "chip", "memory", "data center", "industrial policy", "nvidia"),
    "fx_rates_credit": ("dollar", "yen", "euro", "currency", "forex", "bond", "treasury", "credit", "spread", "debt market"),
}

SYSTEMIC_TERMS = ("federal reserve", "central bank", "tariff", "sanction", "war", "oil", "inflation", "gdp", "semiconductor", "export", "treasury", "credit")

ENTITY_MAP = {
    "nvidia": {"tickers":["NVDA"], "themes":["AI infrastructure", "Semiconductors"], "sectors":["Technology", "Semiconductors"]},
    "micron": {"tickers":["MU"], "themes":["Memory", "AI infrastructure"], "sectors":["Technology", "Semiconductors"]},
    "memory": {"tickers":[], "themes":["Memory", "AI infrastructure"], "sectors":["Semiconductors"]},
    "semiconductor": {"tickers":["SMH"], "themes":["Semiconductors", "AI infrastructure"], "sectors":["Technology", "Semiconductors"]},
    "chip": {"tickers":["SMH"], "themes":["Semiconductors"], "sectors":["Technology", "Semiconductors"]},
    "data center": {"tickers":[], "themes":["AI infrastructure", "Data centers"], "sectors":["Technology", "Industrials"]},
    "uranium": {"tickers":[], "themes":["Nuclear"], "sectors":["Energy", "Nuclear"]},
    "nuclear": {"tickers":[], "themes":["Nuclear"], "sectors":["Energy", "Industrials"]},
    "oil": {"tickers":["XLE"], "themes":["Energy"], "sectors":["Energy"]},
    "crude": {"tickers":["XLE"], "themes":["Energy"], "sectors":["Energy"]},
    "gold": {"tickers":["GLD"], "themes":["Gold"], "sectors":["Materials"]},
    "copper": {"tickers":[], "themes":["Copper", "Industrial metals"], "sectors":["Materials"]},
    "bank": {"tickers":["XLF"], "themes":["Financials"], "sectors":["Financials"]},
    "defense": {"tickers":["ITA"], "themes":["Defense"], "sectors":["Industrials", "Space / Defense"]},
}

EFFECTS = {
    "monetary_policy": {
        "first":["Changes in expected policy rates can reprice bond yields and equity discount rates.", "Rate-sensitive growth and financial assets can react first."],
        "second":["Persistent financing-cost changes can alter corporate investment, housing demand and credit creation.", "FX and global capital flows may adjust if policy differentials widen."],
    },
    "inflation_growth": {
        "first":["Inflation or growth surprises can move rate expectations, cyclicals and broad risk appetite.", "Bond yields and the dollar may transmit the surprise across asset classes."],
        "second":["Earnings expectations can change as demand, wages and input costs are repriced.", "Sector leadership may rotate between cyclicals, defensives and duration-sensitive growth."],
    },
    "geopolitics_security": {
        "first":["Risk premia can rise in directly exposed commodities, defense assets, currencies and regional markets.", "Safe-haven demand and volatility may increase if escalation risk is perceived as material."],
        "second":["Longer disruptions can alter trade routes, input costs, fiscal spending and corporate supply-chain decisions.", "Secondary sanctions or policy responses may broaden the affected asset set."],
    },
    "energy_commodities": {
        "first":["Commodity prices and producers are the most direct transmission channel.", "Large energy moves can feed inflation expectations and rate pricing."],
        "second":["Sustained input-cost changes can affect transportation, manufacturing margins and consumer purchasing power.", "Capital expenditure may rotate toward or away from extraction and infrastructure."],
    },
    "trade_supply_chain": {
        "first":["Directly exposed importers, exporters and constrained supply chains can reprice first.", "FX and commodity markets may react where trade balances or sourcing are material."],
        "second":["Companies may change sourcing, inventory and capital-spending plans, shifting costs across industries.", "Persistent restrictions can accelerate domestic capacity investment or substitution."],
    },
    "fiscal_regulatory": {
        "first":["Affected industries can reprice expected taxes, subsidies, compliance costs or government demand.", "Sovereign yields may respond if the policy materially changes expected borrowing."],
        "second":["Investment incentives and competitive structure may change as firms adapt to the policy.", "Second-order demand can spread through suppliers and adjacent industries."],
    },
    "technology_industrial_policy": {
        "first":["Semiconductors, AI infrastructure and directly named firms can react to changes in demand, access or policy support.", "Supplier and customer expectations may move with perceived capacity constraints."],
        "second":["Capital expenditure can shift across data centers, power, networking, memory and manufacturing equipment.", "Persistent policy or capacity changes can alter competitive positioning across the technology supply chain."],
    },
    "fx_rates_credit": {
        "first":["Currencies, sovereign bonds and credit spreads are the direct pricing channels.", "Rate-sensitive equities can react through discount-rate and funding-cost changes."],
        "second":["Financing conditions can alter refinancing, investment and default risk over time.", "Currency moves can change multinational revenue translation and import/export competitiveness."],
    },
    "general": {
        "first":["The immediate market channel is uncertain and should be confirmed by asset-price response."],
        "second":["Broader effects depend on persistence, policy response and transmission into earnings or financial conditions."],
    },
}

STOPWORDS={"the","a","an","to","of","in","on","for","and","with","as","at","from","by","after","over","amid","new","says","say","will","could","may","its","is","are"}


def _text(article:dict)->str:
    return f" {str(article.get('title') or '').lower()} "


def classify_article(article:dict)->list[str]:
    text=_text(article);scores=[]
    for category,terms in TAXONOMY.items():
        n=sum(1 for term in terms if term in text)
        if n:scores.append((n,category))
    scores.sort(key=lambda x:(-x[0],x[1]))
    return [category for _,category in scores] or ["general"]


def map_exposure(article:dict)->dict:
    text=_text(article);tickers=set();themes=set();sectors=set();matched=[]
    for term,mapping in ENTITY_MAP.items():
        if term in text:
            matched.append(term);tickers.update(mapping["tickers"]);themes.update(mapping["themes"]);sectors.update(mapping["sectors"])
    sectors.update(str(x) for x in (article.get("sectors") or []) if x)
    return {
        "tickers":sorted(tickers),"themes":sorted(themes),"sectors":sorted(sectors),"matched_terms":matched,
        "mapping_basis":"headline_keyword_and_provider_sector_hints" if matched or sectors else "none",
        "causal_confidence":"association_only" if matched or sectors else "unmapped",
    }


def _published(article:dict)->datetime|None:
    raw=article.get("published_at")
    if not raw:return None
    text=str(raw).strip().replace("Z","+00:00")
    for value in (text, text.replace(" ","T")):
        try:
            dt=datetime.fromisoformat(value)
            if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:pass
    # RFC-style dates from the Google RSS fallback.
    try:
        from email.utils import parsedate_to_datetime
        dt=parsedate_to_datetime(text)
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:return None


def importance_score(article:dict,now:datetime|None=None)->float:
    now=now or datetime.now(timezone.utc);base=float(article.get("relevance_score") or 35);published=_published(article)
    age_hours=max(0.0,(now-published).total_seconds()/3600) if published else 72.0
    recency=max(0.0,20.0-min(age_hours,168.0)/168.0*20.0)
    text=_text(article);systemic=min(15.0,sum(1 for x in SYSTEMIC_TERMS if x in text)*4.0)
    categories=classify_article(article);breadth=min(10.0,max(0,len(categories)-1)*3.0+len(article.get("sectors") or [])*2.0)
    return round(min(100.0,base*.55+recency+systemic+breadth),1)


def _tokens(title:str)->set[str]:
    return {w for w in re.findall(r"[a-z0-9]+",title.lower()) if len(w)>2 and w not in STOPWORDS}


def _similar(a:set[str],b:set[str])->float:
    return len(a&b)/max(1,len(a|b))


def _cluster_articles(rows:list[dict])->list[dict]:
    clusters=[]
    for article in sorted(rows,key=lambda x:(_published(x) or datetime.min.replace(tzinfo=timezone.utc)),reverse=True):
        toks=_tokens(str(article.get("title") or ""));category=(article.get("macro_categories") or ["general"])[0];target=None
        for cluster in clusters:
            if cluster["category"]==category and _similar(toks,cluster["tokens"])>=.28:
                target=cluster;break
        if target is None:
            target={"category":category,"tokens":toks,"items":[]};clusters.append(target)
        target["items"].append(article);target["tokens"]|=toks
    out=[]
    for i,c in enumerate(clusters):
        items=sorted(c["items"],key=lambda x:(_published(x) or datetime.min.replace(tzinfo=timezone.utc)))
        domains=sorted({str(x.get("domain") or x.get("discovery_source") or "Unknown") for x in items})
        score=max(float(x.get("importance_score") or 0) for x in items)+min(8,max(0,len(domains)-1)*2)
        out.append({"story_id":f"story-{i+1}","category":c["category"],"headline":max(items,key=lambda x:float(x.get("importance_score") or 0)).get("title"),"importance_score":round(min(100,score),1),"article_count":len(items),"source_count":len(domains),"sources":domains,"timeline":[{"published_at":x.get("published_at"),"title":x.get("title"),"domain":x.get("domain"),"url":x.get("url")} for x in items]})
    return sorted(out,key=lambda x:x["importance_score"],reverse=True)


def synthesize_world_news(payload:dict)->dict:
    now=datetime.now(timezone.utc);rows=[]
    for article in payload.get("articles") or []:
        categories=classify_article(article);primary=categories[0];exposure=map_exposure(article);effects=EFFECTS.get(primary,EFFECTS["general"])
        rows.append({**article,"macro_categories":categories,"primary_category":primary,"importance_score":importance_score(article,now),"exposure_map":exposure,"first_order_effects":effects["first"],"second_order_effects":effects["second"],"effect_status":"hypothesis","effect_policy":"Effects are transmission hypotheses derived from the event category, not claims that the headline caused a price move."})
    rows.sort(key=lambda x:(float(x.get("importance_score") or 0),float(x.get("relevance_score") or 0)),reverse=True)
    stories=_cluster_articles(rows)
    counts={}
    for row in rows:
        for category in row["macro_categories"]:counts[category]=counts.get(category,0)+1
    return {**payload,"articles":rows,"stories":stories,"taxonomy_counts":counts,"synthesis_model":MODEL_VERSION,"synthesis_policy":"Importance combines provider relevance, recency, systemic terms and breadth. Exposure mappings are associations from headline/provider metadata. First- and second-order effects are explicitly hypothetical transmission paths and require market-data confirmation."}
