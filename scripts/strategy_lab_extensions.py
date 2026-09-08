"""Reusable quantitative-research utilities for Williams strategy development.

Includes local dataset caching/versioning, money-weighted return (XIRR), partial/hybrid
cash deployment, maximum-wait enforcement, moving-average/trend and relative-strength
filters, regime tagging, point-in-time universe filtering, and explicit train/holdout
splitting. These helpers are intentionally strategy-agnostic so they can be reused by
future Williams and non-Williams studies.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Callable

CACHE_DIR = Path('.cache/market_data')


def dataset_hash(rows: list[dict]) -> str:
    payload = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest()


def save_cached_history(symbol: str, rows: list[dict], source: str) -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        'symbol': symbol.upper(),
        'source': source,
        'row_count': len(rows),
        'first_date': rows[0]['date'] if rows else None,
        'last_date': rows[-1]['date'] if rows else None,
        'sha256': dataset_hash(rows),
        'rows': rows,
    }
    (CACHE_DIR / f'{symbol.upper()}.json').write_text(json.dumps(meta), encoding='utf-8')
    return meta


def load_cached_history(symbol: str) -> dict | None:
    path = CACHE_DIR / f'{symbol.upper()}.json'
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('sha256') != dataset_hash(data.get('rows') or []):
        raise RuntimeError(f'Cache hash mismatch for {symbol}')
    return data


def xirr(cashflows: list[tuple[str, float]], guess: float = 0.1) -> float | None:
    """Annualized money-weighted return. Contributions should be negative; terminal value positive."""
    if not cashflows or not any(v < 0 for _, v in cashflows) or not any(v > 0 for _, v in cashflows):
        return None
    flows = [(date.fromisoformat(d), float(v)) for d, v in cashflows]
    t0 = flows[0][0]

    def f(rate: float) -> float:
        if rate <= -0.999999:
            return float('inf')
        return sum(v / ((1.0 + rate) ** (((d - t0).days) / 365.2425)) for d, v in flows)

    lo, hi = -0.9999, 10.0
    flo, fhi = f(lo), f(hi)
    while flo * fhi > 0 and hi < 1_000_000:
        hi *= 2
        fhi = f(hi)
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < 1e-9:
            return mid
        if flo * fm <= 0:
            hi = mid
            fhi = fm
        else:
            lo = mid
            flo = fm
    return (lo + hi) / 2


def moving_average_map(rows: list[dict], window: int) -> dict[str, float | None]:
    closes = []
    out = {}
    for r in rows:
        closes.append(float(r['close']))
        out[r['date']] = sum(closes[-window:]) / window if len(closes) >= window else None
    return out


def rising_ma_filter(rows: list[dict], window: int = 200, slope_lookback: int = 20) -> dict[str, bool]:
    ma = moving_average_map(rows, window)
    dates = [r['date'] for r in rows]
    out = {}
    for i, r in enumerate(rows):
        cur = ma[r['date']]
        old = ma[dates[i - slope_lookback]] if i >= slope_lookback else None
        out[r['date']] = bool(cur is not None and old is not None and r['close'] > cur and cur > old)
    return out


def relative_strength_filter(asset_rows: list[dict], benchmark_rows: list[dict], lookback: int = 63) -> dict[str, bool]:
    bench = {r['date']: r for r in benchmark_rows}
    common = [(r, bench[r['date']]) for r in asset_rows if r['date'] in bench]
    out = {r['date']: False for r in asset_rows}
    for i in range(lookback, len(common)):
        a, b = common[i]
        a0, b0 = common[i-lookback]
        ar = a['close'] / a0[0]['close'] - 1
        br = b['close'] / b0[1]['close'] - 1
        out[a['date']] = ar > br
    return out


def regime_tags(rows: list[dict]) -> dict[str, str]:
    ma200 = moving_average_map(rows, 200)
    out = {}
    for r in rows:
        ma = ma200[r['date']]
        if ma is None:
            out[r['date']] = 'unclassified'
        elif r['close'] >= ma:
            out[r['date']] = 'above_200ma'
        else:
            out[r['date']] = 'below_200ma'
    return out


def deploy_fraction_for_williams(wr: float, ladder: tuple[tuple[float, float], ...] = ((-60, .25), (-70, .25), (-80, .50))) -> float:
    """Cumulative desired deployment fraction for a Williams value."""
    total = 0.0
    for threshold, fraction in ladder:
        if wr <= threshold:
            total += fraction
    return min(1.0, max(0.0, total))


def hybrid_monthly_allocation(monthly_contribution: float, immediate_fraction: float = .5) -> tuple[float, float]:
    """Split each contribution into immediate DCA and Williams-reserve cash."""
    immediate_fraction = min(1.0, max(0.0, immediate_fraction))
    return monthly_contribution * immediate_fraction, monthly_contribution * (1 - immediate_fraction)


def max_wait_due(contribution_month: str, current_month: str, max_wait_months: int) -> bool:
    cy, cm = map(int, contribution_month.split('-'))
    ny, nm = map(int, current_month.split('-'))
    age = (ny * 12 + nm) - (cy * 12 + cm)
    return age >= max_wait_months


def point_in_time_universe(records: list[dict], as_of: str) -> list[str]:
    """Filter listing-status records containing symbol, ipo_date/listing_date and optional delisting_date."""
    out = []
    for r in records:
        symbol = r.get('symbol')
        start = r.get('ipo_date') or r.get('listing_date') or '0001-01-01'
        end = r.get('delisting_date') or '9999-12-31'
        if symbol and start <= as_of <= end:
            out.append(symbol.upper())
    return sorted(set(out))


def train_holdout_split(rows: list[dict], holdout_start: str) -> tuple[list[dict], list[dict]]:
    train = [r for r in rows if r['date'] < holdout_start]
    holdout = [r for r in rows if r['date'] >= holdout_start]
    if not train or not holdout:
        raise ValueError('Both train and holdout sets must be non-empty')
    return train, holdout


def walk_forward_boundaries(start_year: int, end_year: int, train_years: int = 4, test_years: int = 1) -> list[dict]:
    out = []
    y = start_year
    while y + train_years + test_years - 1 <= end_year:
        out.append({
            'train_start': f'{y}-01-01',
            'train_end': f'{y + train_years - 1}-12-31',
            'test_start': f'{y + train_years}-01-01',
            'test_end': f'{y + train_years + test_years - 1}-12-31',
        })
        y += test_years
    return out
