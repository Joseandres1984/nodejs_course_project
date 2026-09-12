from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from autonomy_governor import record_decision

MAX_LANES = 4
MAX_FOLLOWUPS = 2
FIRST_FOLLOWUP_HOURS = max(24, int(os.getenv("LUMEN_CLOSER_FIRST_FOLLOWUP_HOURS", "72")))
SECOND_FOLLOWUP_HOURS = max(FIRST_FOLLOWUP_HOURS, int(os.getenv("LUMEN_CLOSER_SECOND_FOLLOWUP_HOURS", "120")))
COLLECTION_FOCUS = os.getenv("LUMEN_COLLECTION_FOCUS", "").strip().lower()

COMMERCIAL_KINDS = {
    "buyer_requirement_request",
    "supplier_rfq",
    "quote_clarification",
    "supplier_negotiation",
    "buyer_information_response",
    "buyer_proposal",
    "follow_up",
    "terms_clarification",
}
BUYER_KINDS = {
    "buyer_requirement_request",
    "buyer_information_response",
    "buyer_proposal",
    "follow_up",
}
CLOSED_TXN_STATES = {"closed", "settled", "paid", "completed", "delivered", "invoiced"}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _hours_since(value: Any) -> float | None:
    ts = _parse_ts(value)
    if not ts:
        return None
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0)


def _account_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) or [] if x.get("id")}


def _opp_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("market_opportunities", []) or [] if x.get("id")}


def _deal_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("deals", []) or [] if x.get("id")}


def _case_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("opportunity_id")): x for x in state.get("interlocution_cases", []) or [] if x.get("opportunity_id")}


def _deal_for_opp(state: Dict[str, Any], opportunity_id: str) -> Dict[str, Any]:
    return next((x for x in state.get("deals", []) or [] if str(x.get("opportunity_id") or "") == str(opportunity_id)), {})


def _risk(state: Dict[str, Any], account_id: Any) -> Dict[str, Any]:
    return dict((state.get("counterparty_risk_index", {}) or {}).get(str(account_id or ""), {}) or {})


def _is_closed(state: Dict[str, Any], deal: Dict[str, Any]) -> bool:
    if not deal:
        return False
    if str(deal.get("stage") or "").lower() in {"closed", "cerrado", "settled", "completed", "cancelled", "lost"}:
        return True
    deal_id = str(deal.get("id") or "")
    return any(str(x.get("deal_id") or "") == deal_id and str(x.get("status") or "").lower() in CLOSED_TXN_STATES for x in state.get("transactions", []) or [])


def _latest_inbound(state: Dict[str, Any], *, deal_id: str = "", opportunity_id: str = "") -> Dict[str, Any]:
    rows = []
    for x in state.get("inbox", []) or []:
        if deal_id and str(x.get("deal_id") or "") == deal_id:
            rows.append(x)
        elif opportunity_id and str(x.get("opportunity_id") or "") == opportunity_id:
            rows.append(x)
        elif opportunity_id:
            source_id = str(x.get("related_message_id") or x.get("revops_source_message_id") or "")
            source = next((m for m in state.get("outbox", []) or [] if str(m.get("id") or "") == source_id), {})
            if str(source.get("opportunity_id") or "") == opportunity_id:
                rows.append(x)
    rows.sort(key=lambda x: str(x.get("received_at") or ""))
    return rows[-1] if rows else {}


