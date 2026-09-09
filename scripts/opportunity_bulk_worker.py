#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

DEFAULT_API = "https://daily-report-api-ero2.onrender.com"


def api_json(url: str, token: str, *, method: str = "GET", payload: dict | None = None, timeout: int = 120) -> dict:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("x-stooq-import-token", token)
    if data is not None:
        request.add_header("content-type", "application/json")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def finite(value):
    try:
        number = float(value)
        return number if pd.notna(number) else None
    except (TypeError, ValueError):
        return None


def normalize_yahoo_symbol(symbol: str) -> str:
    return symbol.replace(".", "-")


def frame_for_symbol(frame: pd.DataFrame, symbol: str, requested: list[str]) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return None
    if isinstance(frame.columns, pd.MultiIndex):
        aliases = [symbol, normalize_yahoo_symbol(symbol)]
        level0 = set(str(x) for x in frame.columns.get_level_values(0))
        level1 = set(str(x) for x in frame.columns.get_level_values(1))
        for alias in aliases:
            if alias in level0:
                out = frame[alias].copy()
                return out
            if alias in level1:
                out = frame.xs(alias, axis=1, level=1).copy()
                return out
        if len(requested) == 1:
            try:
                return frame.droplevel(1, axis=1).copy()
            except Exception:
                return frame.copy()
        return None
    return frame.copy() if len(requested) == 1 else None


def rows_from_frame(frame: pd.DataFrame | None) -> list[dict]:
    if frame is None or frame.empty:
        return []
    columns = {str(c).lower(): c for c in frame.columns}
    required = ["high", "low", "close"]
    if not all(k in columns for k in required):
        return []
    out: list[dict] = []
    for idx, row in frame.iterrows():
        close = finite(row.get(columns["close"]))
        high = finite(row.get(columns["high"]))
        low = finite(row.get(columns["low"]))
        if close is None or high is None or low is None:
            continue
        date = getattr(idx, "date", lambda: idx)()
        out.append({
            "date": str(date)[:10],
            "open": finite(row.get(columns.get("open"))) if columns.get("open") is not None else None,
            "high": high,
            "low": low,
            "close": close,
            "volume": finite(row.get(columns.get("volume"))) or 0.0 if columns.get("volume") is not None else 0.0,
        })
    return out


def fetch_chunk(symbols: list[str]) -> tuple[list[dict], list[dict]]:
    yahoo_symbols = [normalize_yahoo_symbol(s) for s in symbols]
    failures: list[dict] = []
    records: list[dict] = []
    try:
        frame = yf.download(
            " ".join(yahoo_symbols),
            period="2y",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            actions=False,
            threads=True,
            progress=False,
            timeout=30,
        )
    except Exception as exc:
        return [], [{"symbols": symbols[:10], "error": str(exc)[:200]}]

    for original in symbols:
        sub = frame_for_symbol(frame, normalize_yahoo_symbol(original), yahoo_symbols)
        rows = rows_from_frame(sub)
        if len(rows) < 220:
            failures.append({"symbol": original, "bars": len(rows)})
            continue
        records.append({"symbol": original, "rows": rows[-260:]})
    return records, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill missing Opportunity technical coverage from a GitHub runner.")
    parser.add_argument("--limit", type=int, default=400, help="Maximum missing symbols to attempt this run")
    parser.add_argument("--download-chunk", type=int, default=40, help="Yahoo symbols per download request")
    parser.add_argument("--upload-batch", type=int, default=100, help="Records per API ingest request")
    parser.add_argument("--sleep", type=float, default=2.0, help="Pause between provider chunks")
    args = parser.parse_args()

    api_base = (os.getenv("DAILY_REPORT_API_BASE") or DEFAULT_API).rstrip("/")
    token = os.getenv("STOOQ_IMPORT_TOKEN") or ""
    if not token:
        print("STOOQ_IMPORT_TOKEN is not configured; refusing unauthenticated bulk ingest.")
        return 3

    query = urllib.parse.urlencode({"limit": max(1, min(args.limit, 1000))})
    missing = api_json(f"{api_base}/api/v1/opportunities/bulk-missing?{query}", token)
    symbols = list(missing.get("symbols") or [])
    print(json.dumps({"starting_coverage": missing.get("coverage"), "requested_missing": len(symbols)}, indent=2))
    if not symbols:
        print("No missing Opportunity symbols returned.")
        return 0

    all_records: list[dict] = []
    failures: list[dict] = []
    accepted_total = rejected_total = 0
    run_id = os.getenv("GITHUB_RUN_ID") or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    for offset in range(0, len(symbols), max(1, args.download_chunk)):
        chunk = symbols[offset:offset + max(1, args.download_chunk)]
        records, failed = fetch_chunk(chunk)
        all_records.extend(records)
        failures.extend(failed)
        print(f"provider chunk {offset // max(1, args.download_chunk) + 1}: {len(records)} usable / {len(chunk)}")

        while len(all_records) >= max(1, args.upload_batch):
            batch = all_records[:args.upload_batch]
            del all_records[:args.upload_batch]
            result = api_json(
                f"{api_base}/api/v1/opportunities/bulk-ingest",
                token,
                method="POST",
                payload={
                    "source": "Yahoo Finance via GitHub Actions",
                    "source_url": "https://finance.yahoo.com/",
                    "batch_id": f"gha-{run_id}",
                    "records": batch,
                },
                timeout=180,
            )
            accepted_total += int(result.get("accepted") or 0)
            rejected_total += int(result.get("rejected") or 0)
            print(json.dumps({"ingest": {k: result.get(k) for k in ("accepted", "rejected", "coverage")}}, indent=2))
        if offset + args.download_chunk < len(symbols):
            time.sleep(max(0.0, args.sleep))

    if all_records:
        result = api_json(
            f"{api_base}/api/v1/opportunities/bulk-ingest",
            token,
            method="POST",
            payload={
                "source": "Yahoo Finance via GitHub Actions",
                "source_url": "https://finance.yahoo.com/",
                "batch_id": f"gha-{run_id}",
                "records": all_records,
            },
            timeout=180,
        )
        accepted_total += int(result.get("accepted") or 0)
        rejected_total += int(result.get("rejected") or 0)
        final_coverage = result.get("coverage")
    else:
        final_coverage = None

    summary = {
        "attempted": len(symbols),
        "provider_usable": accepted_total + rejected_total,
        "accepted": accepted_total,
        "ingest_rejected": rejected_total,
        "provider_failures": len(failures),
        "failure_examples": failures[:20],
        "final_coverage": final_coverage,
    }
    print(json.dumps(summary, indent=2))
    return 0 if accepted_total else 2


if __name__ == "__main__":
    raise SystemExit(main())
