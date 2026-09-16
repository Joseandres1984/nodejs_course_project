from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List


VERSION = "1.0-parallel-service-revenue"
MAX_PREPARED = 40
SERVICE_LANE_SHARE_CAP = 0.35

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


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _service_for(account: Dict[str, Any]) -> Dict[str, Any] | None:
    kind = str(account.get("type") or "").lower()
    if kind == "buyer":
        return SERVICE_CATALOG[0]
    if kind in {"supplier", "partner", "store"}:
        return SERVICE_CATALOG[1]
    return None


def _eligible_account(account: Dict[str, Any]) -> bool:
    if not isinstance(account, dict):
        return False
    if not account.get("verified_company"):
        return False
    if account.get("risk_tier") == "BLOCKED" or account.get("can_outreach") is False:
        return False
    if not (account.get("commercial_email") or account.get("verified_contact") or account.get("domain")):
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
    raw = f"LUMEN-SERVICE|{account_id}|{service_id}"
    return "SVC-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12].upper()


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
        account_id = str(account.get("id") or account.get("domain") or account.get("company_name") or "").strip()
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
            "company_name": _clean(account.get("company_name") or account.get("name_hint") or account.get("domain") or "Empresa", 180),
            "audience": service["audience"],
            "fit_score": _score(account),
            "status": str(row.get("status") or "prepared_not_sent"),
            "commercial_email": _clean(account.get("commercial_email"), 180),
            "domain": _clean(account.get("domain"), 180),
            "evidence": {
                "verified_company": bool(account.get("verified_company")),
                "verified_contact": bool(account.get("verified_contact")),
                "demand_signal": bool(account.get("demand_signal")),
                "direct_inbound_demand": bool(account.get("direct_inbound_demand")),
            },
            "next_action": (
                "Preparar diagnóstico de sourcing sobre una necesidad real; no enviar ni cotizar sin pasar los controles comerciales."
                if service["id"] == "SRV-SOURCING-EXPRESS"
                else "Preparar diagnóstico de prospección sobre su oferta; no prometer leads ni resultados no verificados."
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


def service_revenue_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    opportunities = _prepare_opportunities(state)
    state["service_revenue_opportunities"] = opportunities
    state["service_catalog"] = [dict(x) for x in SERVICE_CATALOG]

    active = [x for x in SERVICE_CATALOG if x.get("status") == "active"]
    ready = [x for x in opportunities if str(x.get("status") or "") == "prepared_not_sent"]
    realized = _realized_service_revenue(state)
    inquiries = _inquiries(state)

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
        "autonomous_allowed": [
            "identify service-fit among already verified companies",
            "prepare nonbinding service diagnostics",
            "rank service opportunities",
            "learn from inquiry and conversion outcomes",
        ],
        "human_required": [
            "final price or commercial offer",
            "binding contract or acceptance of terms",
            "payment collection or financial commitment",
            "new outbound action outside existing communication gates",
        ],
        "primary_service_action": (
            "Convertir una empresa verificada en una consulta real de Sourcing Express o Prospección B2B sin frenar la vía de comisiones."
            if ready else
            "Captar la primera consulta de servicio y mantener en paralelo la vía de operaciones/comisiones."
        ),
        "updated_at": utcnow(),
    }
    state["service_revenue_runtime"] = summary

    # Surface the second money path without replacing or falsifying the existing First Cash / Revenue logic.
    for key in ("first_cash_mode", "revenue_factory", "continuous_revenue_drive"):
        obj = state.get(key)
        if isinstance(obj, dict):
            obj["parallel_service_revenue"] = {
                "status": "active",
                "prepared": len(ready),
                "inquiries": inquiries.get("total", 0),
                "realized_service_revenue_usd": realized,
                "share_cap": SERVICE_LANE_SHARE_CAP,
                "commission_lane_preserved": True,
            }

    return summary
