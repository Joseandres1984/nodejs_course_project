from __future__ import annotations

"""LUMEN Zero Microservice Factory v1.

Turns reusable internal capabilities into ranked microproduct build candidates. The factory
is deliberately release-gated: it may discover opportunities, define product contracts,
rank demand and prepare build work, but a candidate is never advertised, charged or treated
as LIVE until product-specific checkout, conversion intake, fulfillment, delivery schema and
end-to-end tests all exist.

Production code changes/deployments remain human/PR gated. This runtime only creates bounded,
auditable build work and commercial-learning state; it never spends, purchases, publishes a
new paid offer, moves funds or changes binding authority.
"""

import importlib.util
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

import acquisition_campaigns as acquisition

VERSION = "1.0-microservice-factory"
FACTORY_ID = "MSF-V1"
MAX_CANDIDATES = 6
MAX_HISTORY = 120
MAX_QUEUE = 120

# Product-specific release gates. Generic infrastructure is useful but is never enough to
# declare a new product sellable: every one of these gates must be proven for that product.
RELEASE_GATES = (
    "scope_contract",
    "capability_runtime",
    "conversion_intake",
    "x402_checkout",
    "fulfillment_adapter",
    "delivery_schema",
    "a2a_catalog",
    "e2e_tests",
)

# Existing real products are commercial truth and are not recreated by the factory.
LIVE_MICROPRODUCTS = (
    "MP-SUPPLIER-SNAPSHOT",
    "MP-QUOTE-SANITY",
    "MP-TENDER-SCAN",
    "MP-SOURCING-5",
    "MP-BUYER-SIGNALS",
    "MP-EXPORT-PULSE",
)

CAPABILITY_PROBES: Dict[str, tuple[str, ...]] = {
    "document_extract": ("document_intelligence",),
    "commercial_document_parse": ("document_intelligence", "procurement_document_enrichment_runtime"),
    "public_research": ("scout_connector",),
    "paid_report_fulfillment": ("paid_fulfillment_runtime",),
    "private_report_delivery": ("paid_delivery_runtime",),
    "commercial_truth": ("canonical_revenue_truth_runtime",),
}

