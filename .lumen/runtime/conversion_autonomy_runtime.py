from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

import agent_fleet
import market_pipeline
import professional_casework
import revenue_allocator_runtime

VERSION = "1.0-conversion-autonomy"
MAX_OFFLINE_CASES = 24
LANE_MIN_HOLD_CYCLES = 4
LANE_CONFIRM_CYCLES = 2

_ORIGINAL_CATEGORY = market_pipeline._category
_ORIGINAL_CASEWORK_TICK = professional_casework.professional_casework_tick
_ORIGINAL_RESOLVE_LANE = revenue_allocator_runtime._resolve_lane_with_anti_drift

PROCUREMENT_TERMS = (
    "compra", "compras", "adquisicion", "licitacion", "cotizacion", "presupuesto",
    "pliego", "rfq", "requerimiento", "abastecimiento", "contratacion",
)
SUPPLY_TERMS = (
    "fabricante", "distribuidor", "representante", "importador", "mayorista",
    "catalogo", "stock", "productos", "proveedor",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().strip().split())


def _tokens(value: Any) -> set[str]:
    stop = {
        "para", "con", "del", "las", "los", "una", "uno", "por", "argentina",
        "empresa", "industrial", "industriales", "producto", "productos", "servicio", "servicios",
    }
    return {
        token for token in re.findall(r"[a-z0-9]+", _fold(value))
        if len(token) >= 4 and token not in stop
    }


def canonical_category(value: Any) -> str:
    """Map obvious category synonyms without lowering any commercial evidence gate."""
    text = _fold(value)
    if not text:
        return ""

    rules = (
        ("auriculares", ("auricular", "auriculares", "headphone", "headphones", "earbud", "earbuds")),
        ("smartwatches", ("smartwatch", "smartwatches", "reloj inteligente", "relojes inteligentes")),
        (
            "materiales electricos",
            (
                "material electrico", "materiales electricos", "tablero electrico", "tableros electricos",
                "interruptor", "contactores", "contactor", "guardamotor", "cable electrico", "cables electricos",
            ),
        ),
        (
            "instrumentacion industrial",
            (
                "instrumentacion", "instrumento", "instrumentos", "manometro", "manometros", "presostato",
                "transmisor de presion", "sensor de presion", "caudalimetro", "medicion industrial", "metrologia",
            ),
        ),
        (
            "valvulas bombas y repuestos industriales",
            ("valvula", "valvulas", "bomba industrial", "bombas industriales", "repuesto de bomba", "repuestos de bomba"),
        ),
        (
            "ferreteria industrial",
            ("ferreteria", "herramienta industrial", "herramientas industriales", "buloneria", "tornilleria"),
        ),
        (
            "mantenimiento mecanico industrial",
            ("mantenimiento mecanico", "mantenimiento industrial", "montaje industrial", "reparacion mecanica"),
        ),
        (
            "motores grupos electrogenos y repuestos",
            ("motor electrico", "motores electricos", "grupo electrogeno", "grupos electrogenos", "generador industrial"),
        ),
    )
    for canonical, needles in rules:
        if any(needle in text for needle in needles):
            return canonical
    return _ORIGINAL_CATEGORY(value)


# The old Market Opportunity Builder required byte-for-byte category equality. Canonicalizing only
# clear synonyms lets already-verified buyers and suppliers be compared while preserving score,
# evidence, identity and contact gates.
market_pipeline._category = canonical_category


def _source_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for collection in ("candidate_accounts", "research_leads"):
        for row in state.get(collection, []) or []:
            if isinstance(row, dict) and row.get("id"):
                rows[str(row["id"])] = row
    return rows


