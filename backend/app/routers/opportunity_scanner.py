from __future__ import annotations

import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth_models import AuthAccount
from ..database import SessionLocal, get_db
from ..models import PortfolioHolding, UserWatchlistItem
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from ..normalized_market_models import MarketPipelineState
from ..services.market_data_pipeline import pipeline_status
from ..services.opportunity_scanner import scan_cached_market
from ..services.stooq_manual_import import import_stooq_archive
from ..services.stooq_upload_session import (
    cleanup_archive_bytes,
    create_upload,
    finalize_upload,
    mark_imported,
    upload_status,
    write_chunk,
)
from .intelligence import _opportunity_components, current_user

router = APIRouter(prefix="/api/v1/opportunities", tags=["opportunity-scanner"])


class StooqUploadInit(BaseModel):
    filename: str = "d_us_txt.zip"
    total_bytes: int


def _require_owner(db: Session, user: str) -> None:
    account = db.get(AuthAccount, user)
    if not account or account.role != "owner" or not account.enabled:
        raise HTTPException(status_code=403, detail="Owner access required")


def _state(db: Session, key: str) -> dict:
    row = db.get(MarketPipelineState, key)
    return dict(row.payload or {}) if row else {}


def _run_stooq_import(upload_id: str, archive_path: str, archive_name: str) -> None:
    db = SessionLocal()
    try:
        result = import_stooq_archive(db, archive_path, archive_name=archive_name)
        mark_imported(upload_id, result=result)
    except Exception as exc:
        db.rollback()
        mark_imported(upload_id, error=str(exc)[:1000])
    finally:
        db.close()
        cleanup_archive_bytes(upload_id)


def _tracked_symbols(db: Session, user: str) -> list[str]:
    symbols = {
        r.symbol.upper()
        for r in db.query(UserWatchlistItem).filter(UserWatchlistItem.user_email == user).all()
        if r.symbol and r.symbol != "__INITIALIZED__"
    }
    symbols |= {
        r.symbol.upper()
        for r in db.query(PortfolioHolding).filter(PortfolioHolding.user_email == user).all()
        if r.symbol
    }
    portfolio_ids = [r.id for r in db.query(PortfolioDefinition).filter(PortfolioDefinition.user_email == user).all()]
    if portfolio_ids:
        symbols |= {
            r.symbol.upper()
            for r in db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id.in_(portfolio_ids)).all()
            if r.symbol
        }
    return sorted(symbols)


def _signal(buy: float | None, sell: float | None) -> str:
    b = float(buy or 0)
    s = float(sell or 0)
    if b >= 80 and b >= s + 10:
        return "strong_buy"
    if b >= 65 and b > s:
        return "buy"
    if s >= 80 and s >= b + 10:
        return "strong_sell"
    if s >= 65 and s > b:
        return "sell"
    return "neutral"


@router.get("/tracked")
def tracked_opportunities(db: Session = Depends(get_db), user: str = Depends(current_user)):
    rows = []
    for symbol in _tracked_symbols(db, user):
        opportunity = _opportunity_components(db, symbol)
        if not opportunity:
            continue
        market = opportunity.get("market") or {}
        rows.append({
            "symbol": symbol,
            "signal": _signal(opportunity.get("buy_score"), opportunity.get("sell_score")),
            "buy_score": opportunity.get("buy_score"),
            "sell_score": opportunity.get("sell_score"),
            "components": opportunity.get("components") or {},
            "flow": opportunity.get("flow") or {},
            "sector_score": opportunity.get("sector_score"),
            "williams_r_14": market.get("williams_r_14"),
            "price_vs_ma100_percent": market.get("price_vs_ma100_percent"),
            "price_vs_ma200_percent": market.get("price_vs_ma200_percent"),
            "ma100_slope_20d_percent": market.get("ma100_slope_20d_percent"),
            "approach_velocity_100_5d": market.get("approach_velocity_100_5d"),
            "price": market.get("price"),
            "change_percent": market.get("change_percent"),
            "as_of": market.get("as_of"),
            "retrieved_at": market.get("retrieved_at"),
            "technical_source": market.get("technical_source"),
        })
    rows.sort(
        key=lambda x: max(float(x.get("buy_score") or 0), float(x.get("sell_score") or 0)),
        reverse=True,
    )
    counts = {
        k: sum(1 for r in rows if r["signal"] == k)
        for k in ("strong_buy", "buy", "neutral", "sell", "strong_sell")
    }
    return {
        "rows": rows,
        "counts": counts,
        "universe": "Authenticated user's Markets watchlist union Portfolio holdings; symbols are deduplicated before scoring.",
        "methodology": "Uses the existing auditable multi-factor buy/sell formula and shared cached symbol data. No additional provider request is made by this endpoint.",
    }


@router.get("/market-scan")
def market_opportunities(
    include_near: bool = Query(default=False),
    include_etfs: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    _ = user
    return scan_cached_market(
        db,
        include_near=include_near,
        limit_per_bucket=limit,
        include_etfs=include_etfs,
    )


@router.get("/data-pipeline")
def opportunity_data_pipeline(db: Session = Depends(get_db), user: str = Depends(current_user)):
    _ = user
    result = pipeline_status(db)
    canonical = _state(db, "stooq_manual_archive")
    incremental = _state(db, "opportunity_incremental")
    result["canonical_stooq_archive"] = canonical
    result["incremental_freshness"] = incremental
    result["canonical_history_ready"] = canonical.get("status") == "ready" and bool(canonical.get("canonical"))
    result["effective_history_policy"] = {
        "historical_authority": "Stooq manual archive",
        "incremental_daily_freshness": "Yahoo Finance",
        "tracked_symbol_freshness": "Twelve Data with Yahoo verification",
    }
    return result


@router.post("/stooq-archive/init")
def init_stooq_archive_upload(
    payload: StooqUploadInit,
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    _require_owner(db, user)
    try:
        session = create_upload(payload.filename, payload.total_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "upload_id": session["upload_id"],
        "chunk_bytes": session["chunk_bytes"],
        "total_bytes": session["total_bytes"],
        "status": session["status"],
    }


@router.put("/stooq-archive/{upload_id}/chunk")
async def upload_stooq_archive_chunk(
    upload_id: str,
    request: Request,
    offset: int = Query(ge=0),
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    _require_owner(db, user)
    max_chunk = int(os.getenv("STOOQ_UPLOAD_MAX_CHUNK_BYTES", str(16 * 1024 * 1024)))
    body = await request.body()
    if not body or len(body) > max_chunk:
        raise HTTPException(status_code=400, detail=f"Chunk must be between 1 and {max_chunk} bytes")
    try:
        state = write_chunk(upload_id, offset, body)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "upload_id": upload_id,
        "received_bytes": state.get("received_bytes", 0),
        "total_bytes": state["total_bytes"],
        "status": state["status"],
    }


@router.get("/stooq-archive/{upload_id}")
def stooq_archive_upload_status(
    upload_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    _require_owner(db, user)
    try:
        return upload_status(upload_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/stooq-archive/{upload_id}/finalize", status_code=202)
def finalize_stooq_archive_upload(
    upload_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    _require_owner(db, user)
    try:
        archive_path, manifest = finalize_upload(upload_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(_run_stooq_import, upload_id, archive_path, manifest.get("filename") or "d_us_txt.zip")
    return {
        "upload_id": upload_id,
        "status": "queued_for_import",
        "message": "Stooq archive upload completed; canonical-history import has started.",
    }
