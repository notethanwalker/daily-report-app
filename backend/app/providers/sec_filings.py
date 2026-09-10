from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import httpx

from .sec_companyfacts import _ticker_map

SUBMISSIONS_ROOT = "https://data.sec.gov/submissions"
SOURCE_ROOT = "https://www.sec.gov/edgar/browse/"
_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_SECONDS = 6 * 60 * 60
TRACKED_FORMS = {"8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A", "20-F", "20-F/A", "6-K"}


def _headers():
    return {
        "User-Agent": os.getenv("SEC_USER_AGENT", "DailyReportApp/1.9 market-research"),
        "Accept-Encoding": "gzip, deflate",
    }


class SecFilingsProvider:
    name = "SEC EDGAR"

    def recent(self, symbol: str, limit: int = 12) -> dict:
        s = symbol.strip().upper()
        cached = _CACHE.get(s)
        if cached and time.time() - cached[0] < CACHE_SECONDS:
            return {**cached[1]}
        cik = _ticker_map().get(s)
        if not cik:
            raise RuntimeError(f"SEC ticker mapping unavailable for {s}")
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            response = client.get(f"{SUBMISSIONS_ROOT}/CIK{cik}.json", headers=_headers())
            response.raise_for_status()
            payload = response.json()
        recent = ((payload.get("filings") or {}).get("recent") or {})
        forms = list(recent.get("form") or [])
        accession = list(recent.get("accessionNumber") or [])
        filed = list(recent.get("filingDate") or [])
        primary = list(recent.get("primaryDocument") or [])
        descriptions = list(recent.get("primaryDocDescription") or [])
        items = []
        for idx, form in enumerate(forms):
            if str(form) not in TRACKED_FORMS:
                continue
            accession_no = str(accession[idx]) if idx < len(accession) else ""
            accession_path = accession_no.replace("-", "")
            doc = str(primary[idx]) if idx < len(primary) else ""
            source_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{doc}" if accession_path and doc else f"{SOURCE_ROOT}?CIK={int(cik)}"
            items.append({
                "form": str(form),
                "filed_at": str(filed[idx])[:10] if idx < len(filed) else None,
                "accession_number": accession_no or None,
                "description": str(descriptions[idx]) if idx < len(descriptions) and descriptions[idx] else None,
                "source_url": source_url,
                "provider": self.name,
            })
            if len(items) >= max(1, min(limit, 25)):
                break
        result = {
            "symbol": s,
            "cik": cik,
            "company_name": payload.get("name"),
            "filings": items,
            "provider": self.name,
            "source_url": f"{SOURCE_ROOT}?CIK={int(cik)}",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "policy": "Recent SEC submissions are event context only; form type alone is not interpreted as bullish or bearish.",
        }
        _CACHE[s] = (time.time(), result)
        return {**result}