# Candidate IDs intentionally use CAND-* rather than MP-* so downstream revenue/order logic
# cannot confuse a build hypothesis with a sellable product.
CANDIDATE_LIBRARY: tuple[Dict[str, Any], ...] = (
    {
        "id": "CAND-REPORT-QA",
        "slug": "report-qa",
        "name": "Report QA",
        "target_price_usd": 9,
        "service_id": "SRV-QUOTECHECK",
        "base_opportunity_score": 96,
        "promise": "Control rápido de consistencia, faltantes, afirmaciones débiles y trazabilidad de un informe comercial antes de usarlo o enviarlo.",
        "requires": [
            "Texto del informe/documento o una URL pública accesible",
            "Objetivo del informe y decisión que debe apoyar",
            "Idioma o formato de salida preferido si importa",
        ],
        "deliverables": [
            "Score de QA y resumen ejecutivo",
            "Inconsistencias, datos faltantes y afirmaciones sin soporte visible",
            "Lista priorizada de correcciones y preguntas",
            "Señales de moneda, totales, fechas, fuentes y límites cuando sean detectables",
        ],
        "not_included": [
            "Certificación profesional o auditoría formal",
            "Asesoramiento legal, contable o regulatorio",
            "Validación de información privada no suministrada o no pública",
        ],
        "capabilities": ("document_extract", "commercial_document_parse", "private_report_delivery"),
        "keywords": (
            "revisar informe", "revisión de informe", "revision de informe", "report review",
            "report qa", "control de calidad", "quality check", "consistencia", "informe comercial",
            "corregir informe", "validar reporte", "validar informe",
        ),
        "release": {
            "scope_contract": True,
            "conversion_intake": False,
            "x402_checkout": False,
            "fulfillment_adapter": False,
            "delivery_schema": False,
            "a2a_catalog": False,
            "e2e_tests": False,
        },
        "build_plan": [
            "Agregar contrato Report QA al intake de Conversion con texto/URL y alcance definido.",
            "Crear fulfillment determinístico de QA que analice contenido suministrado sin inventar evidencia.",
            "Definir schema de reporte QA compatible con render/approval/delivery fail-closed.",
            "Agregar ruta x402 y catálogo A2A sólo después de que fulfillment+delivery estén listos.",
            "Agregar tests E2E: unpaid blocked, settled queued, QA generated, PDF approved, private delivery.",
        ],
    },
    {
        "id": "CAND-SPEC-GAP-CHECK",
        "slug": "spec-gap-check",
        "name": "Spec Gap Check",
        "target_price_usd": 8,
        "service_id": "SRV-SOURCING-EXPRESS",
        "base_opportunity_score": 80,
        "promise": "Detectar rápidamente datos técnicos faltantes o ambiguos antes de pedir cotizaciones a proveedores.",
        "requires": ["Especificación/requerimiento", "Producto", "Restricciones obligatorias conocidas"],
        "deliverables": ["Campos faltantes", "Ambigüedades", "Preguntas sugeridas para cerrar el requerimiento"],
        "not_included": ["Aprobación de ingeniería", "Certificación normativa"],
        "capabilities": ("document_extract", "commercial_document_parse"),
        "keywords": ("especificación incompleta", "especificacion incompleta", "spec gap", "rfq incompleto", "faltan datos técnicos", "faltan datos tecnicos"),
        "release": {
            "scope_contract": True,
            "conversion_intake": False,
            "x402_checkout": False,
            "fulfillment_adapter": False,
            "delivery_schema": False,
            "a2a_catalog": False,
            "e2e_tests": False,
        },
        "build_plan": ["Definir parser/gap rules por requerimiento.", "Crear fulfillment y reporte específico.", "Conectar checkout/intake/A2A y validar E2E."],
    },
    {
        "id": "CAND-SUPPLIER-DOC-FLAGS",
        "slug": "supplier-doc-flags",
        "name": "Supplier Document Flags",
        "target_price_usd": 8,
        "service_id": "SRV-SUPPLIERCHECK",
        "base_opportunity_score": 76,
        "promise": "Marcar faltantes e inconsistencias visibles en documentación comercial de un proveedor.",
        "requires": ["Documento o texto comercial", "Proveedor", "Qué compra se está evaluando"],
        "deliverables": ["Flags documentales", "Faltantes", "Preguntas de verificación"],
        "not_included": ["Due diligence legal", "Informe crediticio"],
        "capabilities": ("document_extract", "commercial_document_parse"),
        "keywords": ("documentación proveedor", "documentacion proveedor", "supplier documents", "documentos proveedor", "validar documentación"),
        "release": {
            "scope_contract": True,
            "conversion_intake": False,
            "x402_checkout": False,
            "fulfillment_adapter": False,
            "delivery_schema": False,
            "a2a_catalog": False,
            "e2e_tests": False,
        },
        "build_plan": ["Definir flags permitidos y límites.", "Crear fulfillment/document report.", "Conectar checkout/intake/A2A y tests."],
    },
    {
        "id": "CAND-PRICE-REFERENCE-PACK",
        "slug": "price-reference-pack",
        "name": "Price Reference Pack",
        "target_price_usd": 11,
        "service_id": "SRV-QUOTECHECK",
        "base_opportunity_score": 72,
        "promise": "Paquete compacto de referencias públicas para contextualizar un precio B2B sin afirmar equivalencia cuando no existe.",
        "requires": ["Producto/especificación", "Cantidad", "País/mercado y moneda"],
        "deliverables": ["Referencias públicas trazables", "Diferencias visibles", "Límites de comparabilidad"],
        "not_included": ["Tasación certificada", "Garantía de mejor precio"],
        "capabilities": ("public_research", "paid_report_fulfillment", "private_report_delivery"),
        "keywords": ("referencia de precio", "referencias de mercado", "market price", "price reference", "precio mercado"),
        "release": {
            "scope_contract": True,
            "conversion_intake": False,
            "x402_checkout": False,
            "fulfillment_adapter": False,
            "delivery_schema": False,
            "a2a_catalog": False,
            "e2e_tests": False,
        },
        "build_plan": ["Definir comparability rules.", "Crear fulfillment dedicado.", "Conectar checkout/intake/A2A y tests."],
    },
)

