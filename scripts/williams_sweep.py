#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import itertools
import json
from pathlib import Path

from williams_timeline_backtest import fetch_history, williams, summary


def run_one(rows, symbol, start, end, contribution, threshold, window):
    series = williams(rows, window)
    eligible = [r for r in series if start <= r['date'] <= end]
    if not eligible:
        return None

    first_by_month = {}
    for row in eligible:
        first_by_month.setdefault(row['date'][:7], row)
    contribution_dates = {r['date'] for r in first_by_month.values()}

    dca_shares = 0.0
    for row in first_by_month.values():
        dca_shares += contribution / row['close']

    cash = 0.0
    wr_shares = 0.0
    invested = 0.0
    max_cash = 0.0
    triggers = 0
    previous = None
    for row in series:
        if row['date'] > end:
            break
        if row['date'] < start:
            previous = row
            continue
        if row['date'] in contribution_dates:
            cash += contribution
            max_cash = max(max_cash, cash)
        cur = row.get('williams_r')
        prev = previous.get('williams_r') if previous else None
        if cur is not None and prev is not None and cur <= threshold and prev > threshold and cash > 0:
            wr_shares += cash / row['close']
            invested += cash
            cash = 0.0
            triggers += 1
        previous = row

    total_contributions = len(first_by_month) * contribution
    price = eligible[-1]['close']
    dca = summary(total_contributions, total_contributions, 0.0, dca_shares, price)
    wr = summary(total_contributions, invested, cash, wr_shares, price)
    return {
        'symbol': symbol,
        'start': eligible[0]['date'],
        'end': eligible[-1]['date'],
        'threshold': threshold,
        'window': window,
        'months': len(first_by_month),
        'triggers': triggers,
        'max_cash_waiting': round(max_cash, 2),
        'dca_value': dca['total_portfolio_value'],
        'williams_value': wr['total_portfolio_value'],
        'williams_minus_dca': round(wr['total_portfolio_value'] - dca['total_portfolio_value'], 2),
        'williams_advantage_pct': round(100 * (wr['total_portfolio_value'] / dca['total_portfolio_value'] - 1), 4),
        'dca_cost_basis': dca['effective_cost_basis'],
        'williams_cost_basis': wr['effective_cost_basis'],
        'remaining_cash': wr['remaining_cash'],
        'dca_shares': dca['shares'],
        'williams_shares': wr['shares'],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--symbols', required=True, help='Comma-separated tickers')
    p.add_argument('--start', required=True)
    p.add_argument('--end', required=False)
    p.add_argument('--thresholds', default='-60,-70,-75,-80,-85,-90')
    p.add_argument('--windows', default='7,14,21,28')
    p.add_argument('--contribution', type=float, default=1000.0)
    p.add_argument('--output', default='williams_sweep.csv')
    args = p.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
    thresholds = [float(x) for x in args.thresholds.split(',')]
    windows = [int(x) for x in args.windows.split(',')]
    all_rows = []

    for symbol in symbols:
        rows, source = fetch_history(symbol)
        end = args.end or rows[-1]['date']
        for threshold, window in itertools.product(thresholds, windows):
            result = run_one(rows, symbol, args.start, end, args.contribution, threshold, window)
            if result:
                result['source'] = source
                all_rows.append(result)

    all_rows.sort(key=lambda r: r['williams_advantage_pct'], reverse=True)
    if not all_rows:
        raise RuntimeError('No sweep results produced')

    path = Path(args.output)
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)

    print(json.dumps(all_rows[:25], indent=2))


if __name__ == '__main__':
    main()
