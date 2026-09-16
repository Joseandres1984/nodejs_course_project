from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


VERSION = "2.0-parallel-service-growth"
MAX_PREPARED = 40
SERVICE_LANE_SHARE_CAP = 0.35
FOLLOWUP_DAYS = 4

SERVICE_CATALOG = [
    {
        "id": "SRV-SOURCING-EXPRESS",
        "name": "LUMEN Sourcing Express",
        "audience": "buyer",
        "status": "active",
        "promise": "Investigar y preseleccionar proveedores para una necesidad B2B concreta.",
        "deliverables": [
            "shortlist de proveedores investigados",
            "contactos comerciales públicos o verificados cuando existan",
            "comparación de alternativas con evidencia disponible",
            "próximos pasos recomendados",
        ],
        "commercial_model": "fixed_service_fee_then_optional_success_fee",
        "price_policy": "human_confirmed_before_offer",
        "binding_terms_human_required": True,
    },
    {
        "id": "SRV-B2B-PROSPECTING",
        "name": "LUMEN Prospección B2B",
        "audience": "supplier",
        "status": "active",
        "promise": "Identificar empresas objetivo y señales comerciales compatibles con la oferta de un proveedor.",
        "deliverables": [
            "lista priorizada de empresas objetivo",
            "señales públicas de demanda o encaje comercial cuando existan",
            "canales corporativos verificados cuando existan",
            "priorización de próximos contactos",
        ],
        "commercial_model": "fixed_service_fee_or_monthly_retainer_then_optional_success_fee",
        "price_policy": "human_confirmed_before_offer",
        "binding_terms_human_required": True,
    },
    {
        "id": "SRV-PRICE-INTEL",
        "name": "LUMEN Inteligencia de Precios",
        "audience": "buyer",
        "status": "incubating",
        "promise": "Organizar referencias públicas y alternativas para mejorar una decisión de compra B2B.",
        "commercial_model": "fixed_service_fee",
        "price_policy": "human_confirmed_before_offer",
        "binding_terms_human_required": True,
    },
    {
        "id": "SRV-OPPORTUNITY-RADAR",
        "name": "LUMEN Radar de Oportunidades",
        "audience": "supplier",
        "status": "incubating",
        "promise": "Seguimiento periódico de señales públicas y oportunidades compatibles con un rubro definido.",
        "commercial_model": "monthly_retainer",
        "price_policy": "human_confirmed_before_offer",
        "binding_terms_human_required": True,
    },
]

TERMINAL_STAGES = {"won", "lost"}
STAGE_ORDER = {
    "verification_required": 10,
    "qualified": 20,
    "outreach_prepared": 30,
    "contacted": 40,
    "replied": 50,
    "diagnosis": 60,
    "proposal_ready": 70,
    "followup": 80,
    "won": 90,
    "lost": 90,
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().strip().split())


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _stable(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(x or "") for x in parts)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12].upper()


def _service_by_id(service_id: str) -> Optional[Dict[str, Any]]:
    for item in SERVICE_CATALOG:
        if item.get("id") == service_id:
            return item
    return None


