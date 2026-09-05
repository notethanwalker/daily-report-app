from datetime import datetime, timezone

import httpx

BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
SOURCE_URL = "https://www.gdeltproject.org/"


class GdeltError(RuntimeError):
    pass


class GdeltProvider:
    name = "GDELT"

    def search(self, query: str, max_records: int = 25, timespan: str = "24h") -> dict:
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "sort": "datedesc",
            "maxrecords": max(1, min(max_records, 75)),
            "timespan": timespan,
        }

        with httpx.Client(timeout=25.0) as client:
            response = client.get(BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()

        articles = []
        seen_urls = set()
        for item in data.get("articles", []):
            url = item.get("url")
            title = item.get("title")
            if not url or not title or url in seen_urls:
                continue
            seen_urls.add(url)
            articles.append(
                {
                    "title": title,
                    "url": url,
                    "domain": item.get("domain"),
                    "source_country": item.get("sourcecountry"),
                    "language": item.get("language"),
                    "published_at": item.get("seendate"),
                    "image_url": item.get("socialimage"),
                }
            )

        return {
            "provider": self.name,
            "source_url": SOURCE_URL,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "articles": articles,
        }
