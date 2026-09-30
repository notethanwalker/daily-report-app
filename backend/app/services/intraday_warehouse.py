from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from ..intraday_models import IntradayBar, OptionIntradayBar, IntradayIngestionRun
from ..providers.intraday import AlpacaIntradayProvider, TiingoIntradayProvider
from ..providers.twelve_data import TwelveDataProvider

def _dt(value):
    if isinstance(value,datetime):return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text=str(value).replace("Z","+00:00")
    d=datetime.fromisoformat(text)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def _num(v,default=None):
    try:return default if v in (None,"") else float(v)
    except (TypeError,ValueError):return default

def _upsert_stock(db:Session,rows:list[dict]):
    if not rows:return 0
    stmt=insert(IntradayBar).values(rows)
    stmt=stmt.on_conflict_do_update(
        constraint="uq_intraday_bar_source",
        set_={k:getattr(stmt.excluded,k) for k in ("open","high","low","close","volume","vwap","trade_count","feed","raw","retrieved_at")}
    )
    db.execute(stmt);db.commit();return len(rows)

def _upsert_options(db:Session,rows:list[dict]):
    if not rows:return 0
    stmt=insert(OptionIntradayBar).values(rows)
    stmt=stmt.on_conflict_do_update(
        constraint="uq_option_intraday_bar_source",
        set_={k:getattr(stmt.excluded,k) for k in ("open","high","low","close","volume","vwap","trade_count","feed","raw","retrieved_at")}
    )
    db.execute(stmt);db.commit();return len(rows)

def backfill_stock(db:Session,symbol:str,start:str,end:str,provider:str="twelve_data",interval:str="1min",feed:str|None=None):
    symbol=symbol.strip().upper();run=IntradayIngestionRun(provider=provider,dataset="stock_bars",symbol=symbol,status="running",details={"start":start,"end":end,"interval":interval,"feed":feed});db.add(run);db.commit();db.refresh(run)
    try:
        now=datetime.now(timezone.utc);rows=[]
        if provider=="alpaca":
            p=AlpacaIntradayProvider();data=p.stock_bars(symbol,start,end,timeframe="1Min" if interval=="1min" else interval,feed=feed or "iex")
            for x in data["bars"]:
                rows.append({"symbol":symbol,"asset_type":"stock","interval":interval,"bar_time":_dt(x["t"]),"open":_num(x["o"],0),"high":_num(x["h"],0),"low":_num(x["l"],0),"close":_num(x["c"],0),"volume":_num(x.get("v"),0),"vwap":_num(x.get("vw")),"trade_count":int(x["n"]) if x.get("n") is not None else None,"provider":"Alpaca","feed":data["feed"],"source_url":data["source_url"],"raw":x,"retrieved_at":now})
        elif provider=="tiingo":
            p=TiingoIntradayProvider();data=p.stock_bars(symbol,start,end,resample=interval,derived=(feed or "derived")!="iex")
            for x in data["bars"]:
                rows.append({"symbol":symbol,"asset_type":"stock","interval":interval,"bar_time":_dt(x["date"]),"open":_num(x["open"],0),"high":_num(x["high"],0),"low":_num(x["low"],0),"close":_num(x["close"],0),"volume":_num(x.get("volume"),0),"vwap":None,"trade_count":None,"provider":"Tiingo","feed":data["feed"],"source_url":data["source_url"],"raw":x,"retrieved_at":now})
        elif provider=="twelve_data":
            p=TwelveDataProvider();data=p.intraday_history(symbol,interval=interval,outputsize=5000,start_date=start,end_date=end)
            for x in data.get("values") or []:
                rows.append({"symbol":symbol,"asset_type":"stock","interval":interval,"bar_time":_dt(x["datetime"]),"open":_num(x["open"],0),"high":_num(x["high"],0),"low":_num(x["low"],0),"close":_num(x["close"],0),"volume":_num(x.get("volume"),0),"vwap":None,"trade_count":None,"provider":"Twelve Data","feed":"default","source_url":"https://twelvedata.com/docs","raw":x,"retrieved_at":now})
        else:raise ValueError("provider must be alpaca, tiingo, or twelve_data")
        count=_upsert_stock(db,rows);run.status="completed";run.rows_written=count;run.completed_at=datetime.now(timezone.utc);db.commit()
        return {"run_id":run.id,"symbol":symbol,"provider":provider,"rows_written":count}
    except Exception as exc:
        db.rollback();run=db.get(IntradayIngestionRun,run.id);run.status="failed";run.completed_at=datetime.now(timezone.utc);run.details={**(run.details or {}),"error":str(exc)[:500]};db.commit();raise

