from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import mean

from sqlalchemy.orm import Session

from ..normalized_market_models import NormalizedDailyBar
from .opportunity_formula_v4 import CRITERIA, formula_score, passes_filters, score_components, validate_filters, validate_formula

MODEL_VERSION = "strategy-lab-v4.1"
FORWARD_HORIZONS = (5, 20, 60, 120)


def _rows(db: Session, symbol: str) -> list[dict]:
    rows = db.query(NormalizedDailyBar).filter(NormalizedDailyBar.symbol == symbol.upper()).order_by(NormalizedDailyBar.bar_date.asc()).all()
    return [{"date": r.bar_date, "open": r.open, "high": r.high, "low": r.low, "close": float(r.close), "volume": float(r.volume or 0), "provider": r.provider, "source_url": r.source_url} for r in rows]


def _avg(values):
    vals=[float(x) for x in values if x is not None]
    return sum(vals)/len(vals) if vals else None


def _technical_series(rows: list[dict]) -> list[dict]:
    out=[]
    ma100_history=[]
    distances=[]
    for i,row in enumerate(rows):
        closes=[x["close"] for x in rows[:i+1]]
        vols=[x["volume"] for x in rows[:i+1]]
        def ma(n): return _avg(closes[-n:]) if len(closes)>=n else None
        ma50,ma100,ma200=ma(50),ma(100),ma(200)
        ma100_history.append(ma100)
        d50=(row["close"]/ma50-1)*100 if ma50 else None
        d100=(row["close"]/ma100-1)*100 if ma100 else None
        distances.append(d100)
        slope=None
        if ma100 is not None and i>=20 and ma100_history[i-20] not in (None,0): slope=(ma100/ma100_history[i-20]-1)*100
        approach=None
        if d100 is not None and i>=5 and distances[i-5] is not None: approach=distances[i-5]-d100
        wr=None
        if i>=13:
            look=rows[i-13:i+1]
            highs=[x["high"] for x in look if x["high"] is not None];lows=[x["low"] for x in look if x["low"] is not None]
            if len(highs)==14 and len(lows)==14:
                hh,ll=max(highs),min(lows)
                if hh!=ll: wr=-100.0*(hh-row["close"])/(hh-ll)
        rv=None
        if i>=20:
            base=_avg(vols[i-20:i])
            if base and base>0: rv=row["volume"]/base
        out.append({**row,"price":row["close"],"williams_r_14":wr,"ma50":ma50,"ma100":ma100,"ma200":ma200,"price_vs_ma50_percent":d50,"price_vs_ma100_percent":d100,"ma100_slope_20d_percent":slope,"approach_velocity_100_5d":approach,"relative_volume":rv})
    return out


def _summary(contributions, invested, cash, shares, price):
    market_value=shares*price;total=market_value+cash;profit=total-contributions
    return {"total_contributions":round(contributions,2),"total_invested":round(invested,2),"remaining_cash":round(cash,2),"shares":round(shares,8),"market_value":round(market_value,2),"total_value":round(total,2),"profit":round(profit,2),"return_pct":round(profit/contributions*100,4) if contributions else None}


