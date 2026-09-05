from datetime import datetime, timezone
import re

import httpx

BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
SOURCE_URL = "https://www.gdeltproject.org/"

TOPICS = {
    "AI & Semiconductors": ["ai", "artificial intelligence", "semiconductor", "chip", "nvidia", "memory", "data center"],
    "Rates & Central Banks": ["fed", "federal reserve", "central bank", "interest rate", "yield", "ecb", "boj"],
    "Energy & Commodities": ["oil", "crude", "gas", "energy", "gold", "copper", "commodity"],
    "Trade & Geopolitics": ["tariff", "trade", "sanction", "war", "china", "russia", "iran", "export"],
    "Economy & Inflation": ["inflation", "jobs", "employment", "gdp", "economy", "recession", "consumer"],
    "Markets & Earnings": ["stock", "stocks", "market", "nasdaq", "s&p", "earnings", "guidance"],
}

SECTOR_HINTS = {
    "Technology": ["technology", "software", "semiconductor", "chip", "ai", "data center"],
    "Energy": ["oil", "gas", "energy", "crude"],
    "Financials": ["bank", "financial", "credit", "lending"],
    "Industrials": ["industrial", "manufacturing", "aerospace", "defense", "transport"],
    "Healthcare": ["healthcare", "pharma", "biotech", "drug"],
    "Consumer": ["consumer", "retail", "spending"],
    "Materials": ["materials", "copper", "gold", "mining", "steel"],
}


class GdeltError(RuntimeError):
    pass


def _normalize_title(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())
    stop = {"the", "a", "an", "to", "of", "in", "on", "for", "and", "with", "as", "at", "from"}
    return " ".join(word for word in words if word not in stop)[:180]


def _classify(title: str) -> tuple[list[str], list[str], int, str]:
    text = title.lower()
    topics = [name for name, keys in TOPICS.items() if any(key in text for key in keys)]
    sectors = [name for name, keys in SECTOR_HINTS.items() if any(key in text for key in keys)]
    score = 35 + min(len(topics) * 15, 30) + min(len(sectors) * 10, 20)
    if any(key in text for key in ["fed", "tariff", "inflation", "earnings", "oil", "semiconductor", "war"]):
        score += 10
    score = min(score, 100)
    if sectors:
        why = f"Potential market impact through {', '.join(sectors[:2])}."
    elif topics:
        why = f"Relevant to {topics[0].lower()} and broader risk pricing."
    else:
        why = "Potentially relevant to global market risk or economic expectations."
    return topics or ["General"], sectors, score, why


class GdeltProvider:
    name = "GDELT"

    def search(self, query: str, max_records: int = 25, timespan: str = "24h") -> dict:
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "sort": "datedesc",
            "maxrecords": max(1, min(max_records * 2, 75)),
            "timespan": timespan,
        }

        with httpx.Client(timeout=25.0) as client:
            response = client.get(BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()

        articles = []
        seen_urls = set()
        seen_titles = set()
        for item in data.get("articles", []):
            url = item.get("url")
            title = item.get("title")
            if not url or not title or url in seen_urls:
                continue
            normalized = _normalize_title(title)
            if not normalized or normalized in seen_titles:
                continue
            seen_urls.add(url)
            seen_titles.add(normalized)
            topics, sectors, relevance_score, why_it_matters = _classify(title)
            articles.append(
                {
                    "title": title,
                    "url": url,
                    "domain": item.get("domain"),
                    "source_country": item.get("sourcecountry"),
                    "language": item.get("language"),
                    "published_at": item.get("seendate"),
                    "image_url": item.get("socialimage"),
                    "topics": topics,
                    "sectors": sectors,
                    "relevance_score": relevance_score,
                    "why_it_matters": why_it_matters,
                }
            )
            if len(articles) >= max_records:
                break

        return {
            "provider": self.name,
            "source_url": SOURCE_URL,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "articles": articles,
        }
