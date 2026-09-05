from datetime import datetime, timezone
import time

import httpx

BASE_URL = "https://www.macroradar.io/api/v1/calendar"
SOURCE_URL = "https://www.macroradar.io/developers"
_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_TTL_SECONDS = 21600


def _event_title(item: dict) -> str:
    for key in ("title", "name", "event", "release_name", "series_name", "label", "description"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    kind = item.get("kind") or item.get("type") or item.get("category") or "Macro event"
    return str(kind)


def _event_url(item: dict) -> str | None:
    for key in ("source_url", "url", "canonical_url", "document_url", "link"):
        value = item.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None


def macro_calendar(start_date: str, end_date: str) -> dict:
    key = f"{start_date}:{end_date}"
    cached = _CACHE.get(key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        response = client.get(BASE_URL, params={"from": start_date, "to": end_date}, headers={"User-Agent": "DailyReportApp/1.2"})
        response.raise_for_status()
        payload = response.json()

    raw = payload.get("data", []) if isinstance(payload, dict) else []
    if isinstance(raw, dict):
        raw = raw.get("events") or raw.get("items") or raw.get("calendar") or []
    events = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        event_date = str(item.get("event_date") or item.get("date") or "")[:10]
        if not event_date:
            continue
        events.append({
            "event_date": event_date,
            "title": _event_title(item),
            "category": item.get("category") or item.get("kind") or item.get("type"),
            "source_url": _event_url(item),
            "published_at": item.get("published_at"),
        })

    result = {
        "provider": "MacroRadar",
        "source_url": SOURCE_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "events": events,
    }
    _CACHE[key] = (time.time(), result)
    return result
