from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _count(accounts: List[Dict[str, Any]], kind: str, **flags: Any) -> int:
    total = 0
    for account in accounts:
        if account.get("type") != kind:
            continue
        if all(account.get(key) == value for key, value in flags.items()):
            total += 1
    return total


def _deal_economics_gap(state: Dict[str, Any]) -> int:
    target = float(state.get("policies", {}).get("target_company_share_pct", 12.0))
    return sum(
        1 for deal in state.get("deals", [])
        if deal.get("economics") and float(deal.get("company_share_pct") or 0) < target
    )


def plan_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    accounts = state.setdefault("candidate_accounts", [])
    verified_suppliers = _count(accounts, "supplier", verified_company=True)
    verified_buyers = _count(accounts, "buyer", verified_company=True)
    demand_buyers = sum(1 for x in accounts if x.get("type") == "buyer" and x.get("verified_company") and x.get("demand_signal"))
    opportunities = state.get("market_opportunities", [])
    unconfirmed_opps = sum(1 for x in opportunities if not x.get("requirement_confirmed"))
    unverified_contact_opps = sum(
        1 for x in opportunities
        if not x.get("buyer_contact_verified") or not x.get("supplier_contact_verified")
    )
    margin_gaps = _deal_economics_gap(state)
    pending_approvals = sum(1 for x in state.get("approvals", []) if x.get("status") == "pending")
    strategic = state.get("strategic_directive", {}) or {}
    growth = state.get("growth_directive", {}) or {}

    priorities: List[Dict[str, Any]] = []

    def add(code: str, priority: int, objective: str, reason: str, autonomous: bool = True, source: str = "executive") -> None:
        priorities.append({
            "code": code,
            "priority": priority,
            "objective": objective,
            "reason": reason,
            "autonomous": autonomous,
            "source": source,
        })

    if verified_suppliers == 0:
        add("supplier_gap", 100, "Encontrar y verificar proveedores sólidos", "No hay proveedores verificados para construir oferta real.")
    if verified_suppliers > 0 and verified_buyers == 0:
        add("buyer_gap", 100, "Encontrar y verificar compradores con buen encaje", "Ya existe oferta verificada, pero falta el lado comprador del mercado.")
    elif verified_buyers > 0 and demand_buyers == 0:
        add("demand_gap", 96, "Validar señales reales de demanda", "Hay compradores verificados, pero todavía no existe evidencia suficiente de intención o necesidad.")
    if demand_buyers > 0 and verified_suppliers == 0:
        add("supplier_for_demand", 98, "Encontrar proveedores para demanda verificada", "Existe demanda verificable y falta capacidad de suministro.")
    if unconfirmed_opps:
        add("requirement_gap", 92, "Confirmar requerimientos concretos", f"Hay {unconfirmed_opps} oportunidades con evidencia pero requerimiento aún no confirmado.")
    if unverified_contact_opps:
        add("contact_gap", 90, "Validar canales comerciales corporativos", f"Hay {unverified_contact_opps} oportunidades sin ambos contactos comerciales verificados.")
    if margin_gaps:
        add("margin_gap", 95, "Mejorar economía y proteger margen", f"Hay {margin_gaps} negocios por debajo del margen objetivo.")
    if pending_approvals:
        add("approval_gap", 85, "Presentar decisiones de alto impacto para aprobación", f"Hay {pending_approvals} compromisos que requieren autorización humana.", autonomous=False)

    # Corporate Brain supplies a long-horizon priority. It can steer research and resource allocation,
    # but it intentionally remains below hard operational gaps scored at 100.
    if strategic.get("mode"):
        mode = str(strategic.get("mode"))
        priority = max(70, min(99, int(strategic.get("priority") or 88)))
        focus = ", ".join(str(x) for x in (strategic.get("focus_categories") or [])[:2])
        objective = str(strategic.get("thesis") or "Ejecutar la estrategia corporativa vigente")
        if focus:
            objective += f" Foco: {focus}."
        add(
            f"strategic_{mode}",
            priority,
            objective,
            str(strategic.get("reason") or "Corporate Brain definió una prioridad estratégica respaldada por evidencia persistida."),
            autonomous=True,
            source="corporate_brain",
        )

    # Growth & Expansion is allowed to compete for executive attention only after the base business passes
    # readiness gates. It remains public-research first and cannot authorize cross-border commitments.
    if growth.get("ready") and growth.get("primary_category"):
        readiness = float(growth.get("readiness_score") or 0)
        growth_priority = max(78, min(93, int(78 + readiness * 0.15)))
        market = str(growth.get("primary_market") or "mercado objetivo")
        category = str(growth.get("primary_category") or "categoría prioritaria")
        add(
            "growth_expansion",
            growth_priority,
            f"Validar expansión de {category} en {market} con evidencia pública antes de escalar comercialmente",
            f"Growth Brain readiness {readiness:.1f}; score de expansión {growth.get('primary_score')}; tipo {growth.get('primary_kind')}.",
            autonomous=True,
            source="growth_expansion",
        )

    if not priorities:
        add("expand_market", 70, "Expandir cuentas y categorías de mayor valor", "No hay un cuello de botella crítico; conviene ampliar mercado con disciplina de evidencia.")

    priorities.sort(key=lambda x: x["priority"], reverse=True)
    primary = priorities[0]
    plan = {
        "updated_at": utcnow(),
        "primary": primary,
        "priorities": priorities[:7],
        "snapshot": {
            "verified_suppliers": verified_suppliers,
            "verified_buyers": verified_buyers,
            "buyers_with_demand": demand_buyers,
            "market_opportunities": len(opportunities),
            "pending_approvals": pending_approvals,
            "corporate_strategy_mode": strategic.get("mode"),
            "corporate_strategy_epoch": strategic.get("strategy_epoch"),
            "growth_ready": bool(growth.get("ready")),
            "growth_readiness_score": growth.get("readiness_score"),
            "growth_primary_market": growth.get("primary_market"),
            "growth_primary_category": growth.get("primary_category"),
        },
        "decision_rule": "resolver primero gaps críticos; luego maximizar valor económico sostenible alineado con estrategia corporativa, expansión evidenciada, riesgo, velocidad y calidad de relación",
    }
    state["executive_plan"] = plan
    record_decision(
        state,
        engine="Executive Director",
        object_type="company",
        object_id="LUMEN",
        decision=primary["code"],
        reason=primary["reason"],
        action="prioritize_company_objective",
        confidence=0.9,
        evidence_refs=[],
    )
    return plan