def run_williams_timeline(db: Session, symbol: str, start: str, end: str|None=None, contribution: float=1000.0, threshold: float=-80.0, window: int=14) -> dict:
    if window!=14: raise ValueError("Stored Strategy Lab currently supports the app-standard 14-session Williams %R only")
    raw=_rows(db,symbol)
    if len(raw)<14: raise ValueError("Insufficient stored OHLC history")
    series=_technical_series(raw);end=end or series[-1]["date"]
    eligible=[r for r in series if start<=r["date"]<=end]
    if not eligible: raise ValueError("No stored trading days in requested range")
    first_by_month={}
    for row in eligible:first_by_month.setdefault(row["date"][:7],row)
    contribution_dates={r["date"] for r in first_by_month.values()}
    dca_shares=dca_invested=0.0;dca_tx=[]
    for row in first_by_month.values():
        bought=contribution/row["close"];dca_shares+=bought;dca_invested+=contribution;dca_tx.append({"date":row["date"],"amount":contribution,"close":row["close"],"shares_bought":bought})
    cash=wr_shares=wr_invested=0.0;triggers=[];prev=None
    for row in series:
        if row["date"]>end:break
        if row["date"]<start:prev=row;continue
        if row["date"] in contribution_dates:cash+=contribution
        cur=row["williams_r_14"];prior=prev["williams_r_14"] if prev else None
        if cur is not None and prior is not None and cur<=threshold and prior>threshold and cash>0:
            amount=cash;bought=amount/row["close"];wr_shares+=bought;wr_invested+=amount;cash=0.0;triggers.append({"date":row["date"],"prior_williams_r":round(prior,3),"williams_r":round(cur,3),"close":row["close"],"amount_invested":amount,"shares_bought":bought})
        prev=row
    contributions=len(first_by_month)*contribution;price=eligible[-1]["close"]
    return {"model_version":MODEL_VERSION,"test":"Williams Timeline Test","symbol":symbol.upper(),"source":"stored normalized_daily_bars","parameters":{"start":eligible[0]["date"],"end":eligible[-1]["date"],"monthly_contribution":contribution,"threshold":threshold,"window":window},"valuation":{"date":eligible[-1]["date"],"close":price},"strategy_1_monthly_dca":{**_summary(contributions,dca_invested,0,dca_shares,price),"transactions":dca_tx},"strategy_2_williams_timeline":{**_summary(contributions,wr_invested,cash,wr_shares,price),"triggers":triggers},"methodology":"Monthly contributions use the first stored trading session of each month. Williams deployment requires a crossing from above the selected threshold; after deployment a later crossing requires Williams to have first moved back above the threshold. No provider calls occur during this test."}


def _forward_stats(series: list[dict], signal_indices: list[int], horizons=FORWARD_HORIZONS) -> dict:
    out={}
    for h in horizons:
        values=[]
        for i in signal_indices:
            if i+h>=len(series):continue
            start=series[i]["close"];end=series[i+h]["close"]
            if start>0:values.append((end/start-1)*100)
        out[str(h)]={"samples":len(values),"mean_return_pct":round(mean(values),3) if values else None,"median_return_pct":round(sorted(values)[len(values)//2],3) if values else None,"positive_rate":round(sum(x>0 for x in values)/len(values),3) if values else None}
    return out


def run_formula_history(db: Session, symbol: str, criteria: dict, filters: list[dict]|None=None, score_threshold: float=70.0, start: str|None=None, end: str|None=None) -> dict:
    criteria=validate_formula(criteria);filters=validate_filters(filters)
    unsupported=[k for k in criteria if CRITERIA[k].get("coverage_class")!="broad_cache_safe"]
    if unsupported: raise ValueError("Historical formula tests currently support technical/cache-safe criteria only; point-in-time fundamentals are not backfilled: "+", ".join(unsupported))
    series=_technical_series(_rows(db,symbol))
    if not series: raise ValueError("No stored history")
    start=start or series[0]["date"];end=end or series[-1]["date"]
    signals=[];indices=[]
    for i,row in enumerate(series):
        if not(start<=row["date"]<=end) or not passes_filters(row,filters):continue
        components=score_components(row);score=formula_score(components,criteria)
        if score is not None and score>=score_threshold:
            indices.append(i);signals.append({"date":row["date"],"score":score,"close":row["close"],"williams_r_14":row.get("williams_r_14"),"price_vs_ma100_percent":row.get("price_vs_ma100_percent")})
    return {"model_version":MODEL_VERSION,"test":"Opportunity Formula History","symbol":symbol.upper(),"source":"stored normalized_daily_bars","parameters":{"start":start,"end":end,"criteria":criteria,"filters":filters,"score_threshold":score_threshold},"signals":signals[-250:],"signal_count":len(signals),"forward_returns":_forward_stats(series,indices),"methodology":"Each historical score uses only OHLCV observations available on or before that date. Fundamental criteria are rejected until genuine point-in-time fundamental history exists. Forward returns are descriptive and overlapping windows are not independent."}
