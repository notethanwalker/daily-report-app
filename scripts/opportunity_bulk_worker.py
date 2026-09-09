#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

DEFAULT_API = "https://daily-report-api-ero2.onrender.com"
MIN_BARS = 120
UPLOAD_TAIL = 130
RETRYABLE_HTTP = {429, 500, 502, 503, 504}


def api_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    timeout: int = 120,
    attempts: int = 5,
) -> dict:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    last_error = None
    for attempt in range(1, max(1, attempts) + 1):
        request = urllib.request.Request(url, data=data, method=method)
        oidc = os.getenv("OPPORTUNITY_OIDC_TOKEN") or ""
        static = os.getenv("STOOQ_IMPORT_TOKEN") or ""
        if oidc:
            request.add_header("authorization", f"Bearer {oidc}")
        elif static:
            request.add_header("x-stooq-import-token", static)
        else:
            raise RuntimeError("No Opportunity ingest authentication is configured")
        if data is not None:
            request.add_header("content-type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in RETRYABLE_HTTP or attempt >= attempts:
                raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt >= attempts:
                raise
        delay = min(30, 2 ** attempt)
        print(f"API request retry {attempt}/{attempts} after {last_error}; sleeping {delay}s")
        time.sleep(delay)
    raise RuntimeError(f"API request failed: {last_error}")


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
                return frame[alias].copy()
            if alias in level1:
                return frame.xs(alias, axis=1, level=1).copy()
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
    if not all(k in columns for k in ("high", "low", "close")):
        return []
    out: list[dict] = []
    for idx, row in frame.iterrows():
        close = finite(row.get(columns["close"]))
        high = finite(row.get(columns["high"]))
        low = finite(row.get(columns["low"]))
        if close is None or high is None or low is None:
            continue
        date = getattr(idx, "date", lambda: idx)()
        volume_col = columns.get("volume")
        out.append({
            "date": str(date)[:10],
            "open": finite(row.get(columns.get("open"))) if columns.get("open") is not None else None,
            "high": high,
            "low": low,
            "close": close,
            "volume": finite(row.get(volume_col)) or 0.0 if volume_col is not None else 0.0,
        })
    return out


def fetch_chunk(
    symbols: list[str],
    *,
    period: str = "1y",
    min_bars: int = MIN_BARS,
) -> tuple[list[dict], list[dict]]:
    yahoo_symbols = [normalize_yahoo_symbol(s) for s in symbols]
    failures: list[dict] = []
    records: list[dict] = []
    try:
        frame = yf.download(
            " ".join(yahoo_symbols),
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            actions=False,
            threads=True,
            progress=False,
            timeout=25,
        )
    except Exception as exc:
        return [], [{"symbols": symbols[:10], "error": str(exc)[:200]}]

    for original in symbols:
        sub = frame_for_symbol(frame, normalize_yahoo_symbol(original), yahoo_symbols)
        rows = rows_from_frame(sub)
        if len(rows) < min_bars:
            failures.append({"symbol": original, "bars": len(rows)})
            continue
        records.append({"symbol": original, "rows": rows[-UPLOAD_TAIL:]})
    return records, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap and maintain Opportunity technical coverage from a GitHub runner.")
    parser.add_argument("--limit", type=int, default=250, help="Maximum target symbols to attempt this run")
    parser.add_argument("--download-chunk", type=int, default=15, help="Yahoo symbols per download request")
    parser.add_argument("--upload-batch", type=int, default=25, help="Records per API ingest request")
    parser.add_argument("--sleep", type=float, default=2.0, help="Pause between provider chunks")
    args = parser.parse_args()

    api_base = (os.getenv("DAILY_REPORT_API_BASE") or DEFAULT_API).rstrip("/")
    if not (os.getenv("OPPORTUNITY_OIDC_TOKEN") or os.getenv("STOOQ_IMPORT_TOKEN")):
        print("No secure Opportunity ingest authentication is configured.")
        return 3

    query = urllib.parse.urlencode({"limit": max(1, min(args.limit, 1000))})
    targets = api_json(f"{api_base}/api/v1/opportunities/bulk-missing?{query}")
    symbols = list(targets.get("symbols") or [])
    mode = str(targets.get("mode") or "bootstrap")
    period = "1mo" if mode == "refresh" else "1y"
    min_bars = 1 if mode == "refresh" else MIN_BARS
    print(json.dumps({
        "starting_coverage": targets.get("coverage"),
        "mode": mode,
        "target_count": len(symbols),
        "reference_date": targets.get("reference_date"),
        "wrapped": targets.get("wrapped"),
    }, indent=2))
    if not symbols:
        print("No Opportunity symbols require work in this cycle.")
        return 0

    pending: list[dict] = []
    failures: list[dict] = []
    accepted_total = rejected_total = 0
    final_coverage = targets.get("coverage")
    run_id = os.getenv("GITHUB_RUN_ID") or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    def upload(records: list[dict]) -> None:
        nonlocal accepted_total, rejected_total, final_coverage
        if not records:
            return
        result = api_json(
            f"{api_base}/api/v1/opportunities/bulk-ingest",
            method="POST",
            payload={
                "source": "Yahoo Finance via GitHub Actions",
                "source_url": "https://finance.yahoo.com/",
                "batch_id": f"gha-{run_id}-{mode}",
                "records": records,
            },
            timeout=180,
            attempts=5,
        )
        accepted_total += int(result.get("accepted") or 0)
        rejected_total += int(result.get("rejected") or 0)
        final_coverage = result.get("coverage") or final_coverage
        print(json.dumps({"ingest": {k: result.get(k) for k in (
            "accepted", "rejected", "bootstrap_updates", "refresh_updates", "coverage"
        )}}, indent=2))

    chunk_size = max(1, args.download_chunk)
    upload_size = max(1, args.upload_batch)
    for offset in range(0, len(symbols), chunk_size):
        chunk = symbols[offset:offset + chunk_size]
        records, failed = fetch_chunk(chunk, period=period, min_bars=min_bars)
        pending.extend(records)
        failures.extend(failed)
        print(f"provider chunk {offset // chunk_size + 1}: {len(records)} usable / {len(chunk)} ({mode})")

        while len(pending) >= upload_size:
            batch = pending[:upload_size]
            del pending[:upload_size]
            upload(batch)
        if offset + chunk_size < len(symbols):
            time.sleep(max(0.0, args.sleep))

    upload(pending)
    summary = {
        "mode": mode,
        "attempted": len(symbols),
        "accepted": accepted_total,
        "ingest_rejected": rejected_total,
        "provider_failures": len(failures),
        "failure_examples": failures[:20],
        "final_coverage": final_coverage,
    }
    print(json.dumps(summary, indent=2))
    return 0 if accepted_total or not symbols else 2


if __name__ == "__main__":
    raise SystemExit(main())
