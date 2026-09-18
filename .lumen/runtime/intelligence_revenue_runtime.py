from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import service_revenue_runtime


VERSION = "1.0-intelligence-revenue-engine"
MAX_INTELLIGENCE_CANDIDATES = 24
MAX_INTELLIGENCE_OUTBOUND_ATTENTION = 6

INTELLIGENCE_CATALOG = [
    {
        "id": "SRV-QUOTECHECK",
        "name": "LUMEN QuoteCheck Global",
        "audience": "buyer",
        "status": "active",
        "promise": "Analizar una cotización o decisión de compra con referencias, alternativas y evidencia disponible.",
        "deliverables": [
            "estructura comparable de la cotización recibida",
            "referencias y alternativas públicas cuando existan",
            "desvíos y observaciones sólo cuando haya evidencia suficiente",
            "palancas y próximos pasos para negociar o volver a cotizar",
        ],
        "commercial_model": "fixed_service_fee",
        "price_policy": "human_confirmed_before_offer",
        "binding_terms_human_required": True,
    },
    {
        "id": "SRV-SUPPLIERCHECK",
        "name": "LUMEN SupplierCheck",
        "audience": "buyer",
        "status": "active",
        "promise": "Investigar un proveedor con señales públicas, identidad comercial y evidencia de riesgo disponible.",
        "deliverables": [
            "identidad y huella pública del proveedor",
            "canales corporativos y señales verificables cuando existan",
            "banderas de riesgo y datos faltantes claramente separados",
            "recomendación de verificación antes de comprar o contratar",
        ],
        "commercial_model": "fixed_service_fee",
        "price_policy": "human_confirmed_before_offer",
        "binding_terms_human_required": True,
    },
    {
        "id": "SRV-EXPORT-SCOUT",
        "name": "LUMEN Export Scout",
        "audience": "supplier",
        "status": "active",
        "promise": "Priorizar países, importadores, distribuidores y compradores potenciales para una oferta concreta.",
        "deliverables": [
            "mercados y empresas objetivo priorizados",
            "importadores, distribuidores o compradores públicos cuando existan",
            "señales de encaje y canales corporativos verificables",
            "plan de prospección internacional no vinculante",
        ],
        "commercial_model": "fixed_service_fee_then_optional_outreach",
        "price_policy": "human_confirmed_before_offer",
        "binding_terms_human_required": True,
    },
    {
        "id": "SRV-TENDER-HUNTER",
        "name": "LUMEN Tender Hunter Global",
        "audience": "supplier",
        "status": "active",
        "promise": "Detectar y priorizar licitaciones, compras públicas y oportunidades abiertas compatibles con una oferta.",
        "deliverables": [
            "oportunidades públicas encontradas y deduplicadas",
            "compatibilidad explicada con evidencia disponible",
            "fechas, organismo, fuente y requisitos cuando sean públicos",
            "priorización para revisión humana antes de participar",
        ],
        "commercial_model": "monthly_retainer_or_fixed_watch",
        "price_policy": "human_confirmed_before_offer",
        "binding_terms_human_required": True,
    },
]

INTELLIGENCE_IDS = {str(x["id"]) for x in INTELLIGENCE_CATALOG}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stable(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(x or "") for x in parts)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12].upper()


def _install_catalog() -> None:
    existing = {str(x.get("id") or "") for x in service_revenue_runtime.SERVICE_CATALOG if isinstance(x, dict)}
    for item in INTELLIGENCE_CATALOG:
        if str(item["id"]) not in existing:
            service_revenue_runtime.SERVICE_CATALOG.append(dict(item))


def _service(service_id: str) -> Dict[str, Any]:
    for item in INTELLIGENCE_CATALOG:
        if item["id"] == service_id:
            return item
    return {}


def _account_id(account: Dict[str, Any]) -> str:
    return _clean(
        account.get("id")
        or account.get("domain")
        or account.get("official_domain")
        or account.get("company_name")
        or account.get("name_hint"),
        220,
    )


def _company(account: Dict[str, Any]) -> str:
    return _clean(
        account.get("company_name")
        or account.get("name_hint")
        or account.get("domain")
        or account.get("official_domain")
        or "Empresa",
        180,
    )


