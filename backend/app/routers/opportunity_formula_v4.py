from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.opportunity_formula_v4 import (
    CRITERIA,
    DEFAULT_FORMULA,
    FILTER_FIELDS,
    SCHEMA_VERSION,
    build_opportunity_index,
    formula_metadata,
    validate_filters,
    validate_formula,
)
from ..v4_models import OpportunityFormulaPresetV4
from .intelligence import current_user

router = APIRouter(prefix="/api/v1/opportunities", tags=["opportunity-formula-v4"])


class HardFilter(BaseModel):
    field: str
    operator: str
    value: float


class FormulaDefinition(BaseModel):
    criteria: dict[str, float] = Field(default_factory=dict)
    filters: list[HardFilter] = Field(default_factory=list)


class FormulaPresetCreate(FormulaDefinition):
    name: str = Field(min_length=1, max_length=120)


class FormulaPresetUpdate(FormulaDefinition):
    name: str = Field(min_length=1, max_length=120)


def _clean_name(value: str) -> str:
    clean = " ".join(value.split()).strip()
    if not clean:
        raise HTTPException(status_code=400, detail="Formula name is required")
    return clean


def _decode_config(value: dict | None) -> tuple[dict, list[dict]]:
    raw = dict(value or {})
    if "weights" in raw:
        return dict(raw.get("weights") or {}), list(raw.get("filters") or [])
    return raw, []


def _stored_config(criteria: dict, filters: list[dict]) -> dict:
    return {"weights": criteria, "filters": filters}


def _preset(row: OpportunityFormulaPresetV4) -> dict:
    criteria, filters = _decode_config(row.criteria)
    return {
        "id": row.id,
        "name": row.name,
        "built_in": False,
        "schema_version": row.schema_version,
        "criteria": criteria,
        "filters": filters,
        "formula": formula_metadata(criteria, filters),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _clean_definition(payload: FormulaDefinition) -> tuple[dict, list[dict]]:
    criteria = validate_formula(payload.criteria or DEFAULT_FORMULA)
    filters = validate_filters([item.model_dump() for item in payload.filters])
    return criteria, filters


@router.get("/criteria")
def opportunity_criteria(user: str = Depends(current_user)):
    _ = user
    return {
        "schema_version": SCHEMA_VERSION,
        "criteria": list(CRITERIA.values()),
        "filters": list(FILTER_FIELDS.values()),
        "default_formula": formula_metadata(DEFAULT_FORMULA, []),
    }


@router.post("/index")
def opportunity_index(
    payload: FormulaDefinition,
    include_etfs: bool = Query(default=False),
    limit: int = Query(default=300, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    _ = user
    try:
        criteria, filters = _clean_definition(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_opportunity_index(db, criteria=criteria, filters=filters, include_etfs=include_etfs, limit=limit)


@router.get("/formulas")
def list_opportunity_formulas(db: Session = Depends(get_db), user: str = Depends(current_user)):
    rows = (
        db.query(OpportunityFormulaPresetV4)
        .filter(OpportunityFormulaPresetV4.user_id == user)
        .order_by(OpportunityFormulaPresetV4.name.asc())
        .all()
    )
    return {
        "default": {
            "id": "default",
            "name": "Default Opportunity",
            "built_in": True,
            "schema_version": SCHEMA_VERSION,
            "criteria": DEFAULT_FORMULA,
            "filters": [],
            "formula": formula_metadata(DEFAULT_FORMULA, []),
        },
        "saved": [_preset(row) for row in rows],
    }


@router.post("/formulas", status_code=201)
def create_opportunity_formula(
    payload: FormulaPresetCreate,
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    try:
        criteria, filters = _clean_definition(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = OpportunityFormulaPresetV4(
        user_id=user,
        name=_clean_name(payload.name),
        schema_version=SCHEMA_VERSION,
        criteria=_stored_config(criteria, filters),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A saved Opportunity formula already uses that name") from exc
    db.refresh(row)
    return _preset(row)


@router.put("/formulas/{formula_id}")
def update_opportunity_formula(
    formula_id: int,
    payload: FormulaPresetUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    row = (
        db.query(OpportunityFormulaPresetV4)
        .filter(OpportunityFormulaPresetV4.id == formula_id, OpportunityFormulaPresetV4.user_id == user)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Saved Opportunity formula not found")
    try:
        criteria, filters = _clean_definition(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row.name = _clean_name(payload.name)
    row.criteria = _stored_config(criteria, filters)
    row.schema_version = SCHEMA_VERSION
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A saved Opportunity formula already uses that name") from exc
    db.refresh(row)
    return _preset(row)


@router.delete("/formulas/{formula_id}", status_code=204)
def delete_opportunity_formula(
    formula_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    row = (
        db.query(OpportunityFormulaPresetV4)
        .filter(OpportunityFormulaPresetV4.id == formula_id, OpportunityFormulaPresetV4.user_id == user)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Saved Opportunity formula not found")
    db.delete(row)
    db.commit()
    return None
