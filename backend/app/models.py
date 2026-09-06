from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint, func
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

class UserProfile(Base):
    __tablename__="user_profiles"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    email:Mapped[str]=mapped_column(String(320),unique=True,index=True,nullable=False)
    role:Mapped[str]=mapped_column(String(32),default="approved_user",nullable=False)
    enabled:Mapped[bool]=mapped_column(Boolean,default=True,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)

class UserWatchlistItem(Base):
    __tablename__="user_watchlist_items";__table_args__=(UniqueConstraint("user_email","symbol",name="uq_user_watchlist_symbol"),)
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    user_email:Mapped[str]=mapped_column(String(320),index=True,nullable=False)
    symbol:Mapped[str]=mapped_column(String(20),index=True,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)

class SymbolRegistry(Base):
    __tablename__="symbol_registry"
    symbol:Mapped[str]=mapped_column(String(20),primary_key=True)
    name:Mapped[str|None]=mapped_column(String(256),nullable=True)
    asset_type:Mapped[str|None]=mapped_column(String(64),nullable=True)
    exchange:Mapped[str|None]=mapped_column(String(64),nullable=True)
    sector:Mapped[str|None]=mapped_column(String(128),nullable=True)
    industry:Mapped[str|None]=mapped_column(String(128),nullable=True)
    themes:Mapped[dict]=mapped_column(JSON,default=dict,nullable=False)
    provider_ids:Mapped[dict]=mapped_column(JSON,default=dict,nullable=False)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now(),nullable=False)

class FeatureSnapshot(Base):
    __tablename__="feature_snapshots";__table_args__=(UniqueConstraint("symbol","as_of",name="uq_feature_symbol_date"),)
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    symbol:Mapped[str]=mapped_column(String(20),index=True,nullable=False)
    as_of:Mapped[str]=mapped_column(String(32),index=True,nullable=False)
    payload:Mapped[dict]=mapped_column(JSON,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),index=True,nullable=False)

class PortfolioHolding(Base):
    __tablename__="portfolio_holdings";__table_args__=(UniqueConstraint("user_email","symbol",name="uq_portfolio_user_symbol"),)
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    user_email:Mapped[str]=mapped_column(String(320),index=True,nullable=False)
    symbol:Mapped[str]=mapped_column(String(20),index=True,nullable=False)
    shares:Mapped[float]=mapped_column(Float,default=0.0,nullable=False)
    average_cost:Mapped[float]=mapped_column(Float,default=0.0,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now(),nullable=False)

class AlertRule(Base):
    __tablename__="alert_rules"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    user_email:Mapped[str]=mapped_column(String(320),index=True,nullable=False)
    symbol:Mapped[str|None]=mapped_column(String(20),index=True,nullable=True)
    kind:Mapped[str]=mapped_column(String(64),index=True,nullable=False)
    operator:Mapped[str]=mapped_column(String(8),default=">=",nullable=False)
    threshold:Mapped[float|None]=mapped_column(Float,nullable=True)
    label:Mapped[str]=mapped_column(String(256),nullable=False)
    enabled:Mapped[bool]=mapped_column(Boolean,default=True,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)

class Thesis(Base):
    __tablename__="theses"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    user_email:Mapped[str]=mapped_column(String(320),index=True,nullable=False)
    title:Mapped[str]=mapped_column(String(200),nullable=False)
    statement:Mapped[str]=mapped_column(Text,nullable=False)
    symbols:Mapped[dict]=mapped_column(JSON,default=dict,nullable=False)
    enabled:Mapped[bool]=mapped_column(Boolean,default=True,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now(),nullable=False)

class RefreshQueueItem(Base):
    __tablename__="refresh_queue"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    symbol:Mapped[str]=mapped_column(String(20),index=True,nullable=False)
    data_class:Mapped[str]=mapped_column(String(64),index=True,nullable=False)
    priority:Mapped[int]=mapped_column(Integer,default=50,index=True,nullable=False)
    status:Mapped[str]=mapped_column(String(32),default="queued",index=True,nullable=False)
    requested_by:Mapped[str|None]=mapped_column(String(320),nullable=True)
    error:Mapped[str|None]=mapped_column(String(512),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),index=True,nullable=False)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now(),index=True,nullable=False)
