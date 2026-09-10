from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .opportunity_scanner import (
    MIN_AVG_DOLLAR_VOLUME_20D,
    MIN_PRICE,
    _confirmation_score,
    _is_scannable,
    _latest_snapshot_rows,
    _ma100_score,
    _registry_map,
    _williams_score,
)

SCHEMA_VERSION = "opportunity-formula-v1"
DEFAULT_FORMULA = {
    "williams": 60.0,
    "ma100_proximity": 30.0,
    "ma100_slope": 5.0,
    "approach_velocity": 5.0,
}
SORT_FIELDS = {"score", "williams", "ma100_proximity", "ma100_slope", "approach_velocity", "liquidity", "symbol"}
SORT_DIRECTIONS = {"asc", "desc"}

CRITERIA = {
    "williams": {
        "key": "williams",
        "label": "Williams %R",
        "description": "Rewards deeper oversold conditions. Default-model primary signal.",
        "raw_field": "williams_r_14",
        "higher_score_is_better": True,
        "hypothesis": "Deep short-term oversold states can create asymmetric mean-reversion entries when other setup conditions are supportive.",
    },
    "ma100_proximity": {
        "key": "ma100_proximity",
        "label": "100MA proximity",
        "description": "Rewards price approaching the 100-day moving average from above.",
        "raw_field": "price_vs_ma100_percent",
        "higher_score_is_better": True,
        "hypothesis": "Pullbacks toward an established medium-term trend reference can improve entry asymmetry without requiring a trend break.",
    },
    "ma100_slope": {
        "key": "ma100_slope",
        "label": "100MA slope",
        "description": "Rewards a positively sloped 100-day moving average.",
        "raw_field": "ma100_slope_20d_percent",
        "higher_score_is_better": True,
        "hypothesis": "A rising 100-day moving average provides trend confirmation and may distinguish constructive pullbacks from structural deterioration.",
    },
    "approach_velocity": {
        "key": "approach_velocity",
        "label": "5D approach velocity",
        "description": "Rewards movement toward the 100MA over the latest five sessions.",
        "raw_field": "approach_velocity_100_5d",
        "higher_score_is_better": True,
        "hypothesis": "A measured approach toward support can identify developing entries before the static distance condition is fully reached.",
    },
}

FILTER_FIELDS = {
    "williams_r_14": {"key": "williams_r_14", "label": "Williams %R", "operators": ["<=", ">="], "default_operator": "<=", "default_value": -80.0},
    "price_vs_ma100_percent": {"key": "price_vs_ma100_percent", "label": "Distance above 100MA (%)", "operators": ["<=", ">="], "default_operator": ">=", "default_value": 0.0},
    "ma100_slope_20d_percent": {"key": "ma100_slope_20d_percent", "label": "100MA 20D slope (%)", "operators": ["<=", ">="], "default_operator": ">=", "default_value": 0.0},
    "approach_velocity_100_5d": {"key": "approach_velocity_100_5d", "label": "5D approach velocity", "operators": ["<=", ">="], "default_operator": ">=", "default_value": 0.0},
}