def _candidate_product(account: Dict[str, Any]) -> Optional[str]:
    kind = str(account.get("type") or "").strip().lower()
    if kind == "buyer":
        if account.get("direct_inbound_demand") or account.get("demand_signal"):
            return "SRV-QUOTECHECK"
        return "SRV-SUPPLIERCHECK"
    if kind in {"supplier", "partner", "store"}:
        if account.get("demand_signal") or account.get("direct_inbound_demand"):
            return "SRV-TENDER-HUNTER"
        return "SRV-EXPORT-SCOUT"
    return None


def _candidate_score(account: Dict[str, Any], service_id: str) -> float:
    score = max(_f(account.get("verification_score")), _f(account.get("lead_score")))
    if account.get("verified_company"):
        score += 8
    if account.get("verified_contact"):
        score += 8
    if account.get("commercial_email"):
        score += 8
    if account.get("direct_inbound_demand"):
        score += 18
    elif account.get("demand_signal"):
        score += 10
    if service_id in {"SRV-EXPORT-SCOUT", "SRV-TENDER-HUNTER"} and account.get("category"):
        score += 4
    return round(min(100.0, score), 1)


def _eligible_candidate(account: Dict[str, Any]) -> bool:
    if not isinstance(account, dict) or not account.get("verified_company"):
        return False
    if account.get("risk_tier") == "BLOCKED" or account.get("can_outreach") is False:
        return False
    if not _account_id(account) or not _clean(account.get("commercial_email"), 180):
        return False
    return _candidate_product(account) is not None


def _build_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for account in state.get("candidate_accounts", []) or []:
        if not _eligible_candidate(account):
            continue
        sid = _candidate_product(account)
        if not sid:
            continue
        service = _service(sid)
        aid = _account_id(account)
        rows.append({
            "id": _stable("INTFIT-", aid, sid),
            "account_id": account.get("id") or aid,
            "company_name": _company(account),
            "email": _clean(account.get("commercial_email"), 180).lower(),
            "domain": _clean(account.get("domain") or account.get("official_domain"), 180),
            "service_id": sid,
            "service_name": service.get("name"),
            "audience": service.get("audience"),
            "fit_score": _candidate_score(account, sid),
            "reason": (
                "verified_buyer_with_purchase_signal"
                if sid == "SRV-QUOTECHECK" else
                "verified_buyer_supplier_risk_fit"
                if sid == "SRV-SUPPLIERCHECK" else
                "verified_supplier_with_public_opportunity_fit"
                if sid == "SRV-TENDER-HUNTER" else
                "verified_supplier_export_growth_fit"
            ),
            "paid_spend": False,
            "binding_commitment": False,
            "updated_at": utcnow(),
        })
    rows.sort(key=lambda x: (-_f(x.get("fit_score")), str(x.get("id") or "")))
    return rows[:MAX_INTELLIGENCE_CANDIDATES]


def _research_plan(service_id: str) -> List[str]:
    plans = {
        "SRV-QUOTECHECK": [
            "normalizar producto, cantidad, moneda, país y alcance de la cotización",
            "reutilizar primero evidencia interna vigente y referencias ya verificadas",
            "buscar referencias públicas adicionales sólo cuando exista presupuesto autorizado",
            "separar precio comparable de costos no observados como flete, impuestos o condiciones",
            "emitir observaciones y palancas de negociación sin inventar un precio de mercado",
        ],
        "SRV-SUPPLIERCHECK": [
            "resolver identidad, dominio y canales oficiales del proveedor",
            "reunir señales públicas verificables y banderas de riesgo",
            "distinguir evidencia confirmada, ausencia de datos y afirmaciones del proveedor",
            "preparar checklist de due diligence previo a compra o contratación",
        ],
        "SRV-EXPORT-SCOUT": [
            "definir producto, categoría, mercados y restricciones declaradas",
            "reutilizar cuentas verificadas y evidencia internacional ya disponible",
            "priorizar importadores, distribuidores y compradores por encaje verificable",
            "crear shortlist y siguiente acción de prospección sin prometer ventas",
        ],
        "SRV-TENDER-HUNTER": [
            "definir oferta, geografía y palabras clave de elegibilidad",
            "revisar señales y fuentes públicas ya disponibles",
            "deduplicar oportunidades y separar licitación real de contenido informativo",
            "priorizar por compatibilidad, fecha límite, fuente y requisitos observables",
            "mantener participación y términos vinculantes bajo revisión humana",
        ],
    }
    return list(plans.get(service_id, []))