def _detect_objection(incoming: Dict[str, Any]) -> Dict[str, Any]:
    if not incoming:
        return {"kind": None, "directive": None, "confidence": 0.0}
    classified = str((incoming.get("classification") or {}).get("kind") or "")
    text = f"{incoming.get('subject', '')} {incoming.get('body', '')}".lower()
    if classified == "opt_out" or any(x in text for x in ("no contactar", "no me interesa", "quitarme", "unsubscribe")):
        return {"kind": "opt_out", "directive": "stop_contact_immediately", "confidence": 0.99}
    if classified == "price_objection" or any(x in text for x in ("fuera de presupuesto", "muy caro", "precio alto", "mejor precio", "descuento")):
        return {"kind": "price", "directive": "improve_supplier_economics_before_buyer_concession", "confidence": 0.95}
    if any(x in text for x in ("más adelante", "mas adelante", "ahora no", "mes que viene", "próximo trimestre", "proximo trimestre", "retomar después", "retomar despues")):
        return {"kind": "timing", "directive": "cooldown_and_reengage_later", "confidence": 0.9}
    if any(x in text for x in ("tengo que consultar", "debemos consultar", "aprobación interna", "aprobacion interna", "gerencia", "mi jefe", "compras debe aprobar")):
        return {"kind": "internal_approval", "directive": "prepare_decision_summary_without_pressure", "confidence": 0.88}
    if any(x in text for x in ("otro proveedor", "ya tenemos proveedor", "otra oferta", "otra cotización", "otra cotizacion", "competidor")):
        return {"kind": "competitor", "directive": "differentiate_on_verified_value_not_unproven_claims", "confidence": 0.88}
    if classified == "delivery_question" or any(x in text for x in ("fecha de entrega", "plazo de entrega", "cuándo entreg", "cuando entreg")):
        return {"kind": "delivery", "directive": "answer_only_from_verified_offer_or_revalidate_supplier", "confidence": 0.94}
    if any(x in text for x in ("ficha técnica", "ficha tecnica", "especificación", "especificacion", "compatibilidad", "modelo exacto", "hoja de datos")):
        return {"kind": "technical", "directive": "answer_only_from_traceable_technical_evidence", "confidence": 0.9}
    if classified == "buyer_interest" or any(x in text for x in ("avancemos", "sigamos", "nos interesa", "me interesa")):
        return {"kind": "interest", "directive": "accelerate_without_skipping_requirements_or_close_controls", "confidence": 0.9}
    return {"kind": classified or "general", "directive": "continue_evidence_based_discovery", "confidence": 0.65}


def _stage(state: Dict[str, Any], opp: Dict[str, Any], deal: Dict[str, Any], case: Dict[str, Any], close_pack: Dict[str, Any]) -> str:
    if close_pack.get("status") == "READY_FOR_HUMAN_APPROVAL":
        return "READY_FOR_HUMAN_APPROVAL"
    if deal and (deal.get("red_team_hold") or deal.get("incident_hold") or deal.get("legal_review_required")):
        return "RISK_HOLD"
    if close_pack.get("status") == "BLOCKED_RISK":
        return "RISK_HOLD"
    if deal and deal.get("economics", {}).get("viable"):
        return "NEGOTIATION_OR_CLOSE"
    real_offers = [x for x in state.get("offers", []) or [] if str(x.get("deal_id") or "") == str(deal.get("id") or "") and x.get("source") != "demo/simulación"]
    if real_offers:
        return "QUOTE_NORMALIZATION"
    if case.get("supplier_rfq_ready"):
        return "SUPPLIER_SOURCING"
    if opp:
        return "BUYER_DISCOVERY"
    return "PIPELINE_ACQUISITION"


