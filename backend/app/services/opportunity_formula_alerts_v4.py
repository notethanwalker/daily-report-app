from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from ..models import AlertRule
from ..v4_models import OpportunityFormulaAlertBindingV4, OpportunityFormulaPresetV4
from .opportunity_formula_v4 import build_opportunity_index

FORMULA_ALERT_KINDS={"opportunity_formula_score","opportunity_formula_rank"}


def _decode_config(value:dict|None)->tuple[dict,list[dict]]:
    raw=dict(value or {})
    if "weights" in raw:return dict(raw.get("weights") or {}),list(raw.get("filters") or [])
    return raw,[]


def evaluate_formula_alert_values(db:Session,rules:list[AlertRule])->dict[int,tuple[float|None,dict]]:
    relevant=[r for r in rules if r.kind in FORMULA_ALERT_KINDS]
    if not relevant:return {}
    rule_map={r.id:r for r in relevant}
    bindings=db.query(OpportunityFormulaAlertBindingV4).filter(OpportunityFormulaAlertBindingV4.alert_id.in_(list(rule_map))).all()
    by_formula:dict[int,list[OpportunityFormulaAlertBindingV4]]=defaultdict(list)
    for binding in bindings:
        rule=rule_map.get(binding.alert_id)
        if rule and binding.user_id==rule.user_email:by_formula[binding.formula_id].append(binding)
    presets={p.id:p for p in db.query(OpportunityFormulaPresetV4).filter(OpportunityFormulaPresetV4.id.in_(list(by_formula))).all()} if by_formula else {}
    out:dict[int,tuple[float|None,dict]]={}
    for formula_id,group in by_formula.items():
        preset=presets.get(formula_id)
        if not preset:
            for binding in group:out[binding.alert_id]=(None,{"state":"unavailable","reason":"formula_missing","formula_id":formula_id})
            continue
        valid=[b for b in group if b.user_id==preset.user_id and rule_map[b.alert_id].user_email==preset.user_id]
        if not valid:continue
        criteria,filters=_decode_config(preset.criteria)
        symbols=sorted({b.symbol.upper() for b in valid})
        index=build_opportunity_index(db,criteria=criteria,filters=filters,include_etfs=False,limit=1,sort_by="score",sort_dir="desc",target_symbols=symbols)
        targets={r["symbol"]:r for r in index.get("target_rows") or []}
        for binding in valid:
            rule=rule_map[binding.alert_id];row=targets.get(binding.symbol.upper())
            base={"formula_id":preset.id,"formula_name":preset.name,"symbol":binding.symbol.upper(),"formula_complete":index.get("counts",{}).get("formula_complete"),"generated_at":index.get("generated_at"),"last_cache_update":index.get("last_cache_update")}
            if not row:
                out[rule.id]=(None,{**base,"state":"not_eligible","score":None,"rank":None,"reason":"symbol_missing_or_failed_formula_filters"})
                continue
            score=float(row["score"]);rank=int(row["formula_rank"])
            if rule.kind=="opportunity_formula_score":
                threshold=float(rule.threshold or 0);state="at_or_above" if score>=threshold else "below"
                out[rule.id]=(score,{**base,"state":state,"score":score,"rank":rank,"threshold":threshold})
            else:
                top_n=max(1,int(rule.threshold or 1));state="inside" if rank<=top_n else "outside"
                out[rule.id]=(float(rank),{**base,"state":state,"score":score,"rank":rank,"top_n":top_n})
    for rule in relevant:
        if rule.id not in out:out[rule.id]=(None,{"state":"unavailable","reason":"formula_binding_missing"})
    return out
