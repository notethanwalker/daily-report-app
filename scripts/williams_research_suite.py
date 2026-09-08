#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections import deque
from datetime import date
from pathlib import Path

from williams_timeline_backtest import fetch_history, williams, summary


def aggregate_monthly(rows: list[dict]) -> list[dict]:
    months: dict[str, list[dict]] = {}
    for r in rows:
        months.setdefault(r['date'][:7], []).append(r)
    out = []
    for key in sorted(months):
        rs = months[key]
        out.append({
            'date': rs[-1]['date'],
            'open': rs[0]['open'],
            'high': max(r['high'] for r in rs),
            'low': min(r['low'] for r in rs),
            'close': rs[-1]['close'],
            'volume': sum(r.get('volume') or 0 for r in rs),
            'month': key,
        })
    return out


def first_trading_days(rows: list[dict], start: str, end: str) -> dict[str, dict]:
    out = {}
    for r in rows:
        if start <= r['date'] <= end:
            out.setdefault(r['date'][:7], r)
    return out


def month_index(d: str) -> int:
    y, m = map(int, d[:7].split('-'))
    return y * 12 + m


def simulate_timeline(
    daily_rows: list[dict],
    signal_rows: list[dict],
    start: str,
    contribution_end: str,
    signal_end: str,
    valuation_price: float,
    threshold: float = -80.0,
    window: int = 14,
    contribution: float = 1000.0,
) -> dict:
    monthly_contribs = first_trading_days(daily_rows, start, contribution_end)
    contrib_by_date = {r['date']: k for k, r in monthly_contribs.items()}
    series = williams(signal_rows, window)

    cash = shares = invested = 0.0
    max_cash = 0.0
    triggers = []
    waiting = deque()

    events = []
    for month, r in monthly_contribs.items():
        events.append((r['date'], 0, 'contribution', {'month': month, 'row': r}))
    for i, r in enumerate(series):
        if r['date'] < start or r['date'] > signal_end:
            continue
        prev = series[i - 1].get('williams_r') if i > 0 else None
        cur = r.get('williams_r')
        if prev is not None and cur is not None and prev > threshold and cur <= threshold:
            events.append((r['date'], 1, 'trigger', {'row': r, 'prev': prev, 'cur': cur}))
    events.sort(key=lambda x: (x[0], x[1]))

    wait_months = []
    for dt, _, kind, payload in events:
        if kind == 'contribution':
            cash += contribution
            waiting.append((payload['month'], contribution))
            max_cash = max(max_cash, cash)
        elif cash > 0:
            r = payload['row']
            amount = cash
            bought = amount / r['close']
            shares += bought
            invested += amount
            trigger_month = r['date'][:7]
            while waiting:
                m, amt = waiting.popleft()
                wait_months.append(max(0, month_index(trigger_month) - month_index(m)))
            cash = 0.0
            triggers.append({
                'date': r['date'],
                'williams_r': payload['cur'],
                'prior_williams_r': payload['prev'],
                'close': r['close'],
                'amount': amount,
                'shares_bought': bought,
            })

    contributions = len(monthly_contribs) * contribution
    result = summary(contributions, invested, cash, shares, valuation_price)
    result.update({
        'trigger_count': len(triggers),
        'max_cash_waiting': round(max_cash, 2),
        'avg_wait_months': round(sum(wait_months) / len(wait_months), 3) if wait_months else None,
        'max_wait_months': max(wait_months) if wait_months else None,
        'triggers': triggers,
    })
    return result


def simulate_dca(daily_rows, start, contribution_end, valuation_price, contribution=1000.0):
    months = first_trading_days(daily_rows, start, contribution_end)
    shares = 0.0
    ledger = []
    for r in months.values():
        bought = contribution / r['close']
        shares += bought
        ledger.append({'date': r['date'], 'close': r['close'], 'shares_bought': bought})
    total = len(months) * contribution
    return {**summary(total, total, 0.0, shares, valuation_price), 'transactions': ledger}


def max_stock_drawdown(rows: list[dict], start: str, end: str) -> float | None:
    peak = None
    worst = 0.0
    for r in rows:
        if not (start <= r['date'] <= end):
            continue
        c = r['close']
        peak = c if peak is None else max(peak, c)
        if peak:
            worst = min(worst, c / peak - 1.0)
    return round(worst * 100, 3) if peak is not None else None


