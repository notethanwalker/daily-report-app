#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

from williams_timeline_backtest import fetch_history, williams, summary
from williams_research_suite import aggregate_monthly, first_trading_days


def monthly_signal_map(rows: list[dict], window: int = 14) -> dict[str, float | None]:
    monthly = aggregate_monthly(rows)
    wr = williams(monthly, window)
    return {r['date'][:7]: r.get('williams_r') for r in wr}


def simulate_hybrid(rows: list[dict], start: str, end: str, valuation_price: float, wait_months: int, contribution: float = 1000.0):
    firsts = first_trading_days(rows, start, end)
    monthly_wr = monthly_signal_map(rows, 14)
    immediate = contribution * 0.5
    reserve_add = contribution * 0.5

    shares = 0.0
    invested = 0.0
    reserve = deque()  # [month, amount, original_amount]
    ledger = []
    max_cash = 0.0

    months = sorted(firsts)
    for idx, month in enumerate(months):
        row = firsts[month]
        close = float(row['close'])
        # immediate half DCA
        shares += immediate / close
        invested += immediate
        reserve.append([month, reserve_add, reserve_add])

        # use latest COMPLETED monthly Williams signal (previous calendar month)
        prev_month = months[idx - 1] if idx > 0 else None
        wr = monthly_wr.get(prev_month) if prev_month else None

        # tier target: cumulative fraction of current reserve to have deployed at each band
        fraction = 0.0
        if wr is not None:
            if wr <= -80:
                fraction = 1.0
            elif wr <= -70:
                fraction = 0.75
            elif wr <= -60:
                fraction = 0.25

        cash_before = sum(x[1] for x in reserve)
        target_deploy = cash_before * fraction
        deploy = 0.0

        # forced deployment of lots that have waited at least wait_months
        current_ord = int(month[:4]) * 12 + int(month[5:7])
        forced = 0.0
        for lot in reserve:
            lot_ord = int(lot[0][:4]) * 12 + int(lot[0][5:7])
            if current_ord - lot_ord >= wait_months:
                forced += lot[1]

        amount_to_deploy = max(target_deploy, forced)
        remaining = amount_to_deploy
        while remaining > 1e-9 and reserve:
            lot = reserve[0]
            take = min(lot[1], remaining)
            lot[1] -= take
            remaining -= take
            deploy += take
            if lot[1] <= 1e-9:
                reserve.popleft()
        if deploy > 0:
            shares += deploy / close
            invested += deploy

        max_cash = max(max_cash, sum(x[1] for x in reserve))
        ledger.append({'month': month, 'close': close, 'prior_month_williams_r': wr, 'reserve_deployed': round(deploy,2), 'reserve_remaining': round(sum(x[1] for x in reserve),2)})

    cash = sum(x[1] for x in reserve)
    total_contributions = len(firsts) * contribution
    return {**summary(total_contributions, invested, cash, shares, valuation_price), 'max_cash_waiting': round(max_cash,2), 'ledger': ledger}


def dca_result(rows, start, end, valuation_price, contribution=1000.0):
    firsts = first_trading_days(rows, start, end)
    shares = sum(contribution / float(r['close']) for r in firsts.values())
    total = len(firsts) * contribution
    return summary(total, total, 0.0, shares, valuation_price)


def run(symbols, start, end):
    out = []
    for symbol in symbols:
        rows, source = fetch_history(symbol)
        eligible = [r for r in rows if start <= r['date'] <= end]
        if not eligible:
            continue
        actual_start = eligible[0]['date']
        actual_end = eligible[-1]['date']
        price = float(eligible[-1]['close'])
        dca = dca_result(rows, actual_start, actual_end, price)
        h2 = simulate_hybrid(rows, actual_start, actual_end, price, 2)
        h3 = simulate_hybrid(rows, actual_start, actual_end, price, 3)
        out.append({
            'symbol': symbol,
            'source': source,
            'start': actual_start,
            'end': actual_end,
            'dca': dca,
            'hybrid_2m': h2,
            'hybrid_3m': h3,
            'hybrid_2m_adv_pct': round(100*(h2['total_portfolio_value']/dca['total_portfolio_value']-1),4),
            'hybrid_3m_adv_pct': round(100*(h3['total_portfolio_value']/dca['total_portfolio_value']-1),4),
        })
    return out


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--symbols', required=True)
    p.add_argument('--start', default='2017-01-01')
    p.add_argument('--end', default='2026-09-04')
    p.add_argument('--output', default='williams_hybrid_results.json')
    a=p.parse_args()
    results=run([x.strip().upper() for x in a.symbols.split(',') if x.strip()], a.start, a.end)
    Path(a.output).write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps([{k:v for k,v in r.items() if k not in ('dca','hybrid_2m','hybrid_3m')} | {
        'dca_value':r['dca']['total_portfolio_value'],
        'hybrid_2m_value':r['hybrid_2m']['total_portfolio_value'],
        'hybrid_3m_value':r['hybrid_3m']['total_portfolio_value'],
        'h2_adv_pct':r['hybrid_2m_adv_pct'],
        'h3_adv_pct':r['hybrid_3m_adv_pct'],
        'h2_max_cash':r['hybrid_2m']['max_cash_waiting'],
        'h3_max_cash':r['hybrid_3m']['max_cash_waiting'],
    } for r in results], indent=2))

if __name__=='__main__': main()
