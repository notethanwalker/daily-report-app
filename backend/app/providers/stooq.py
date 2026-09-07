from __future__ import annotations

import csv
import hashlib
import os
import shutil
import tempfile
from collections import deque
from datetime import datetime, timezone
from io import StringIO, TextIOWrapper
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import httpx

BASE_URL = "https://stooq.com/q/d/l/"
SOURCE_URL = "https://stooq.com/"
DEFAULT_BULK_US_URL = "https://static.stooq.com/db/h/d_us_txt.zip"


class StooqError(RuntimeError):
    pass


class StooqInsufficientDiskError(StooqError):
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


def symbol_key(symbol: str) -> str:
    """Provider-neutral key for punctuation-only ticker differences (BRK.B vs BRK-B)."""
    return "".join(ch for ch in symbol.upper() if ch.isalnum())


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


def _bulk_urls() -> list[str]:
    configured = os.getenv("STOOQ_US_BULK_URLS") or os.getenv("STOOQ_US_BULK_URL") or DEFAULT_BULK_US_URL
    urls = []
    for raw in configured.split(","):
        url = raw.strip()
        if url and url not in urls:
            urls.append(url)
    if DEFAULT_BULK_US_URL not in urls:
        urls.append(DEFAULT_BULK_US_URL)
    return urls


class StooqProvider:
    name = "Stooq"

    def __init__(self):
        self.last_bulk_metadata: dict = {}

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

    def _temp_dir(self) -> str:
        configured = os.getenv("MARKET_BULK_TEMP_DIR")
        if configured:
            os.makedirs(configured, exist_ok=True)
            return configured
        return tempfile.gettempdir()

    def _validate_archive(self, path: str) -> dict:
        min_files = int(os.getenv("STOOQ_BULK_MIN_DATA_FILES", "1000"))
        try:
            with ZipFile(path) as zf:
                names = [name for name in zf.namelist() if name.lower().endswith(".txt")]
                if len(names) < min_files:
                    raise StooqError(f"Stooq bulk archive contained only {len(names)} data files")
                # Opening representative members catches corrupt central-directory/member metadata
                # without decompressing the entire archive twice.
                for name in (names[0], names[len(names) // 2], names[-1]):
                    with zf.open(name) as handle:
                        sample = handle.read(512)
                        if not sample:
                            raise StooqError("Stooq bulk archive contained an empty data member")
                return {"data_files": len(names)}
        except BadZipFile as exc:
            raise StooqError("Stooq bulk download was not a valid ZIP archive") from exc

    def download_us_bulk_archive(self) -> str:
        """Safely stream a bulk archive to ephemeral disk with mirror/fallback support."""
        temp_dir = self._temp_dir()
        reserve = int(os.getenv("MARKET_BULK_DISK_RESERVE_BYTES", str(128 * 1024 * 1024)))
        max_bytes = int(os.getenv("STOOQ_BULK_MAX_BYTES", str(2 * 1024 * 1024 * 1024)))
        min_bytes = int(os.getenv("STOOQ_BULK_MIN_BYTES", str(10 * 1024 * 1024)))
        attempts = []
        last_error: Exception | None = None

        for url in _bulk_urls():
            fd, path = tempfile.mkstemp(prefix="stooq-us-", suffix=".zip", dir=temp_dir)
            os.close(fd)
            digest = hashlib.sha256()
            downloaded = 0
            try:
                free_before = shutil.disk_usage(temp_dir).free
                with httpx.Client(timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=True) as client:
                    with client.stream("GET", url, headers={"User-Agent": "daily-report-app/1.0"}) as response:
                        response.raise_for_status()
                        advertised = int(response.headers.get("content-length") or 0)
                        if advertised and advertised > max_bytes:
                            raise StooqError(f"Stooq archive advertised {advertised} bytes, above safety limit")
                        if advertised and free_before < advertised + reserve:
                            raise StooqInsufficientDiskError(
                                f"Bulk archive needs about {advertised + reserve} bytes including reserve; only {free_before} bytes are free"
                            )
                        with open(path, "wb") as out:
                            for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                                if not chunk:
                                    continue
                                downloaded += len(chunk)
                                if downloaded > max_bytes:
                                    raise StooqError("Stooq archive exceeded configured maximum size")
                                # When Content-Length is missing, retain the reserve dynamically.
                                if not advertised and shutil.disk_usage(temp_dir).free < len(chunk) + reserve:
                                    raise StooqInsufficientDiskError("Insufficient temporary disk while streaming Stooq archive")
                                digest.update(chunk)
                                out.write(chunk)
                if downloaded < min_bytes:
                    raise StooqError(f"Stooq archive was unexpectedly small ({downloaded} bytes)")
                validation = self._validate_archive(path)
                self.last_bulk_metadata = {
                    "url": url,
                    "bytes": downloaded,
                    "sha256": digest.hexdigest(),
                    "free_bytes_before": free_before,
                    "disk_reserve_bytes": reserve,
                    **validation,
                    "downloaded_at": datetime.now(timezone.utc).isoformat(),
                }
                return path
            except Exception as exc:
                last_error = exc
                attempts.append({"url": url, "error": str(exc)[:240]})
                try:
                    os.remove(path)
                except OSError:
                    pass
                if isinstance(exc, StooqInsufficientDiskError):
                    # Trying another mirror cannot fix local disk pressure.
                    break

        self.last_bulk_metadata = {"attempts": attempts, "failed_at": datetime.now(timezone.utc).isoformat()}
        if isinstance(last_error, StooqInsufficientDiskError):
            raise last_error
        raise StooqError("All configured Stooq bulk archive sources failed") from last_error

    def iter_us_bulk_history(self, archive_path: str, tail: int = 260):
        """Yield one symbol at a time, retaining only the requested tail in memory."""
        source_url = self.last_bulk_metadata.get("url") or DEFAULT_BULK_US_URL
        with ZipFile(archive_path) as zf:
            for name in zf.namelist():
                symbol = _archive_symbol(name)
                if not symbol:
                    continue
                rows = deque(maxlen=max(220, tail))
                try:
                    with zf.open(name) as raw, TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="") as text:
                        for item in csv.DictReader(text):
                            parsed = _parse_archive_row(item)
                            if parsed:
                                rows.append(parsed)
                except Exception:
                    continue
                if len(rows) < 220:
                    continue
                yield {
                    "symbol": symbol,
                    "rows": list(rows),
                    "provider": self.name,
                    "source_url": source_url,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