def _score_lane(state: Dict[str, Any], opp: Dict[str, Any]) -> Dict[str, Any]:
    accounts = _account_index(state)
    case = _case_index(state).get(str(opp.get("id") or ""), {})
    deal = _deal_for_opp(state, str(opp.get("id") or ""))
    buyer = accounts.get(str(opp.get("buyer_account_id") or ""), {})
    supplier = accounts.get(str(opp.get("supplier_account_id") or ""), {})
    close_pack = dict((state.get("closing_pack_index", {}) or {}).get(str(deal.get("id") or ""), {}) or {})
    score = _f(opp.get("portfolio_priority_score"), _f(opp.get("score"), 0.0))
    score += 10 if opp.get("buyer_demand_verified") else 0
    score += 8 if buyer.get("verified_contact") else 0
    score += 5 if buyer.get("commercial_channel_verified") else 0
    score += 5 if supplier.get("verified_company") else 0
    score += 4 if supplier.get("verified_contact") else 0
    score += 8 if case.get("supplier_rfq_ready") else 0
    score += 10 if deal.get("economics", {}).get("viable") else 0
    score += 15 if close_pack.get("status") == "READY_FOR_HUMAN_APPROVAL" else 0
    if COLLECTION_FOCUS == "mercadopago_ars":
        score += 12 if opp.get("collection_focus_eligible") else -80
    buyer_risk = _risk(state, buyer.get("id"))
    supplier_risk = _risk(state, supplier.get("id"))
    if buyer_risk.get("risk_tier") == "BLOCKED" or supplier_risk.get("risk_tier") == "BLOCKED":
        score -= 100
    if deal.get("red_team_hold") or deal.get("incident_hold"):
        score -= 70
    stage = _stage(state, opp, deal, case, close_pack)
    incoming = _latest_inbound(state, deal_id=str(deal.get("id") or ""), opportunity_id=str(opp.get("id") or ""))
    objection = _detect_objection(incoming)
    return {
        "lane_id": f"opportunity:{opp.get('id')}",
        "opportunity_id": opp.get("id"),
        "deal_id": deal.get("id"),
        "buyer_account_id": buyer.get("id"),
        "supplier_account_id": supplier.get("id"),
        "category": opp.get("category"),
        "score": round(max(0.0, min(100.0, score)), 2),
        "stage": stage,
        "collection_focus_eligible": bool(opp.get("collection_focus_eligible", True)),
        "buyer_contact_ready": bool(buyer.get("verified_contact")),
        "supplier_contact_ready": bool(supplier.get("verified_contact")),
        "requirement_ready": bool(case.get("supplier_rfq_ready")),
        "economics_viable": bool(deal.get("economics", {}).get("viable")),
        "close_pack_status": close_pack.get("status"),
        "objection": objection,
        "last_inbound_id": incoming.get("id") if incoming else None,
        "blocked": score <= 0 or stage == "RISK_HOLD" or objection.get("kind") == "opt_out" or _is_closed(state, deal),
    }


def _lane_cap(state: Dict[str, Any]) -> int:
    stage = str((state.get("go_live_memory", {}) or {}).get("stage") or "CANARY").upper()
    return {"CANARY": 1, "LIMITED_LIVE": 2, "GOVERNED_LIVE": 4, "PRELAUNCH": 0, "HOLD": 0}.get(stage, 1)


def _next_action(lane: Dict[str, Any]) -> str:
    objection = (lane.get("objection") or {}).get("directive")
    if objection and (lane.get("objection") or {}).get("kind") not in {None, "general"}:
        return str(objection)
    stage = str(lane.get("stage") or "")
    return {
        "PIPELINE_ACQUISITION": "find_verified_argentina_demand",
        "BUYER_DISCOVERY": "confirm_buyer_requirement",
        "SUPPLIER_SOURCING": "collect_comparable_supplier_quotes",
        "QUOTE_NORMALIZATION": "normalize_quotes_and_compute_real_economics",
        "NEGOTIATION_OR_CLOSE": "improve_terms_or_build_close_pack",
        "READY_FOR_HUMAN_APPROVAL": "request_single_human_close_approval",
        "RISK_HOLD": "repair_risk_before_commercial_pressure",
    }.get(stage, "continue_evidence_based_execution")


def _message_lane(state: Dict[str, Any], item: Dict[str, Any]) -> str:
    opp_id = str(item.get("opportunity_id") or "")
    if opp_id:
        return f"opportunity:{opp_id}"
    deal_id = str(item.get("deal_id") or "")
    if deal_id:
        deal = _deal_index(state).get(deal_id, {})
        opp_id = str(deal.get("opportunity_id") or "")
        if opp_id:
            return f"opportunity:{opp_id}"
    case_id = str(item.get("interlocution_case_id") or "")
    if case_id:
        case = next((x for x in state.get("interlocution_cases", []) or [] if str(x.get("id") or "") == case_id), {})
        opp_id = str(case.get("opportunity_id") or "")
        if opp_id:
            return f"opportunity:{opp_id}"
    return ""


