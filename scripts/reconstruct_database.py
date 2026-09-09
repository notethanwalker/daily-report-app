#!/usr/bin/env python3
"""Create the schema and reconstruct only state supported by auditable sources.

This intentionally does not invent users, alerts, theses, preferences, or edits
that existed only in the failed database.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app import (  # noqa: E402,F401
    auth_models,
    future_models,
    intelligence_cache_models,
    models,
    multiuser_models,
    normalized_market_models,
    v2_models,
    v3_models,
    v4_models,
)
from app.auth_models import AuthAccount  # noqa: E402
from app.main import DEFAULT_WATCHLIST  # noqa: E402
from app.models import UserWatchlistItem, WatchlistItem  # noqa: E402
from app.multiuser_models import PortfolioDefinition, PortfolioPosition  # noqa: E402
from app.routers.portfolio_access import _ensure_joint_fidelity  # noqa: E402
from app.services.auth_security import bootstrap_admin  # noqa: E402
from app.services.storage_guard import capacity_status  # noqa: E402


def reconstruct() -> dict:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for symbol in DEFAULT_WATCHLIST:
            if not db.get(WatchlistItem, symbol):
                db.add(WatchlistItem(symbol=symbol))
        db.commit()

        owner = bootstrap_admin(db)
        if owner is None:
            owner = (
                db.query(AuthAccount)
                .filter(
                    AuthAccount.role == "owner",
                    AuthAccount.status == "approved",
                    AuthAccount.enabled.is_(True),
                )
                .order_by(AuthAccount.created_at.asc())
                .first()
            )
        if owner is None:
            return {
                "status": "shared_state_reconstructed_owner_pending",
                "schema_tables": len(Base.metadata.tables),
                "shared_watchlist_symbols": db.query(WatchlistItem).count(),
                "capacity": capacity_status(db),
                "next_step": "Run this command again where the existing AUTH_BOOTSTRAP_ADMIN_* variables are available.",
                "not_reconstructed": [
                    "owner account and owner-scoped defaults",
                    "Joint Fidelity portfolio and positions",
                    "other users",
                    "custom watchlist edits",
                    "alerts and push subscriptions",
                    "theses and custom events",
                    "user preference edits",
                    "historical snapshots and disposable market caches",
                ],
            }

        os.environ["OWNER_EMAIL"] = owner.id
        existing_symbols = {
            row.symbol
            for row in db.query(UserWatchlistItem)
            .filter(UserWatchlistItem.user_email == owner.id)
            .all()
        }
        for symbol in DEFAULT_WATCHLIST:
            if symbol not in existing_symbols:
                db.add(UserWatchlistItem(user_email=owner.id, symbol=symbol))
        db.commit()
        _ensure_joint_fidelity(db, owner.id)

        portfolio = (
            db.query(PortfolioDefinition)
            .filter(
                PortfolioDefinition.user_email == owner.id,
                PortfolioDefinition.name == "Joint Fidelity",
            )
            .first()
        )
        return {
            "status": "reconstructed",
            "schema_tables": len(Base.metadata.tables),
            "owner_accounts": db.query(AuthAccount).filter(AuthAccount.role == "owner").count(),
            "shared_watchlist_symbols": db.query(WatchlistItem).count(),
            "owner_watchlist_symbols": db.query(UserWatchlistItem)
            .filter(
                UserWatchlistItem.user_email == owner.id,
                UserWatchlistItem.symbol != "__INITIALIZED__",
            )
            .count(),
            "portfolio_definitions": db.query(PortfolioDefinition)
            .filter(PortfolioDefinition.user_email == owner.id)
            .count(),
            "portfolio_positions": db.query(PortfolioPosition)
            .filter(PortfolioPosition.portfolio_id == portfolio.id)
            .count()
            if portfolio
            else 0,
            "capacity": capacity_status(db),
            "not_reconstructed": [
                "other users",
                "custom watchlist edits",
                "alerts and push subscriptions",
                "theses and custom events",
                "user preference edits",
                "historical snapshots and disposable market caches",
            ],
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(json.dumps(reconstruct(), indent=2, sort_keys=True))
