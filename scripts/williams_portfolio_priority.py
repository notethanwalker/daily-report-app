#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from pathlib import Path

from williams_timeline_backtest import fetch_history, williams
from williams_research_suite import aggregate_monthly, first_trading_days


def prior_month_wr(rows):
    monthly = aggregate_monthly(rows)
    wr = williams(monthly, 14)
    return {r['date'][:7]: r.get('williams_r') for r in wr}


def month_ord(m):
    y, mo = map(int, m.split('-'))
    return y * 12 + mo


def portfolio_value(shares, prices):
    return sum(shares[s] * prices[s] for s in shares)


def allocation_weights(symbols, wr_map, tilt):
    available = [(s, wr_map.get(s)) for s in symbols]
    vals = [(s, v) for s, v in available if v is not None]
    if len(vals) < len(symbols):
        return {s: 1.0 / len(symbols) for s in symbols}
    # More negative Williams = higher priority. Linear cross-sectional rank.
    ordered = sorted(vals, key=lambda x: x[1], reverse=True)  # least oversold first
    rank = {s: i + 1 for i, (s, _) in enumerate(ordered)}
    denom = sum(range(1, len(symbols) + 1))
    base = (1.0 - tilt) / len(symbols)
    return {s: base + tilt * rank[s] / denom for s in symbols}


def run(symbols, start, end, monthly_cash, tilts):
    data = {}
    for s in symbols:
        rows, source = fetch_history(s)
        eligible = [r for r in rows if start <= r['date'] <= end]
        if not eligible or eligible[0]['date'] > start[:7] + '-31':
            raise RuntimeError(f'{s} does not cover requested start period')
        firsts = first_trading_days(rows, start, end)
        data[s] = {'rows': rows, 'firsts': firsts, 'wr': prior_month_wr(rows), 'source': source}

    months = sorted(set.intersection(*(set(data[s]['firsts']) for s in symbols)))
    shares_by_variant = {'equal': {s: 0.0 for s in symbols}}
    for t in tilts:
        shares_by_variant[f'tilt_{int(t*100)}'] = {s: 0.0 for s in symbols}

    ledgers = {k: [] for k in shares_by_variant}
    for idx, month in enumerate(months):
        prices = {s: float(data[s]['firsts'][month]['close']) for s in symbols}
        # Equal-weight baseline
        eqw = {s: 1.0 / len(symbols) for s in symbols}
        for s in symbols:
            shares_by_variant['equal'][s] += monthly_cash * eqw[s] / prices[s]
        ledgers['equal'].append({'month': month, 'weights': eqw})

        prev_month = months[idx - 1] if idx > 0 else None
        wr_cross = {s: (data[s]['wr'].get(prev_month) if prev_month else None) for s in symbols}
        for t in tilts:
            key = f'tilt_{int(t*100)}'
            w = allocation_weights(symbols, wr_cross, t)
            for s in symbols:
                shares_by_variant[key][s] += monthly_cash * w[s] / prices[s]
            ledgers[key].append({'month': month, 'prior_month_williams': wr_cross, 'weights': w})

    final_prices = {}
    for s in symbols:
        eligible = [r for r in data[s]['rows'] if r['date'] <= end]
        final_prices[s] = float(eligible[-1]['close'])

    total_contributions = len(months) * monthly_cash
    results = {}
    for key, shares in shares_by_variant.items():
        value = portfolio_value(shares, final_prices)
        by_stock = {s: round(shares[s] * final_prices[s], 2) for s in symbols}
        results[key] = {
            'portfolio_value': round(value, 2),
            'profit': round(value - total_contributions, 2),
            'return_pct': round(100 * (value / total_contributions - 1), 4),
            'by_stock_value': by_stock,
            'final_weights_pct': {s: round(100 * by_stock[s] / value, 3) for s in symbols},
        }
    eq = results['equal']['portfolio_value']
    for key in results:
        results[key]['vs_equal_pct'] = round(100 * (results[key]['portfolio_value'] / eq - 1), 4)

    return {
        'strategy': 'Cross-sectional monthly Williams priority allocation',
        'symbols': symbols,
        'start': months[0],
        'end': months[-1],
        'monthly_cash': monthly_cash,
        'months': len(months),
        'total_contributions': total_contributions,
        'rule': 'All cash invested monthly. Base equal weight plus Williams rank tilt using prior completed 14-month Williams %R; more oversold receives higher allocation.',
        'tilts_tested': tilts,
        'results': results,
        'ledgers': ledgers,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--symbols', required=True)
    p.add_argument('--start', default='2017-01-01')
    p.add_argument('--end', default='2026-09-04')
    p.add_argument('--monthly-cash', type=float, default=10000.0)
    p.add_argument('--tilts', default='0.25,0.5,0.75,1.0')
    p.add_argument('--output', default='williams_portfolio_priority.json')
    a = p.parse_args()
    out = run([x.strip().upper() for x in a.symbols.split(',') if x.strip()], a.start, a.end, a.monthly_cash, [float(x) for x in a.tilts.split(',')])
    Path(a.output).write_text(json.dumps(out, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in out.items() if k != 'ledgers'}, indent=2))

if __name__ == '__main__':
    main()
