from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class PortfolioBaseline(Base):
    __tablename__ = "portfolio_baselines"
    portfolio_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initial_cash: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    initial_invested_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    initial_total_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PortfolioPositionBaseline(Base):
    __tablename__ = "portfolio_position_baselines"
    position_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initial_shares: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    initial_average_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    initial_cost_basis: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    initial_market_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    initial_market_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PortfolioPositionRevision(Base):
    __tablename__ = "portfolio_position_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    average_cost: Mapped[float] = mapped_column(Float, nullable=False)
    cost_basis: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    endpoint_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    subscription: Mapped[dict] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AlertDeliveryPreference(Base):
    __tablename__ = "alert_delivery_preferences"
    __table_args__ = (UniqueConstraint("alert_id", name="uq_alert_delivery_rule"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    user_email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    channels: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=360, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