def _apply_lane_gate(state: Dict[str, Any], active_ids: set[str], cap: int) -> Dict[str, int]:
    stats = {"allowed": 0, "held": 0, "released": 0}
    for item in state.get("outbox", []) or []:
        kind = str(item.get("kind") or "")
        if kind not in COMMERCIAL_KINDS:
            continue
        lane = _message_lane(state, item)
        item["closer_lane_id"] = lane or None
        item["closer_governed"] = True
        if item.get("status") == "closer_hold" and (cap > 0 and lane in active_ids):
            item["status"] = "ready"
            item.pop("closer_hold_reason", None)
            stats["released"] += 1
        if item.get("status") != "ready":
            continue
        if cap <= 0 or not lane or lane not in active_ids:
            item["status"] = "closer_hold"
            item["closer_hold_reason"] = "Fuera de la(s) conversación(es) activa(s) del Closer para la etapa Go-Live actual."
            stats["held"] += 1
        else:
            item["closer_allowed"] = True
            stats["allowed"] += 1
    return stats


def _latest_buyer_sent(state: Dict[str, Any], lane_id: str) -> Dict[str, Any]:
    rows = [x for x in state.get("outbox", []) or [] if x.get("status") == "sent" and x.get("kind") in BUYER_KINDS and _message_lane(state, x) == lane_id]
    rows.sort(key=lambda x: str(x.get("sent_at") or ""))
    return rows[-1] if rows else {}


def _buyer_inbound_after(state: Dict[str, Any], sent: Dict[str, Any]) -> bool:
    sent_at = _parse_ts(sent.get("sent_at"))
    if not sent_at:
        return False
    contact = str(sent.get("contact") or "").strip().lower()
    for row in state.get("inbox", []) or []:
        if str(row.get("from") or "").strip().lower() != contact:
            continue
        received = _parse_ts(row.get("received_at"))
        if received and received > sent_at:
            return True
    return False


def _followup_count(state: Dict[str, Any], lane_id: str) -> int:
    return sum(1 for x in state.get("outbox", []) or [] if x.get("kind") == "follow_up" and _message_lane(state, x) == lane_id and x.get("status") in {"ready", "sent", "closer_hold"})


def _prepare_followup(state: Dict[str, Any], lane: Dict[str, Any]) -> bool:
    if lane.get("blocked") or lane.get("stage") in {"READY_FOR_HUMAN_APPROVAL", "RISK_HOLD"}:
        return False
    if (lane.get("objection") or {}).get("kind") in {"opt_out", "timing"}:
        return False
    lane_id = str(lane.get("lane_id") or "")
    sent = _latest_buyer_sent(state, lane_id)
    if not sent or _buyer_inbound_after(state, sent):
        return False
    count = _followup_count(state, lane_id)
    if count >= MAX_FOLLOWUPS:
        return False
    elapsed = _hours_since(sent.get("sent_at"))
    threshold = FIRST_FOLLOWUP_HOURS if count == 0 else SECOND_FOLLOWUP_HOURS
    if elapsed is None or elapsed < threshold:
        return False
    contact = str(sent.get("contact") or "").strip().lower()
    account_id = str(sent.get("counterparty_account_id") or lane.get("buyer_account_id") or "")
    account = _account_index(state).get(account_id, {})
    if not contact or not account.get("verified_contact") or contact in {str(x).lower() for x in state.get("opt_out", []) or []}:
        return False
    risk = _risk(state, account_id)
    if risk.get("risk_tier") == "BLOCKED" or risk.get("can_outreach") is False:
        return False
    key = f"closer_followup|{lane_id}|{count+1}"
    if any(str(x.get("execution_key") or "") == key for x in state.get("outbox", []) or []):
        return False
    category = str(lane.get("category") or "requerimiento")
    state.setdefault("outbox", []).append({
        "id": f"MSG-{len(state.get('outbox', []))+1:04d}",
        "deal_id": lane.get("deal_id"),
        "opportunity_id": lane.get("opportunity_id"),
        "counterparty_account_id": account_id,
        "kind": "follow_up",
        "purpose": "closer_persistent_follow_up",
        "counterparty": account.get("company_name") or account.get("name_hint") or account.get("domain"),
        "channel": "email",
        "contact": contact,
        "contact_verified": True,
        "subject": f"Seguimiento — {category}"[:180],
        "body": (
            "Retomo este requerimiento por si sigue vigente. Podemos avanzar con una comparación concreta de alternativas y condiciones sobre la información ya relevada, sin asumir datos que ustedes no hayan confirmado. "
            "Si la prioridad cambió o prefieren retomarlo más adelante, indíquennos y ajustamos el seguimiento."
        ),
        "status": "ready",
        "execution_key": key,
        "created_at": utcnow(),
        "nonbinding": True,
        "closer_generated": True,
    })
    return True