def _service_for(account: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    kind = str(account.get("type") or "").lower()
    if kind == "buyer":
        return SERVICE_CATALOG[0]
    if kind in {"supplier", "partner", "store"}:
        return SERVICE_CATALOG[1]
    return None


def _eligible_account(account: Dict[str, Any]) -> bool:
    if not isinstance(account, dict) or not account.get("verified_company"):
        return False
    if account.get("risk_tier") == "BLOCKED" or account.get("can_outreach") is False:
        return False
    if not (
        account.get("commercial_email")
        or account.get("verified_contact")
        or account.get("domain")
        or account.get("official_domain")
    ):
        return False
    return _service_for(account) is not None


def _score(account: Dict[str, Any]) -> float:
    score = max(_f(account.get("verification_score")), _f(account.get("lead_score")))
    if account.get("direct_inbound_demand"):
        score += 24
    if account.get("demand_signal"):
        score += 14
    if account.get("commercial_email"):
        score += 8
    if account.get("verified_contact"):
        score += 6
    return round(min(100.0, score), 1)


def _opp_id(account_id: str, service_id: str) -> str:
    return _stable("SVC-", "LUMEN-SERVICE", account_id, service_id)


def _prepare_opportunities(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    existing_rows = state.get("service_revenue_opportunities", []) or []
    existing = {str(x.get("id") or ""): x for x in existing_rows if isinstance(x, dict)}
    ranked = [x for x in state.get("candidate_accounts", []) or [] if _eligible_account(x)]
    ranked.sort(key=lambda x: (-_score(x), str(x.get("id") or "")))

    prepared: List[Dict[str, Any]] = []
    for account in ranked[:MAX_PREPARED]:
        service = _service_for(account)
        if not service:
            continue
        account_id = str(
            account.get("id")
            or account.get("domain")
            or account.get("official_domain")
            or account.get("company_name")
            or ""
        ).strip()
        if not account_id:
            continue
        oid = _opp_id(account_id, str(service["id"]))
        row = existing.get(oid, {})
        if str(row.get("status") or "") in {"won", "lost", "declined", "contracted"}:
            prepared.append(row)
            continue
        row.update({
            "id": oid,
            "service_id": service["id"],
            "service_name": service["name"],
            "account_id": account.get("id"),
            "company_name": _clean(
                account.get("company_name")
                or account.get("name_hint")
                or account.get("domain")
                or account.get("official_domain")
                or "Empresa",
                180,
            ),
            "audience": service["audience"],
            "fit_score": _score(account),
            "status": str(row.get("status") or "prepared_not_sent"),
            "commercial_email": _clean(account.get("commercial_email"), 180),
            "domain": _clean(account.get("domain") or account.get("official_domain"), 180),
            "evidence": {
                "verified_company": bool(account.get("verified_company")),
                "verified_contact": bool(account.get("verified_contact")),
                "demand_signal": bool(account.get("demand_signal")),
                "direct_inbound_demand": bool(account.get("direct_inbound_demand")),
            },
            "next_action": (
                "Preparar diagnóstico de sourcing; no enviar ni cotizar sin pasar los controles comerciales."
                if service["id"] == "SRV-SOURCING-EXPRESS"
                else "Preparar diagnóstico de prospección; no prometer leads ni resultados no verificados."
            ),
            "price_status": "not_quoted_human_confirmation_required",
            "binding_terms_human_required": True,
            "updated_at": utcnow(),
        })
        row.setdefault("created_at", utcnow())
        prepared.append(row)
    return prepared[:MAX_PREPARED]


def _realized_service_revenue(state: Dict[str, Any]) -> float:
    total = 0.0
    for row in state.get("service_revenue_transactions", []) or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").lower() not in {"paid", "settled", "completed"}:
            continue
        total += max(0.0, _f(row.get("amount_received_usd") or row.get("revenue_usd")))
    return round(total, 2)


def _inquiries(state: Dict[str, Any]) -> Dict[str, int]:
    rows = [x for x in state.get("service_inquiries", []) or [] if isinstance(x, dict)]
    return {
        "total": len(rows),
        "new": sum(1 for x in rows if str(x.get("status") or "") in {"new", "new_unverified"}),
        "qualified": sum(1 for x in rows if str(x.get("status") or "") == "qualified"),
        "converted": sum(1 for x in rows if str(x.get("status") or "") in {"won", "contracted", "paid"}),
    }


def _email_domain(email: Any) -> str:
    text = str(email or "").strip().lower()
    return text.split("@", 1)[1] if "@" in text else ""


def _account_domain(account: Dict[str, Any]) -> str:
    return str(account.get("domain") or account.get("official_domain") or "").strip().lower().removeprefix("www.")


def _match_verified_account(state: Dict[str, Any], company: str, email: str) -> Optional[Dict[str, Any]]:
    email_domain = _email_domain(email).removeprefix("www.")
    company_norm = _norm(company)
    for account in state.get("candidate_accounts", []) or []:
        if not isinstance(account, dict) or not account.get("verified_company"):
            continue
        domain = _account_domain(account)
        if email_domain and domain and email_domain == domain:
            return account
    if company_norm:
        for account in state.get("candidate_accounts", []) or []:
            if not isinstance(account, dict) or not account.get("verified_company"):
                continue
            name = _norm(account.get("company_name") or account.get("name_hint"))
            if name and company_norm == name:
                return account
    return None


def _outreach_draft(service_id: str, company: str) -> str:
    company = company or "su empresa"
    if service_id == "SRV-SOURCING-EXPRESS":
        return (
            f"Hola {company}, desde LUMEN desarrollamos búsquedas B2B de proveedores para necesidades concretas. "
            "Si hoy tienen una búsqueda activa, podemos preparar una preselección de proveedores y alternativas con evidencia disponible. "
            "Si te sirve, contame qué necesitan y lo revisamos."
        )
    return (
        f"Hola {company}, LUMEN ayuda a proveedores B2B a priorizar empresas objetivo y señales comerciales verificables. "
        "Podemos preparar un diagnóstico no vinculante de prospección sobre su oferta. "
        "Si te interesa, contame qué productos o rubros quieren mover y lo armamos."
    )


def _diagnostic_brief(service_id: str, company: str, need: str = "") -> Dict[str, Any]:
    service = _service_by_id(service_id) or {}
    return {
        "service_id": service_id,
        "service_name": service.get("name"),
        "company": company,
        "stated_need": _clean(need, 1200),
        "objective": service.get("promise"),
        "deliverables": list(service.get("deliverables", []) or []),
        "evidence_rule": "Usar sólo datos públicos, verificados o declarados por el cliente; no inferir demanda ni resultados.",
        "binding": False,
    }


def _proposal_draft(service_id: str, company: str, need: str) -> Dict[str, Any]:
    brief = _diagnostic_brief(service_id, company, need)
    return {
        "status": "prepared_nonbinding",
        "title": f"Borrador de alcance · {brief.get('service_name') or service_id}",
        "company": company,
        "objective": brief.get("objective"),
        "stated_need": brief.get("stated_need"),
        "deliverables": brief.get("deliverables"),
        "price": "pending_human_confirmation",
        "terms": "pending_human_confirmation",
        "exclusions": [
            "No garantiza ventas, respuestas, adjudicaciones ni disponibilidad de terceros.",
            "No constituye contrato, presupuesto final ni aceptación de términos.",
        ],
        "binding": False,
    }


def _instagram_service(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict) or str(item.get("status") or "") == "dismissed":
        return None
    text = _norm(item.get("text"))
    if not text or not item.get("commercial_signal"):
        return None
    supplier_terms = (
        "somos proveedores", "somos proveedor", "fabricamos", "somos fabricantes", "ofrecemos",
        "conseguir clientes", "buscar clientes", "mas clientes", "vender", "ventas", "prospeccion",
        "compradores", "distribuir", "distribucion",
    )
    sourcing_terms = (
        "necesito", "busco", "comprar", "cotizacion", "cotizar", "presupuesto", "abastecimiento",
        "proveedores", "un proveedor", "precio", "stock", "disponibilidad",
    )
    if any(term in text for term in supplier_terms):
        return SERVICE_CATALOG[1]
    if any(term in text for term in sourcing_terms):
        return SERVICE_CATALOG[0]
    return None


def _pipeline_id(source: str, source_id: str, service_id: str) -> str:
    return _stable("SCRM-", source, source_id, service_id)


def _advance(row: Dict[str, Any], stage: str, reason: str) -> None:
    current = str(row.get("stage") or "verification_required")
    if current in TERMINAL_STAGES and stage not in TERMINAL_STAGES:
        return
    if stage not in STAGE_ORDER:
        return
    if stage not in TERMINAL_STAGES and STAGE_ORDER.get(stage, 0) < STAGE_ORDER.get(current, 0):
        return
    if current != stage:
        history = list(row.get("history", []) or [])[-19:]
        history.append({"from": current, "to": stage, "reason": reason, "at": utcnow()})
        row["history"] = history
        row["stage"] = stage
        row["stage_reason"] = reason


def _base_pipeline_row(existing: Dict[str, Any], **values: Any) -> Dict[str, Any]:
    row = dict(existing or {})
    row.update(values)
    row.setdefault("created_at", utcnow())
    row.setdefault("stage", "verification_required")
    row.setdefault("contact_truth", "not_contacted")
    row.setdefault("binding_commitment", False)
    row.setdefault("price_status", "human_confirmation_required")
    row["updated_at"] = utcnow()
    return row


def _explicit_close_status(value: Any) -> Optional[str]:
    status = str(value or "").lower()
    if status in {"won", "contracted", "paid"}:
        return "won"
    if status in {"lost", "declined"}:
        return "lost"
    return None


def _apply_outbound_truth(state: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
    by_id = {str(x.get("id") or ""): x for x in rows}
    by_opp = {str(x.get("service_opportunity_id") or ""): x for x in rows if x.get("service_opportunity_id")}
    now = _now_dt()
    for audit in state.get("service_outbound_audit", []) or []:
        if not isinstance(audit, dict):
            continue
        row = by_id.get(str(audit.get("pipeline_id") or "")) or by_opp.get(str(audit.get("service_opportunity_id") or ""))
        if not row:
            continue
        error = _clean(audit.get("error"), 500)
        accepted = audit.get("provider_accepted") is True and not error
        if accepted:
            row["contact_truth"] = "provider_accepted"
            row["contacted_at"] = audit.get("accepted_at") or audit.get("created_at") or utcnow()
            _advance(row, "contacted", "provider_accepted_without_error")
            if not row.get("next_followup_at"):
                row["next_followup_at"] = (now + timedelta(days=FOLLOWUP_DAYS)).isoformat()
        if audit.get("reply_received") is True:
            row["contact_truth"] = "replied"
            row["replied_at"] = audit.get("reply_at") or utcnow()
            _advance(row, "replied", "verified_inbound_reply")
        if audit.get("proposal_provider_accepted") is True and not error:
            row["proposal_truth"] = "provider_accepted"
            _advance(row, "followup", "proposal_provider_accepted")


def _followup_due(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt <= _now_dt()
    except Exception:
        return False


def _build_pipeline(state: Dict[str, Any], opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    old_rows = [x for x in state.get("service_sales_pipeline", []) or [] if isinstance(x, dict)]
    existing = {str(x.get("id") or ""): x for x in old_rows}
    rows: List[Dict[str, Any]] = []

    contactable = [
        x for x in opportunities
        if x.get("commercial_email") or bool((x.get("evidence") or {}).get("verified_contact"))
    ]
    contactable.sort(key=lambda x: (-_f(x.get("fit_score")), str(x.get("id") or "")))
    proactive_cap = max(1, int(math.ceil(len(opportunities) * SERVICE_LANE_SHARE_CAP))) if opportunities else 0
    active_opp_ids = {str(x.get("id") or "") for x in contactable[:proactive_cap]}

    # Proactive lane: verified service-fit accounts. Preparation is not contact.
    for opp in opportunities:
        service_id = str(opp.get("service_id") or "")
        source_id = str(opp.get("id") or "")
        pid = _pipeline_id("verified_account_fit", source_id, service_id)
        evidence = dict(opp.get("evidence", {}) or {})
        active = source_id in active_opp_ids
        row = _base_pipeline_row(
            existing.get(pid, {}),
            id=pid,
            source="verified_account_fit",
            source_id=source_id,
            service_opportunity_id=source_id,
            service_id=service_id,
            service_name=opp.get("service_name"),
            account_id=opp.get("account_id"),
            company_name=opp.get("company_name"),
            email=opp.get("commercial_email"),
            domain=opp.get("domain"),
            qualification_score=_f(opp.get("fit_score")),
            evidence=evidence,
            proactive_attention_active=active,
            inbound_priority=False,
            outreach_draft=_outreach_draft(service_id, str(opp.get("company_name") or "")),
            diagnostic_brief=_diagnostic_brief(service_id, str(opp.get("company_name") or "")),
        )
        close = _explicit_close_status(opp.get("status"))
        if close:
            _advance(row, close, "explicit_service_opportunity_status")
        elif row.get("contact_truth") in {"provider_accepted", "replied"}:
            pass
        elif active:
            _advance(row, "outreach_prepared", "top_verified_service_fit_within_35pct_cap")
        else:
            _advance(row, "qualified", "verified_service_fit_waiting_proactive_capacity")
        row["next_action"] = (
            "Pasar el mensaje personalizado por el control de outbound; no contar contacto hasta aceptación del proveedor."
            if active else
            "Mantener calificado y reordenar por encaje cuando se libere capacidad del carril de servicios."
        )
        rows.append(row)

    # Public inbound: a genuine inquiry is prioritized but company identity remains unverified until matched.
    for inquiry in state.get("service_inquiries", []) or []:
        if not isinstance(inquiry, dict):
            continue
        service_id = str(inquiry.get("service_id") or "")
        if not _service_by_id(service_id):
            continue
        source_id = str(inquiry.get("id") or _stable("INQ-", inquiry.get("email"), inquiry.get("company"), inquiry.get("need")))
        pid = _pipeline_id("public_service_form", source_id, service_id)
        match = _match_verified_account(state, str(inquiry.get("company") or ""), str(inquiry.get("email") or ""))
        company = _clean(inquiry.get("company"), 180)
        need = _clean(inquiry.get("need"), 1500)
        row = _base_pipeline_row(
            existing.get(pid, {}),
            id=pid,
            source="public_service_form",
            source_id=source_id,
            service_id=service_id,
            service_name=(_service_by_id(service_id) or {}).get("name"),
            account_id=match.get("id") if match else None,
            company_name=company,
            contact_name=_clean(inquiry.get("name"), 120),
            email=_clean(inquiry.get("email"), 180),
            stated_need=need,
            qualification_score=max(70.0, _score(match)) if match else 60.0,
            evidence={
                "inbound_received": True,
                "company_verified_match": bool(match),
                "user_submitted_need": True,
            },
            proactive_attention_active=False,
            inbound_priority=True,
            contact_truth="inbound_received",
            diagnostic_brief=_diagnostic_brief(service_id, company, need),
            proposal_draft=_proposal_draft(service_id, company, need),
            proposal_draft_status="prepared_nonbinding",
        )
        close = _explicit_close_status(inquiry.get("status"))
        if close:
            _advance(row, close, "explicit_inquiry_status")
        elif match:
            _advance(row, "diagnosis", "genuine_inbound_with_verified_company_match")
            if str(inquiry.get("status") or "") in {"new", "new_unverified"}:
                inquiry["status"] = "qualified"
                inquiry["evidence_status"] = "verified_company_match"
        else:
            _advance(row, "verification_required", "genuine_inbound_company_not_yet_verified")
        row["next_action"] = (
            "Revisar necesidad declarada y completar diagnóstico; precio final requiere decisión humana."
            if match else
            "Verificar identidad de la empresa antes de avanzar a propuesta comercial."
        )
        rows.append(row)

    # Instagram inbound: only messages with clear service intent enter the service CRM.
    for item in state.get("instagram_inbox", []) or []:
        if not isinstance(item, dict):
            continue
        service = _instagram_service(item)
        if not service:
            continue
        source_id = str(item.get("id") or item.get("external_id") or "")
        if not source_id:
            continue
        service_id = str(service.get("id"))
        pid = _pipeline_id("instagram_inbound", source_id, service_id)
        signal = _clean(item.get("text"), 1200)
        username = _clean(item.get("sender_username") or item.get("sender_id"), 180)
        row = _base_pipeline_row(
            existing.get(pid, {}),
            id=pid,
            source="instagram_inbound",
            source_id=source_id,
            service_id=service_id,
            service_name=service.get("name"),
            company_name=username or "Instagram inbound",
            instagram_sender_id=item.get("sender_id"),
            instagram_username=item.get("sender_username"),
            stated_need=signal,
            qualification_score=max(60.0, _f(item.get("priority"))),
            evidence={
                "inbound_received": True,
                "instagram_event_id": item.get("external_id"),
                "service_intent_from_message_text": True,
                "company_verified_match": False,
            },
            proactive_attention_active=False,
            inbound_priority=True,
            contact_truth="inbound_received",
            diagnostic_brief=_diagnostic_brief(service_id, username, signal),
        )
        _advance(row, "verification_required", "genuine_instagram_inbound_with_service_intent")
        row["next_action"] = "Calificar la necesidad y empresa; responder sólo por el flujo autorizado del Instagram Operator."
        rows.append(row)

    _apply_outbound_truth(state, rows)

    # Existing explicit advanced evidence may arrive through manually reviewed service rows.
    for row in rows:
        if row.get("contact_truth") == "replied":
            _advance(row, "replied", "verified_reply_truth")
        if row.get("proposal_truth") == "provider_accepted":
            _advance(row, "followup", "verified_proposal_delivery_truth")
        row["followup_due"] = bool(row.get("contact_truth") in {"provider_accepted", "replied"} and _followup_due(row.get("next_followup_at")))

    # Preserve previously won/lost rows if their source temporarily disappears from the active inputs.
    current_ids = {str(x.get("id") or "") for x in rows}
    for old in old_rows:
        if str(old.get("id") or "") not in current_ids and str(old.get("stage") or "") in TERMINAL_STAGES:
            rows.append(old)

    rows.sort(key=lambda x: (
        0 if x.get("inbound_priority") else 1,
        0 if x.get("proactive_attention_active") else 1,
        -_f(x.get("qualification_score")),
        str(x.get("id") or ""),
    ))
    return rows[:500]


def _execution_queue(state: Dict[str, Any], pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    existing = {str(x.get("pipeline_id") or ""): x for x in state.get("service_execution_queue", []) or [] if isinstance(x, dict)}
    out: List[Dict[str, Any]] = []
    for row in pipeline:
        if str(row.get("stage") or "") != "won":
            continue
        pid = str(row.get("id") or "")
        item = dict(existing.get(pid, {}))
        item.update({
            "id": item.get("id") or _stable("EXEC-", pid),
            "pipeline_id": pid,
            "service_id": row.get("service_id"),
            "company_name": row.get("company_name"),
            "status": item.get("status") or (
                "sourcing_request_pending" if row.get("service_id") == "SRV-SOURCING-EXPRESS" else "prospecting_request_pending"
            ),
            "binding_close_evidence_required": True,
            "updated_at": utcnow(),
        })
        item.setdefault("created_at", utcnow())
        out.append(item)
    return out[:200]


def _pipeline_summary(pipeline: List[Dict[str, Any]], opportunities: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_stage: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    by_service: Dict[str, int] = {}
    for row in pipeline:
        stage = str(row.get("stage") or "unknown")
        source = str(row.get("source") or "unknown")
        service = str(row.get("service_id") or "unknown")
        by_stage[stage] = by_stage.get(stage, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1
        by_service[service] = by_service.get(service, 0) + 1

    proactive_cap = max(1, int(math.ceil(len(opportunities) * SERVICE_LANE_SHARE_CAP))) if opportunities else 0
    return {
        "pipeline_total": len(pipeline),
        "by_stage": by_stage,
        "by_source": by_source,
        "by_service": by_service,
        "outbound_attention_active": sum(1 for x in pipeline if x.get("proactive_attention_active")),
        "outbound_attention_cap": proactive_cap,
        "verification_required": by_stage.get("verification_required", 0),
        "qualified_waiting": by_stage.get("qualified", 0),
        "outreach_prepared": by_stage.get("outreach_prepared", 0),
        "real_contacted": sum(1 for x in pipeline if x.get("contact_truth") == "provider_accepted"),
        "inbound_service_leads": sum(1 for x in pipeline if x.get("contact_truth") == "inbound_received"),
        "replies": sum(1 for x in pipeline if x.get("contact_truth") == "replied"),
        "diagnosis": by_stage.get("diagnosis", 0),
        "proposal_drafts": sum(1 for x in pipeline if x.get("proposal_draft_status") == "prepared_nonbinding"),
        "proposal_sent_verified": sum(1 for x in pipeline if x.get("proposal_truth") == "provider_accepted"),
        "followups_due": sum(1 for x in pipeline if x.get("followup_due")),
        "won": by_stage.get("won", 0),
        "lost": by_stage.get("lost", 0),
        "searches_used": 0,
    }


def service_revenue_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    opportunities = _prepare_opportunities(state)
    state["service_revenue_opportunities"] = opportunities
    state["service_catalog"] = [dict(x) for x in SERVICE_CATALOG]

    pipeline = _build_pipeline(state, opportunities)
    state["service_sales_pipeline"] = pipeline
    state["service_crm"] = pipeline
    execution = _execution_queue(state, pipeline)
    state["service_execution_queue"] = execution

    active = [x for x in SERVICE_CATALOG if x.get("status") == "active"]
    ready = [x for x in opportunities if str(x.get("status") or "") == "prepared_not_sent"]
    realized = _realized_service_revenue(state)
    inquiries = _inquiries(state)
    p = _pipeline_summary(pipeline, opportunities)

    state["service_sales_learning"] = {
        "version": VERSION,
        "stage_yield": dict(p.get("by_stage", {})),
        "source_yield": dict(p.get("by_source", {})),
        "service_yield": dict(p.get("by_service", {})),
        "realized_service_revenue_usd": realized,
        "rule": "Reforzar sólo canales con respuestas, cierres o ingresos verificables; no aprender de estados preparados como si fueran conversiones.",
        "updated_at": utcnow(),
    }

    if p["inbound_service_leads"]:
        primary = "Priorizar consultas entrantes: verificar identidad, completar diagnóstico y preparar propuesta no vinculante."
    elif p["real_contacted"]:
        primary = "Trabajar respuestas y seguimientos de contactos aceptados por proveedor sin inventar entrega ni conversión."
    elif p["outreach_prepared"]:
        primary = "Mover los mejores borradores personalizados por el outbound autorizado y exigir aceptación real del proveedor."
    else:
        primary = "Mantener el carril de servicios preparado sin desplazar la búsqueda y conversión del negocio de comisiones."

    summary = {
        "version": VERSION,
        "status": "active",
        "mode": "parallel_to_commission_business",
        "active_services": len(active),
        "active_service_ids": [x["id"] for x in active],
        "prepared_service_opportunities": len(ready),
        "service_inquiries": inquiries,
        "realized_service_revenue_usd": realized,
        "service_lane_share_cap": SERVICE_LANE_SHARE_CAP,
        "commission_business_preserved": True,
        "pipeline_total": p["pipeline_total"],
        "pipeline_by_stage": p["by_stage"],
        "pipeline_by_source": p["by_source"],
        "pipeline_by_service": p["by_service"],
        "outbound_attention_active": p["outbound_attention_active"],
        "outbound_attention_cap": p["outbound_attention_cap"],
        "verification_required": p["verification_required"],
        "qualified_waiting": p["qualified_waiting"],
        "outreach_prepared": p["outreach_prepared"],
        "real_contacted": p["real_contacted"],
        "inbound_service_leads": p["inbound_service_leads"],
        "replies": p["replies"],
        "diagnosis": p["diagnosis"],
        "proposal_drafts": p["proposal_drafts"],
        "proposal_sent_verified": p["proposal_sent_verified"],
        "followups_due": p["followups_due"],
        "won": p["won"],
        "lost": p["lost"],
        "execution_ready": len(execution),
        "searches_used_by_service_crm": 0,
        "autonomous_allowed": [
            "identify and score service-fit among already verified companies",
            "capture genuine inbound service intent from web and Instagram",
            "prepare personalized outreach drafts without claiming they were sent",
            "maintain service CRM stages and evidence",
            "prepare nonbinding diagnostics and proposal drafts",
            "schedule follow-up only after verified provider acceptance or reply",
            "learn from verified inquiry, response, close and payment outcomes",
        ],
        "human_required": [
            "final price or commercial offer",
            "binding contract or acceptance of terms",
            "payment collection or financial commitment",
            "new outbound action outside existing communication gates",
            "Instagram external publication approval",
        ],
        "primary_service_action": primary,
        "updated_at": utcnow(),
    }
    state["service_revenue_runtime"] = summary

    for key in ("first_cash_mode", "revenue_factory", "continuous_revenue_drive"):
        obj = state.get(key)
        if isinstance(obj, dict):
            obj["parallel_service_revenue"] = {
                "status": "active",
                "prepared": len(ready),
                "pipeline_total": p["pipeline_total"],
                "outreach_prepared": p["outreach_prepared"],
                "real_contacted": p["real_contacted"],
                "inbound_service_leads": p["inbound_service_leads"],
                "won": p["won"],
                "inquiries": inquiries.get("total", 0),
                "realized_service_revenue_usd": realized,
                "share_cap": SERVICE_LANE_SHARE_CAP,
                "commission_lane_preserved": True,
            }

    print({
        "service_growth_pipeline": {
            "version": VERSION,
            "pipeline_total": p["pipeline_total"],
            "outbound_attention": f"{p['outbound_attention_active']}/{p['outbound_attention_cap']}",
            "outreach_prepared": p["outreach_prepared"],
            "real_contacted": p["real_contacted"],
            "inbound_service_leads": p["inbound_service_leads"],
            "proposal_drafts": p["proposal_drafts"],
            "followups_due": p["followups_due"],
            "won": p["won"],
            "realized_service_revenue_usd": realized,
            "searches_used": 0,
            "truth_rule": "prepared_is_not_contacted",
        }
    }, flush=True)
    return summary
