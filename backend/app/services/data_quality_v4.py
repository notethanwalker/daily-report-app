from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

QUALITY_MODEL_VERSION="data-quality-v4.1"
VERIFIED_STATES={"verified","partially_verified","verified_different_as_of","cross_checked","matched"}
DISCREPANCY_STATES={"discrepancy","discrepant","mismatch"}
PRIMARY_ONLY_STATES={"primary_only"}


def _utc(value):
    if value is None:return None
    if isinstance(value,datetime):return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:return datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except Exception:return None


def normalize_verification(value)->str:
    raw=str(value or "").strip().lower()
    if raw in VERIFIED_STATES:return "cross_checked"
    if raw in DISCREPANCY_STATES:return "discrepant"
    if raw in PRIMARY_ONLY_STATES:return "primary_only"
    if raw in {"not_applicable","n/a","na"}:return "not_applicable"
    return "unverified"


def confidence_multiplier(confidence:float)->float:
    c=max(0.0,min(1.0,float(confidence)))
    return round(0.50+0.50*c,4)


def confidence_adjusted_score(score,confidence):
    if score is None:return None
    return round(float(score)*confidence_multiplier(float(confidence)),2)


def build_quality_summary(*,sections:dict[str,dict]|None=None,verification_status=None,feature_status=None,required_sections:list[str]|tuple[str,...]|None=None,failures:list[dict]|None=None,source_rows:list[dict]|None=None,now:datetime|None=None)->dict[str,Any]:
    now=now or datetime.now(timezone.utc);sections=sections or {};required=list(required_sections or sections.keys());failures=list(failures or []);sources=list(source_rows or [])
    states={};fresh=available=0;problems=[]
    for key in required:
        item=sections.get(key) or {};is_available=bool(item.get("available"));is_fresh=bool(item.get("fresh"));state="fresh" if is_fresh else "stale" if is_available else "missing";states[key]=state
        available+=int(is_available);fresh+=int(is_fresh)
        if state!="fresh":problems.append({"code":f"{key}_{state}","severity":"warning" if state=="stale" else "error","data_class":key,"state":state,"detail":item.get("degrade_reason") or item.get("reason")})
        for src in item.get("sources") or []:
            if isinstance(src,dict):sources.append(src)
    verification=normalize_verification(verification_status)
    if verification=="primary_only":problems.append({"code":"verification_primary_only","severity":"warning","data_class":"verification","state":"primary_only","detail":"Independent cross-check is not currently available."})
    elif verification=="discrepant":problems.append({"code":"verification_discrepant","severity":"error","data_class":"verification","state":"discrepant","detail":"Primary and secondary observations disagree beyond policy tolerance."})
    elif verification=="unverified":problems.append({"code":"verification_unverified","severity":"warning","data_class":"verification","state":"unverified","detail":"Verification state is unavailable."})
    feature=str(feature_status or "unknown").lower()
    if feature not in {"available","complete","ready","unknown","not_applicable"}:problems.append({"code":"feature_context_incomplete","severity":"warning","data_class":"features","state":feature,"detail":"Derived feature context is incomplete."})
    for failure in failures:
        if isinstance(failure,dict):problems.append({"code":failure.get("code") or "data_failure","severity":failure.get("severity") or "error","data_class":failure.get("data_class") or "unknown","state":"failed","detail":failure.get("detail")})
    total=max(len(required),1);completeness=available/total if required else 1.0;freshness=fresh/total if required else 1.0
    verification_factor={"cross_checked":1.0,"not_applicable":1.0,"primary_only":0.82,"unverified":0.72,"discrepant":0.45}[verification]
    feature_factor=1.0 if feature in {"available","complete","ready","not_applicable"} else 0.85 if feature=="unknown" else 0.65
    failure_penalty=max(0.45,1.0-0.12*sum(1 for p in problems if p.get("state")=="failed"))
    confidence=max(0.0,min(1.0,(0.45*completeness+0.35*freshness+0.20*verification_factor)*feature_factor*failure_penalty))
    if any(p["severity"]=="error" for p in problems):overall="failed" if confidence<0.35 else "incomplete"
    elif confidence>=0.90:overall="verified" if verification=="cross_checked" else "fresh"
    elif confidence>=0.70:overall="degraded"
    else:overall="incomplete"
    normalized_sources=[];seen=set()
    for src in sources:
        if not isinstance(src,dict):continue
        provider=str(src.get("provider") or src.get("source") or "unknown");retrieved=src.get("retrieved_at") or src.get("as_of");key=(provider,str(retrieved))
        if key in seen:continue
        seen.add(key);dt=_utc(retrieved);age=round((now-dt).total_seconds()/60,1) if dt else None
        normalized_sources.append({"provider":provider,"retrieved_at":str(retrieved) if retrieved is not None else None,"age_minutes":age,"url":src.get("source_url") or src.get("url")})
    return {"model_version":QUALITY_MODEL_VERSION,"state":overall,"verification":verification,"feature_context":feature,"section_states":states,"completeness":round(completeness,4),"freshness":round(freshness,4),"confidence":round(confidence,4),"confidence_percent":round(confidence*100,1),"confidence_multiplier":confidence_multiplier(confidence),"problems":problems,"sources":normalized_sources,"policy":"Raw analytical scores remain unchanged. Confidence-adjusted scores are separate, explicitly labeled ranking aids."}
