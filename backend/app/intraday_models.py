from datetime import datetime
from sqlalchemy import DateTime, Float, Integer, JSON, String, UniqueConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class IntradayBar(Base):
    __tablename__="intraday_bars"
    __table_args__=(
        UniqueConstraint("symbol","bar_time","interval","provider",name="uq_intraday_bar_source"),
        Index("ix_intraday_symbol_time","symbol","bar_time"),
    )
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    symbol:Mapped[str]=mapped_column(String(32),index=True,nullable=False)
    asset_type:Mapped[str]=mapped_column(String(16),default="stock",index=True,nullable=False)
    interval:Mapped[str]=mapped_column(String(16),default="1min",nullable=False)
    bar_time:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True,nullable=False)
    open:Mapped[float]=mapped_column(Float,nullable=False)
    high:Mapped[float]=mapped_column(Float,nullable=False)
    low:Mapped[float]=mapped_column(Float,nullable=False)
    close:Mapped[float]=mapped_column(Float,nullable=False)
    volume:Mapped[float]=mapped_column(Float,default=0.0,nullable=False)
    vwap:Mapped[float|None]=mapped_column(Float,nullable=True)
    trade_count:Mapped[int|None]=mapped_column(Integer,nullable=True)
    provider:Mapped[str]=mapped_column(String(32),index=True,nullable=False)
    feed:Mapped[str|None]=mapped_column(String(32),nullable=True)
    source_url:Mapped[str]=mapped_column(String(1024),nullable=False)
    raw:Mapped[dict]=mapped_column(JSON,default=dict,nullable=False)
    retrieved_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),index=True,nullable=False)

class OptionIntradayBar(Base):
    __tablename__="option_intraday_bars"
    __table_args__=(
        UniqueConstraint("contract","bar_time","interval","provider",name="uq_option_intraday_bar_source"),
        Index("ix_option_underlying_time","underlying","bar_time"),
    )
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    contract:Mapped[str]=mapped_column(String(64),index=True,nullable=False)
    underlying:Mapped[str]=mapped_column(String(32),index=True,nullable=False)
    expiration:Mapped[str]=mapped_column(String(16),index=True,nullable=False)
    option_type:Mapped[str]=mapped_column(String(8),index=True,nullable=False)
    strike:Mapped[float]=mapped_column(Float,index=True,nullable=False)
    interval:Mapped[str]=mapped_column(String(16),default="1min",nullable=False)
    bar_time:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True,nullable=False)
    open:Mapped[float]=mapped_column(Float,nullable=False)
    high:Mapped[float]=mapped_column(Float,nullable=False)
    low:Mapped[float]=mapped_column(Float,nullable=False)
    close:Mapped[float]=mapped_column(Float,nullable=False)
    volume:Mapped[float]=mapped_column(Float,default=0.0,nullable=False)
    vwap:Mapped[float|None]=mapped_column(Float,nullable=True)
    trade_count:Mapped[int|None]=mapped_column(Integer,nullable=True)
    provider:Mapped[str]=mapped_column(String(32),index=True,nullable=False)
    feed:Mapped[str|None]=mapped_column(String(32),nullable=True)
    source_url:Mapped[str]=mapped_column(String(1024),nullable=False)
    raw:Mapped[dict]=mapped_column(JSON,default=dict,nullable=False)
    retrieved_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),index=True,nullable=False)

class IntradayIngestionRun(Base):
    __tablename__="intraday_ingestion_runs"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    provider:Mapped[str]=mapped_column(String(32),index=True,nullable=False)
    dataset:Mapped[str]=mapped_column(String(64),index=True,nullable=False)
    symbol:Mapped[str|None]=mapped_column(String(64),index=True,nullable=True)
    started_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)
    completed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    status:Mapped[str]=mapped_column(String(24),index=True,nullable=False,default="running")
    rows_written:Mapped[int]=mapped_column(Integer,default=0,nullable=False)
    cursor:Mapped[str|None]=mapped_column(String(2048),nullable=True)
    details:Mapped[dict]=mapped_column(JSON,default=dict,nullable=False)

class IntradayResearchResult(Base):
    __tablename__="intraday_research_results"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    strategy:Mapped[str]=mapped_column(String(128),index=True,nullable=False)
    version:Mapped[str]=mapped_column(String(32),index=True,nullable=False)
    symbol:Mapped[str]=mapped_column(String(32),index=True,nullable=False)
    start_date:Mapped[str]=mapped_column(String(16),nullable=False)
    end_date:Mapped[str]=mapped_column(String(16),nullable=False)
    parameters:Mapped[dict]=mapped_column(JSON,default=dict,nullable=False)
    metrics:Mapped[dict]=mapped_column(JSON,default=dict,nullable=False)
    provenance:Mapped[dict]=mapped_column(JSON,default=dict,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),index=True,nullable=False)
