from datetime import datetime
from sqlalchemy import DateTime, Float, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class WatchlistItem(Base):
    __tablename__="watchlist_items";symbol:Mapped[str]=mapped_column(String(20),primary_key=True);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)
class MarketSnapshot(Base):
    __tablename__="market_snapshots";id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True);symbol:Mapped[str]=mapped_column(String(20),index=True,nullable=False);as_of:Mapped[str]=mapped_column(String(64),nullable=False);provider:Mapped[str]=mapped_column(String(64),nullable=False);payload:Mapped[dict]=mapped_column(JSON,nullable=False);retrieved_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),index=True,nullable=False)
class HistoricalDailyBar(Base):
    __tablename__="historical_daily_bars";__table_args__=(UniqueConstraint("symbol","bar_date",name="uq_historical_symbol_date"),);id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True);symbol:Mapped[str]=mapped_column(String(20),index=True,nullable=False);bar_date:Mapped[str]=mapped_column(String(16),index=True,nullable=False);close:Mapped[float]=mapped_column(Float,nullable=False);volume:Mapped[float]=mapped_column(Float,nullable=False,default=0.0);provider:Mapped[str]=mapped_column(String(64),nullable=False);source_url:Mapped[str]=mapped_column(String(1024),nullable=False);retrieved_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),index=True,nullable=False)
class SecondaryVerificationCache(Base):
    __tablename__="secondary_verification_cache";symbol:Mapped[str]=mapped_column(String(20),primary_key=True);provider:Mapped[str]=mapped_column(String(64),nullable=False);payload:Mapped[dict]=mapped_column(JSON,nullable=False);retrieved_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now(),index=True,nullable=False)
class FundamentalCache(Base):
    __tablename__="fundamental_cache";symbol:Mapped[str]=mapped_column(String(20),primary_key=True);provider:Mapped[str]=mapped_column(String(64),nullable=False);payload:Mapped[dict]=mapped_column(JSON,nullable=False);retrieved_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now(),index=True,nullable=False)
class ReportSnapshot(Base):
    __tablename__="report_snapshots";id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True);report_date:Mapped[str]=mapped_column(String(16),index=True,nullable=False);payload:Mapped[dict]=mapped_column(JSON,nullable=False);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),index=True,nullable=False)
class FlowEvent(Base):
    __tablename__="flow_events";id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True);event_type:Mapped[str]=mapped_column(String(32),index=True,nullable=False);symbol:Mapped[str]=mapped_column(String(20),index=True,nullable=False);provider:Mapped[str]=mapped_column(String(64),nullable=False);outlier_score:Mapped[float]=mapped_column(Float,index=True,nullable=False,default=0.0);source_url:Mapped[str]=mapped_column(String(1024),nullable=False);payload:Mapped[dict]=mapped_column(JSON,nullable=False);occurred_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True,nullable=False);retrieved_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),index=True,nullable=False)