def _evidence_text(case: Dict[str, Any], source: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("title", "name_hint", "snippet", "category", "need", "requirement", "requirement_spec"):
        if source.get(key):
            parts.append(str(source.get(key)))
    for row in case.get("evidence", []) or []:
        if isinstance(row, dict):
            parts.extend([str(row.get("title") or ""), str(row.get("snippet") or "")])
    return _fold(" ".join(parts))


def _compatible_accounts(state: Dict[str, Any], category: Any, kind: str) -> List[Dict[str, Any]]:
    target = canonical_category(category)
    if not target:
        return []
    rows = [
        row for row in state.get("candidate_accounts", []) or []
        if isinstance(row, dict)
        and row.get("type") == kind
        and row.get("verified_company")
        and canonical_category(row.get("category")) == target
    ]
    rows.sort(
        key=lambda row: (
            bool(row.get("commercial_channel_verified")),
            bool(row.get("verified_contact")),
            float(row.get("verification_score") or 0),
            float(row.get("lead_score") or 0),
        ),
        reverse=True,
    )
    return rows


def _advance_case(case: Dict[str, Any], next_stage: str, note: str, next_action: str) -> None:
    stages = professional_casework.BUYER_STAGES if case.get("subject_kind") == "buyer" else professional_casework.SUPPLIER_STAGES
    if next_stage not in stages:
        return
    old_stage = str(case.get("stage") or "")
    idx = stages.index(next_stage)
    case["stage"] = next_stage
    case["stage_index"] = idx
    case["progress_pct"] = int(round(100 * idx / max(1, len(stages))))
    case["status"] = "ready_for_handoff" if next_stage == "thesis" else "active"
    case["next_action"] = next_action
    case["last_worked_at"] = utcnow()
    case.setdefault("history", []).append(
        {
            "ts": utcnow(),
            "stage": old_stage,
            "event": "offline_evidence_advance",
            "detail": note,
        }
    )
    case["history"] = case["history"][-80:]


def _offline_case_step(state: Dict[str, Any], case: Dict[str, Any], source: Dict[str, Any]) -> bool:
    kind = str(case.get("subject_kind") or "buyer")
    stage = str(case.get("stage") or "triage")
    text = _evidence_text(case, source)
    category = source.get("category") or case.get("category")

    if stage == "identity" and source.get("verified_company"):
        next_stage = "demand" if kind == "buyer" else "capability"
        _advance_case(
            case,
            next_stage,
            "Se reutilizó la verificación corporativa ya existente; no se consumió una nueva búsqueda web.",
            "Revisar evidencia de demanda ya reunida" if kind == "buyer" else "Revisar evidencia de capacidad ya reunida",
        )
        return True

    if kind == "buyer" and stage == "demand":
        demand_verified = bool(source.get("demand_signal") or source.get("direct_inbound_demand"))
        evidence_support = any(term in text for term in PROCUREMENT_TERMS)
        if demand_verified or evidence_support:
            case.setdefault("facts", {})["demand_offline"] = {
                "verified_flag": demand_verified,
                "existing_evidence_support": evidence_support,
                "compiled_at": utcnow(),
            }
            _advance_case(
                case,
                "contact",
                "La demanda pudo sostenerse con evidencia ya almacenada; no se hizo una búsqueda adicional.",
                "Validar o reutilizar un canal comercial existente",
            )
            return True

    if kind == "buyer" and stage == "contact":
        if source.get("verified_contact") or source.get("commercial_channel_verified"):
            matches = _compatible_accounts(state, category, "supplier")
            if matches:
                case.setdefault("facts", {})["supplier_matches"] = [str(row.get("id")) for row in matches[:3]]
                _advance_case(
                    case,
                    "supplier_match",
                    "Se reutilizó un canal comprador ya verificado y se cruzaron proveedores verificados de la misma categoría.",
                    "Revisar encaje comprador-proveedor y preparar tesis comercial no vinculante",
                )
                return True

    if kind == "buyer" and stage == "supplier_match":
        matches = list((case.get("facts", {}) or {}).get("supplier_matches") or [])
        if matches:
            _advance_case(
                case,
                "thesis",
                "El caso ya tiene comprador, demanda y proveedores compatibles respaldados por evidencia existente.",
                "Entregar caso al embudo comercial con evidencia y riesgos explícitos",
            )
            return True

    if kind == "supplier" and stage == "capability":
        capability_flag = bool(source.get("capability_verified") or source.get("catalog_verified") or source.get("product_catalog"))
        evidence_support = any(term in text for term in SUPPLY_TERMS)
        if capability_flag or (source.get("verified_company") and evidence_support):
            case.setdefault("facts", {})["capability_offline"] = {
                "verified_flag": capability_flag,
                "existing_evidence_support": evidence_support,
                "compiled_at": utcnow(),
            }
            _advance_case(
                case,
                "contact",
                "La capacidad se sostuvo con evidencia ya almacenada, sin consumir una búsqueda adicional.",
                "Validar o reutilizar un canal comercial existente",
            )
            return True

    if kind == "supplier" and stage == "contact":
        if source.get("verified_contact") or source.get("commercial_channel_verified"):
            matches = _compatible_accounts(state, category, "buyer")
            matches = [row for row in matches if row.get("demand_signal")]
            if matches:
                case.setdefault("facts", {})["buyer_matches"] = [str(row.get("id")) for row in matches[:3]]
                _advance_case(
                    case,
                    "buyer_fit",
                    "Se reutilizó un canal proveedor verificado y se cruzaron compradores con demanda verificada.",
                    "Revisar encaje proveedor-comprador y preparar tesis comercial no vinculante",
                )
                return True

    if kind == "supplier" and stage == "buyer_fit":
        matches = list((case.get("facts", {}) or {}).get("buyer_matches") or [])
        if matches:
            _advance_case(
                case,
                "thesis",
                "El caso ya tiene proveedor, capacidad, contacto y compradores compatibles respaldados por evidencia existente.",
                "Entregar caso al embudo comercial con evidencia y riesgos explícitos",
            )
            return True

    return False


def _offline_advance_cases(state: Dict[str, Any]) -> Dict[str, int]:
    sources = _source_map(state)
    candidates = [
        case for case in state.get("professional_cases", []) or []
        if isinstance(case, dict) and case.get("status") in {"active", "waiting_budget"}
    ]
    candidates.sort(
        key=lambda case: (
            0 if case.get("status") == "waiting_budget" else 1,
            str(case.get("last_worked_at") or ""),
            str(case.get("id") or ""),
        )
    )
    reviewed = advanced = handoffs = 0
    for case in candidates[:MAX_OFFLINE_CASES]:
        source = sources.get(str(case.get("source_id") or ""), {})
        if not source:
            continue
        reviewed += 1
        # At most two evidence-only stage movements per case per cycle. This prevents a case from
        # jumping through the funnel just because several flags are present in the same row.
        for _ in range(2):
            if not _offline_case_step(state, case, source):
                break
            advanced += 1
        if case.get("status") == "ready_for_handoff":
            handoffs += 1
    return {"reviewed": reviewed, "advanced": advanced, "ready_for_handoff": handoffs}


def _casework_with_conversion(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_CASEWORK_TICK(state) or {})
    offline = _offline_advance_cases(state)
    budget = agent_fleet._budget(state)
    report["offline_conversion"] = offline
    report["offline_mode"] = int(budget.get("general_queries_remaining") or 0) <= 0
    report["existing_evidence_reused"] = int(offline.get("advanced") or 0)
    cases = list(state.get("professional_cases", []) or [])
    report["status_counts"] = {
        status: sum(1 for case in cases if case.get("status") == status)
        for status in ("active", "waiting_budget", "ready_for_handoff", "parked")
    }
    report["ready_for_handoff"] = report["status_counts"].get("ready_for_handoff", 0)
    state["professional_casework"] = report
    return report


professional_casework.professional_casework_tick = _casework_with_conversion


def _lane_metric(lane: str, metrics: Dict[str, int]) -> int:
    metric_name = revenue_allocator_runtime.LANE_SUCCESS_METRICS.get(lane)
    mapping = {
        "canonical_close_ready": "close_ready",
        "canonical_real_offers": "real_offers",
        "canonical_opportunities": "market_opportunities",
        "eligible_external_prospects": "eligible_external_prospects",
        "buyers_with_verified_demand": "buyers_with_demand",
    }
    return int(metrics.get(mapping.get(str(metric_name), ""), 0) or 0)


def _resolve_lane_with_hysteresis(state: Dict[str, Any], truth: Dict[str, Any], metrics: Dict[str, int]) -> Dict[str, Any]:
    resolved = dict(_ORIGINAL_RESOLVE_LANE(state, truth, metrics) or {})
    desired = str(resolved.get("lane") or "demand_discovery")
    memory = state.setdefault("revenue_lane_hysteresis", {})
    current = str(memory.get("current_lane") or desired)
    if current not in revenue_allocator_runtime.LANE_WEIGHTS:
        current = desired
    hold = int(memory.get("hold_cycles") or 0)
    pending = str(memory.get("pending_lane") or "")
    pending_count = int(memory.get("pending_count") or 0)
    switched = False

    # Evidence-backed closing and quote lanes are allowed to pre-empt research immediately.
    urgent = desired in {"closing", "quote_creation"}
    if desired == current:
        hold += 1
        pending = ""
        pending_count = 0
    elif urgent:
        current = desired
        hold = 1
        pending = ""
        pending_count = 0
        switched = True
    else:
        if pending == desired:
            pending_count += 1
        else:
            pending = desired
            pending_count = 1
        if hold >= LANE_MIN_HOLD_CYCLES and pending_count >= LANE_CONFIRM_CYCLES:
            current = desired
            hold = 1
            pending = ""
            pending_count = 0
            switched = True
        else:
            resolved["lane"] = current
            resolved["success_metric"] = revenue_allocator_runtime.LANE_SUCCESS_METRICS.get(current, resolved.get("success_metric"))
            resolved["reason"] = (
                str(resolved.get("reason") or "")
                + f" Hysteresis activa: mantener {current} hasta acumular evidencia suficiente para cambiar de carril."
            ).strip()
            resolved["anti_drift_applied"] = False
            resolved["anti_drift_guard_reason"] = "conversion_hysteresis_hold"

    memory.update(
        {
            "version": "1.0",
            "current_lane": current,
            "hold_cycles": hold,
            "pending_lane": pending or None,
            "pending_count": pending_count,
            "current_metric_value": _lane_metric(current, metrics),
            "last_desired_lane": desired,
            "switched_this_cycle": switched,
            "updated_at": utcnow(),
        }
    )
    resolved["lane"] = current
    resolved["hysteresis"] = dict(memory)
    return resolved


revenue_allocator_runtime._resolve_lane_with_anti_drift = _resolve_lane_with_hysteresis


def _engineering_backlog(state: Dict[str, Any], pipeline: Dict[str, Any], offline: Dict[str, int]) -> Dict[str, Any]:
    truth = state.get("canonical_revenue_truth", {}) or {}
    counts = truth.get("counts", {}) or {}
    waiting = sum(1 for case in state.get("professional_cases", []) or [] if case.get("status") == "waiting_budget")
    proposals: List[Dict[str, Any]] = []
    if waiting:
        proposals.append(
            {
                "code": "OFFLINE-EVIDENCE-REUSE",
                "problem": f"{waiting} casos todavía dependen de búsqueda externa.",
                "next_safe_change": "Seguir ampliando reglas de reutilización de evidencia sólo cuando existan flags verificables.",
                "production_change_requires_human": True,
            }
        )
    if int(counts.get("canonical_opportunities") or 0) <= 0:
        proposals.append(
            {
                "code": "CONVERSION-GAP",
                "problem": "Hay demanda verificada pero todavía no existe una oportunidad canónica.",
                "next_safe_change": "Priorizar compatibilidad de categorías y evidencia de requisitos sin bajar umbrales canónicos.",
                "production_change_requires_human": True,
            }
        )
    return {
        "status": "active",
        "version": "1.0-controlled-engineering",
        "production_code_self_modify": False,
        "deploy_requires_human": True,
        "proposals": proposals[:4],
        "last_pipeline": dict(pipeline or {}),
        "offline_advances": int(offline.get("advanced") or 0),
        "updated_at": utcnow(),
    }


def conversion_autonomy_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    # Annotate canonical categories for auditability without destroying the original human-readable value.
    canonicalized = 0
    for account in state.get("candidate_accounts", []) or []:
        if not isinstance(account, dict):
            continue
        value = canonical_category(account.get("category"))
        if value and account.get("category_canonical") != value:
            account["category_canonical"] = value
            canonicalized += 1

    offline = _offline_advance_cases(state)
    # Re-run the existing governed opportunity builder after category normalization. Its original
    # score >=75, verified-company and evidence gates remain unchanged.
    pipeline = dict(market_pipeline.build_market_pipeline(state) or {})

    budget = agent_fleet._budget(state)
    report = {
        "version": VERSION,
        "status": "active",
        "mode": "CONVERT_EXISTING_EVIDENCE_FIRST",
        "search_budget_exhausted": int(budget.get("general_queries_remaining") or 0) <= 0,
        "search_remaining": int(budget.get("general_queries_remaining") or 0),
        "canonicalized_accounts": canonicalized,
        "offline_cases_reviewed": int(offline.get("reviewed") or 0),
        "offline_stage_advances": int(offline.get("advanced") or 0),
        "offline_ready_for_handoff": int(offline.get("ready_for_handoff") or 0),
        "pipeline_created": int(pipeline.get("created") or 0),
        "pipeline_pairs_evaluated": int(pipeline.get("pairs_evaluated") or 0),
        "pipeline_below_threshold": int(pipeline.get("below_threshold") or 0),
        "lane_hysteresis": dict(state.get("revenue_lane_hysteresis", {}) or {}),
        "authority": "reuse_existing_evidence_and_nonbinding_conversion_only",
        "binding_actions_human_gated": True,
        "updated_at": utcnow(),
    }
    state["conversion_autonomy"] = report
    state["autonomous_engineering"] = _engineering_backlog(state, pipeline, offline)
    state.setdefault("activity", []).insert(
        0,
        {
            "ts": utcnow(),
            "msg": (
                "Autonomía de Conversión reutilizó evidencia existente, aplicó categorías canónicas y "
                "mantuvo intactos los gates de identidad, score, evidencia, contratos y pagos."
            ),
        },
    )
    state["activity"] = state["activity"][:100]
    return report


print(
    {
        "conversion_autonomy_runtime": {
            "version": VERSION,
            "status": "installed",
            "category_normalization": True,
            "offline_evidence_reuse": True,
            "lane_hysteresis": True,
            "production_code_self_modify": False,
        }
    },
    flush=True,
)
