from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision


MAX_QUEUE = 80
MAX_TOP_ACTIONS = 12


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _log(state: Dict[str, Any], msg: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": msg})
    state["activity"] = state["activity"][:100]


def _score(impact: float, urgency: float, confidence: float, effort: float, risk: str) -> float:
    risk_penalty = {"low": 0.0, "medium": 6.0, "high": 18.0}.get(risk, 5.0)
    raw = impact * 0.46 + urgency * 0.29 + max(0.0, min(1.0, confidence)) * 25.0
    return round(max(0.0, raw / (1.0 + max(0.0, effort) * 0.08) - risk_penalty), 2)


def _task(key: str, kind: str, title: str, reason: str, *, impact: float, urgency: float,
          confidence: float = 0.8, effort: float = 1.0, risk: str = "low",
          autonomous: bool = True, object_type: str | None = None,
          object_id: str | None = None, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "key": key,
        "kind": kind,
        "title": title,
        "reason": reason,
        "impact": impact,
        "urgency": urgency,
        "confidence": confidence,
        "effort": effort,
        "risk": risk,
        "autonomous": autonomous,
        "object_type": object_type,
        "object_id": object_id,
        "payload": payload or {},
        "priority_score": _score(impact, urgency, confidence, effort, risk),
        "created_at": utcnow(),
    }


def _deal_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}


def _account_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) if x.get("id")}


def _latest_sent_for_contact(state: Dict[str, Any], contact: str) -> Dict[str, Any] | None:
    contact = str(contact or "").strip().lower()
    items = [
        x for x in state.get("outbox", [])
        if x.get("status") == "sent" and str(x.get("contact") or "").strip().lower() == contact
    ]
    return items[-1] if items else None


def _build_supplier_competitions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    competitions: List[Dict[str, Any]] = []
    account_by_id = _account_map(state)
    for case in state.get("deep_dive_cases", []):
        if case.get("status") != "attack":
            continue
        alternatives = []
        for supplier in case.get("supplier_alternatives", []) or []:
            account = account_by_id.get(str(supplier.get("id") or ""), {})
            alternatives.append({
                "supplier_account_id": supplier.get("id"),
                "name": supplier.get("name"),
                "domain": supplier.get("domain"),
                "verification_score": _f(supplier.get("verification_score")),
                "commercial_channel_verified": bool(supplier.get("commercial_channel_verified")),
                "lead_score": _f(account.get("lead_score")),
                "status": "ready_for_rfq" if supplier.get("commercial_channel_verified") else "channel_verification_required",
            })
        alternatives.sort(
            key=lambda x: (x["commercial_channel_verified"], x["verification_score"], x["lead_score"]),
            reverse=True,
        )
        competitions.append({
            "id": f"COMP-{len(competitions)+1:05d}",
            "deep_dive_case_id": case.get("id"),
            "opportunity_id": case.get("opportunity_id"),
            "category": case.get("category"),
            "target": "crear competencia real entre proveedores sin inventar ofertas",
            "alternatives": alternatives,
            "ready_supplier_count": sum(1 for x in alternatives if x["commercial_channel_verified"]),
            "comparison_dimensions": [
                "precio total", "plazo de entrega", "forma de pago", "validez", "garantía",
                "documentación técnica", "flete", "impuestos", "cumplimiento técnico", "riesgo de contraparte",
            ],
            "updated_at": utcnow(),
        })
    state["supplier_competitions"] = competitions
    return competitions


