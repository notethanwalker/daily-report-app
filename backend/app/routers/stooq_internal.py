from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.stooq_durable_import import create_upload, finalize_upload, process_batch, status, write_chunk

router = APIRouter(prefix="/internal/stooq", tags=["stooq-internal"])


class UploadInit(BaseModel):
    filename: str = "stooq_opportunities_package.zip"
    total_bytes: int


def _require_token(request: Request) -> None:
    expected = os.getenv("STOOQ_IMPORT_TOKEN") or ""
    provided = request.headers.get("x-stooq-import-token") or ""
    if not expected or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid Stooq import token")


@router.post("/init")
def init_upload(payload: UploadInit, request: Request, db: Session = Depends(get_db)):
    _require_token(request)
    try:
        return create_upload(db, payload.filename, payload.total_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{upload_id}/chunk")
async def upload_chunk(upload_id: str, request: Request, offset: int = Query(ge=0), db: Session = Depends(get_db)):
    _require_token(request)
    body = await request.body()
    max_chunk = int(os.getenv("STOOQ_UPLOAD_MAX_CHUNK_BYTES", str(16 * 1024 * 1024)))
    if not body or len(body) > max_chunk:
        raise HTTPException(status_code=400, detail=f"Chunk must be between 1 and {max_chunk} bytes")
    try:
        return write_chunk(db, upload_id, offset, body)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{upload_id}/finalize", status_code=202)
def finalize(upload_id: str, request: Request, db: Session = Depends(get_db)):
    _require_token(request)
    try:
        return finalize_upload(db, upload_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{upload_id}")
def get_status(upload_id: str, request: Request, db: Session = Depends(get_db)):
    _require_token(request)
    try:
        return status(db, upload_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/process/next")
def process_next(request: Request, batch_symbols: int = Query(default=500, ge=1, le=2000), db: Session = Depends(get_db)):
    _require_token(request)
    try:
        return process_batch(db, batch_symbols=batch_symbols)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)[:1000]) from exc
