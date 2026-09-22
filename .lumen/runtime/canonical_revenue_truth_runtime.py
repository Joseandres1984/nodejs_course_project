from __future__ import annotations

"""Canonical Revenue Truth for LUMEN."""
from datetime import datetime, timezone
from typing import Any, Dict, List
import autonomy_operating_system

VERSION = "1.2-canonical-revenue-truth-demand-first"
MIN_OPPORTUNITY_SCORE = 75.0
TRACEABLE_SOURCES = {"public_evidence", "manual_verified", "verified_inbound", "formal_quote"}
TERMINAL_DEAL_STAGES = {"closed", "lost", "cancelled", "canceled", "cerrado", "perdido", "cancelado"}
CLOSE_READY_STAGES = {"listo para cerrar", "close_ready", "autorizado para cierre"}
CLOSE_PATH_STAGES = {"oferta", "offer", "proposal", "propuesta", "negotiation", "negociacion", "negociación", "preclose", "pre_close", "close_ready", "listo para cerrar", "autorizado para cierre"}
_ORIGINAL_CANONICAL_CASES = autonomy_operating_system._canonical_cases

def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
def _f(value: Any, default: float = 0.0) -> float:
    try: return float(value)
    except (TypeError, ValueError): return default
def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())
def _account_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) or [] if isinstance(x, dict) and x.get("id")}

