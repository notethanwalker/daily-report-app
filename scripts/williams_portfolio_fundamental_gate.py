#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, time, urllib.request, gzip
from datetime import date
from pathlib import Path
from williams_timeline_backtest import fetch_history, williams
from williams_research_suite import aggregate_monthly, first_trading_days
UA='DailyReportResearch/1.0 research@example.com'; SEC_TICKERS='https://www.sec.gov/files/company_tickers.json'; SEC_FACTS='https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json'
def get_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept-Encoding':'gzip'})
    with urllib.request.urlopen(req,timeout=30) as r:
        b=r.read(); enc=(r.headers.get('Content-Encoding') or '').lower()
        if 'gzip' in enc or b[:2]==b'\x1f\x8b': b=gzip.decompress(b)
        return json.loads(b.decode('utf-8'))
def ticker_ciks(): return {v['ticker'].upper():int(v['cik_str']) for v in get_json(SEC_TICKERS).values()}
def annual_series(facts,tags):
    us=facts.get('facts',{}).get('us-gaap',{}); rows=[]
    for tag in tags:
        node=us.get(tag)
        if not node: continue
        for x in (node.get('units',{}).get('USD') or []):
            if x.get('form') not in ('10-K','10-K/A','20-F','20-F/A','40-F','40-F/A') or x.get('fp')!='FY' or x.get('fy') is None or x.get('val') is None: continue
            st,en,filed=x.get('start'),x.get('end'),x.get('filed')
            if not (st and en and filed): continue
            try: dur=(date.fromisoformat(en)-date.fromisoformat(st)).days
            except: continue
            if 250<=dur<=450: rows.append({'fy':int(x['fy']),'filed':filed,'end':en,'val':float(x['val']),'tag':tag})
        if rows: break
    return rows
def latest_by_fy(rows,asof):
    by={}
    for r in rows:
        if r['filed']<=asof and (r['fy'] not in by or r['filed']>by[r['fy']]['filed']): by[r['fy']]=r
    return by
def gate_state(series,asof):
    metric={k:latest_by_fy(v,asof) for k,v in series.items()}; fys=sorted(set(metric['revenue']) & (set(metric['net_income'])|set(metric['cfo'])|set(metric['op_income'])))
    if len(fys)<2:return {'blocked':False,'flags':[],'reason':'insufficient_point_in_time_fundamentals'}
    fy1,fy0=fys[-2],fys[-1]; flags=[]; severe=[]
    def val(n,fy): return metric[n].get(fy,{}).get('val')
    r1,r0=val('revenue',fy1),val('revenue',fy0)
    if r1 not in (None,0) and r0 is not None:
        g=r0/r1-1
        if g<=-0.10: flags.append('revenue_down_10pct')
        if g<=-0.20: severe.append('revenue_down_20pct')
    o1,o0=val('op_income',fy1),val('op_income',fy0)
    if None not in (o1,o0,r1,r0) and r1 and r0 and (o0/r0-o1/r1)<=-0.05: flags.append('operating_margin_down_5pp')
    n1,n0=val('net_income',fy1),val('net_income',fy0)
    if n0 is not None and n1 is not None and ((n1>=0 and n0<0) or (n1>0 and n0/n1-1<=-0.30)): flags.append('net_income_deterioration')
    c1,c0=val('cfo',fy1),val('cfo',fy0)
    if c0 is not None and (c0<=0 or (c1 is not None and c1>0 and c0/c1-1<=-0.30)): flags.append('cash_flow_deterioration')
    if n0 is not None and c0 is not None and n0<0 and c0<0: severe.append('negative_income_and_cfo')
    return {'blocked':bool(severe) or len(set(flags))>=2,'flags':sorted(set(flags+severe))}
def sec_series(symbol,cikmap,cache):
    if symbol in cache:return cache[symbol]
    cik=cikmap.get(symbol)
    if not cik: cache[symbol]=None; return None
    try: f=get_json(SEC_FACTS.format(cik=cik)); time.sleep(0.11)
    except Exception: cache[symbol]=None; return None
    tags={'revenue':['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'],'op_income':['OperatingIncomeLoss'],'net_income':['NetIncomeLoss','ProfitLoss'],'cfo':['NetCashProvidedByUsedInOperatingActivities','NetCashProvidedByUsedInOperatingActivitiesContinuingOperations']}
    cache[symbol]={k:annual_series(f,v) for k,v in tags.items()}; return cache[symbol]