def _deliverable_schema(service_id: str) -> Dict[str, Any]:
    service = _service(service_id)
    return {
        "title": service.get("name"),
        "objective": service.get("promise"),
        "deliverables": list(service.get("deliverables", []) or []),
        "evidence_sections": ["verified_facts", "public_sources", "unknowns", "risks", "recommended_next_actions"],
        "currency_policy": "preserve_native_currency_and_convert_only_with_verified_fx_source",
        "truth_rule": "no_market_price_no_supplier_status_no_tender_fit_without_evidence",
        "binding": False,
    }


def _build_intelligence_cases(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    old = {str(x.get("id") or ""): x for x in state.get("intelligence_cases", []) or [] if isinstance(x, dict)}
    pipeline_by_source = {
        str(x.get("source_id") or ""): x
        for x in state.get("service_sales_pipeline", []) or []
        if isinstance(x, dict) and str(x.get("service_id") or "") in INTELLIGENCE_IDS
    }
    out: List[Dict[str, Any]] = []
    for inquiry in state.get("service_inquiries", []) or []:
        if not isinstance(inquiry, dict):
            continue
        sid = str(inquiry.get("service_id") or "")
        if sid not in INTELLIGENCE_IDS:
            continue
        source_id = str(inquiry.get("id") or "")
        if not source_id:
            continue
        cid = _stable("INTCASE-", source_id, sid)
        row = dict(old.get(cid, {}))
        pipeline = pipeline_by_source.get(source_id, {})
        payload = dict(inquiry.get("intelligence_payload", {}) or {})
        row.update({
            "id": cid,
            "source_inquiry_id": source_id,
            "service_id": sid,
            "service_name": _service(sid).get("name"),
            "company": _clean(inquiry.get("company"), 180),
            "contact_name": _clean(inquiry.get("name"), 120),
            "email": _clean(inquiry.get("email"), 180).lower(),
            "need": _clean(inquiry.get("need"), 1800),
            "country": _clean(payload.get("country"), 120),
            "product": _clean(payload.get("product"), 300),
            "quantity": _clean(payload.get("quantity"), 120),
            "quote_amount": _clean(payload.get("quote_amount"), 120),
            "quote_currency": _clean(payload.get("quote_currency"), 20).upper(),
            "supplier_name": _clean(payload.get("supplier_name"), 180),
            "pipeline_stage": pipeline.get("stage") or "verification_required",
            "research_status": row.get("research_status") or "queued_for_evidence_review",
            "research_plan": _research_plan(sid),
            "deliverable_schema": _deliverable_schema(sid),
            "search_spend_authorized": False,
            "paid_spend": False,
            "price_status": "human_confirmation_required",
            "binding_commitment": False,
            "updated_at": utcnow(),
        })
        row.setdefault("created_at", inquiry.get("created_at") or utcnow())
        out.append(row)
    out.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return out[:300]


def _pipeline_row(old: Dict[str, Any], candidate: Dict[str, Any], active: bool) -> Dict[str, Any]:
    row = dict(old or {})
    sid = str(candidate.get("service_id") or "")
    row.update({
        "id": _stable("SCRM-INT-", candidate.get("id"), sid),
        "source": "intelligence_product_fit",
        "source_id": candidate.get("id"),
        "service_opportunity_id": candidate.get("id"),
        "service_id": sid,
        "service_name": candidate.get("service_name"),
        "account_id": candidate.get("account_id"),
        "company_name": candidate.get("company_name"),
        "email": candidate.get("email"),
        "domain": candidate.get("domain"),
        "qualification_score": candidate.get("fit_score"),
        "evidence": {
            "verified_company": True,
            "commercial_email_present": bool(candidate.get("email")),
            "fit_reason": candidate.get("reason"),
        },
        "proactive_attention_active": active,
        "inbound_priority": False,
        "intelligence_revenue": True,
        "diagnostic_brief": _deliverable_schema(sid),
        "price_status": "human_confirmation_required",
        "binding_commitment": False,
        "updated_at": utcnow(),
    })
    row.setdefault("created_at", utcnow())
    row.setdefault("contact_truth", "not_contacted")
    current = str(row.get("stage") or "")
    if current not in {"contacted", "replied", "diagnosis", "proposal_ready", "followup", "won", "lost"}:
        row["stage"] = "outreach_prepared" if active else "qualified"
        row["stage_reason"] = (
            "top_intelligence_product_fit_within_existing_outbound_caps"
            if active else "verified_intelligence_fit_waiting_attention_capacity"
        )
    row["next_action"] = (
        "Pasar la propuesta del producto de inteligencia por el outbound gobernado; no contar contacto antes de aceptación real."
        if active else
        "Mantener priorizado y reordenar por encaje; no enviar fuera de los límites actuales."
    )
    return row


def _augment_service_pipeline(state: Dict[str, Any], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    base = [x for x in state.get("service_sales_pipeline", []) or [] if isinstance(x, dict) and x.get("source") != "intelligence_product_fit"]
    previous = {
        str(x.get("source_id") or ""): x
        for x in state.get("service_sales_pipeline", []) or []
        if isinstance(x, dict) and x.get("source") == "intelligence_product_fit"
    }
    intel_rows: List[Dict[str, Any]] = []
    for idx, candidate in enumerate(candidates):
        active = idx < MAX_INTELLIGENCE_OUTBOUND_ATTENTION
        intel_rows.append(_pipeline_row(previous.get(str(candidate.get("id") or ""), {}), candidate, active))

    # The outbound bridge syncs provider truth before the service tick. Apply that truth to the
    # intelligence rows as well so queued/sent/replied remain distinct and evidence-backed.
    try:
        service_revenue_runtime._apply_outbound_truth(state, intel_rows)
    except Exception:
        pass

    rows = base + intel_rows
    rows.sort(key=lambda x: (
        0 if x.get("inbound_priority") else 1,
        0 if x.get("proactive_attention_active") else 1,
        -_f(x.get("qualification_score")),
        str(x.get("id") or ""),
    ))
    state["service_sales_pipeline"] = rows[:700]
    state["service_crm"] = state["service_sales_pipeline"]
    return intel_rows


def _realized_intelligence_revenue(state: Dict[str, Any]) -> float:
    total = 0.0
    for row in state.get("service_revenue_transactions", []) or []:
        if not isinstance(row, dict) or str(row.get("service_id") or "") not in INTELLIGENCE_IDS:
            continue
        if str(row.get("status") or "").lower() not in {"paid", "settled", "completed"}:
            continue
        total += max(0.0, _f(row.get("amount_received_usd") or row.get("revenue_usd")))
    return round(total, 2)


def intelligence_revenue_tick(state: Dict[str, Any], service_summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    candidates = _build_candidates(state)
    state["intelligence_revenue_candidates"] = candidates
    intel_pipeline = _augment_service_pipeline(state, candidates)
    cases = _build_intelligence_cases(state)
    state["intelligence_cases"] = cases
    state["intelligence_products"] = [dict(x) for x in INTELLIGENCE_CATALOG]

    queue: List[Dict[str, Any]] = []
    for case in cases:
        queue.append({
            "id": _stable("INTWORK-", case.get("id")),
            "priority": 100,
            "kind": "inbound_intelligence_case",
            "case_id": case.get("id"),
            "service_id": case.get("service_id"),
            "next_action": "Verificar identidad y evidencia disponible; preparar diagnóstico no vinculante.",
            "paid_spend": False,
        })
    for row in intel_pipeline:
        if row.get("proactive_attention_active"):
            queue.append({
                "id": _stable("INTWORK-", row.get("id")),
                "priority": round(_f(row.get("qualification_score")), 1),
                "kind": "governed_outbound_candidate",
                "pipeline_id": row.get("id"),
                "service_id": row.get("service_id"),
                "company_name": row.get("company_name"),
                "next_action": "Usar el outbound existente sin ampliar límites ni saltar calidad, riesgo u opt-out.",
                "paid_spend": False,
            })
    queue.sort(key=lambda x: (-_f(x.get("priority")), str(x.get("id") or "")))
    state["intelligence_work_queue"] = queue[:100]

    by_service = {sid: 0 for sid in INTELLIGENCE_IDS}
    for row in candidates:
        sid = str(row.get("service_id") or "")
        if sid in by_service:
            by_service[sid] += 1

    outbound_active = sum(1 for x in intel_pipeline if x.get("proactive_attention_active"))
    contacted = sum(1 for x in intel_pipeline if x.get("contact_truth") == "provider_accepted")
    replied = sum(1 for x in intel_pipeline if x.get("contact_truth") == "replied")
    realized = _realized_intelligence_revenue(state)
    summary = {
        "version": VERSION,
        "status": "active",
        "mode": "monetize_intelligence_without_paid_search",
        "active_products": len(INTELLIGENCE_CATALOG),
        "active_product_ids": sorted(INTELLIGENCE_IDS),
        "public_inquiries": len(cases),
        "verified_product_fit_candidates": len(candidates),
        "candidates_by_product": by_service,
        "outbound_attention_active": outbound_active,
        "outbound_attention_cap": MAX_INTELLIGENCE_OUTBOUND_ATTENTION,
        "real_contacted": contacted,
        "replies": replied,
        "work_queue": len(queue),
        "realized_intelligence_revenue_usd": realized,
        "searches_used": 0,
        "paid_spend": False,
        "serper_required_to_operate": False,
        "multicurrency_capture": True,
        "truth_rules": [
            "no fabricated benchmark or market price",
            "no supplier verification without evidence",
            "no tender compatibility claim without a public source",
            "queued is not sent and sent is not replied",
            "revenue is zero until a paid or settled transaction exists",
        ],
        "human_required": [
            "final commercial price",
            "binding contract or acceptance of terms",
            "payment collection",
            "purchase or tender participation commitment",
        ],
        "updated_at": utcnow(),
    }
    state["intelligence_revenue_runtime"] = summary

    if isinstance(service_summary, dict):
        service_summary["intelligence_revenue"] = dict(summary)
        service_summary["active_services"] = len([x for x in service_revenue_runtime.SERVICE_CATALOG if x.get("status") == "active"])
        service_summary["active_service_ids"] = [x["id"] for x in service_revenue_runtime.SERVICE_CATALOG if x.get("status") == "active"]
        state["service_revenue_runtime"] = service_summary

    print({
        "intelligence_revenue_engine": {
            "version": VERSION,
            "status": "active",
            "products": len(INTELLIGENCE_CATALOG),
            "public_inquiries": len(cases),
            "verified_candidates": len(candidates),
            "outbound_attention": f"{outbound_active}/{MAX_INTELLIGENCE_OUTBOUND_ATTENTION}",
            "real_contacted": contacted,
            "replies": replied,
            "realized_revenue_usd": realized,
            "searches_used": 0,
            "paid_spend": False,
        }
    }, flush=True)
    return summary


_install_catalog()
_ORIGINAL_SERVICE_TICK = service_revenue_runtime.service_revenue_tick


def _service_tick_with_intelligence(state: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(_ORIGINAL_SERVICE_TICK(state) or {})
    intelligence_revenue_tick(state, summary)
    return summary


if not getattr(service_revenue_runtime, "_lumen_intelligence_revenue_installed", False):
    service_revenue_runtime.service_revenue_tick = _service_tick_with_intelligence
    service_revenue_runtime._lumen_intelligence_revenue_installed = True

print({
    "intelligence_revenue_install": {
        "version": VERSION,
        "status": "installed",
        "products": [x["id"] for x in INTELLIGENCE_CATALOG],
        "search_spend": 0,
        "binding_authority_changed": False,
    }
}, flush=True)
