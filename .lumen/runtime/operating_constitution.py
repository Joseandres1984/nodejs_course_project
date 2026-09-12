from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


CONSTITUTION_VERSION = "1.0"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def constitutional_doctrine() -> Dict[str, Any]:
    return {
        "version": CONSTITUTION_VERSION,
        "supreme_objective": (
            "Maximizar beneficio empresarial sostenible ajustado por riesgo, preservando integridad de datos, "
            "autoridad humana, caja, reputación y cumplimiento."
        ),
        "priority_order": [
            {"rank": 1, "principle": "integrity_and_reliability", "rule": "No operar sobre estado incierto, persistencia degradada o datos críticos inconsistentes."},
            {"rank": 2, "principle": "human_authority_and_compliance", "rule": "Contratos, pagos, órdenes, compromisos financieros y términos vinculantes requieren autorización humana."},
            {"rank": 3, "principle": "cash_reputation_and_counterparty_safety", "rule": "Cobro, concentración, identidad, opt-out y reputación prevalecen sobre crecimiento."},
            {"rank": 4, "principle": "risk_adjusted_profit", "rule": "Priorizar beneficio esperado ajustado por riesgo y resultados realizados, no actividad bruta."},
            {"rank": 5, "principle": "conversion_and_execution", "rule": "Cerrar brechas del funnel y avanzar oportunidades reales antes de ampliar complejidad innecesaria."},
            {"rank": 6, "principle": "growth_and_expansion", "rule": "Expandir solo con readiness suficiente y sin canibalizar el negocio base."},
            {"rank": 7, "principle": "exploration_and_learning", "rule": "Mantener exploración controlada; nunca sacrificar evidencia, seguridad o caja por novedad."},
        ],
        "authority_matrix": {
            "public_research": "autonomous",
            "company_verification": "autonomous",
            "opportunity_scoring": "autonomous",
            "document_parsing": "autonomous",
            "prepare_outreach": "autonomous_governed",
            "send_verified_corporate_outreach": "autonomous_governed",
            "request_quote": "autonomous_governed",
            "nonbinding_negotiation": "autonomous_governed",
            "prepare_proposal": "autonomous_governed",
            "contract": "human_required",
            "accept_binding_terms": "human_required",
            "place_order": "human_required",
            "payment": "human_required",
            "financial_commitment": "human_required",
        },
        "non_negotiables": [
            "no fabricated demand, quotes, contacts, prices or cash balances",
            "no deception, impersonation or fake negotiation leverage",
            "no bypass of authentication, paywalls, anti-bot or access controls",
            "verified corporate channels only for outbound",
            "respect opt-out and cooldown",
            "simulated outcomes never count as real transactions",
            "historical prices are evidence, never silently current prices",
            "binding actions remain human-controlled",
        ],
        "conflict_rule": "A lower-ranked objective may not override a higher-ranked constitutional principle.",
        "resource_rule": "Budgets allocate attention, research and governed outreach only; they never authorize spending or financial commitments.",
        "audit_rule": "Material overrides, kill-switches and resource reallocations must be persisted with reason and evidence context.",
        "updated_at": utcnow(),
    }


def ensure_constitution(state: Dict[str, Any]) -> Dict[str, Any]:
    doctrine = constitutional_doctrine()
    current = state.get("operating_constitution", {}) or {}
    if current.get("version") != doctrine["version"]:
        state["operating_constitution"] = doctrine
    else:
        # Refresh doctrine text while retaining any human-approved extension fields.
        merged = dict(current)
        merged.update(doctrine)
        state["operating_constitution"] = merged
    return state["operating_constitution"]


def authority_for(state: Dict[str, Any], action: str) -> str:
    constitution = ensure_constitution(state)
    return str((constitution.get("authority_matrix", {}) or {}).get(action, "human_required"))


def is_binding_action(action: str) -> bool:
    return action in {"contract", "accept_binding_terms", "place_order", "payment", "financial_commitment"}


def constitutional_check(state: Dict[str, Any], action: str, *, outbound: bool = False) -> Dict[str, Any]:
    constitution = ensure_constitution(state)
    authority = authority_for(state, action)
    governance = state.get("master_governance", {}) or {}
    switches = governance.get("kill_switches", {}) or {}
    reasons: List[str] = []

    allowed = authority != "human_required"
    requires_approval = authority == "human_required"

    if switches.get("global_pause"):
        allowed = False
        reasons.append("global_pause")
    if outbound and switches.get("outbound_pause"):
        allowed = False
        reasons.append("outbound_pause")
    if action == "public_research" and switches.get("research_pause"):
        allowed = False
        reasons.append("research_pause")
    if action == "nonbinding_negotiation" and switches.get("negotiation_pause"):
        allowed = False
        reasons.append("negotiation_pause")

    return {
        "allowed": allowed,
        "requires_approval": requires_approval,
        "authority": authority,
        "reasons": reasons,
        "constitution_version": constitution.get("version"),
    }