def _opportunity_assessment(state: Dict[str, Any], opp: Dict[str, Any], accounts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    oid = str(opp.get("id") or ""); buyer = accounts.get(str(opp.get("buyer_account_id") or ""), {}); supplier = accounts.get(str(opp.get("supplier_account_id") or ""), {})
    reasons: List[str] = []; source = _norm(opp.get("source")); status = _norm(opp.get("status")); evidence = [str(x) for x in (opp.get("evidence_refs") or []) if str(x or "").strip()]; score = _f(opp.get("score") or opp.get("portfolio_priority_score"))
    if not oid: reasons.append("missing_opportunity_id")
    if source in {"demo", "demo/simulación", "simulation", "simulated"}: reasons.append("non_real_source")
    elif source and source not in TRACEABLE_SOURCES and not opp.get("source_traceable"): reasons.append("source_not_canonical")
    if status in {"parked_collection_focus", "cancelled", "canceled", "rejected", "invalid"}: reasons.append("opportunity_not_active")
    if not buyer or buyer.get("type") != "buyer" or not buyer.get("verified_company"): reasons.append("buyer_not_verified")
    if not buyer.get("demand_signal"): reasons.append("buyer_demand_not_verified")
    if not supplier or supplier.get("type") != "supplier" or not supplier.get("verified_company"): reasons.append("supplier_not_verified")
    if score < MIN_OPPORTUNITY_SCORE: reasons.append("opportunity_score_below_threshold")
    if len(evidence) < 2: reasons.append("insufficient_traceable_evidence")
    return {"id": oid, "canonical": not reasons, "reasons": reasons, "score": round(score,1), "buyer_account_id": opp.get("buyer_account_id"), "supplier_account_id": opp.get("supplier_account_id"), "requirement_confirmed": bool(opp.get("requirement_confirmed")), "buyer_channel_verified": bool(opp.get("buyer_channel_verified") or buyer.get("commercial_channel_verified")), "supplier_channel_verified": bool(opp.get("supplier_channel_verified") or supplier.get("commercial_channel_verified")), "evidence_count": len(evidence), "source": opp.get("source"), "status": opp.get("status")}

def _row_links(row: Dict[str, Any], canonical_opp_ids: set[str], canonical_deal_ids: set[str]) -> bool:
    return str(row.get("opportunity_id") or "") in canonical_opp_ids or str(row.get("deal_id") or "") in canonical_deal_ids

def _linked_real_offer(state: Dict[str, Any], deal: Dict[str, Any], opportunity_id: str) -> bool:
    did = str(deal.get("id") or "")
    return any(isinstance(r,dict) and _norm(r.get("source")) not in {"demo","demo/simulación","simulation","simulated"} and ((did and str(r.get("deal_id") or "")==did) or (opportunity_id and str(r.get("opportunity_id") or "")==opportunity_id)) for r in state.get("offers",[]) or [])
def _linked_proposal(state: Dict[str, Any], deal: Dict[str, Any], opportunity_id: str) -> bool:
    did = str(deal.get("id") or "")
    return any(isinstance(r,dict) and ((did and str(r.get("deal_id") or "")==did) or (opportunity_id and str(r.get("opportunity_id") or "")==opportunity_id)) for r in state.get("proposals",[]) or [])

def _deal_assessment(state: Dict[str, Any], deal: Dict[str, Any], canonical_opportunities: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    did=str(deal.get("id") or ""); oid=str(deal.get("opportunity_id") or ""); opp=canonical_opportunities.get(oid); reasons=[]; stage=_norm(deal.get("stage")); source=_norm(deal.get("source"))
    if not did: reasons.append("missing_deal_id")
    if not oid: reasons.append("missing_opportunity_link")
    elif opp is None: reasons.append("linked_opportunity_not_canonical")
    if source in {"demo","demo/simulación","simulation","simulated"}: reasons.append("non_real_source")
    elif source and source not in TRACEABLE_SOURCES and not deal.get("source_traceable"): reasons.append("deal_source_not_canonical")
    if opp:
        ob=str(opp.get("buyer_account_id") or ""); os=str(opp.get("supplier_account_id") or ""); db=str(deal.get("buyer_account_id") or ""); ds=str(deal.get("supplier_account_id") or "")
        if db and ob and db!=ob: reasons.append("buyer_lineage_mismatch")
        if ds and os and ds!=os: reasons.append("supplier_lineage_mismatch")
    canonical=not reasons; terminal=stage in TERMINAL_DEAL_STAGES; active=canonical and not terminal; requirement=bool(opp and opp.get("requirement_confirmed")); real_offer=_linked_real_offer(state,deal,oid) if canonical else False; proposal=_linked_proposal(state,deal,oid) if canonical else False
    return {"id":did,"opportunity_id":oid or None,"canonical":canonical,"active":active,"terminal":terminal,"close_path_eligible":bool(active and requirement and real_offer and (proposal or stage in CLOSE_PATH_STAGES)),"close_ready":bool(canonical and stage in CLOSE_READY_STAGES),"requirement_confirmed":requirement,"has_real_offer":real_offer,"has_proposal":proposal,"stage":deal.get("stage"),"reasons":reasons}

def canonical_revenue_truth_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    accounts=_account_map(state); opps=[_opportunity_assessment(state,x,accounts) for x in state.get("market_opportunities",[]) or [] if isinstance(x,dict)]; canonical_opp_map={x["id"]:x for x in opps if x.get("canonical") and x.get("id")}; deals=[_deal_assessment(state,x,canonical_opp_map) for x in state.get("deals",[]) or [] if isinstance(x,dict)]
    copps=[x for x in opps if x.get("canonical")]; qopps=[x for x in opps if not x.get("canonical")]; cdeals=[x for x in deals if x.get("canonical")]; qdeals=[x for x in deals if not x.get("canonical")]; active=[x for x in cdeals if x.get("active")]; closepath=[x for x in cdeals if x.get("close_path_eligible")]; closeready=[x for x in cdeals if x.get("close_ready")]
    opp_ids=set(x["id"] for x in copps); deal_ids=set(x["id"] for x in cdeals)
    offers=[x for x in state.get("offers",[]) or [] if isinstance(x,dict) and _norm(x.get("source")) not in {"demo","demo/simulación","simulation","simulated"} and _row_links(x,opp_ids,deal_ids)]
    proposals=[x for x in state.get("proposals",[]) or [] if isinstance(x,dict) and _row_links(x,opp_ids,deal_ids)]
    buyers=[x for x in accounts.values() if x.get("type")=="buyer" and x.get("verified_company")]; demand=[x for x in buyers if x.get("demand_signal")]; readiness=state.get("external_market_readiness",{}) or {}; inelig=readiness.get("ineligibility_reasons",{}) or {}
    if closepath and not closeready:
        lane,target,reason="closing","canonical_close_ready","Existe al menos un deal canónico con requerimiento confirmado y oferta real; corresponde empujarlo hacia cierre seguro."
    elif copps and not offers:
        lane,target,reason="quote_creation","canonical_real_offers","Existen oportunidades canónicas pero todavía no hay ofertas reales vinculadas; priorizar RFQ y cotización comparable."
    elif demand and not copps:
        lane,target,reason="opportunity_building","canonical_opportunities","Existe demanda verificada pero ninguna oportunidad supera todavía los gates canónicos de evidencia."
    # Demand is upstream of outreach. If verified buyers exist but none has a verified need, more
    # contact verification cannot create a canonical deal and must not outrank the real bottleneck.
    elif buyers and not demand:
        lane,target,reason="demand_discovery","buyers_with_verified_demand","Hay compradores verificados pero 0 con demanda pública confirmada; priorizar evidencia de necesidad real antes de ampliar contacto comercial."
    elif int(readiness.get("eligible_external_prospects") or 0)<=0 and (int(inelig.get("company_not_verified") or 0)+int(inelig.get("contact_not_verified") or 0))>0:
        lane,target,reason="verification_contact","eligible_external_prospects","La salida comercial está bloqueada por verificación de identidad/contacto."
    else:
        lane,target,reason="demand_discovery","buyers_with_verified_demand","No existe todavía una ruta canónica suficientemente madura; ampliar demanda verificada sin degradar calidad."
    snap={"version":VERSION,"status":"active","updated_at":utcnow(),"truth_rule":"raw_activity_never_drives_closing; only traceable evidence-backed opportunity lineage may create canonical deals","recommended_lane":lane,"target_metric":target,"reason":reason,"counts":{"verified_buyers":len(buyers),"raw_market_opportunities":len(opps),"canonical_opportunities":len(copps),"quarantined_opportunities":len(qopps),"raw_deals":len(deals),"canonical_deals":len(cdeals),"canonical_active_deals":len(active),"closing_eligible_deals":len(closepath),"canonical_close_ready":len(closeready),"buyers_with_verified_demand":len(demand),"canonical_real_offers":len(offers),"canonical_proposals":len(proposals),"quarantined_deals":len(qdeals)},"canonical_opportunity_ids":list(opp_ids),"canonical_deal_ids":list(deal_ids),"closing_eligible_deal_ids":[x["id"] for x in closepath],"quarantined_opportunities":qopps[:20],"quarantined_deals":qdeals[:20],"governance":{"legacy_rows_preserved_for_audit":True,"legacy_rows_can_drive_closing":False,"binding_actions_remain_human_gated":True,"evidence_threshold_lowered":False,"demand_is_upstream_of_outreach":True}}
    state["canonical_revenue_truth"]=snap; return snap

def _canonical_cases_with_truth(state: Dict[str, Any]):
    truth=canonical_revenue_truth_tick(state); ao=set(str(x) for x in truth.get("canonical_opportunity_ids",[]) or []); ad=set(str(x) for x in truth.get("canonical_deal_ids",[]) or []); out=[]
    for case in list(_ORIGINAL_CANONICAL_CASES(state) or []):
        st=str(case.get("source_type") or ""); sid=str(case.get("source_id") or "")
        if st=="opportunity" and sid not in ao: continue
        if st=="deal" and sid not in ad: continue
        out.append(case)
    return out

autonomy_operating_system._canonical_cases=_canonical_cases_with_truth
print({"canonical_revenue_truth_runtime":{"version":VERSION,"status":"active","autonomy_filter":True,"demand_gap_priority":True}},flush=True)