def closer_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("closer_memory", {})
    memory["cycles"] = int(memory.get("cycles") or 0) + 1
    lanes = []
    for opp in state.get("market_opportunities", []) or []:
        if opp.get("source") != "public_evidence":
            continue
        if COLLECTION_FOCUS == "mercadopago_ars" and not opp.get("collection_focus_eligible"):
            continue
        lane = _score_lane(state, opp)
        if not lane.get("blocked"):
            lane["next_action"] = _next_action(lane)
            lanes.append(lane)
    lanes.sort(key=lambda x: (_f(x.get("score")), x.get("stage") == "READY_FOR_HUMAN_APPROVAL"), reverse=True)

    cap = _lane_cap(state)
    active = lanes[:cap] if cap > 0 else []
    active_ids = {str(x.get("lane_id")) for x in active}
    gate = _apply_lane_gate(state, active_ids, cap)

    followup_created = False
    if active:
        followup_created = _prepare_followup(state, active[0])
        if followup_created:
            gate = _apply_lane_gate(state, active_ids, cap)

    primary = active[0] if active else None
    human_required = bool(primary and primary.get("stage") == "READY_FOR_HUMAN_APPROVAL")
    if primary:
        memory["primary_lane_id"] = primary.get("lane_id")
        memory["primary_opportunity_id"] = primary.get("opportunity_id")
        memory["primary_deal_id"] = primary.get("deal_id")
    memory["active_lane_ids"] = list(active_ids)
    memory["last_cycle_at"] = utcnow()

    status = "NO_ELIGIBLE_OPPORTUNITY"
    if primary:
        status = "READY_FOR_HUMAN_APPROVAL" if human_required else "CLOSING_AUTONOMOUSLY"
    if cap <= 0:
        status = "GO_LIVE_HOLD"

    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_evidence_based_closer",
        "status": status,
        "go_live_stage": (state.get("go_live_memory", {}) or {}).get("stage"),
        "lane_cap": cap,
        "eligible_lanes": len(lanes),
        "active_lanes": active,
        "primary_lane": primary,
        "primary_next_action": (primary or {}).get("next_action"),
        "human_action_required": human_required,
        "followup_created": followup_created,
        "outbound_gate": gate,
        "collection_focus": COLLECTION_FOCUS or "standard",
        "governance": {
            "one_owner_rule": "Closer Orchestrator owns prioritization from verified demand through close packet; specialist engines remain authoritative for evidence, quotes, risk, negotiation and payments.",
            "persistence_rule": "At most two evidence-based buyer follow-ups; first after 72h, second after 120h, unless the buyer replies, opts out or asks to revisit later.",
            "objection_rule": "Price objections first trigger supplier-economics improvement; delivery/technical answers require traceable evidence; competitor objections never trigger invented claims.",
            "canary_rule": "CANARY keeps one active commercial lane; LIMITED_LIVE two; GOVERNED_LIVE four. Other new-sale messages are held, not deleted.",
            "authority_rule": "Research, outreach, RFQ, clarification and nonbinding negotiation may be autonomous. Contract acceptance, binding terms, orders, payments and final legal commitments remain human-authorized.",
        },
    }
    state["closer_orchestrator"] = report
    state["closer_active_lane_ids"] = list(active_ids)

    if primary:
        record_decision(
            state,
            engine="Closer Orchestrator",
            object_type="deal" if primary.get("deal_id") else "market_opportunity",
            object_id=str(primary.get("deal_id") or primary.get("opportunity_id") or ""),
            decision=f"closer:{str(primary.get('stage') or '').lower()}",
            reason=(
                f"Score {primary.get('score')}; foco de cobro {COLLECTION_FOCUS or 'standard'}; "
                f"objeción {((primary.get('objection') or {}).get('kind') or 'ninguna')}; siguiente acción {primary.get('next_action')}."
            ),
            action="request_human_close_approval" if human_required else "advance_commercial_case",
            confidence=max(0.55, min(0.99, _f(primary.get("score")) / 100.0)),
            evidence_refs=[],
            allowed=True,
            requires_approval=human_required,
        )
    return report
