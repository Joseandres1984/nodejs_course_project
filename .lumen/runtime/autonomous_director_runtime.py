from __future__ import annotations

"""Bounded Autonomous Director for LUMEN Zero.

Adds a management reflex above Adaptive Operator + Autonomy Core: detect verified
commercial stagnation, rotate reversible tactics, reallocate role attention, keep
useful work moving after currently-unlocked public-search quota exhaustion, and
open a parallel zero-cost first-cash lane after prolonged stalls.

It never widens financial, binding, legal, connector, paid-media, publication,
or production-code authority. Evidence and Governor gates remain authoritative.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

import adaptive_operator_runtime
import autonomy_core_runtime

VERSION = "1.1-autonomous-director"
MAX_HISTORY = 60
MAX_PLAN = 6
ROLE_BOOST_CAP = float(getattr(autonomy_core_runtime, "ROLE_BOOST_CAP", 0.12))

_ORIGINAL_METRICS = adaptive_operator_runtime._metrics
_ORIGINAL_SELECT_STRATEGY = adaptive_operator_runtime._select_strategy
_ORIGINAL_ROLE_ATTENTION = autonomy_core_runtime._role_attention
_ORIGINAL_BLACKBOARD = autonomy_core_runtime._blackboard_and_briefings


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _service_snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    """Read the persisted service CRM truth, with compatibility fallbacks."""
    persisted = _safe_dict(state.get("service_revenue_runtime"))
    legacy = _safe_dict(state.get("service_growth_pipeline"))
    opportunities = _safe_list(state.get("service_revenue_opportunities"))
    pipeline = _safe_list(state.get("service_sales_pipeline"))
    return {
        "pipeline_total": max(
            _i(persisted.get("pipeline_total")),
            _i(legacy.get("pipeline_total")),
            len(pipeline),
            len(opportunities),
        ),
        "replies": max(_i(persisted.get("replies")), _i(legacy.get("replies"))),
        "inbound_service_leads": max(
            _i(persisted.get("inbound_service_leads")),
            _i(legacy.get("inbound_service_leads")),
        ),
        "won": max(_i(persisted.get("won")), _i(legacy.get("won"))),
        "realized_service_revenue_usd": max(
            _f(persisted.get("realized_service_revenue_usd")),
            _f(legacy.get("realized_service_revenue_usd")),
        ),
    }


def _intelligence_snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    direct = _safe_dict(state.get("intelligence_revenue_engine"))
    continuous = _safe_dict(_safe_dict(state.get("continuous_revenue_drive")).get("intelligence_revenue"))
    return {
        "verified_candidates": max(
            _i(direct.get("verified_candidates")),
            _i(continuous.get("verified_product_fit_candidates")),
        ),
        "replies": max(_i(direct.get("replies")), _i(continuous.get("replies"))),
        "realized_revenue_usd": max(
            _f(direct.get("realized_revenue_usd")),
            _f(continuous.get("realized_intelligence_revenue_usd")),
        ),
    }


def _expanded_metrics(state: Dict[str, Any]) -> Dict[str, float]:
    metrics = dict(_ORIGINAL_METRICS(state) or {})
    counts = _safe_dict(_safe_dict(state.get("canonical_revenue_truth")).get("counts"))
    funnel = _safe_dict(state.get("business_funnel"))
    readiness = _safe_dict(state.get("external_market_readiness"))
    services = _service_snapshot(state)
    intelligence = _intelligence_snapshot(state)
    acquisition = _safe_dict(state.get("acquisition_campaigns"))
    realized_profit = max(
        _f(metrics.get("realized_profit_usd")),
        _f(services.get("realized_service_revenue_usd")),
        _f(intelligence.get("realized_revenue_usd")),
    )
    metrics.update({
        "verified_buyers": _f(counts.get("verified_buyers") or funnel.get("verified_buyers")),
        "buyers_with_verified_demand": _f(counts.get("buyers_with_verified_demand") or funnel.get("buyers_with_public_demand")),
        "eligible_external_prospects": _f(readiness.get("eligible_external_prospects")),
        "inbound_received": _f(funnel.get("inbound_received")),
        "outbound_sent": _f(funnel.get("outbound_sent")),
        "service_replies": _f(services.get("replies") or services.get("inbound_service_leads")),
        "service_won": _f(services.get("won")),
        "intelligence_replies": _f(intelligence.get("replies")),
        "acquisition_leads": _f(acquisition.get("leads")),
        "realized_profit_usd": realized_profit,
    })
    return metrics


def _expanded_bottleneck(metrics: Dict[str, float]) -> tuple[str, str]:
    if metrics.get("realized_profit_usd", 0) > 0:
        return "scale_verified_revenue", "realized_profit_usd"
    if metrics.get("verified_buyers", 0) > 0 and metrics.get("buyers_with_verified_demand", 0) <= 0:
        return "demand_discovery", "buyers_with_verified_demand"
    if metrics.get("buyers_with_verified_demand", 0) > 0 and metrics.get("eligible_external_prospects", 0) <= 0:
        return "verification_contact", "eligible_external_prospects"
    if metrics.get("canonical_opportunities", 0) <= 0:
        return "opportunity_creation", "canonical_opportunities"
    if metrics.get("requirements_ready_for_rfq", 0) <= 0:
        return "requirement_completion", "requirements_ready_for_rfq"
    if metrics.get("canonical_real_offers", 0) <= 0:
        return "quote_capture", "canonical_real_offers"
    if metrics.get("canonical_proposals", 0) <= 0:
        return "proposal_creation", "canonical_proposals"
    if metrics.get("canonical_close_ready", 0) <= 0:
        return "close_path", "canonical_close_ready"
    return "realized_revenue", "realized_profit_usd"


PROGRESS_KEYS = (
    "buyers_with_verified_demand",
    "eligible_external_prospects",
    "canonical_opportunities",
    "requirements_ready_for_rfq",
    "canonical_real_offers",
    "canonical_proposals",
    "canonical_close_ready",
    "inbound_received",
    "service_replies",
    "service_won",
    "intelligence_replies",
    "acquisition_leads",
    "realized_profit_usd",
)


def _record_progress_v2(op: Dict[str, Any], metrics: Dict[str, float], cycle: int) -> bool:
    history = list(op.get("metric_history", []) or [])
    previous = _safe_dict(history[-1].get("metrics")) if history else {}
    progressed = any(_f(metrics.get(k)) > _f(previous.get(k)) for k in PROGRESS_KEYS) if previous else False
    op["no_progress_cycles"] = 0 if progressed else (_i(op.get("no_progress_cycles")) + (1 if previous else 0))
    history.append({
        "cycle": cycle,
        "at": _now(),
        "metrics": dict(metrics),
        "verified_progress": progressed,
        "progress_keys": [k for k in PROGRESS_KEYS if _f(metrics.get(k)) > _f(previous.get(k))] if previous else [],
    })
    op["metric_history"] = history[-MAX_HISTORY:]
    return progressed


def _escalation(stall_cycles: int) -> Dict[str, Any]:
    stall = max(0, _i(stall_cycles))
    if stall >= 12:
        return {"level": 3, "mode": "challenge_plan", "reason": "prolonged_verified_stagnation"}
    if stall >= 6:
        return {"level": 2, "mode": "rotate_tactic", "reason": "repeated_verified_stagnation"}
    if stall >= 3:
        return {"level": 1, "mode": "rebalance", "reason": "early_verified_stagnation"}
    return {"level": 0, "mode": "observe", "reason": "normal_learning_window"}


adaptive_operator_runtime._STRATEGIES.setdefault("demand_discovery", [
    {
        "id": "official_demand_precision",
        "needs_search": True,
        "roles": ["buyer_hunter", "research_analyst"],
        "directive": "Prioritize exact current public purchase or requirement evidence for already verified buyers; avoid broad discovery and never infer demand.",
    },
    {
        "id": "stored_demand_evidence_mining",
        "needs_search": False,
        "roles": ["research_analyst", "buyer_hunter", "revops"],
        "directive": "Mine stored buyer-bound documents, messages and public evidence for exact demand signals; promote only evidence that passes existing lineage and score gates.",
    },
    {
        "id": "buyer_portfolio_rotation",
        "needs_search": False,
        "roles": ["buyer_hunter", "research_analyst"],
        "directive": "Rotate attention from repeatedly stagnant buyers toward verified buyers with stronger existing evidence while preserving all demand-verification gates.",
    },
])
adaptive_operator_runtime._STRATEGIES.setdefault("verification_contact", [
    {
        "id": "stored_contact_repair",
        "needs_search": False,
        "roles": ["research_analyst", "buyer_hunter", "revops"],
        "directive": "Reconcile stored official-domain and contact evidence for demand-verified buyers, respecting opt-outs and cooldowns; do not infer personal addresses.",
    },
    {
        "id": "official_contact_precision",
        "needs_search": True,
        "roles": ["research_analyst", "buyer_hunter"],
        "directive": "Use bounded public research only for official corporate contact channels belonging to demand-verified buyers; preserve current verification thresholds.",
    },
])


def _select_strategy_v2(op: Dict[str, Any], bottleneck: str, search_remaining: int) -> Dict[str, Any]:
    choices = list(adaptive_operator_runtime._STRATEGIES.get(bottleneck) or adaptive_operator_runtime._STRATEGIES["opportunity_creation"])
    eligible = [x for x in choices if not x.get("needs_search") or search_remaining > 0]
    if not eligible:
        eligible = [x for x in choices if not x.get("needs_search")] or choices

    stall = _i(op.get("no_progress_cycles"))
    active = _safe_dict(op.get("active_experiment"))
    current_id = str(active.get("strategy_id") or "")
    recent = [str(x.get("strategy_id") or "") for x in list(op.get("experiments", []) or [])[-5:] if isinstance(x, dict)]

    if stall >= 6:
        rotated = [x for x in eligible if str(x.get("id") or "") != current_id and str(x.get("id") or "") not in recent[-2:]]
        if rotated:
            eligible = rotated
        return min(
            eligible,
            key=lambda row: (
                _i(adaptive_operator_runtime._score_entry(op, str(row.get("id") or "")).get("attempts")),
                _i(adaptive_operator_runtime._score_entry(op, str(row.get("id") or "")).get("losses")),
                -_f(adaptive_operator_runtime._score_entry(op, str(row.get("id") or "")).get("score"), 1.0),
                str(row.get("id") or ""),
            ),
        )
    return _ORIGINAL_SELECT_STRATEGY(op, bottleneck, search_remaining)


def _task(task_id: str, priority: int, roles: List[str], action: str, metric: str, mode: str, why: str) -> Dict[str, Any]:
    return {
        "id": task_id,
        "priority": priority,
        "roles": roles,
        "action": action,
        "success_metric": metric,
        "mode": mode,
        "reason": why,
        "binding": False,
        "spend_usd": 0,
    }


def _effective_search_remaining(state: Dict[str, Any], adaptive: Dict[str, Any]) -> Dict[str, int]:
    reported = max(0, _i(_safe_dict(adaptive.get("search")).get("remaining")))
    available_now = reported
    try:
        import search_budget_governor as governor

        summary = _safe_dict(governor.summary(state))
        pacing = _safe_dict(summary.get("pacing"))
        if pacing.get("enabled") is True and "available_now" in pacing:
            available_now = min(reported, max(0, _i(pacing.get("available_now"))))
    except Exception:
        pass
    return {"reported_remaining": reported, "available_now": available_now}


def _build_plan(state: Dict[str, Any], metrics: Dict[str, float], bottleneck: str, target_metric: str, stall: int, search_remaining: int) -> List[Dict[str, Any]]:
    offline = search_remaining <= 0
    plan: List[Dict[str, Any]] = []
    primary = {
        "demand_discovery": _task("DIR-DEMAND-EVIDENCE", 100, ["research_analyst", "buyer_hunter", "revops"], "Revisar primero evidencia guardada de compradores verificados y promover solamente demanda exacta con trazabilidad; si queda cupo actualmente desbloqueado, usar búsqueda pública de precisión sobre compradores concretos.", "buyers_with_verified_demand", "offline_existing_evidence" if offline else "stored_first_then_bounded_search", "Sin demanda verificada no puede existir una oportunidad canónica."),
        "verification_contact": _task("DIR-CONTACT-REPAIR", 100, ["research_analyst", "buyer_hunter", "revops"], "Convertir compradores con demanda verificada en prospectos utilizables reparando identidad y canales corporativos oficiales, sin inferir emails personales ni saltar cooldowns.", "eligible_external_prospects", "offline_existing_evidence" if offline else "stored_first_then_bounded_search", "La demanda existe pero todavía no puede ejecutarse contacto seguro."),
        "opportunity_creation": _task("DIR-OPPORTUNITY-BUILD", 100, ["revops", "research_analyst", "supplier_hunter"], "Cruzar demanda verificada con proveedores verificados y materializar sólo oportunidades con evidencia y linaje completos.", "canonical_opportunities", "offline_existing_evidence", "Hay evidencia aguas arriba pero todavía no se convirtió en una oportunidad canónica."),
        "requirement_completion": _task("DIR-RFQ-PACK", 100, ["research_analyst", "revops", "risk_quality"], "Completar alcance técnico, cantidad y lugar de entrega únicamente desde documentos o mensajes existentes; buscar afuera sólo si queda cupo actualmente desbloqueado.", "requirements_ready_for_rfq", "offline_existing_evidence" if offline else "stored_first_then_bounded_search", "Sin paquete RFQ completo no corresponde avanzar a cotización."),
        "quote_capture": _task("DIR-QUOTE-CAPTURE", 100, ["supplier_hunter", "negotiator", "revops"], "Priorizar RFQ no vinculante hacia proveedores ya verificados y normalizar respuestas reales para comparabilidad.", "canonical_real_offers", "nonbinding_execution", "El cuello de botella está en obtener evidencia real de oferta/cotización."),
        "proposal_creation": _task("DIR-PROPOSAL", 100, ["negotiator", "revops", "finance", "risk_quality"], "Preparar propuesta no vinculante usando únicamente cotizaciones comparables y economía verificable.", "canonical_proposals", "offline_existing_evidence", "Ya hay evidencia de oferta; falta convertirla en propuesta comprensible y trazable."),
        "close_path": _task("DIR-CLOSE-PATH", 100, ["revops", "negotiator", "risk_quality", "finance"], "Identificar la condición exacta que impide cierre y resolver automáticamente sólo lo reversible; elevar cualquier aceptación vinculante al humano.", "canonical_close_ready", "nonbinding_execution", "La oportunidad avanzó y ahora importa eliminar fricción de cierre sin ampliar autoridad."),
        "realized_revenue": _task("DIR-COLLECTION-READINESS", 100, ["revops", "finance", "risk_quality"], "Verificar entrega, cobro y conciliación; no mover fondos ni aceptar compromisos por cuenta propia.", "realized_profit_usd", "collection_readiness", "La prioridad final es convertir avance comercial en ingreso realizado verificable."),
        "scale_verified_revenue": _task("DIR-SCALE-WINNER", 100, ["revops", "research_analyst", "finance"], "Replicar sólo tácticas que ya demostraron ingreso o progreso comercial verificable, preservando gates y márgenes.", "realized_profit_usd", "winner_replication", "Con primera caja verificada, el objetivo pasa a repetir evidencia ganadora."),
    }
    plan.append(primary.get(bottleneck, primary["opportunity_creation"]))

    if stall >= 3:
        plan.append(_task("DIR-REBALANCE", 92, ["research_analyst", "revops"], "Reasignar atención desde tareas sin efecto hacia el cuello de botella actual y evitar repetir trabajo idéntico sin nueva evidencia.", target_metric, "reversible_attention_reallocation", "Se detectó una racha temprana sin progreso comercial verificable."))
    if stall >= 6:
        plan.append(_task("DIR-TACTIC-ROTATION", 96, ["research_analyst", "revops", "buyer_hunter", "supplier_hunter"], "Rotar automáticamente la táctica reversible del experimento activo y elegir una alternativa menos intentada, manteniendo los mismos gates.", target_metric, "reversible_strategy_rotation", "La táctica actual no produjo progreso verificable en varios ciclos."))

    services = _service_snapshot(state)
    intelligence = _intelligence_snapshot(state)
    if stall >= 10 and _f(metrics.get("realized_profit_usd")) <= 0 and (
        _i(services.get("pipeline_total")) > 0 or _i(intelligence.get("verified_candidates")) > 0
    ):
        plan.append(_task("DIR-FIRST-CASH-PARALLEL", 98, ["revops", "market_manager", "research_analyst"], "Mantener el cuello de botella principal, pero abrir en paralelo una ruta de primera caja con servicios/inteligencia ya preparados: seguimiento, mejora de mensaje y conversión orgánica sobre candidatos verificados.", "service_replies", "parallel_zero_cost_cash_lane", "Una racha prolongada justifica diversificar reversiblemente la vía de ingreso sin abandonar la evidencia principal."))
    if offline:
        plan.append(_task("DIR-ZERO-QUOTA-MODE", 94, ["research_analyst", "revops", "risk_quality"], "Mientras el cupo actualmente desbloqueado de búsqueda sea cero, usar memoria D1: deduplicar, releer documentos, reparar identidades, priorizar follow-ups y preparar el próximo lote de búsquedas de máxima precisión.", target_metric, "offline_existing_evidence", "No debe existir tiempo ocioso sólo porque el cupo gratuito está temporalmente agotado."))
    return sorted(plan, key=lambda x: -_i(x.get("priority")))[:MAX_PLAN]


def _role_boosts(plan: List[Dict[str, Any]]) -> Dict[str, float]:
    raw: Dict[str, float] = {}
    for item in plan:
        increment = 0.02 + max(0, min(100, _i(item.get("priority")))) / 2500.0
        for role in item.get("roles", []) or []:
            raw[str(role)] = raw.get(str(role), 0.0) + increment
    return {role: round(min(ROLE_BOOST_CAP, value), 4) for role, value in raw.items()}


def director_tick(state: Dict[str, Any], adaptive_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    director = state.setdefault("autonomous_director", {})
    metrics = _expanded_metrics(state)
    bottleneck, target_metric = _expanded_bottleneck(metrics)
    adaptive = adaptive_report if isinstance(adaptive_report, dict) else _safe_dict(state.get("adaptive_operator"))
    stall = _i(adaptive.get("no_progress_cycles"))
    search = _effective_search_remaining(state, adaptive)
    search_remaining = _i(search.get("available_now"))
    plan = _build_plan(state, metrics, bottleneck, target_metric, stall, search_remaining)
    history = list(director.get("history", []) or [])
    history.append({
        "cycle": _i(state.get("ticks")),
        "at": _now(),
        "bottleneck": bottleneck,
        "target_metric": target_metric,
        "stall_cycles": stall,
        "search_reported_remaining": _i(search.get("reported_remaining")),
        "search_available_now": search_remaining,
        "plan_ids": [x.get("id") for x in plan],
        "metrics": metrics,
    })
    director.update({
        "version": VERSION,
        "status": "active",
        "updated_at": _now(),
        "objective": "first verified cash through continuous evidence-based autonomous adaptation",
        "bottleneck": bottleneck,
        "target_metric": target_metric,
        "stall_cycles": stall,
        "escalation": _escalation(stall),
        "operating_mode": "offline_existing_evidence" if search_remaining <= 0 else "bounded_market_plus_internal",
        "search_remaining": search_remaining,
        "search_reported_remaining": _i(search.get("reported_remaining")),
        "search_available_now": search_remaining,
        "plan": plan,
        "role_boosts": _role_boosts(plan),
        "history": history[-MAX_HISTORY:],
        "authority": {
            "autonomous": [
                "reversible attention reallocation",
                "reversible strategy rotation",
                "research priority changes",
                "case prioritization and temporary rotation",
                "nonbinding commercial preparation within existing gates",
            ],
            "human_required": [
                "binding contracts or acceptance of binding terms",
                "payments, orders or financial commitments",
                "material legal or liability decisions",
                "new external connectors or account authorization",
                "paid media spend",
                "production code changes or deployments",
            ],
            "monetary_budget_usd": 0,
            "binding_authority_changed": False,
            "evidence_gates_preserved": True,
            "production_self_modify": False,
        },
    })
    state["autonomous_director"] = director
    return director


def _role_attention_with_director(core: Dict[str, Any]) -> Dict[str, float]:
    base = dict(_ORIGINAL_ROLE_ATTENTION(core) or {})
    boosts = _safe_dict(_safe_dict(core.get("director_context")).get("role_boosts"))
    for role, value in boosts.items():
        base[role] = round(min(ROLE_BOOST_CAP, max(_f(base.get(role)), _f(value))), 4)
    core["role_attention"] = base
    if isinstance(core.get("policy_hints"), dict):
        core["policy_hints"]["autonomous_director_role_boosts"] = dict(boosts)
    return base


def _blackboard_with_director(state: Dict[str, Any], core: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    director = _safe_dict(state.get("autonomous_director"))
    core["director_context"] = {"role_boosts": dict(_safe_dict(director.get("role_boosts")))}
    _ORIGINAL_BLACKBOARD(state, core, issues)
    cards = list(core.get("blackboard", []) or [])
    for item in list(director.get("plan", []) or []):
        cards.append({
            "kind": "autonomous_director",
            "id": item.get("id"),
            "priority": item.get("priority"),
            "text": item.get("action"),
            "roles": item.get("roles"),
            "metric": item.get("success_metric"),
            "mode": item.get("mode"),
            "binding": False,
        })
    cards.sort(key=lambda x: -_i(x.get("priority")))
    core["blackboard"] = cards[:getattr(autonomy_core_runtime, "MAX_BLACKBOARD", 60)]
    briefings = _safe_dict(core.get("role_briefings"))
    for role, briefing in briefings.items():
        if isinstance(briefing, dict):
            briefing["director_tasks"] = [
                {
                    "id": item.get("id"),
                    "priority": item.get("priority"),
                    "action": item.get("action"),
                    "metric": item.get("success_metric"),
                    "mode": item.get("mode"),
                }
                for item in list(director.get("plan", []) or [])
                if role in (item.get("roles", []) or [])
            ][:4]
    state.setdefault("agent_workforce", {})["autonomy_briefing"] = briefings
    state["agent_workforce"]["shared_blackboard"] = core["blackboard"][:30]


adaptive_operator_runtime._metrics = _expanded_metrics
adaptive_operator_runtime._bottleneck = _expanded_bottleneck
adaptive_operator_runtime._record_progress = _record_progress_v2
adaptive_operator_runtime._select_strategy = _select_strategy_v2
autonomy_core_runtime._role_attention = _role_attention_with_director
autonomy_core_runtime._blackboard_and_briefings = _blackboard_with_director

_ORIGINAL_ADAPTIVE_TICK = adaptive_operator_runtime.adaptive_operator_tick


def _adaptive_with_director(state: Dict[str, Any]) -> Dict[str, Any]:
    op = _safe_dict(state.get("adaptive_operator"))
    stall = _i(op.get("no_progress_cycles"))
    active = _safe_dict(op.get("active_experiment"))
    if stall >= 6 and active.get("status") == "TESTING" and _i(active.get("samples"), 1) >= 2:
        active["status"] = "DEMOTED"
        active["result"] = "director_forced_rotation_after_verified_stagnation"
        active["updated_at"] = _now()
        op["active_experiment"] = None
        state["adaptive_operator"] = op

    report = dict(_ORIGINAL_ADAPTIVE_TICK(state) or {})
    director = director_tick(state, report)
    state.setdefault("autonomy_core", {})["director_context"] = {"role_boosts": dict(director.get("role_boosts") or {})}
    report["director"] = {
        "version": director.get("version"),
        "status": director.get("status"),
        "bottleneck": director.get("bottleneck"),
        "target_metric": director.get("target_metric"),
        "stall_cycles": director.get("stall_cycles"),
        "escalation": director.get("escalation"),
        "operating_mode": director.get("operating_mode"),
        "search_reported_remaining": director.get("search_reported_remaining"),
        "search_available_now": director.get("search_available_now"),
        "plan_ids": [x.get("id") for x in director.get("plan", []) or []],
        "role_boosts": director.get("role_boosts"),
        "monetary_budget_usd": 0,
        "binding_authority_changed": False,
    }
    print({"autonomous_director": report["director"]}, flush=True)
    return report


adaptive_operator_runtime.adaptive_operator_tick = _adaptive_with_director

print({
    "autonomous_director_runtime": {
        "version": VERSION,
        "status": "active",
        "anti_stall_escalation": True,
        "reversible_strategy_rotation": True,
        "role_reallocation": True,
        "pacing_aware_zero_quota_mode": True,
        "parallel_first_cash_lane": True,
        "persistent_service_truth": True,
        "monetary_budget_usd": 0,
        "binding_authority_changed": False,
        "production_self_modify": False,
    }
}, flush=True)