def _build_approval_briefs(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    deals = _deal_map(state)
    briefs: List[Dict[str, Any]] = []
    for approval in state.get("approvals", []):
        if approval.get("status") != "pending":
            continue
        deal = deals.get(str(approval.get("deal_id") or ""), {})
        econ = deal.get("economics", {}) or {}
        briefs.append({
            "id": f"BRIEF-{len(briefs)+1:05d}",
            "approval_id": approval.get("id"),
            "deal_id": deal.get("id"),
            "buyer": deal.get("buyer"),
            "supplier": deal.get("supplier"),
            "need": deal.get("need"),
            "sale_price": econ.get("sale_price"),
            "supplier_cost": econ.get("supplier_cost"),
            "company_profit": econ.get("company_profit"),
            "company_share_pct": econ.get("company_share_pct"),
            "close_probability": deal.get("close_prob"),
            "preclose_missing": list(deal.get("preclose_missing") or []),
            "risk_flags": list(deal.get("risk_flags") or []),
            "recommendation": "aprobar solo si identidad, términos, fiscalidad, entrega, pago y documentación están confirmados",
            "status": "human_decision_required",
            "updated_at": utcnow(),
        })
    state["approval_briefs"] = briefs
    return briefs


def _materialize_followups(state: Dict[str, Any]) -> int:
    outbox = state.setdefault("outbox", [])
    accounts = _account_map(state)
    created = 0
    existing_keys = {str(x.get("os_action_key")) for x in outbox if x.get("os_action_key")}

    for action in state.get("relationship_actions", []) or []:
        contact = str(action.get("contact") or "").strip().lower()
        if not contact:
            continue
        relation = next(
            (x for x in state.get("commercial_relationships", []) if x.get("key") == action.get("relationship_key")),
            {},
        )
        if relation.get("opted_out") or relation.get("relationship_state") == "cooldown":
            continue
        source = _latest_sent_for_contact(state, contact)
        if not source:
            continue
        action_key = f"followup|{action.get('relationship_key')}|{relation.get('last_outbound_at')}"
        if action_key in existing_keys:
            continue
        account = accounts.get(str(relation.get("account_id") or ""), {})
        verified = bool(account.get("verified_contact"))
        outbox.append({
            "id": f"MSG-{len(outbox)+1:04d}",
            "deal_id": source.get("deal_id"),
            "kind": "follow_up",
            "counterparty": action.get("counterparty") or source.get("counterparty"),
            "channel": "email",
            "contact": contact,
            "contact_verified": verified,
            "subject": "Seguimiento de nuestra conversación comercial",
            "body": "Queríamos consultar si pudieron revisar nuestro mensaje anterior y si podemos aportar información adicional para facilitar la evaluación.",
            "status": "ready" if verified else "needs_verified_contact",
            "os_action_key": action_key,
            "created_at": utcnow(),
        })
        existing_keys.add(action_key)
        created += 1
    return created


def _build_postmortems(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    old = {str(x.get("deal_id")): x for x in state.setdefault("deal_postmortems", []) if x.get("deal_id")}
    for deal in state.get("deals", []):
        if deal.get("stage") not in {"descartado", "cancelado", "perdido", "closed_lost"}:
            continue
        deal_id = str(deal.get("id") or "")
        if not deal_id or deal_id in old:
            continue
        reasons = list(deal.get("loss_reasons") or [])
        if not reasons:
            reasons = [str(deal.get("next_action") or "motivo no estructurado")]
        old[deal_id] = {
            "id": f"PM-{len(old)+1:05d}",
            "deal_id": deal_id,
            "category": deal.get("need") or deal.get("category"),
            "expected_value": deal.get("expected_value"),
            "company_profit": deal.get("company_profit"),
            "reasons": reasons[:8],
            "lesson": "evitar repetir el patrón de pérdida y alimentar ranking de mercado/contrapartes",
            "created_at": utcnow(),
        }
    state["deal_postmortems"] = list(old.values())[-100:]
    return state["deal_postmortems"]


def _build_expansion_plans(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    deals = _deal_map(state)
    plans: List[Dict[str, Any]] = []
    for txn in state.get("transactions", []):
        if str(txn.get("status") or "") in {"closed_simulated", "simulated"}:
            continue
        if str(txn.get("status") or "") not in {"closed", "settled", "paid", "completed"}:
            continue
        deal = deals.get(str(txn.get("deal_id") or ""), {})
        plans.append({
            "id": f"EXP-{len(plans)+1:05d}",
            "transaction_id": txn.get("id"),
            "deal_id": deal.get("id"),
            "buyer": deal.get("buyer"),
            "category": deal.get("need") or deal.get("category"),
            "objective": "convertir una venta exitosa en relación recurrente sin asumir demanda no confirmada",
            "actions": [
                "verificar satisfacción y cumplimiento de entrega",
                "documentar qué funcionó comercialmente",
                "identificar necesidades adyacentes solo con evidencia",
                "priorizar repetición si margen, cobro y relación fueron saludables",
            ],
            "created_at": utcnow(),
        })
    state["account_expansion_plans"] = plans
    return plans


def _collect_tasks(state: Dict[str, Any], competitions: List[Dict[str, Any]], briefs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []

    for case in state.get("deep_dive_cases", []) or []:
        if case.get("status") not in {"attack", "watch"}:
            continue
        primary = (case.get("strategy", {}) or {}).get("primary_action", {}) or {}
        tasks.append(_task(
            f"deepdive|{case.get('id')}|{primary.get('code')}",
            "deep_dive",
            str(primary.get("objective") or case.get("next_action") or "Avanzar oportunidad prioritaria"),
            f"Win score {case.get('win_score', 0)}; gaps: {', '.join(case.get('gaps', [])[:4]) or 'sin gap crítico'}",
            impact=min(100.0, 55.0 + _f(case.get("win_score")) * 0.45),
            urgency=90.0 if case.get("status") == "attack" else 65.0,
            confidence=min(0.98, max(0.45, _f(case.get("win_score")) / 100.0)),
            effort=2.0,
            risk="low",
            autonomous=bool(primary.get("autonomous", True)),
            object_type="deep_dive_case",
            object_id=str(case.get("id") or ""),
        ))

    revops = state.get("commercial_execution_directive", {}) or {}
    if revops.get("primary_case_id") and revops.get("primary_status"):
        status = str(revops.get("primary_status"))
        urgency = {
            "nonbinding_negotiation": 98,
            "quote_clarification": 94,
            "commercial_comparison_ready": 92,
            "rfq_execution": 90,
            "requirement_discovery": 88,
            "single_quote_ready": 84,
            "awaiting_supplier_response": 68,
            "buyer_question_answered": 62,
        }.get(status, 70)
        tasks.append(_task(
            f"revops|{revops.get('primary_case_id')}|{status}",
            "commercial_execution",
            f"RevOps: {revops.get('primary_next_action') or status}",
            f"Caso {revops.get('primary_case_id')} en estado {status}; {revops.get('active_cases', 0)} caso(s) comerciales activos.",
            impact=95 if status in {"nonbinding_negotiation", "commercial_comparison_ready"} else 88,
            urgency=urgency,
            confidence=0.95,
            effort=1.0,
            risk="medium" if status in {"nonbinding_negotiation", "rfq_execution", "quote_clarification"} else "low",
            autonomous=True,
            object_type="commercial_case",
            object_id=str(revops.get("primary_case_id")),
            payload={"next_action": revops.get("primary_next_action")},
        ))

    for action in state.get("relationship_actions", []) or []:
        tasks.append(_task(
            f"relationship|{action.get('relationship_key')}|{action.get('kind')}",
            "follow_up",
            f"Seguimiento profesional: {action.get('counterparty') or 'contraparte'}",
            str(action.get("reason") or "Seguimiento debido"),
            impact=72, urgency=82, confidence=0.95, effort=0.5, risk="medium", autonomous=True,
            object_type="relationship", object_id=str(action.get("relationship_key") or ""),
        ))

    for brief in briefs:
        tasks.append(_task(
            f"approval|{brief.get('approval_id')}",
            "human_approval",
            f"Decisión vinculante requerida: {brief.get('deal_id')}",
            f"Beneficio estimado {brief.get('company_profit')} / margen {brief.get('company_share_pct')}%; controles faltantes: {', '.join(brief.get('preclose_missing', [])[:4]) or 'ninguno'}",
            impact=100, urgency=95, confidence=0.98, effort=1.0, risk="high", autonomous=False,
            object_type="approval", object_id=str(brief.get("approval_id") or ""),
        ))

    for comp in competitions:
        if comp.get("ready_supplier_count", 0) < 2:
            tasks.append(_task(
                f"competition|{comp.get('deep_dive_case_id')}|depth",
                "supplier_competition",
                f"Aumentar competencia de proveedores para {comp.get('category')}",
                "Hay menos de dos proveedores con canal comercial verificado; falta poder de negociación real.",
                impact=88, urgency=78, confidence=0.9, effort=2.0, risk="low", autonomous=True,
                object_type="supplier_competition", object_id=str(comp.get("id") or ""),
            ))

    for deal in state.get("deals", []):
        missing = list(deal.get("preclose_missing") or [])
        if missing:
            tasks.append(_task(
                f"preclose|{deal.get('id')}",
                "preclose_controls",
                f"Completar controles de cierre de {deal.get('id')}",
                "Faltan: " + ", ".join(missing[:6]),
                impact=96, urgency=90, confidence=1.0, effort=2.0, risk="high", autonomous=False,
                object_type="deal", object_id=str(deal.get("id") or ""),
            ))

    for message in state.get("outbox", []):
        if message.get("status") == "blocked_quality":
            tasks.append(_task(
                f"quality|{message.get('id')}",
                "repair_outbound",
                f"Reparar mensaje bloqueado {message.get('id')}",
                "; ".join(message.get("quality_reasons", [])[:4]) or "No superó control de calidad",
                impact=60, urgency=58, confidence=0.98, effort=1.0, risk="low", autonomous=True,
                object_type="message", object_id=str(message.get("id") or ""),
            ))

    telemetry = state.get("connector_telemetry", {}) or {}
    if telemetry and not telemetry.get("postgres", {}).get("connected", False):
        tasks.append(_task(
            "health|postgres", "operational_health", "Restablecer persistencia PostgreSQL",
            "La memoria operativa no debe depender de estado efímero.",
            impact=100, urgency=100, confidence=1.0, effort=2.0, risk="low", autonomous=False,
            object_type="system", object_id="postgres",
        ))

    by_key: Dict[str, Dict[str, Any]] = {}
    for task in tasks:
        key = str(task["key"])
        if key not in by_key or task["priority_score"] > by_key[key]["priority_score"]:
            by_key[key] = task
    ordered = sorted(by_key.values(), key=lambda x: x["priority_score"], reverse=True)
    return ordered[:MAX_QUEUE]


def professional_os_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    competitions = _build_supplier_competitions(state)
    briefs = _build_approval_briefs(state)
    followups_created = _materialize_followups(state)
    postmortems = _build_postmortems(state)
    expansions = _build_expansion_plans(state)
    queue = _collect_tasks(state, competitions, briefs)

    autonomous = [x for x in queue if x.get("autonomous")]
    human = [x for x in queue if not x.get("autonomous")]
    top = queue[:MAX_TOP_ACTIONS]

    state["operating_action_queue"] = queue
    state["chief_of_staff"] = {
        "updated_at": utcnow(),
        "mode": "professional_company_os",
        "top_actions": top,
        "autonomous_actions": len(autonomous),
        "human_decisions_required": len(human),
        "followups_materialized": followups_created,
        "supplier_competitions": len(competitions),
        "approval_briefs": len(briefs),
        "postmortems": len(postmortems),
        "account_expansion_plans": len(expansions),
        "operating_rule": "cada ciclo debe convertir señales en acciones concretas; automatizar lo reversible y de bajo riesgo, escalar únicamente compromisos vinculantes o controles que requieran autoridad humana",
    }

    if top:
        first = top[0]
        record_decision(
            state,
            engine="LUMEN Professional OS",
            object_type=str(first.get("object_type") or "company"),
            object_id=str(first.get("object_id") or "LUMEN"),
            decision=str(first.get("kind") or "prioritize_action"),
            reason=str(first.get("reason") or first.get("title") or "Prioridad operativa"),
            action="score_opportunity" if first.get("autonomous") else "prepare_draft",
            confidence=float(first.get("confidence") or 0.8),
            evidence_refs=[],
            allowed=True,
            requires_approval=not bool(first.get("autonomous")),
        )

    if followups_created or briefs or competitions:
        _log(
            state,
            f"Professional OS: {len(queue)} acciones priorizadas, {followups_created} seguimientos preparados, {len(competitions)} competencias de proveedores y {len(briefs)} decisiones humanas empaquetadas.",
        )

    return {
        "updated_at": utcnow(),
        "queue_size": len(queue),
        "top_action": top[0] if top else None,
        "autonomous_actions": len(autonomous),
        "human_decisions_required": len(human),
        "followups_materialized": followups_created,
        "supplier_competitions": len(competitions),
        "approval_briefs": len(briefs),
        "postmortems": len(postmortems),
        "account_expansion_plans": len(expansions),
    }
