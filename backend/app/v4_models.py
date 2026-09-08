from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RotationSnapshotV4(Base):
    __tablename__ = "rotation_snapshots_v4"
    __table_args__ = (UniqueConstraint("symbol", "observation_date", "model_version", name="uq_rotation_v4_symbol_date_model"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    observation_date: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    rotation_score: Mapped[float] = mapped_column(Float, nullable=False)
    rotation_pressure: Mapped[float] = mapped_column(Float, nullable=False)
    state: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    forward_bias: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    conviction: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)


class CandidateObservationV4(Base):
    __tablename__ = "candidate_observations_v4"
    __table_args__ = (UniqueConstraint("symbol", "observation_date", "model_version", name="uq_candidate_v4_symbol_date_model"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    observation_date: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    funnel_score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    setup_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    rotation_proxy: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)


class CandidateOutcomeV4(Base):
    __tablename__ = "candidate_outcomes_v4"
    __table_args__ = (UniqueConstraint("candidate_id", "horizon_days", name="uq_candidate_outcome_v4_horizon"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_favorable_excursion_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_adverse_excursion_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="pending")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)
