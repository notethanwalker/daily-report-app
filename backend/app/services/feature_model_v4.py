from __future__ import annotations

import hashlib
import json

MODEL_VERSION = "opportunity-v3.1"
COMPONENT_WEIGHTS = {"technical": .25, "valuation": .20, "sector": .15, "flow": .15, "momentum": .15, "risk": .10}
MODEL_CONFIG_HASH = hashlib.sha256(json.dumps(COMPONENT_WEIGHTS, sort_keys=True).encode()).hexdigest()[:12]


def version_payload(payload: dict | None) -> dict:
    out = dict(payload or {})
    out.setdefault("model_version", MODEL_VERSION)
    out.setdefault("model_config_hash", MODEL_CONFIG_HASH)
    out.setdefault("model_component_weights", COMPONENT_WEIGHTS)
    return out