def forward_trigger_returns(signal_rows: list[dict], triggers: list[dict], horizons=(1, 3, 6)) -> dict:
    by_date = {r['date']: i for i, r in enumerate(signal_rows)}
    vals = {h: [] for h in horizons}
    # For monthly bars horizons are months; for daily bars caller may pass trading-day-equivalent horizons.
    for t in triggers:
        idx = by_date.get(t['date'])
        if idx is None:
            continue
        entry = signal_rows[idx]['close']
        for h in horizons:
            j = idx + h
            if j < len(signal_rows):
                vals[h].append(signal_rows[j]['close'] / entry - 1.0)
    return {
        str(h): round(100 * sum(v) / len(v), 3) if v else None
        for h, v in vals.items()
    }


def rolling_start_advantages(daily_rows, signal_rows, base_start, contribution_end, signal_end, valuation_price, threshold, window, contribution):
    starts = []
    first_year = int(base_start[:4])
    last_year = int(signal_end[:4]) - 2
    for y in range(first_year, last_year + 1):
        s = f'{y}-01-01'
        if not any(r['date'] >= s for r in daily_rows):
            continue
        dca = simulate_dca(daily_rows, s, contribution_end, valuation_price, contribution)
        wr = simulate_timeline(daily_rows, signal_rows, s, contribution_end, signal_end, valuation_price, threshold, window, contribution)
        if dca['total_portfolio_value']:
            adv = 100 * (wr['total_portfolio_value'] / dca['total_portfolio_value'] - 1)
            starts.append(round(adv, 3))
    if not starts:
        return {'count': 0, 'beat_dca_pct': None, 'median_advantage_pct': None, 'worst_advantage_pct': None}
    ordered = sorted(starts)
    med = ordered[len(ordered)//2] if len(ordered) % 2 else (ordered[len(ordered)//2-1] + ordered[len(ordered)//2]) / 2
    return {
        'count': len(starts),
        'beat_dca_pct': round(100 * sum(x > 0 for x in starts) / len(starts), 2),
        'median_advantage_pct': round(med, 3),
        'worst_advantage_pct': min(starts),
    }


def parameter_stability(daily_rows, signal_rows, start, contribution_end, signal_end, valuation_price, contribution, center_threshold=-80, center_window=14):
    thresholds = [-70, -75, -80, -85, -90]
    windows = [10, 12, 14, 16, 18]
    vals = []
    dca = simulate_dca(daily_rows, start, contribution_end, valuation_price, contribution)
    for th in thresholds:
        for w in windows:
            wr = simulate_timeline(daily_rows, signal_rows, start, contribution_end, signal_end, valuation_price, th, w, contribution)
            if dca['total_portfolio_value']:
                vals.append(100 * (wr['total_portfolio_value'] / dca['total_portfolio_value'] - 1))
    vals.sort()
    if not vals:
        return {}
    return {
        'variants': len(vals),
        'profitable_vs_dca_pct': round(100 * sum(v > 0 for v in vals) / len(vals), 2),
        'median_advantage_pct': round(vals[len(vals)//2], 3),
        'best_advantage_pct': round(max(vals), 3),
        'worst_advantage_pct': round(min(vals), 3),
    }


def run_symbol(symbol: str, group: str, requested_start: str, signal_end: str, valuation_end: str, contribution=1000.0):
    daily, source = fetch_history(symbol)
    available = [r for r in daily if r['date'] <= valuation_end]
    if not available:
        raise RuntimeError(f'No data for {symbol}')
    actual_start = max(requested_start, available[0]['date'])
    valuation_row = [r for r in available if r['date'] <= valuation_end][-1]
    valuation_price = valuation_row['close']
    contribution_end = valuation_end

    completed_daily = [r for r in daily if r['date'] <= signal_end]
    monthly_all = aggregate_monthly(daily)
    # Exclude the current/incomplete valuation month from monthly signal logic.
    signal_month = signal_end[:7]
    completed_monthly = [r for r in monthly_all if r['month'] < valuation_end[:7] and r['date'] <= signal_end]

    dca = simulate_dca(daily, actual_start, contribution_end, valuation_price, contribution)
    daily_wr = simulate_timeline(daily, completed_daily, actual_start, contribution_end, signal_end, valuation_price, -80, 14, contribution)
    monthly_wr = simulate_timeline(daily, completed_monthly, actual_start, contribution_end, completed_monthly[-1]['date'] if completed_monthly else signal_end, valuation_price, -80, 14, contribution)

    def enrich(wr, sigrows, timeframe):
        dca_value = dca['total_portfolio_value']
        wr['advantage_vs_dca_pct'] = round(100 * (wr['total_portfolio_value'] / dca_value - 1), 3) if dca_value else None
        wr['advantage_vs_dca_dollars'] = round(wr['total_portfolio_value'] - dca_value, 2)
        wr['rolling_starts'] = rolling_start_advantages(daily, sigrows, actual_start, contribution_end, signal_end if timeframe == 'daily' else (sigrows[-1]['date'] if sigrows else signal_end), valuation_price, -80, 14, contribution)
        wr['parameter_stability'] = parameter_stability(daily, sigrows, actual_start, contribution_end, signal_end if timeframe == 'daily' else (sigrows[-1]['date'] if sigrows else signal_end), valuation_price, contribution)
        horizons = (21, 63, 126) if timeframe == 'daily' else (1, 3, 6)
        wr['avg_forward_returns_pct'] = forward_trigger_returns(sigrows, wr['triggers'], horizons)

    enrich(daily_wr, completed_daily, 'daily')
    enrich(monthly_wr, completed_monthly, 'monthly')

    return {
        'symbol': symbol,
        'group': group,
        'source': source,
        'start': actual_start,
        'valuation_date': valuation_row['date'],
        'valuation_price': valuation_price,
        'stock_max_drawdown_pct': max_stock_drawdown(daily, actual_start, signal_end),
        'dca': dca,
        'williams_14_day': daily_wr,
        'williams_14_month': monthly_wr,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--large', default='NVDA,MSFT,GOOGL,AMZN,META')
    p.add_argument('--mid', default='CELH,CROX,ELF,ACLS,CAVA')
    p.add_argument('--start', default='2017-01-01')
    p.add_argument('--signal-end', default='2026-09-04')
    p.add_argument('--valuation-end', default='2026-09-08')
    p.add_argument('--contribution', type=float, default=1000.0)
    p.add_argument('--output', default='williams_research_report.json')
    args = p.parse_args()

    results = []
    for group, raw in [('large_cap', args.large), ('mid_cap', args.mid)]:
        for symbol in [x.strip().upper() for x in raw.split(',') if x.strip()]:
            results.append(run_symbol(symbol, group, args.start, args.signal_end, args.valuation_end, args.contribution))

    report = {
        'test': 'Williams Timeline Test',
        'default_williams_timeframe': 'monthly',
        'rules': {
            'contribution': args.contribution,
            'contribution_timing': 'first trading day of each month',
            'threshold': -80,
            'fresh_cross_only': True,
            'daily_variant': '14 trading-day Williams %R',
            'monthly_variant': '14 completed-month Williams %R',
            'execution': 'signal bar close',
            'signal_end': args.signal_end,
            'valuation_end': args.valuation_end,
        },
        'results': results,
    }
    Path(args.output).write_text(json.dumps(report, indent=2), encoding='utf-8')

    compact = []
    for r in results:
        compact.append({
            'symbol': r['symbol'], 'group': r['group'], 'start': r['start'],
            'dca_value': r['dca']['total_portfolio_value'],
            'daily_value': r['williams_14_day']['total_portfolio_value'],
            'daily_adv_pct': r['williams_14_day']['advantage_vs_dca_pct'],
            'monthly_value': r['williams_14_month']['total_portfolio_value'],
            'monthly_adv_pct': r['williams_14_month']['advantage_vs_dca_pct'],
            'monthly_triggers': r['williams_14_month']['trigger_count'],
            'monthly_cash': r['williams_14_month']['remaining_cash'],
            'monthly_rolling_beat_pct': r['williams_14_month']['rolling_starts']['beat_dca_pct'],
            'monthly_stability_positive_pct': r['williams_14_month']['parameter_stability'].get('profitable_vs_dca_pct'),
        })
    print(json.dumps(compact, indent=2))


if __name__ == '__main__':
    main()
