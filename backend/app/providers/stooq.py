from __future__ import annotations

import csv
import os
import tempfile
from collections import deque
from datetime import datetime, timezone
from io import StringIO, TextIOWrapper
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import httpx

BASE_URL = "https://stooq.com/q/d/l/"
SOURCE_URL = "https://stooq.com/"
BULK_US_URL = os.getenv("STOOQ_US_BULK_URL", "https://static.stooq.com/db/h/d_us_txt.zip")


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
    return s.lower() if "." in s else f"{s.lower()}.us"


def _archive_symbol(name: str) -> str | None:
    leaf = Path(name).name.lower()
    if not leaf.endswith(".txt"):
        return None
    symbol = leaf[:-4]
    if symbol.endswith(".us"):
        symbol = symbol[:-3]
    symbol = symbol.strip().upper()
    return symbol or None


def _parse_archive_row(row: dict) -> dict | None:
    dt = str(row.get("<DATE>") or row.get("DATE") or "").strip()
    if len(dt) == 8 and dt.isdigit():
        dt = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
    close = _number(row.get("<CLOSE>") or row.get("CLOSE"))
    if not dt or close is None:
        return None
    return {
        "date": dt[:10],
        "open": _number(row.get("<OPEN>") or row.get("OPEN")),
        "high": _number(row.get("<HIGH>") or row.get("HIGH")),
        "low": _number(row.get("<LOW>") or row.get("LOW")),
        "close": close,
        "volume": _number(row.get("<VOL>") or row.get("VOL")) or 0.0,
    }


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

    def download_us_bulk_archive(self) -> str:
        """Stream the Stooq U.S. daily archive to disk instead of holding ~500MB in RAM."""
        fd, path = tempfile.mkstemp(prefix="stooq-us-", suffix=".zip")
        os.close(fd)
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=True) as client:
                with client.stream("GET", BULK_US_URL, headers={"User-Agent": "daily-report-app/1.0"}) as response:
                    response.raise_for_status()
                    with open(path, "wb") as out:
                        for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                            out.write(chunk)
            try:
                with ZipFile(path) as zf:
                    if not zf.testzip() is None:
                        raise StooqError("Stooq bulk archive failed ZIP integrity check")
            except BadZipFile as exc:
                raise StooqError("Stooq bulk download was not a valid ZIP archive") from exc
            return path
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise

    def iter_us_bulk_history(self, archive_path: str, tail: int = 260):
        """Yield one symbol at a time, retaining only the requested tail in memory."""
        with ZipFile(archive_path) as zf:
            for name in zf.namelist():
                symbol = _archive_symbol(name)
                if not symbol:
                    continue
                rows = deque(maxlen=max(200, tail))
                try:
                    with zf.open(name) as raw, TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="") as text:
                        for item in csv.DictReader(text):
                            parsed = _parse_archive_row(item)
                            if parsed:
                                rows.append(parsed)
                except Exception:
                    continue
                if len(rows) < 200:
                    continue
                yield {
                    "symbol": symbol,
                    "rows": list(rows),
                    "provider": self.name,
                    "source_url": BULK_US_URL,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
