from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class PortfolioValueSnapshot(Base):
    __tablename__ = "portfolio_value_snapshots"
    __table_args__ = (UniqueConstraint("portfolio_id", "as_of", name="uq_portfolio_value_snapshot_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    as_of: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    market_value: Mapped[float] = mapped_column(Float, nullable=False)
    invested_value: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)


class UserCustomEvent(Base):
    __tablename__ = "user_custom_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    event_date: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    event_time: Mapped[str | None] = mapped_column(String(16), nullable=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="Custom", index=True, nullable=False)
    impact: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
