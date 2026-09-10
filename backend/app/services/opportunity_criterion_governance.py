from __future__ import annotations

# Criterion status is intentionally separate from scoring math so research evidence can
# change a factor's governance state without changing historical formula semantics.
VALIDATION_STATUSES = {"baseline", "experimental", "validated", "rejected"}

CRITERION_GOVERNANCE = {
    "williams": {
        "validation_status": "baseline",
        "evidence_basis": "Default Opportunity model hypothesis; prospective validation still required before probabilistic interpretation.",
    },
    "ma100_proximity": {
        "validation_status": "baseline",
        "evidence_basis": "Default Opportunity model hypothesis; prospective validation still required before probabilistic interpretation.",
    },
    "ma100_slope": {
        "validation_status": "baseline",
        "evidence_basis": "Default Opportunity model confirmation factor; prospective validation still required.",
    },
    "approach_velocity": {
        "validation_status": "baseline",
        "evidence_basis": "Default Opportunity model confirmation factor; prospective validation still required.",
    },
    "ma50_proximity": {
        "validation_status": "experimental",
        "evidence_basis": "Optional V4 hypothesis added for research comparison; not yet promoted by independent-sample evidence.",
    },
    "relative_volume": {
        "validation_status": "experimental",
        "evidence_basis": "Optional V4 confirmation hypothesis; not yet promoted by independent-sample evidence.",
    },
}


def criterion_governance(key: str) -> dict:
    value = dict(CRITERION_GOVERNANCE.get(key) or {})
    status = value.get("validation_status", "experimental")
    if status not in VALIDATION_STATUSES:
        raise ValueError(f"Invalid Opportunity criterion validation status: {status}")
    value["validation_status"] = status
    value["validated"] = status == "validated"
    return value


def governed_catalog(criteria: dict[str, dict]) -> list[dict]:
    rows = []
    for key, definition in criteria.items():
        governance = criterion_governance(key)
        status_label = governance["validation_status"].replace("_", " ").title()
        rows.append({
            **definition,
            **governance,
            "label": f"{definition['label']} · {status_label}",
            "canonical_label": definition["label"],
        })
    return rows