def _f(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def validate_formula(criteria: dict | None) -> dict[str, float]:
    source = DEFAULT_FORMULA if criteria is None else criteria
    if not isinstance(source, dict) or not source:
        raise ValueError("Formula must contain at least one criterion")
    clean: dict[str, float] = {}
    for key, weight in source.items():
        if key not in CRITERIA:
            raise ValueError(f"Unknown Opportunity criterion: {key}")
        try:
            number = float(weight)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid weight for {key}") from exc
        if number <= 0 or number > 1000:
            raise ValueError(f"Weight for {key} must be greater than 0 and no more than 1000")
        clean[key] = round(number, 4)
    return clean


def validate_filters(filters: list[dict] | None) -> list[dict]:
    clean: list[dict] = []
    for item in filters or []:
        if not isinstance(item, dict):
            raise ValueError("Opportunity filters must be objects")
        field = str(item.get("field") or "").strip()
        operator = str(item.get("operator") or "").strip()
        if field not in FILTER_FIELDS:
            raise ValueError(f"Unknown Opportunity filter field: {field}")
        if operator not in FILTER_FIELDS[field]["operators"]:
            raise ValueError(f"Unsupported operator for {field}: {operator}")
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid filter value for {field}") from exc
        clean.append({"field": field, "operator": operator, "value": round(value, 6)})
    if len(clean) > 12:
        raise ValueError("Opportunity formulas support at most 12 hard filters")
    return clean


def validate_sort(sort_by: str, sort_dir: str) -> tuple[str, str]:
    by = str(sort_by or "score").strip().lower()
    direction = str(sort_dir or "desc").strip().lower()
    if by not in SORT_FIELDS:
        raise ValueError(f"Unsupported Opportunity sort field: {by}")
    if direction not in SORT_DIRECTIONS:
        raise ValueError(f"Unsupported Opportunity sort direction: {direction}")
    return by, direction


def normalized_weights(criteria: dict | None) -> dict[str, float]:
    clean = validate_formula(criteria)
    total = sum(clean.values())
    return {key: round(value / total * 100.0, 4) for key, value in clean.items()}


def score_components(payload: dict) -> dict[str, float | None]:
    williams = _f(payload.get("williams_r_14"))
    ma100_distance = _f(payload.get("price_vs_ma100_percent"))
    _, confirmation = _confirmation_score(payload)
    return {
        "williams": None if williams is None else round(_williams_score(williams), 4),
        "ma100_proximity": None if ma100_distance is None else round(_ma100_score(ma100_distance), 4),
        "ma100_slope": _f(confirmation.get("ma_slope_score")),
        "approach_velocity": _f(confirmation.get("approach_score")),
    }


def formula_score(components: dict[str, float | None], criteria: dict | None) -> float | None:
    weights = validate_formula(criteria)
    if any(components.get(key) is None for key in weights):
        return None
    denominator = sum(weights.values())
    if denominator <= 0:
        return None
    value = sum(float(components[key]) * weight for key, weight in weights.items()) / denominator
    return round(value, 2)


def passes_filters(payload: dict, filters: list[dict] | None) -> bool:
    for item in validate_filters(filters):
        observed = _f(payload.get(item["field"]))
        if observed is None:
            return False
        if item["operator"] == "<=" and not observed <= item["value"]:
            return False
        if item["operator"] == ">=" and not observed >= item["value"]:
            return False
    return True


def formula_metadata(criteria: dict | None, filters: list[dict] | None = None) -> dict:
    clean = validate_formula(criteria)
    clean_filters = validate_filters(filters)
    effective = normalized_weights(clean)
    return {
        "schema_version": SCHEMA_VERSION,
        "criteria": clean,
        "filters": clean_filters,
        "effective_weights_percent": effective,
        "label": " + ".join(f"{effective[key]:.1f}% {CRITERIA[key]['label']}" for key in clean),
        "score_semantics": "Relative Opportunity Index (0–100). It is a ranking score, not an expected-return or probability estimate.",
        "filter_semantics": "Hard screens determine universe membership before ranking and never contribute points to the Opportunity Index.",
    }


def _sort_value(item: dict, sort_by: str):
    if sort_by == "score":
        return item.get("score")
    if sort_by == "symbol":
        return item.get("symbol")
    if sort_by == "liquidity":
        return item.get("average_dollar_volume_20d")
    return (item.get("raw_criteria") or {}).get(sort_by)


def sort_index_rows(rows: list[dict], sort_by: str = "score", sort_dir: str = "desc") -> tuple[list[dict], str, str]:
    by, direction = validate_sort(sort_by, sort_dir)
    present = [item for item in rows if _sort_value(item, by) is not None]
    missing = [item for item in rows if _sort_value(item, by) is None]
    reverse = direction == "desc"
    if by == "symbol":
        present.sort(key=lambda item: str(_sort_value(item, by)), reverse=reverse)
    else:
        present.sort(key=lambda item: (float(_sort_value(item, by)), item.get("symbol") or ""), reverse=reverse)
    ordered = present + missing
    for position, item in enumerate(ordered, 1):
        item["display_position"] = position
    return ordered, by, direction


def build_opportunity_index(
    db: Session,
    *,
    criteria: dict | None = None,
    filters: list[dict] | None = None,
    include_etfs: bool = False,
    limit: int = 300,
    sort_by: str = "score",
    sort_dir: str = "desc",
) -> dict:
    weights = validate_formula(criteria)
    clean_filters = validate_filters(filters)
    requested_sort, requested_direction = validate_sort(sort_by, sort_dir)
    registry = _registry_map(db)
    latest_rows = _latest_snapshot_rows(db)
    rows: list[dict] = []
    scannable = technical_complete = liquidity_eligible = formula_complete = filtered_out = 0
    newest = None

    for row in latest_rows:
        payload = row.payload or {}
        reg = registry.get(row.symbol.upper())
        if not _is_scannable(reg, payload, include_etfs):
            continue
        scannable += 1
        newest = row.retrieved_at if newest is None or row.retrieved_at > newest else newest
        price = _f(payload.get("price"))
        williams = _f(payload.get("williams_r_14"))
        ma100_distance = _f(payload.get("price_vs_ma100_percent"))
        avg_dollar_volume = _f(payload.get("average_dollar_volume_20d"))
        if price is None or williams is None or ma100_distance is None:
            continue
        technical_complete += 1
        if price < MIN_PRICE or avg_dollar_volume is None or avg_dollar_volume < MIN_AVG_DOLLAR_VOLUME_20D:
            continue
        liquidity_eligible += 1
        if not passes_filters(payload, clean_filters):
            filtered_out += 1
            continue
        components = score_components(payload)
        score = formula_score(components, weights)
        if score is None:
            continue
        formula_complete += 1
        raw = {
            "williams": round(williams, 2),
            "ma100_proximity": round(ma100_distance, 3),
            "ma100_slope": _f(payload.get("ma100_slope_20d_percent")),
            "approach_velocity": _f(payload.get("approach_velocity_100_5d")),
        }
        rows.append({
            "symbol": row.symbol.upper(),
            "name": (reg.name if reg else None) or payload.get("name"),
            "sector": (reg.sector if reg else None) or payload.get("sector"),
            "industry": (reg.industry if reg else None) or payload.get("industry"),
            "asset_type": (reg.asset_type if reg else None) or payload.get("asset_type"),
            "score": score,
            "criterion_scores": components,
            "raw_criteria": raw,
            "price": round(price, 4),
            "ma100": _f(payload.get("ma100")),
            "ma200": _f(payload.get("ma200")),
            "change_percent": _f(payload.get("change_percent")),
            "seven_day_percent": _f(payload.get("seven_day_percent")),
            "thirty_day_percent": _f(payload.get("thirty_day_percent")),
            "average_dollar_volume_20d": round(avg_dollar_volume, 2),
            "relative_volume": _f(payload.get("relative_volume")),
            "verification_status": payload.get("verification_status") or "unknown",
            "as_of": payload.get("as_of") or row.as_of,
            "retrieved_at": row.retrieved_at.isoformat(),
            "provider": payload.get("provider") or row.provider,
            "technical_source": payload.get("technical_source"),
            "source_url": payload.get("source_url"),
        })

    formula_ranked = sorted(rows, key=lambda item: (float(item["score"]), item["symbol"]), reverse=True)
    for rank, item in enumerate(formula_ranked, 1):
        item["formula_rank"] = rank
    ordered, requested_sort, requested_direction = sort_index_rows(formula_ranked, requested_sort, requested_direction)
    result_limit = max(1, min(int(limit), 1000))
    return {
        "rows": ordered[:result_limit],
        "formula": formula_metadata(weights, clean_filters),
        "sort": {"by": requested_sort, "direction": requested_direction},
        "criteria_catalog": list(CRITERIA.values()),
        "filter_catalog": list(FILTER_FIELDS.values()),
        "counts": {
            "latest_snapshot_symbols": len(latest_rows),
            "scannable": scannable,
            "technical_complete": technical_complete,
            "liquidity_eligible": liquidity_eligible,
            "filtered_out": filtered_out,
            "formula_complete": formula_complete,
            "returned": min(len(ordered), result_limit),
        },
        "liquidity_filter": {"min_price": MIN_PRICE, "min_average_dollar_volume_20d": MIN_AVG_DOLLAR_VOLUME_20D},
        "include_etfs": include_etfs,
        "last_cache_update": newest.isoformat() if newest else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_strategy": "Ranks the full cached, technically complete and liquid universe after optional hard screens, then applies the requested full-universe sort before truncating results. The index performs zero provider calls.",
    }