def backfill_options_alpaca(db:Session,contracts:list[dict],start:str,end:str,interval:str="1min",feed:str="indicative"):
    if not contracts:return {"rows_written":0}
    run=IntradayIngestionRun(provider="alpaca",dataset="option_bars",symbol=contracts[0].get("underlying"),status="running",details={"start":start,"end":end,"contracts":len(contracts),"feed":feed});db.add(run);db.commit();db.refresh(run)
    try:
        metadata={x["contract"]:x for x in contracts};p=AlpacaIntradayProvider();data=p.option_bars(list(metadata),start,end,timeframe="1Min" if interval=="1min" else interval,feed=feed);now=datetime.now(timezone.utc);rows=[]
        for contract,x in data["bars"]:
            m=metadata.get(contract) or {}
            rows.append({"contract":contract,"underlying":m["underlying"].upper(),"expiration":m["expiration"],"option_type":m["option_type"],"strike":float(m["strike"]),"interval":interval,"bar_time":_dt(x["t"]),"open":_num(x["o"],0),"high":_num(x["h"],0),"low":_num(x["l"],0),"close":_num(x["c"],0),"volume":_num(x.get("v"),0),"vwap":_num(x.get("vw")),"trade_count":int(x["n"]) if x.get("n") is not None else None,"provider":"Alpaca","feed":data["feed"],"source_url":data["source_url"],"raw":x,"retrieved_at":now})
        count=_upsert_options(db,rows);run.status="completed";run.rows_written=count;run.completed_at=datetime.now(timezone.utc);db.commit();return {"run_id":run.id,"rows_written":count}
    except Exception as exc:
        db.rollback();run=db.get(IntradayIngestionRun,run.id);run.status="failed";run.completed_at=datetime.now(timezone.utc);run.details={**(run.details or {}),"error":str(exc)[:500]};db.commit();raise

def coverage(db:Session,symbol:str|None=None):
    q=db.query(IntradayBar.provider,IntradayBar.symbol,func.min(IntradayBar.bar_time),func.max(IntradayBar.bar_time),func.count(IntradayBar.id)).group_by(IntradayBar.provider,IntradayBar.symbol)
    if symbol:q=q.filter(IntradayBar.symbol==symbol.upper())
    stocks=[{"provider":p,"symbol":s,"start":a.isoformat() if a else None,"end":b.isoformat() if b else None,"rows":n} for p,s,a,b,n in q.all()]
    oq=db.query(OptionIntradayBar.provider,OptionIntradayBar.underlying,func.min(OptionIntradayBar.bar_time),func.max(OptionIntradayBar.bar_time),func.count(OptionIntradayBar.id),func.count(func.distinct(OptionIntradayBar.contract))).group_by(OptionIntradayBar.provider,OptionIntradayBar.underlying)
    if symbol:oq=oq.filter(OptionIntradayBar.underlying==symbol.upper())
    options=[{"provider":p,"underlying":s,"start":a.isoformat() if a else None,"end":b.isoformat() if b else None,"rows":n,"contracts":c} for p,s,a,b,n,c in oq.all()]
    return {"stocks":stocks,"options":options}
