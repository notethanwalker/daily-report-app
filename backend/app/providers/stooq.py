from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO

import httpx

BASE_URL = "https://stooq.com/q/d/l/"
SOURCE_URL = "https://stooq.com/"


class StooqError(RuntimeError):
    pass


def _number(value):
    try:
        if value in (None, "", "N/D"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _stooq_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    # Stooq's U.S. equity convention is lower-case SYMBOL.US.
    # Preserve explicit Stooq suffixes supplied by callers.
    return s.lower() if "." in s else f"{s.lower()}.us"


class StooqProvider:
    name = "Stooq"

    def daily_history(self, symbol: str) -> dict:
        s = symbol.strip().upper()
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(
                    BASE_URL,
                    params={"s": _stooq_symbol(s), "i": "d"},
                    headers={"User-Agent": "daily-report-app/1.0"},
                )
                response.raise_for_status()
                text = response.text
        except Exception as exc:
            raise StooqError(f"Stooq history request failed for {s}") from exc

        rows = []
        try:
            for row in csv.DictReader(StringIO(text)):
                dt = str(row.get("Date") or "")[:10]
                close = _number(row.get("Close"))
                if not dt or close is None:
                    continue
                rows.append({
                    "date": dt,
                    "open": _number(row.get("Open")),
                    "high": _number(row.get("High")),
                    "low": _number(row.get("Low")),
                    "close": close,
                    "volume": _number(row.get("Volume")) or 0.0,
                })
        except Exception as exc:
            raise StooqError(f"Stooq returned malformed history for {s}") from exc
        if len(rows) < 14:
            raise StooqError(f"Stooq returned insufficient history for {s}")
        rows.sort(key=lambda x: x["date"])
        return {
            "symbol": s,
            "rows": rows,
            "provider": self.name,
            "source_url": SOURCE_URL,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