def prior_month_wr(rows): return {r['date'][:7]:r.get('williams_r') for r in williams(aggregate_monthly(rows),14)}
def allocation_weights(symbols,wr_map,tilt,blocked):
    eligible=[s for s in symbols if s not in blocked]
    if not eligible:return {s:0 for s in symbols}
    vals=[(s,wr_map.get(s)) for s in eligible]
    if any(v is None for _,v in vals): w={s:1/len(eligible) for s in eligible}
    else:
        ordered=sorted(vals,key=lambda x:x[1],reverse=True); rank={s:i+1 for i,(s,_) in enumerate(ordered)}; denom=sum(range(1,len(eligible)+1)); base=(1-tilt)/len(eligible); w={s:base+tilt*rank[s]/denom for s in eligible}
    return {s:w.get(s,0.0) for s in symbols}
def run(symbols,start,end,monthly_cash,tilts):
    data={}
    for s in symbols:
        rows,source=fetch_history(s); elig=[r for r in rows if start<=r['date']<=end]
        if not elig or elig[0]['date']>start[:7]+'-31': raise RuntimeError(f'{s} does not cover requested start period')
        data[s]={'rows':rows,'firsts':first_trading_days(rows,start,end),'wr':prior_month_wr(rows)}
    months=sorted(set.intersection(*(set(data[s]['firsts']) for s in symbols)))
    variants={'equal':{s:0.0 for s in symbols}}
    for t in tilts: variants[f'tilt_{int(t*100)}']={s:0.0 for s in symbols}; variants[f'gated_{int(t*100)}']={s:0.0 for s in symbols}
    cikmap=ticker_ciks(); cache={}; fundamentals={s:sec_series(s,cikmap,cache) for s in symbols}; block_months={s:0 for s in symbols}; insufficient={s:0 for s in symbols}
    for idx,m in enumerate(months):
        prices={s:float(data[s]['firsts'][m]['close']) for s in symbols}; eq={s:1/len(symbols) for s in symbols}
        for s in symbols: variants['equal'][s]+=monthly_cash*eq[s]/prices[s]
        prev=months[idx-1] if idx else None; wr={s:(data[s]['wr'].get(prev) if prev else None) for s in symbols}; asof=data[symbols[0]]['firsts'][m]['date']; blocked=set()
        for s in symbols:
            fs=fundamentals[s]
            if fs is None: insufficient[s]+=1; continue
            st=gate_state(fs,asof)
            if st.get('reason'): insufficient[s]+=1
            if st['blocked']: blocked.add(s); block_months[s]+=1
        for t in tilts:
            u=allocation_weights(symbols,wr,t,set()); g=allocation_weights(symbols,wr,t,blocked)
            for s in symbols: variants[f'tilt_{int(t*100)}'][s]+=monthly_cash*u[s]/prices[s]; variants[f'gated_{int(t*100)}'][s]+=monthly_cash*g[s]/prices[s]
    final={s:float([r for r in data[s]['rows'] if r['date']<=end][-1]['close']) for s in symbols}; contrib=len(months)*monthly_cash; results={}
    for k,sh in variants.items():
        v=sum(sh[s]*final[s] for s in symbols); results[k]={'portfolio_value':round(v,2),'return_pct':round(100*(v/contrib-1),4)}
    eqv=results['equal']['portfolio_value']
    for k in results: results[k]['vs_equal_pct']=round(100*(results[k]['portfolio_value']/eqv-1),4)
    comparison={}
    for t in tilts:
        a=results[f'tilt_{int(t*100)}']['portfolio_value']; b=results[f'gated_{int(t*100)}']['portfolio_value']; comparison[str(int(t*100))]={'ungated_vs_equal_pct':results[f'tilt_{int(t*100)}']['vs_equal_pct'],'gated_vs_equal_pct':results[f'gated_{int(t*100)}']['vs_equal_pct'],'gate_increment_pct':round(100*(b/a-1),4)}
    return {'symbols':symbols,'start':months[0],'end':months[-1],'months':len(months),'total_contributions':contrib,'comparison':comparison,'block_months':block_months,'insufficient_months':insufficient,'results':results}
def main():
    p=argparse.ArgumentParser(); p.add_argument('--symbols',required=True); p.add_argument('--start',required=True); p.add_argument('--end',required=True); p.add_argument('--monthly-cash',type=float,default=10000); p.add_argument('--tilts',default='0.25,0.5,0.75,1.0'); p.add_argument('--output',default='fundamental_gate.json'); a=p.parse_args(); out=run([x.strip().upper() for x in a.symbols.split(',') if x.strip()],a.start,a.end,a.monthly_cash,[float(x) for x in a.tilts.split(',')]); Path(a.output).write_text(json.dumps(out,indent=2)); print(json.dumps(out,indent=2))
if __name__=='__main__':main()
