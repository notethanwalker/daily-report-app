from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth_models import AuthAccount
from ..database import get_db
from ..models import PortfolioHolding, UserWatchlistItem
from ..multiuser_models import PortfolioDefinition, PortfolioPosition
from ..normalized_market_models import MarketPipelineState
from ..services.market_data_pipeline import pipeline_status
from ..services.opportunity_scanner import scan_cached_market
from ..services.stooq_durable_import import (
    create_upload as create_durable_upload,
    finalize_upload as finalize_durable_upload,
    process_batch as process_durable_batch,
    status as durable_upload_status,
    write_chunk as write_durable_chunk,
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


def _require_import_token(request: Request) -> None:
    expected = os.getenv("STOOQ_IMPORT_TOKEN") or ""
    provided = request.headers.get("x-stooq-import-token") or ""
    if not expected or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid Stooq import token")


def _state(db: Session, key: str) -> dict:
    row = db.get(MarketPipelineState, key)
    return dict(row.payload or {}) if row else {}


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
    rows.sort(key=lambda x: max(float(x.get("buy_score") or 0), float(x.get("sell_score") or 0)), reverse=True)
    counts = {k: sum(1 for r in rows if r["signal"] == k) for k in ("strong_buy", "buy", "neutral", "sell", "strong_sell")}
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
    return scan_cached_market(db, include_near=include_near, limit_per_bucket=limit, include_etfs=include_etfs)


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
        "historical_authority": "Stooq durable manual archive",
        "incremental_daily_freshness": "Yahoo Finance after canonical import",
        "tracked_symbol_freshness": "Twelve Data with Yahoo verification",
    }
    return result


@router.post("/stooq-archive/init")
def init_stooq_archive_upload(payload: StooqUploadInit, db: Session = Depends(get_db), user: str = Depends(current_user)):
    _require_owner(db, user)
    try:
        return create_durable_upload(db, payload.filename, payload.total_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        return write_durable_chunk(db, upload_id, offset, body)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/stooq-archive/{upload_id}")
def stooq_archive_upload_status(upload_id: str, db: Session = Depends(get_db), user: str = Depends(current_user)):
    _require_owner(db, user)
    try:
        return durable_upload_status(db, upload_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/stooq-archive/{upload_id}/finalize", status_code=202)
def finalize_stooq_archive_upload(upload_id: str, db: Session = Depends(get_db), user: str = Depends(current_user)):
    _require_owner(db, user)
    try:
        result = finalize_durable_upload(db, upload_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "upload_id": upload_id,
        "status": result["status"],
        "message": "Stooq archive is durably queued in Postgres. The resumable importer will process it independently of web-service restarts.",
    }


@router.post("/stooq-archive/process")
def process_stooq_archive(request: Request, batch_symbols: int = Query(default=500, ge=1, le=2000), db: Session = Depends(get_db)):
    _require_import_token(request)
    try:
        return process_durable_batch(db, batch_symbols=batch_symbols)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)[:1000]) from exc


@router.post("/stooq-archive/token/init")
def token_init_stooq_archive(payload: StooqUploadInit, request: Request, db: Session = Depends(get_db)):
    _require_import_token(request)
    try:
        return create_durable_upload(db, payload.filename, payload.total_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/stooq-archive/token/{upload_id}/chunk")
async def token_upload_stooq_archive_chunk(upload_id: str, request: Request, offset: int = Query(ge=0), db: Session = Depends(get_db)):
    _require_import_token(request)
    body = await request.body()
    max_chunk = int(os.getenv("STOOQ_UPLOAD_MAX_CHUNK_BYTES", str(16 * 1024 * 1024)))
    if not body or len(body) > max_chunk:
        raise HTTPException(status_code=400, detail=f"Chunk must be between 1 and {max_chunk} bytes")
    try:
        return write_durable_chunk(db, upload_id, offset, body)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/stooq-archive/token/{upload_id}/finalize", status_code=202)
def token_finalize_stooq_archive(upload_id: str, request: Request, db: Session = Depends(get_db)):
    _require_import_token(request)
    try:
        return finalize_durable_upload(db, upload_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
