from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision


MAX_ROOMS = 80
MAX_TIMELINE = 40


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _accounts(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) if x.get("id")}


def _opportunities(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = list(state.get("market_opportunities", []) or []) + list(state.get("opportunities", []) or [])
    return {str(x.get("id")): x for x in rows if x.get("id")}


def _cfo_rows(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(x.get("deal_id")): x
        for x in (state.get("cfo", {}) or {}).get("deal_financial_rankings", []) or []
        if x.get("deal_id")
    }


def _messages_by_deal(state: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in state.get("outbox", []) or []:
        deal_id = str(item.get("deal_id") or "")
        if deal_id:
            rows[deal_id].append({
                "direction": "outbound",
                "id": item.get("id"),
                "ts": item.get("sent_at") or item.get("created_at"),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "counterparty": item.get("counterparty"),
                "contact": item.get("contact"),
                "subject": item.get("subject"),
                "purpose": item.get("purpose"),
            })
    for item in state.get("inbox", []) or []:
        deal_id = str(item.get("deal_id") or "")
        if deal_id:
            cls = item.get("classification", {}) or {}
            rows[deal_id].append({
                "direction": "inbound",
                "id": item.get("id"),
                "ts": item.get("received_at"),
                "kind": cls.get("kind"),
                "status": "received",
                "counterparty": item.get("from"),
                "contact": item.get("from"),
                "subject": item.get("subject"),
                "purpose": item.get("processing_note"),
            })
    for deal_id in rows:
        rows[deal_id] = sorted(rows[deal_id], key=lambda x: str(x.get("ts") or ""), reverse=True)[:MAX_TIMELINE]
    return rows


def _documents_by_deal(state: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    docs = {str(x.get("id")): x for x in state.get("document_registry", []) or [] if x.get("id")}
    inbox_deal = {str(x.get("id")): str(x.get("deal_id") or "") for x in state.get("inbox", []) or [] if x.get("id")}
    doc_deals: Dict[str, set[str]] = defaultdict(set)

    for offer in state.get("offers", []) or []:
        doc_id = str(offer.get("document_id") or "")
        deal_id = str(offer.get("deal_id") or "")
        if doc_id and deal_id:
            doc_deals[doc_id].add(deal_id)

    for doc_id, doc in docs.items():
        for msg_id in doc.get("source_messages", []) or []:
            deal_id = inbox_deal.get(str(msg_id), "")
            if deal_id:
                doc_deals[doc_id].add(deal_id)

    rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for doc_id, deal_ids in doc_deals.items():
        doc = docs.get(doc_id, {})
        facts = doc.get("facts", {}) or {}
        summary = {
            "id": doc_id,
            "filename": doc.get("filename"),
            "document_type": doc.get("document_type"),
            "type_confidence": doc.get("document_type_confidence"),
            "extraction_status": doc.get("extraction_status"),
            "sender": doc.get("sender"),
            "facts": {
                "amount": facts.get("amount"),
                "currency": facts.get("currency"),
                "lead_days": facts.get("lead_days"),
                "payment_terms": facts.get("payment_terms"),
                "validity_days": facts.get("validity_days"),
                "warranty": facts.get("warranty"),
                "freight_terms": facts.get("freight_terms"),
                "tax_terms": facts.get("tax_terms"),
                "incoterm": facts.get("incoterm"),
                "origin_statement": facts.get("origin_statement"),
                "quote_number": facts.get("quote_number"),
                "technical_compliance": facts.get("technical_compliance"),
            },
            "source_messages": list(doc.get("source_messages") or [])[:8],
            "created_at": doc.get("created_at"),
        }
        for deal_id in deal_ids:
            rows[deal_id].append(summary)
    return rows


def _decisions_by_deal(state: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in state.get("decision_ledger", []) or []:
        if entry.get("object_type") != "deal" or not entry.get("object_id"):
            continue
        rows[str(entry["object_id"])].append({
            "id": entry.get("id"),
            "ts": entry.get("ts"),
            "engine": entry.get("engine"),
            "decision": entry.get("decision"),
            "reason": entry.get("reason"),
            "risk": entry.get("risk"),
            "confidence": entry.get("confidence"),
            "requires_approval": entry.get("requires_approval"),
            "evidence_refs": list(entry.get("evidence_refs") or [])[:8],
        })
    for deal_id in rows:
        rows[deal_id] = rows[deal_id][-MAX_TIMELINE:][::-1]
    return rows


def _revops_case(state: Dict[str, Any], deal: Dict[str, Any]) -> Dict[str, Any]:
    deal_id = str(deal.get("id") or "")
    opp_id = str(deal.get("opportunity_id") or "")
    memory = state.get("commercial_execution_memory", {}) or {}
    cases = memory.get("cases", []) or []
    for case in reversed(cases):
        if str(case.get("deal_id") or "") == deal_id:
            return case
    for case in reversed(cases):
        if opp_id and str(case.get("opportunity_id") or "") == opp_id:
            return case
    return {}


def _quote_comparison(state: Dict[str, Any], deal_id: str) -> Dict[str, Any]:
    rows = [x for x in state.get("quote_comparisons", []) or [] if str(x.get("deal_id") or "") == deal_id]
    if not rows:
        return {}
    return rows[-1]


def _trade(state: Dict[str, Any], deal_id: str) -> Dict[str, Any]:
    cases = [x for x in state.get("trade_cases", []) or [] if str(x.get("deal_id") or "") == deal_id]
    comparisons = [x for x in state.get("trade_route_comparisons", []) or [] if str(x.get("deal_id") or "") == deal_id]
    return {
        "cases": cases[:12],
        "comparison": comparisons[-1] if comparisons else None,
        "has_cross_border": any(x.get("cross_border") is True for x in cases),
        "all_routes_decision_ready": bool(cases) and all(bool(x.get("decision_ready")) for x in cases),
    }


def _approvals(state: Dict[str, Any], deal_id: str) -> List[Dict[str, Any]]:
    return [
        {
            "id": x.get("id"),
            "kind": x.get("kind"),
            "status": x.get("status"),
            "reason": x.get("reason"),
            "requested_at": x.get("requested_at") or x.get("created_at"),
            "approved_at": x.get("approved_at"),
            "rejected_at": x.get("rejected_at"),
        }
        for x in state.get("approvals", []) or []
        if str(x.get("deal_id") or "") == deal_id
    ]


def _transactions(state: Dict[str, Any], deal_id: str) -> List[Dict[str, Any]]:
    return [
        {
            "id": x.get("id"),
            "status": x.get("status"),
            "sale_price": x.get("sale_price"),
            "supplier_cost": x.get("supplier_cost"),
            "company_profit": x.get("company_profit"),
            "created_at": x.get("created_at"),
        }
        for x in state.get("transactions", []) or []
        if str(x.get("deal_id") or "") == deal_id
    ]


def _readiness(
    deal: Dict[str, Any], buyer: Dict[str, Any], supplier: Dict[str, Any], offers: List[Dict[str, Any]],
    comparison: Dict[str, Any], cfo: Dict[str, Any], trade: Dict[str, Any], docs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    components: Dict[str, Dict[str, Any]] = {}

    components["buyer_identity"] = {"weight": 10, "ready": bool(buyer.get("verified_company") or deal.get("buyer_legal_identity_verified"))}
    components["supplier_identity"] = {"weight": 10, "ready": bool(supplier.get("verified_company") or deal.get("supplier_legal_identity_verified"))}
    components["requirement"] = {"weight": 15, "ready": bool(deal.get("requirement_confirmed"))}
    comparable = bool(comparison and comparison.get("status") == "comparable")
    components["supplier_evidence"] = {"weight": 15, "ready": comparable or len(offers) >= 2}
    econ = deal.get("economics", {}) or {}
    economics_known = bool(deal.get("economic_value_known")) or _f(cfo.get("company_profit_usd")) > 0 or _f(econ.get("company_profit")) > 0
    components["economics"] = {"weight": 15, "ready": economics_known and (econ.get("viable") is not False)}

    trade_needed = bool(trade.get("has_cross_border"))
    trade_ready = not trade_needed or bool((trade.get("comparison") or {}).get("status") == "comparable_routes") or bool(trade.get("all_routes_decision_ready"))
    components["trade_logistics"] = {"weight": 10, "ready": trade_ready, "required": trade_needed}

    checklist = deal.get("preclose_checklist", {}) or {}
    close_control_keys = [
        "commercial_terms_confirmed", "delivery_terms_confirmed", "invoice_tax_treatment_confirmed", "payment_instructions_verified"
    ]
    close_controls_ready = sum(1 for key in close_control_keys if bool(checklist.get(key) or deal.get(key)))
    components["commercial_controls"] = {
        "weight": 15,
        "ready": close_controls_ready == len(close_control_keys),
        "progress": close_controls_ready / len(close_control_keys),
    }
    traceable_docs = [x for x in docs if x.get("extraction_status") == "extracted"]
    components["document_traceability"] = {"weight": 5, "ready": bool(traceable_docs or any(x.get("source_traceable") for x in offers))}
    components["human_authority"] = {"weight": 5, "ready": bool(checklist.get("human_close_approval") or deal.get("human_close_approval") or deal.get("close_approval_status") == "approved")}

    score = 0.0
    for component in components.values():
        progress = component.get("progress")
        if progress is not None:
            score += _f(component.get("weight")) * max(0.0, min(1.0, _f(progress)))
        elif component.get("ready"):
            score += _f(component.get("weight"))

    close_keys = [
        "buyer_legal_identity_verified", "supplier_legal_identity_verified", "requirement_confirmed",
        "commercial_terms_confirmed", "delivery_terms_confirmed", "invoice_tax_treatment_confirmed",
        "payment_instructions_verified", "human_close_approval",
    ]
    close_check = deal.get("preclose_checklist", {}) or {}
    close_ready_count = sum(1 for key in close_keys if bool(close_check.get(key) or deal.get(key) or (key == "human_close_approval" and deal.get("close_approval_status") == "approved")))
    return {
        "score": round(score, 1),
        "components": components,
        "close_readiness_pct": round(close_ready_count / len(close_keys) * 100.0, 1),
    }


def _blockers(deal: Dict[str, Any], cfo: Dict[str, Any], offers: List[Dict[str, Any]], trade: Dict[str, Any], docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blockers: List[Dict[str, Any]] = []
    for flag in cfo.get("risk_flags", []) or []:
        blockers.append({"source": "CFO", "severity": "high" if flag in {"payment_instructions_unverified", "buyer_identity_unverified", "supplier_identity_unverified"} else "medium", "code": flag})
    for field in deal.get("preclose_missing", []) or []:
        blockers.append({"source": "Pre-Close Gate", "severity": "human" if field == "human_close_approval" else "high", "code": field})
    for offer in offers:
        for field in offer.get("missing_commercial_fields", []) or []:
            blockers.append({"source": f"Quote {offer.get('id')}", "severity": "medium", "code": str(field)})
    for case in trade.get("cases", []) or []:
        for field in case.get("critical_missing", []) or []:
            blockers.append({"source": f"Trade {case.get('offer_id')}", "severity": "high", "code": str(field)})
    for doc in docs:
        if doc.get("extraction_status") == "ocr_required":
            blockers.append({"source": f"Document {doc.get('id')}", "severity": "medium", "code": "ocr_required"})

    seen = set()
    deduped: List[Dict[str, Any]] = []
    for row in blockers:
        key = (row.get("source"), row.get("code"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped[:30]


def _next_action(
    deal: Dict[str, Any], readiness: Dict[str, Any], offers: List[Dict[str, Any]], comparison: Dict[str, Any],
    trade: Dict[str, Any], approvals: List[Dict[str, Any]], blockers: List[Dict[str, Any]],
) -> Dict[str, Any]:
    pending_approval = next((x for x in approvals if x.get("status") == "pending"), None)
    nonhuman_preclose = [x for x in deal.get("preclose_missing", []) or [] if x != "human_close_approval"]
    only_human = bool(deal.get("preclose_missing")) and not nonhuman_preclose and "human_close_approval" in (deal.get("preclose_missing") or [])

    if only_human or (pending_approval and not nonhuman_preclose and readiness.get("close_readiness_pct", 0) >= 87.5):
        return {"code": "human_close_decision", "owner": "José", "autonomous": False, "title": "Decisión humana de cierre", "reason": "Los controles operativos están completos o casi completos y resta autoridad humana vinculante."}
    if not deal.get("requirement_confirmed"):
        return {"code": "confirm_requirement", "owner": "RevOps", "autonomous": True, "title": "Confirmar requerimiento del comprador", "reason": "No avanzar economía/cotización sobre una necesidad no confirmada."}
    if not offers:
        return {"code": "obtain_supplier_quotes", "owner": "RevOps", "autonomous": True, "title": "Obtener cotizaciones reales", "reason": "El expediente todavía no tiene evidencia económica de proveedores."}
    incomplete = [x for x in offers if x.get("normalization_status") == "clarification_required" or x.get("missing_commercial_fields")]
    if incomplete:
        return {"code": "clarify_quotes", "owner": "RevOps / Quote Engine", "autonomous": True, "title": "Completar cotizaciones incompletas", "reason": "Hay ofertas reales que todavía no son homogéneas/comparables."}
    if len(offers) < 2 or not comparison or comparison.get("status") != "comparable":
        return {"code": "build_supplier_competition", "owner": "RevOps / Deep Dive", "autonomous": True, "title": "Construir competencia de proveedores", "reason": "Se necesitan al menos dos alternativas comparables para una decisión comercial robusta."}
    if trade.get("has_cross_border") and not ((trade.get("comparison") or {}).get("status") == "comparable_routes" or trade.get("all_routes_decision_ready")):
        return {"code": "complete_trade_model", "owner": "Trade & Logistics", "autonomous": True, "title": "Completar landed cost y ruta logística", "reason": "Existe componente internacional y todavía faltan datos para comparar costo puesto en destino."}
    if not deal.get("economics") or _f((deal.get("economics") or {}).get("company_profit")) <= 0:
        return {"code": "complete_deal_economics", "owner": "CFO / Commerce", "autonomous": True, "title": "Completar economía del deal", "reason": "No hay beneficio/margen trazable suficiente para decidir."}
    if nonhuman_preclose:
        return {"code": "complete_preclose_controls", "owner": "Pre-Close Gate", "autonomous": True, "title": "Completar controles de pre-cierre", "reason": ", ".join(nonhuman_preclose[:5])}
    if pending_approval:
        return {"code": "human_close_decision", "owner": "José", "autonomous": False, "title": "Decisión humana de cierre", "reason": "Existe aprobación ejecutiva pendiente."}
    return {"code": "advance_deal", "owner": "RevOps", "autonomous": True, "title": str(deal.get("next_action") or "Avanzar próxima etapa comercial"), "reason": "El Deal Room no detecta un bloqueo superior adicional."}


def _room_status(deal: Dict[str, Any], next_action: Dict[str, Any], transactions: List[Dict[str, Any]], blockers: List[Dict[str, Any]]) -> str:
    real_tx = [x for x in transactions if str(x.get("status") or "") not in {"closed_simulated", "simulated"}]
    if real_tx:
        return "transaction_recorded"
    if next_action.get("autonomous") is False:
        return "human_decision_required"
    if deal.get("close_gate") == "ready" or deal.get("stage") == "listo para cierre aprobado":
        return "close_ready"
    if any(x.get("severity") == "high" for x in blockers):
        return "blocked"
    return "active"


def build_deal_room(state: Dict[str, Any], deal: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    context = context or {}
    accounts = context.get("accounts") or _accounts(state)
    opportunities = context.get("opportunities") or _opportunities(state)
    cfo_map = context.get("cfo") or _cfo_rows(state)
    docs_map = context.get("documents") or _documents_by_deal(state)
    messages_map = context.get("messages") or _messages_by_deal(state)
    decisions_map = context.get("decisions") or _decisions_by_deal(state)

    deal_id = str(deal.get("id") or "")
    opportunity = opportunities.get(str(deal.get("opportunity_id") or ""), {})
    buyer = accounts.get(str(deal.get("buyer_account_id") or ""), {})
    supplier = accounts.get(str(deal.get("supplier_account_id") or ""), {})
    offers = [x for x in state.get("offers", []) or [] if str(x.get("deal_id") or "") == deal_id and x.get("source") != "demo/simulación"]
    comparison = _quote_comparison(state, deal_id)
    trade = _trade(state, deal_id)
    docs = docs_map.get(deal_id, [])
    approvals = _approvals(state, deal_id)
    transactions = _transactions(state, deal_id)
    cfo = cfo_map.get(deal_id, {})
    readiness = _readiness(deal, buyer, supplier, offers, comparison, cfo, trade, docs)
    blockers = _blockers(deal, cfo, offers, trade, docs)
    next_action = _next_action(deal, readiness, offers, comparison, trade, approvals, blockers)
    status = _room_status(deal, next_action, transactions, blockers)
    revops = _revops_case(state, deal)

    proposal = next((x for x in reversed(state.get("proposals", []) or []) if str(x.get("deal_id") or "") == deal_id), None)
    war_item = next((x for x in (state.get("war_room", {}) or {}).get("top_money_opportunities", []) or [] if str(x.get("deal_id") or "") == deal_id), None)

    room = {
        "deal_id": deal_id,
        "updated_at": utcnow(),
        "status": status,
        "stage": deal.get("stage"),
        "category": deal.get("need") or deal.get("category") or opportunity.get("category"),
        "source": deal.get("source"),
        "opportunity": {
            "id": opportunity.get("id"),
            "source": opportunity.get("source"),
            "score": opportunity.get("portfolio_priority_score") or opportunity.get("score"),
            "evidence_refs": list(opportunity.get("evidence_refs") or [])[:10],
        },
        "buyer": {
            "name": deal.get("buyer") or buyer.get("company_name") or buyer.get("name_hint"),
            "account_id": buyer.get("id") or deal.get("buyer_account_id"),
            "verified_company": bool(buyer.get("verified_company") or deal.get("buyer_legal_identity_verified")),
            "verified_contact": bool(buyer.get("commercial_channel_verified") or buyer.get("verified_contact")),
            "domain": buyer.get("domain"),
            "market": buyer.get("market") or buyer.get("growth_market"),
        },
        "primary_supplier": {
            "name": deal.get("supplier") or supplier.get("company_name") or supplier.get("name_hint"),
            "account_id": supplier.get("id") or deal.get("supplier_account_id"),
            "verified_company": bool(supplier.get("verified_company") or deal.get("supplier_legal_identity_verified")),
            "verified_contact": bool(supplier.get("commercial_channel_verified") or supplier.get("verified_contact")),
            "domain": supplier.get("domain"),
            "market": supplier.get("market") or supplier.get("growth_market"),
        },
        "requirement": {
            "confirmed": bool(deal.get("requirement_confirmed")),
            "revops_status": revops.get("status"),
            "revops_next_action": revops.get("next_action"),
            "details": revops.get("requirement") or deal.get("requirement") or {},
        },
        "offers": offers[:20],
        "quote_comparison": comparison or None,
        "documents": docs[:20],
        "communications": messages_map.get(deal_id, []),
        "trade_logistics": trade,
        "economics": {
            "deal": deal.get("economics") or {},
            "cfo": cfo,
            "war_room": war_item or {},
            "proposal": proposal,
        },
        "risks_and_controls": {
            "blockers": blockers,
            "risk_flags": list(cfo.get("risk_flags") or []),
            "preclose_checklist": deal.get("preclose_checklist") or {},
            "preclose_missing": list(deal.get("preclose_missing") or []),
            "close_gate": deal.get("close_gate"),
        },
        "readiness": readiness,
        "approvals": approvals,
        "transactions": transactions,
        "decisions": decisions_map.get(deal_id, []),
        "next_best_action": next_action,
        "audit": {
            "single_source_rule": "Deal Room aggregates references to authoritative engine state; it does not overwrite source evidence.",
            "historical_price_rule": "Historical prices remain evidence only and are never silently treated as current quotes.",
            "binding_rule": "Contracts, orders, payments and binding terms remain human-controlled.",
        },
    }
    return room


def deal_room_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    context = {
        "accounts": _accounts(state),
        "opportunities": _opportunities(state),
        "cfo": _cfo_rows(state),
        "documents": _documents_by_deal(state),
        "messages": _messages_by_deal(state),
        "decisions": _decisions_by_deal(state),
    }
    deals = [
        x for x in state.get("deals", []) or []
        if x.get("id") and x.get("source") != "demo" and str(x.get("stage") or "") not in {"cerrado (simulación)", "closed_simulated"}
    ]
    rooms = [build_deal_room(state, deal, context) for deal in deals]
    rooms.sort(key=lambda x: (
        x.get("status") == "human_decision_required",
        _f((x.get("economics", {}).get("cfo", {}) or {}).get("money_score")),
        _f(x.get("readiness", {}).get("score")),
    ), reverse=True)
    rooms = rooms[:MAX_ROOMS]
    state["deal_rooms"] = rooms
    state["deal_room_index"] = {str(x.get("deal_id")): x for x in rooms}

    status_counts: Dict[str, int] = defaultdict(int)
    for room in rooms:
        status_counts[str(room.get("status") or "unknown")] += 1

    primary = rooms[0] if rooms else None
    report = {
        "updated_at": utcnow(),
        "rooms": len(rooms),
        "status_counts": dict(status_counts),
        "primary_deal_id": (primary or {}).get("deal_id"),
        "primary_status": (primary or {}).get("status"),
        "primary_readiness_score": (primary or {}).get("readiness", {}).get("score") if primary else None,
        "primary_next_action": (primary or {}).get("next_best_action") if primary else None,
        "human_decisions_required": status_counts.get("human_decision_required", 0),
        "blocked_rooms": status_counts.get("blocked", 0),
        "governance": {
            "source_of_truth": "authoritative engine state + immutable references",
            "does_not_execute_binding_actions": True,
            "binding_actions_require_human": True,
        },
    }
    state["deal_room"] = report

    if primary:
        next_action = primary.get("next_best_action", {}) or {}
        record_decision(
            state,
            engine="Autonomous Deal Room",
            object_type="deal",
            object_id=str(primary.get("deal_id") or ""),
            decision=f"dossier_status:{primary.get('status')}",
            reason=f"Readiness {primary.get('readiness', {}).get('score')}%; next action {next_action.get('code')}: {next_action.get('title')}.",
            action="prepare_draft" if next_action.get("autonomous") is False else "score_opportunity",
            confidence=max(0.55, min(0.98, _f(primary.get("readiness", {}).get("score"), 50.0) / 100.0)),
            evidence_refs=list((primary.get("opportunity") or {}).get("evidence_refs") or [])[:8],
            allowed=True,
            requires_approval=not bool(next_action.get("autonomous", True)),
        )
    return report
