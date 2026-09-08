#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from williams_timeline_backtest import fetch_history, williams
from williams_research_suite import aggregate_monthly, first_trading_days


def monthly_wr(rows):
    return {r['date'][:7]: r.get('williams_r') for r in williams(aggregate_monthly(rows), 14)}

def prior_month(m):
    y,mo=map(int,m.split('-')); mo-=1
    if mo==0: y-=1; mo=12
    return f'{y:04d}-{mo:02d}'

def priority_weights(symbols, wrs):
    vals=[(s,wrs.get(s)) for s in symbols]
    if any(v is None for _,v in vals):
        return {s:1/len(symbols) for s in symbols}
    ordered=sorted(vals,key=lambda x:x[1],reverse=True)  # least oversold first
    rank={s:i+1 for i,(s,_) in enumerate(ordered)}      # most oversold highest rank
    denom=sum(range(1,len(symbols)+1))
    return {s:rank[s]/denom for s in symbols}

def value(shares, prices): return sum(shares[s]*prices[s] for s in shares)

def trade_to_target(shares, prices, target, total_value, cost_rate=0.0):
    desired={s:total_value*target[s] for s in shares}
    current={s:shares[s]*prices[s] for s in shares}
    gross=sum(abs(desired[s]-current[s]) for s in shares)
    # proportional transaction-cost approximation; cost is removed from portfolio and targets rescaled
    cost=gross*cost_rate
    investable=max(0.0,total_value-cost)
    for s in shares: shares[s]=(investable*target[s])/prices[s]
    return gross,cost

def simulate(symbols,start,end,monthly_cash=10000.0,cost_rate=0.0):
    data={}
    for s in symbols:
        rows,_=fetch_history(s)
        firsts=first_trading_days(rows,start,end)
        data[s]={'rows':rows,'firsts':firsts,'wr':monthly_wr(rows)}
    common=sorted(set.intersection(*(set(data[s]['firsts']) for s in symbols)))
    if not common: raise RuntimeError('No common monthly dates')
    # Require every symbol to have begun trading by the first common month; caller may supply an earlier start.
    actual_start=common[0]
    shares={name:{s:0.0 for s in symbols} for name in ('equal','priority_new_money','priority_quarterly','priority_monthly')}
    turnovers={k:0.0 for k in shares}; costs={k:0.0 for k in shares}; contributions=0.0
    equity={k:[] for k in shares}
    for i,m in enumerate(common):
        prices={s:float(data[s]['firsts'][m]['close']) for s in symbols}
        pm=prior_month(m); wrs={s:data[s]['wr'].get(pm) for s in symbols}; pw=priority_weights(symbols,wrs); eq={s:1/len(symbols) for s in symbols}
        contributions+=monthly_cash
        # equal: new cash equal, no selling
        for s in symbols: shares['equal'][s]+=(monthly_cash*eq[s])/prices[s]
        # priority new-money only
        for s in symbols: shares['priority_new_money'][s]+=(monthly_cash*pw[s])/prices[s]
        # quarterly: add cash by priority monthly, then full priority rebalance in Jan/Apr/Jul/Oct
        for s in symbols: shares['priority_quarterly'][s]+=(monthly_cash*pw[s])/prices[s]
        if int(m[-2:]) in (1,4,7,10):
            tv=value(shares['priority_quarterly'],prices)
            g,c=trade_to_target(shares['priority_quarterly'],prices,pw,tv,cost_rate); turnovers['priority_quarterly']+=g; costs['priority_quarterly']+=c
        # monthly: contribute then rebalance full portfolio to priority weights
        for s in symbols: shares['priority_monthly'][s]+=(monthly_cash*pw[s])/prices[s]
        tv=value(shares['priority_monthly'],prices)
        g,c=trade_to_target(shares['priority_monthly'],prices,pw,tv,cost_rate); turnovers['priority_monthly']+=g; costs['priority_monthly']+=c
        for k in shares: equity[k].append(value(shares[k],prices))
    final_prices={s:float([r for r in data[s]['rows'] if r['date']<=end][-1]['close']) for s in symbols}
    out={}
    for k in shares:
        v=value(shares[k],final_prices); ret=100*(v/contributions-1)
        peak=0; dd=0
        for x in equity[k]:
            peak=max(peak,x)
            if peak: dd=min(dd,x/peak-1)
        out[k]={'portfolio_value':round(v,2),'return_pct':round(ret,4),'turnover_dollars':round(turnovers[k],2),'turnover_multiple_contributions':round(turnovers[k]/contributions,3),'transaction_costs':round(costs[k],2),'max_monthly_path_drawdown_pct':round(dd*100,3)}
    base=out['priority_new_money']['portfolio_value']
    eqv=out['equal']['portfolio_value']
    for k in out:
        out[k]['vs_equal_pct']=round(100*(out[k]['portfolio_value']/eqv-1),4)
        out[k]['vs_priority_new_money_pct']=round(100*(out[k]['portfolio_value']/base-1),4)
    return {'symbols':symbols,'requested_start':start,'actual_start_month':actual_start,'end':common[-1],'months':len(common),'total_contributions':round(contributions,2),'cost_rate':cost_rate,'signal':'14 completed-month Williams %R; previous month only; rank weights 1..N with most oversold receiving highest weight','results':out}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--symbols',required=True); p.add_argument('--start',required=True); p.add_argument('--end',required=True); p.add_argument('--monthly-cash',type=float,default=10000); p.add_argument('--cost-bps',type=float,default=0); p.add_argument('--output',default='rebalance.json')
    a=p.parse_args(); syms=[x.strip().upper() for x in a.symbols.split(',') if x.strip()]
    d=simulate(syms,a.start,a.end,a.monthly_cash,a.cost_bps/10000); Path(a.output).write_text(json.dumps(d,indent=2)); print(json.dumps(d,indent=2))
if __name__=='__main__': main()
