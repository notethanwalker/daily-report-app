from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from ..intraday_models import IntradayBar, OptionIntradayBar, IntradayResearchResult

NY=ZoneInfo("America/New_York")

def _local(dt:datetime):
    if dt.tzinfo is None:dt=dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(NY)

def _at_or_after(rows,hhmm):
    target=time.fromisoformat(hhmm)
    valid=[r for r in rows if _local(r.bar_time).time()>=target]
    return min(valid,key=lambda r:_local(r.bar_time)) if valid else None

def _between(rows,start_hhmm,end_hhmm):
    a=time.fromisoformat(start_hhmm);b=time.fromisoformat(end_hhmm)
    return [r for r in rows if a<=_local(r.bar_time).time()<=b]

def _sign(x):return 1 if x>0 else -1 if x<0 else 0

def run_net_drift_proxy(db:Session,symbol:str,start_date:str,end_date:str,stock_provider:str|None=None,option_provider:str|None=None,signal_time:str="10:30",horizon_time:str="11:30",min_abs_pressure:float=0.0,save:bool=True):
    symbol=symbol.upper()
    sq=db.query(IntradayBar).filter(IntradayBar.symbol==symbol,IntradayBar.bar_time>=datetime.fromisoformat(start_date),IntradayBar.bar_time<datetime.fromisoformat(end_date+"T23:59:59"))
    if stock_provider:sq=sq.filter(IntradayBar.provider==stock_provider)
    oq=db.query(OptionIntradayBar).filter(OptionIntradayBar.underlying==symbol,OptionIntradayBar.bar_time>=datetime.fromisoformat(start_date),OptionIntradayBar.bar_time<datetime.fromisoformat(end_date+"T23:59:59"))
    if option_provider:oq=oq.filter(OptionIntradayBar.provider==option_provider)
    stocks=defaultdict(list);opts=defaultdict(list)
    for r in sq.order_by(IntradayBar.bar_time).all():stocks[_local(r.bar_time).date().isoformat()].append(r)
    for r in oq.order_by(OptionIntradayBar.bar_time).all():opts[_local(r.bar_time).date().isoformat()].append(r)
    trades=[];baseline=[]
    for d,sbars in sorted(stocks.items()):
        open_bar=_at_or_after(sbars,"09:30");sig_bar=_at_or_after(sbars,signal_time);exit_bar=_at_or_after(sbars,horizon_time)
        if not open_bar or not sig_bar or not exit_bar or sig_bar.close<=0:continue
        pdir=_sign(sig_bar.close-open_bar.open)
        if pdir:
            raw=(exit_bar.close/sig_bar.close-1)*pdir
            baseline.append(raw)
        obars=[x for x in opts.get(d,[]) if x.expiration==d]
        if not obars:continue
        strikes=defaultdict(set)
        for x in obars:strikes[float(x.strike)].add(x.option_type)
        candidates=[k for k,v in strikes.items() if {"call","put"}.issubset(v)]
        if not candidates:continue
        strike=min(candidates,key=lambda k:abs(k-open_bar.open))
        chosen=[x for x in obars if float(x.strike)==strike and x.option_type in {"call","put"}]
        window=_between(chosen,"09:30",signal_time)
        if not window:continue
        pressure=0.0;total=0.0
        for x in window:
            premium=(x.vwap if x.vwap is not None else (x.open+x.high+x.low+x.close)/4.0)*x.volume*100.0
            signed=premium*_sign(x.close-x.open)*(1 if x.option_type=="call" else -1)
            pressure+=signed;total+=abs(premium)
        norm=pressure/total if total else 0.0;fdir=_sign(norm)
        agree=bool(fdir and pdir and fdir==pdir and abs(norm)>=min_abs_pressure)
        directional=(exit_bar.close/sig_bar.close-1)*fdir if fdir else 0.0
        trades.append({"date":d,"strike":strike,"open":open_bar.open,"signal_price":sig_bar.close,"exit_price":exit_bar.close,"price_dir":pdir,"flow_dir":fdir,"normalized_pressure":norm,"agree":agree,"directional_return":directional})
    selected=[x for x in trades if x["agree"]]
    divergence=[x for x in trades if x["flow_dir"] and x["price_dir"] and x["flow_dir"]!=x["price_dir"]]
    def stats(xs,key="directional_return"):
        vals=[x[key] if isinstance(x,dict) else x for x in xs]
        return {"n":len(vals),"wins":sum(v>0 for v in vals),"win_rate":sum(v>0 for v in vals)/len(vals) if vals else None,"avg_return":sum(vals)/len(vals) if vals else None,"sum_return":sum(vals) if vals else None}
    metrics={"agreement":stats(selected),"divergence":stats(divergence),"price_momentum_baseline":stats(baseline,key=None),"eligible_option_days":len(trades),"stock_days":len(stocks)}
    payload={"strategy":"qqq_net_drift_confirmation_proxy","version":"2.0","symbol":symbol,"start_date":start_date,"end_date":end_date,"parameters":{"signal_time":signal_time,"horizon_time":horizon_time,"min_abs_pressure":min_abs_pressure,"stock_provider":stock_provider,"option_provider":option_provider,"atm_selection":"nearest common call/put strike to 09:30 underlying open","flow_proxy":"sum premium*sign(option bar close-open)*(call +1 / put -1), normalized by absolute premium"},"metrics":metrics,"trades":trades}
    if save:
        db.add(IntradayResearchResult(strategy=payload["strategy"],version=payload["version"],symbol=symbol,start_date=start_date,end_date=end_date,parameters=payload["parameters"],metrics=metrics,provenance={"stock_provider":stock_provider or "mixed","option_provider":option_provider or "mixed","causal":True,"true_aggressor_net_drift":False}));db.commit()
    return payload
