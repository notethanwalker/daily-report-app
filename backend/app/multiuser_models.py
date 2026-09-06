from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class PortfolioDefinition(Base):
    __tablename__ = "portfolio_definitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    brokerage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    account_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cash: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "symbol", name="uq_portfolio_position_symbol"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    shares: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    average_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    imported_last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    imported_market_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    imported_day_gain: Mapped[float | None] = mapped_column(Float, nullable=True)
    imported_day_gain_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    imported_total_gain: Mapped[float | None] = mapped_column(Float, nullable=True)
    imported_total_gain_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    imported_account_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class UserAccessConfig(Base):
    __tablename__ = "user_access_config"
    user_email: Mapped[str] = mapped_column(String(320), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="approved_user", nullable=False)
    token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    permissions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    allowed_tabs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class UserPreferences(Base):
    __tablename__ = "user_preferences"
    user_email: Mapped[str] = mapped_column(String(320), primary_key=True)
    visible_tabs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    information_modules: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
