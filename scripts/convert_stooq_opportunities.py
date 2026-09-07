#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_TAIL = 260
MIN_BARS = 220
FORMAT = "daily-report-stooq-opportunities-v1"


def number(v):
    try:
        if v in (None, "", "N/D"):
            return None
        return float(v)
    except Exception:
        return None


def parse_date(raw: str) -> str | None:
    s = str(raw or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) >= 10 and s[4:5] == "-":
        return s[:10]
    return None


def archive_symbol(member_name: str) -> str | None:
    leaf = Path(member_name).name.lower()
    if not leaf.endswith(".txt"):
        return None
    symbol = leaf[:-4]
    if symbol.endswith(".us"):
        symbol = symbol[:-3]
    symbol = symbol.strip().upper()
    return symbol or None


def is_plausible_equity_symbol(symbol: str) -> bool:
    if not symbol or len(symbol) > 12:
        return False
    if any(token in symbol for token in ("^", "/", "=", "#")):
        return False
    if symbol.endswith((".W", ".U", ".R")):
        return False
    return bool(re.fullmatch(r"[A-Z0-9.-]+", symbol))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_rows_from_member(zf: zipfile.ZipFile, name: str):
    with zf.open(name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        reader = csv.DictReader(text)
        for row in reader:
            dt = parse_date(row.get("<DATE>") or row.get("DATE"))
            close = number(row.get("<CLOSE>") or row.get("CLOSE"))
            if not dt or close is None:
                continue
            yield {
                "date": dt,
                "open": number(row.get("<OPEN>") or row.get("OPEN")),
                "high": number(row.get("<HIGH>") or row.get("HIGH")),
                "low": number(row.get("<LOW>") or row.get("LOW")),
                "close": close,
                "volume": number(row.get("<VOL>") or row.get("VOL")) or 0.0,
            }


def main():
    p = argparse.ArgumentParser(description="Convert Stooq d_us_txt.zip into a compact Daily Report Opportunities package.")
    p.add_argument("input_zip", type=Path, help="Path to Stooq d_us_txt.zip")
    p.add_argument("-o", "--output", type=Path, default=Path("stooq_opportunities_package.zip"))
    p.add_argument("--tail", type=int, default=DEFAULT_TAIL, help="Daily OHLCV bars retained per symbol (default: 260)")
    p.add_argument("--min-bars", type=int, default=MIN_BARS, help="Minimum usable bars (default: 220)")
    args = p.parse_args()

    src = args.input_zip.resolve()
    out = args.output.resolve()
    if not src.exists():
        raise SystemExit(f"Input ZIP not found: {src}")
    if args.tail < 220:
        raise SystemExit("--tail must be at least 220 so MA200 and opportunity technicals remain available")
    if args.min_bars < 120 or args.min_bars > args.tail:
        raise SystemExit("--min-bars must be between 120 and --tail")

    print(f"Hashing source archive: {src.name}")
    src_sha = sha256_file(src)
    symbol_count = 0
    skipped = 0
    latest_date = None
    earliest_date = None

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as source_zip, zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output_zip:
        members = [n for n in source_zip.namelist() if n.lower().endswith(".txt")]
        with output_zip.open("symbols.ndjson", "w") as ndjson:
            for idx, name in enumerate(members, 1):
                symbol = archive_symbol(name)
                if not symbol or not is_plausible_equity_symbol(symbol):
                    skipped += 1
                    continue

                tail = deque(maxlen=args.tail)
                all_time_high = None
                history_start = None
                usable = 0
                for row in iter_rows_from_member(source_zip, name):
                    usable += 1
                    if history_start is None:
                        history_start = row["date"]
                    high = row.get("high")
                    if high is not None:
                        all_time_high = high if all_time_high is None else max(all_time_high, high)
                    tail.append(row)

                if usable < args.min_bars or len(tail) < args.min_bars:
                    skipped += 1
                    continue

                rows = list(tail)
                latest = rows[-1]["date"]
                latest_date = latest if latest_date is None or latest > latest_date else latest_date
                if history_start:
                    earliest_date = history_start if earliest_date is None or history_start < earliest_date else earliest_date

                record = {
                    "symbol": symbol,
                    "history_start_date": history_start,
                    "all_time_high": all_time_high,
                    "rows": rows,
                }
                ndjson.write((json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8"))
                symbol_count += 1

                if idx % 500 == 0:
                    print(f"Processed {idx:,}/{len(members):,} files; retained {symbol_count:,} symbols")

        manifest = {
            "format": FORMAT,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_archive_name": src.name,
            "source_archive_sha256": src_sha,
            "source_archive_bytes": src.stat().st_size,
            "tail_sessions": args.tail,
            "minimum_bars": args.min_bars,
            "symbols": symbol_count,
            "skipped_members": skipped,
            "archive_latest_bar_date": latest_date,
            "archive_history_start_date": earliest_date,
            "notes": "Stooq canonical package: latest OHLCV tail per symbol plus full-history ATH metadata. Nasdaq/common-stock and liquidity filtering occurs server-side.",
        }
        output_zip.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")))

    print("\nConversion complete")
    print(f"Input:  {src} ({src.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"Output: {out} ({out.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"Symbols retained: {symbol_count:,}")
    print(f"Latest bar date: {latest_date}")
    print(f"Source SHA-256: {src_sha}")
    print("\nUpload the generated stooq_opportunities_package.zip to the owner Stooq archive control in Market Opportunities.")


if __name__ == "__main__":
    main()
