#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
import williams_portfolio_fundamental_gate as base

def latest_by_end(rows, asof):
    by={}
    for r in rows:
        if r['filed']<=asof and (r['end'] not in by or r['filed']>by[r['end']]['filed']):
            by[r['end']]=r
    return by

def gate_state(series, asof):
    metric={k:latest_by_end(v,asof) for k,v in series.items()}
    rev_ends=sorted(metric['revenue'])
    if len(rev_ends)<2:
        return {'blocked':False,'flags':[],'reason':'insufficient_point_in_time_fundamentals'}
    e1,e0=rev_ends[-2],rev_ends[-1]
    r1,r0=metric['revenue'][e1]['val'],metric['revenue'][e0]['val']
    if not r1:
        return {'blocked':False,'flags':[],'reason':'insufficient_point_in_time_fundamentals'}
    rev_g=r0/r1-1
    flags=[]
    if rev_g<=-0.10: flags.append('revenue_down_10pct')
    if rev_g<=-0.20: flags.append('revenue_down_20pct')

    def v(name,end): return metric[name].get(end,{}).get('val')
    o1,o0=v('op_income',e1),v('op_income',e0)
    margin_bad=False
    if None not in (o1,o0) and r1 and r0:
        margin_bad=(o0/r0-o1/r1)<=-0.05
        if margin_bad: flags.append('operating_margin_down_5pp')
    n1,n0=v('net_income',e1),v('net_income',e0)
    ni_bad=False
    if n0 is not None and n1 is not None:
        ni_bad=((n1>=0 and n0<0) or (n1>0 and n0/n1-1<=-0.30))
        if ni_bad: flags.append('net_income_deterioration')
    c1,c0=v('cfo',e1),v('cfo',e0)
    cfo_bad=False
    if c0 is not None:
        cfo_bad=(c0<=0 or (c1 is not None and c1>0 and c0/c1-1<=-0.30))
        if cfo_bad: flags.append('cash_flow_deterioration')

    severe_rev=rev_g<=-0.20
    confirmed_rev=(rev_g<=-0.10 and (margin_bad or ni_bad or cfo_bad))
    cash_profit_failure=(n0 is not None and c0 is not None and n0<0 and c0<0)
    if cash_profit_failure: flags.append('negative_income_and_cfo')
    return {'blocked':bool(severe_rev or confirmed_rev or cash_profit_failure),'flags':sorted(set(flags))}

base.gate_state=gate_state

def main():
    p=argparse.ArgumentParser(); p.add_argument('--symbols',required=True); p.add_argument('--start',required=True); p.add_argument('--end',required=True); p.add_argument('--monthly-cash',type=float,default=10000); p.add_argument('--tilts',default='0.25,0.5,0.75,1.0'); p.add_argument('--output',default='fundamental_gate_v2.json')
    a=p.parse_args(); out=base.run([x.strip().upper() for x in a.symbols.split(',') if x.strip()],a.start,a.end,a.monthly_cash,[float(x) for x in a.tilts.split(',')]); out['gate_version']='v2_end_date_matched_revenue_anchored'; Path(a.output).write_text(json.dumps(out,indent=2)); print(json.dumps(out,indent=2))
if __name__=='__main__':main()