_ORIGINAL_ACQUISITION_TICK = acquisition.acquisition_campaign_tick


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _module_ready(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def capability_inventory() -> Dict[str, bool]:
    return {
        capability: all(_module_ready(module) for module in modules)
        for capability, modules in CAPABILITY_PROBES.items()
    }


def _flatten_strings(value: Any, *, depth: int = 0) -> Iterable[str]:
    if depth > 3:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: List[str] = []
        for key, child in list(value.items())[:60]:
            if key in {"password", "token", "secret", "authorization", "api_key"}:
                continue
            out.extend(_flatten_strings(child, depth=depth + 1))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for child in list(value)[:80]:
            out.extend(_flatten_strings(child, depth=depth + 1))
        return out
    return []


def _market_text(state: Dict[str, Any]) -> str:
    sources = (
        state.get("lumen_conversion_leads", []),
        state.get("public_inquiries", []),
        state.get("service_inquiries", []),
        state.get("research_leads", []),
        state.get("interlocution_cases", []),
        state.get("acquisition_sprint_briefs", []),
        state.get("market_opportunities", []),
    )
    text: List[str] = []
    for source in sources:
        text.extend(_flatten_strings(source))
    return re.sub(r"\s+", " ", " ".join(text)).lower()[:120000]


def _demand_hits(candidate: Dict[str, Any], market_text: str) -> int:
    return sum(market_text.count(str(keyword).lower()) for keyword in candidate.get("keywords", ()))


def _status(gates: Dict[str, bool]) -> str:
    if all(bool(gates.get(gate)) for gate in RELEASE_GATES):
        return "PUBLISH_READY"
    if bool(gates.get("scope_contract")) and bool(gates.get("capability_runtime")):
        return "BUILD_READY"
    return "DISCOVERED"


def _candidate(candidate: Dict[str, Any], capabilities: Dict[str, bool], market_text: str) -> Dict[str, Any]:
    required_caps = tuple(candidate.get("capabilities", ()))
    cap_map = {name: bool(capabilities.get(name)) for name in required_caps}
    capability_ready = bool(required_caps) and all(cap_map.values())
    gates = {gate: bool((candidate.get("release") or {}).get(gate)) for gate in RELEASE_GATES}
    gates["capability_runtime"] = capability_ready
    missing = [gate for gate in RELEASE_GATES if not gates.get(gate)]
    readiness = round(100.0 * (len(RELEASE_GATES) - len(missing)) / len(RELEASE_GATES), 1)
    hits = _demand_hits(candidate, market_text)
    demand_score = min(100.0, hits * 14.0)
    opportunity = min(
        100.0,
        _f(candidate.get("base_opportunity_score"), 50.0) * 0.62
        + readiness * 0.28
        + demand_score * 0.10,
    )
    status = _status(gates)
    publishable = status == "PUBLISH_READY"
    return {
        "id": candidate["id"],
        "slug": candidate["slug"],
        "name": candidate["name"],
        "target_price_usd": candidate["target_price_usd"],
        "service_id": candidate["service_id"],
        "promise": candidate["promise"],
        "requires": list(candidate.get("requires", [])),
        "deliverables": list(candidate.get("deliverables", [])),
        "not_included": list(candidate.get("not_included", [])),
        "capabilities_required": list(required_caps),
        "capability_probe": cap_map,
        "gates": gates,
        "missing_gates": missing,
        "readiness_pct": readiness,
        "demand_hits": hits,
        "demand_score": demand_score,
        "opportunity_score": round(opportunity, 1),
        "status": status,
        "publishable": publishable,
        "charge_enabled": False,
        "public_catalog_enabled": False,
        "autonomous_code_change": False,
        "autonomous_deploy": False,
        "build_plan": list(candidate.get("build_plan", [])),
    }


def _materialize_build_action(state: Dict[str, Any], top: Dict[str, Any] | None) -> Dict[str, Any]:
    if not top or top.get("publishable"):
        return {"queued": False, "reason": "no_build_candidate"}
    queue = [row for row in (state.get("operating_action_queue", []) or []) if isinstance(row, dict)]
    key = f"microservice_factory|{top['id']}"
    task = {
        "key": key,
        "kind": "microservice_factory_build",
        "title": f"Construir microproducto: {top['name']}",
        "reason": f"Capacidades reutilizables detectadas; faltan gates de producto: {', '.join(top.get('missing_gates') or [])}.",
        "impact": top.get("opportunity_score"),
        "urgency": min(84.0, 62.0 + _f(top.get("opportunity_score")) * 0.20),
        "confidence": min(0.95, 0.55 + _f(top.get("readiness_pct")) / 250.0),
        "effort": 2.0,
        "risk": "low_to_medium",
        "autonomous": False,
        "object_type": "microservice_candidate",
        "object_id": top["id"],
        "payload": {
            "factory_id": FACTORY_ID,
            "candidate": top,
            "required_change_mode": "pr_reviewed_code_change",
            "release_rule": "all_product_specific_gates_required_before_publication_or_charge",
        },
        "priority_score": min(84.0, 62.0 + _f(top.get("opportunity_score")) * 0.20),
        "created_at": utcnow(),
    }
    by_key = {str(row.get("key")): row for row in queue if row.get("key")}
    by_key[key] = task
    state["operating_action_queue"] = sorted(
        by_key.values(), key=lambda row: _f(row.get("priority_score")), reverse=True
    )[:MAX_QUEUE]
    return {"queued": True, "key": key, "autonomous": False, "priority_score": task["priority_score"]}


def microservice_factory_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    capabilities = capability_inventory()
    market_text = _market_text(state)
    candidates = [_candidate(raw, capabilities, market_text) for raw in CANDIDATE_LIBRARY]
    candidates.sort(
        key=lambda row: (_f(row.get("opportunity_score")), _f(row.get("readiness_pct")), row.get("id")),
        reverse=True,
    )
    candidates = candidates[:MAX_CANDIDATES]
    top = candidates[0] if candidates else None
    build_action = _materialize_build_action(state, top)

    report = {
        "version": VERSION,
        "factory_id": FACTORY_ID,
        "updated_at": utcnow(),
        "status": "active",
        "mode": "capability_to_guarded_microproduct_pipeline",
        "objective": "discover -> define -> build -> test -> publish only when every product-specific release gate is proven",
        "live_microproducts_preserved": list(LIVE_MICROPRODUCTS),
        "live_microproducts_count": len(LIVE_MICROPRODUCTS),
        "candidate_count": len(candidates),
        "publish_ready_count": sum(1 for row in candidates if row.get("publishable")),
        "top_candidate_id": top.get("id") if top else None,
        "top_candidate_name": top.get("name") if top else None,
        "top_candidate_status": top.get("status") if top else None,
        "top_candidate_missing_gates": list(top.get("missing_gates") or []) if top else [],
        "capability_inventory": capabilities,
        "candidates": candidates,
        "build_action": build_action,
        "release_gates": list(RELEASE_GATES),
        "governance": {
            "candidate_ids_are_not_product_ids": True,
            "new_charge_before_publish_ready": False,
            "new_public_catalog_before_publish_ready": False,
            "production_code_self_modify": False,
            "autonomous_deploy": False,
            "code_changes": "PR/review gated",
            "outgoing_spend_usd": 0,
            "autonomous_purchase": False,
            "binding_authority_changed": False,
            "first_cash_priority_preserved": True,
        },
    }
    state["microservice_factory"] = report
    history = [row for row in (state.get("microservice_factory_history", []) or []) if isinstance(row, dict)]
    history.append({
        "ts": report["updated_at"],
        "top_candidate_id": report["top_candidate_id"],
        "top_candidate_status": report["top_candidate_status"],
        "publish_ready_count": report["publish_ready_count"],
        "candidate_count": report["candidate_count"],
    })
    state["microservice_factory_history"] = history[-MAX_HISTORY:]
    return report


def acquisition_tick_with_microservice_factory(state: Dict[str, Any]) -> Dict[str, Any]:
    # Existing acquisition/first-cash logic runs first. The factory only prepares the next product;
    # it never steals the current commercial slot or turns a candidate into a live offer.
    report = dict(_ORIGINAL_ACQUISITION_TICK(state) or {})
    factory = microservice_factory_tick(state)
    report["microservice_factory"] = {
        "version": VERSION,
        "status": factory.get("status"),
        "top_candidate_id": factory.get("top_candidate_id"),
        "top_candidate_name": factory.get("top_candidate_name"),
        "top_candidate_status": factory.get("top_candidate_status"),
        "top_candidate_missing_gates": factory.get("top_candidate_missing_gates"),
        "publish_ready_count": factory.get("publish_ready_count"),
        "live_microproducts_count": factory.get("live_microproducts_count"),
        "build_action": factory.get("build_action"),
        "outgoing_spend_usd": 0,
    }
    return report


# Install after Acquisition Sprint. The wrapper preserves its current commercial execution and only
# appends a lower-authority product-building lane for the next revenue source.
acquisition.acquisition_campaign_tick = acquisition_tick_with_microservice_factory

print({
    "microservice_factory_runtime": {
        "version": VERSION,
        "status": "installed",
        "candidate_library": [row["id"] for row in CANDIDATE_LIBRARY],
        "first_candidate": "CAND-REPORT-QA",
        "release_gates": list(RELEASE_GATES),
        "new_charge_enabled": False,
        "new_public_product_enabled": False,
        "production_code_self_modify": False,
        "autonomous_deploy": False,
        "outgoing_spend_usd": 0,
    }
}, flush=True)
