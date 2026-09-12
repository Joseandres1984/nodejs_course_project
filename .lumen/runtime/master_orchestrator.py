from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision
from operating_constitution import ensure_constitution


MAX_HISTORY = 160


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


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


def _signals(state: Dict[str, Any], db_status: Dict[str, Any]) -> Dict[str, Any]:
    cfo = state.get("cfo", {}) or {}
    finance = cfo.get("financial_snapshot", {}) or {}
    corporate = state.get("strategic_directive", {}) or (state.get("corporate_brain", {}) or {}).get("strategy", {}) or {}
    revenue = state.get("revenue_factory", {}) or {}
    growth = state.get("growth_expansion", {}) or {}
    war = state.get("war_room", {}) or {}
    operations = state.get("operations_memory", {}) or {}
    engines = operations.get("engines", {}) or {}
    critical_circuits = [
        name for name, rec in engines.items()
        if rec.get("critical") and _i(rec.get("circuit_until_cycle")) > _i(operations.get("cycle"))
    ]
    pending_approvals = [x for x in state.get("approvals", []) if x.get("status") == "pending"]
    ready_approvals = []
    deals = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}
    for approval in pending_approvals:
        deal = deals.get(str(approval.get("deal_id") or ""), {})
        if not list(deal.get("preclose_missing") or []):
            ready_approvals.append(approval)

    warnings = [str(x) for x in cfo.get("warnings", []) or []]
    collection_risk = any("collection" in x.lower() or "receivable" in x.lower() for x in warnings)
    strategy_mode = str(corporate.get("mode") or "")
    revenue_directive = revenue.get("directive", {}) or {}
    revenue_plan = revenue.get("reverse_plan", {}) or {}
    growth_readiness = growth.get("readiness", {}) or {}

    return {
        "persistence_connected": bool(db_status.get("connected")),
        "critical_engine_circuits": critical_circuits,
        "cfo_warnings": warnings,
        "collection_risk": collection_risk,
        "gross_unsettled_receivable_usd": _f(finance.get("gross_unsettled_receivable_usd")),
        "risk_adjusted_expected_profit_usd": _f(finance.get("risk_adjusted_expected_profit_usd")),
        "strategy_mode": strategy_mode,
        "strategy_focus": list(corporate.get("focus_categories") or []),
        "revenue_directive": revenue_directive.get("code"),
        "revenue_directive_priority": _f(revenue_directive.get("priority")),
        "revenue_profit_gap_usd": revenue_plan.get("profit_gap_usd"),
        "revenue_plan_status": revenue_plan.get("status"),
        "growth_ready": bool(growth_readiness.get("ready")),
        "growth_readiness_score": _f(growth_readiness.get("score")),
        "pending_approvals": len(pending_approvals),
        "ready_approvals": len(ready_approvals),
        "primary_money_score": _f((war.get("primary_money_move") or {}).get("money_score")),
    }


def _resolve_mode(signals: Dict[str, Any]) -> Dict[str, Any]:
    if not signals["persistence_connected"] or signals["critical_engine_circuits"]:
        return {
            "mode": "RECOVERY",
            "rank": 1,
            "reason": "Integridad/persistencia o motor crítico degradado; recuperación prevalece sobre actividad comercial.",
            "winning_engine": "Autonomous COO / Constitution",
        }

    if signals["strategy_mode"] == "protect_cash_quality" or signals["collection_risk"]:
        return {
            "mode": "PROTECT_CASH",
            "rank": 3,
            "reason": "Riesgo de caja/cobro detectado; conversión y cobranza prevalecen sobre expansión.",
            "winning_engine": "CFO",
        }

    if signals["ready_approvals"] > 0:
        return {
            "mode": "CLOSE_REVENUE",
            "rank": 4,
            "reason": "Existen cierres listos para decisión humana; proteger conversión y preparación de cierre.",
            "winning_engine": "War Room / Approval Cockpit",
        }

    revenue_code = str(signals.get("revenue_directive") or "")
    if revenue_code and revenue_code not in {"maintain_factory"} and _f(signals.get("revenue_directive_priority")) >= 82:
        return {
            "mode": "REVENUE_EXECUTION",
            "rank": 5,
            "reason": f"Revenue Factory detectó una brecha prioritaria: {revenue_code}.",
            "winning_engine": "Autonomous Revenue Factory",
        }

    if signals["strategy_mode"] in {"convert_pipeline", "repair_funnel"}:
        return {
            "mode": "PIPELINE_EXECUTION",
            "rank": 5,
            "reason": f"Corporate Brain está en {signals['strategy_mode']}; convertir el pipeline existente tiene prioridad.",
            "winning_engine": "Corporate Brain",
        }

    if signals["strategy_mode"] in {"scale_winner", "balanced_growth"} and signals["growth_ready"]:
        return {
            "mode": "CONTROLLED_GROWTH",
            "rank": 6,
            "reason": "Base comercial suficiente y expansión habilitada; crecer sin canibalizar ejecución base.",
            "winning_engine": "Corporate Brain / Growth & Expansion",
        }

    if signals["strategy_mode"] == "build_foundation":
        return {
            "mode": "BUILD_FOUNDATION",
            "rank": 7,
            "reason": "Todavía falta densidad de mercado/evidencia; priorizar base comercial y aprendizaje.",
            "winning_engine": "Corporate Brain",
        }

    return {
        "mode": "BALANCED",
        "rank": 6,
        "reason": "No hay conflicto superior activo; mantener conversión rentable con exploración controlada.",
        "winning_engine": "Master Orchestrator",
    }


def _kill_switches(mode: str, signals: Dict[str, Any]) -> Dict[str, Any]:
    global_pause = mode == "RECOVERY"
    expansion_pause = mode in {"RECOVERY", "PROTECT_CASH", "BUILD_FOUNDATION"} or not signals.get("growth_ready")
    return {
        "global_pause": global_pause,
        "outbound_pause": global_pause,
        "research_pause": global_pause,
        "negotiation_pause": global_pause,
        "expansion_pause": expansion_pause,
        "new_market_pause": expansion_pause,
        "binding_actions_require_human": True,
        "financial_commitments_require_human": True,
        "reason": "constitutional_mode:" + mode.lower(),
    }


def _resource_plan(mode: str, state: Dict[str, Any]) -> Dict[str, Any]:
    profiles = {
        "RECOVERY": {"core_research_pct": 0, "deep_dive_pct": 0, "expansion_pct": 0, "exploration_pct": 0, "outbound_cap": 0, "mission_queries_cap": 0, "expansion_queries_cap": 0},
        "PROTECT_CASH": {"core_research_pct": 25, "deep_dive_pct": 55, "expansion_pct": 0, "exploration_pct": 20, "outbound_cap": 2, "mission_queries_cap": 1, "expansion_queries_cap": 0},
        "CLOSE_REVENUE": {"core_research_pct": 20, "deep_dive_pct": 60, "expansion_pct": 5, "exploration_pct": 15, "outbound_cap": 3, "mission_queries_cap": 1, "expansion_queries_cap": 0},
        "REVENUE_EXECUTION": {"core_research_pct": 35, "deep_dive_pct": 45, "expansion_pct": 10, "exploration_pct": 10, "outbound_cap": 3, "mission_queries_cap": 1, "expansion_queries_cap": 1},
        "PIPELINE_EXECUTION": {"core_research_pct": 30, "deep_dive_pct": 45, "expansion_pct": 10, "exploration_pct": 15, "outbound_cap": 3, "mission_queries_cap": 1, "expansion_queries_cap": 1},
        "CONTROLLED_GROWTH": {"core_research_pct": 35, "deep_dive_pct": 30, "expansion_pct": 25, "exploration_pct": 10, "outbound_cap": 3, "mission_queries_cap": 1, "expansion_queries_cap": 1},
        "BUILD_FOUNDATION": {"core_research_pct": 70, "deep_dive_pct": 10, "expansion_pct": 0, "exploration_pct": 20, "outbound_cap": 2, "mission_queries_cap": 2, "expansion_queries_cap": 0},
        "BALANCED": {"core_research_pct": 45, "deep_dive_pct": 30, "expansion_pct": 15, "exploration_pct": 10, "outbound_cap": 3, "mission_queries_cap": 1, "expansion_queries_cap": 1},
    }
    plan = dict(profiles.get(mode, profiles["BALANCED"]))
    policy_cap = max(0, _i((state.get("policies", {}) or {}).get("max_outbound_per_tick"), 3))
    plan["outbound_cap"] = min(plan["outbound_cap"], policy_cap)
    budget = state.get("scout_budget", {}) or {}
    plan["daily_queries_remaining"] = _i(budget.get("queries_remaining"))
    plan["resource_type"] = "attention_research_and_governed_outreach_only"
    plan["authorizes_spending"] = False
    return plan


def _conflicts(signals: Dict[str, Any], mode: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    strategy = signals.get("strategy_mode")
    if strategy in {"scale_winner", "balanced_growth"} and mode in {"PROTECT_CASH", "RECOVERY"}:
        rows.append({
            "conflict": "growth_vs_safety",
            "requesting_engine": "Corporate Brain / Growth & Expansion",
            "blocked_by": "CFO/COO constitutional priority",
            "resolution": mode,
        })
    if signals.get("growth_ready") and mode == "REVENUE_EXECUTION":
        rows.append({
            "conflict": "expansion_vs_revenue_gap",
            "requesting_engine": "Growth & Expansion",
            "blocked_by": "Revenue Factory",
            "resolution": "expansion receives bounded residual budget",
        })
    if signals.get("pending_approvals", 0) and mode not in {"CLOSE_REVENUE", "RECOVERY", "PROTECT_CASH"}:
        rows.append({
            "conflict": "human_authority_pending",
            "requesting_engine": "Closer",
            "blocked_by": "Human authority boundary",
            "resolution": "continue reversible work; binding action waits",
        })
    return rows


def master_orchestrator_tick(state: Dict[str, Any], db_status: Dict[str, Any], preflight: Dict[str, Any] | None = None) -> Dict[str, Any]:
    constitution = ensure_constitution(state)
    signals = _signals(state, db_status)
    resolution = _resolve_mode(signals)
    mode = resolution["mode"]
    switches = _kill_switches(mode, signals)
    resources = _resource_plan(mode, state)
    conflicts = _conflicts(signals, mode)

    # Expansion is a lower constitutional priority; if paused it receives no query allocation regardless of its local score.
    if switches["expansion_pause"]:
        resources["expansion_pct"] = 0
        resources["expansion_queries_cap"] = 0

    previous = state.get("master_governance", {}) or {}
    changed = previous.get("company_mode") != mode or previous.get("kill_switches") != switches
    report = {
        "updated_at": utcnow(),
        "constitution_version": constitution.get("version"),
        "company_mode": mode,
        "constitutional_rank": resolution.get("rank"),
        "reason": resolution.get("reason"),
        "winning_engine": resolution.get("winning_engine"),
        "signals": signals,
        "kill_switches": switches,
        "resource_plan": resources,
        "conflicts_resolved": conflicts,
        "preflight": preflight or {},
        "changed": changed,
        "single_command_rule": "higher constitutional priority wins; lower engines receive residual resources and may not bypass kill-switches",
    }
    state["master_governance"] = report
    state["master_resource_plan"] = resources
    state["master_kill_switches"] = switches

    state.setdefault("orchestration_history", []).append({
        "ts": report["updated_at"],
        "mode": mode,
        "reason": resolution.get("reason"),
        "winning_engine": resolution.get("winning_engine"),
        "kill_switches": switches,
        "resource_plan": resources,
        "conflict_count": len(conflicts),
    })
    state["orchestration_history"] = state["orchestration_history"][-MAX_HISTORY:]

    record_decision(
        state,
        engine="Master Orchestrator",
        object_type="company",
        object_id="LUMEN",
        decision=f"company_mode:{mode.lower()}",
        reason=str(resolution.get("reason") or "Constitutional arbitration"),
        action="score_opportunity",
        confidence=0.98 if mode in {"RECOVERY", "PROTECT_CASH"} else 0.9,
        evidence_refs=[],
        allowed=True,
        requires_approval=False,
    )
    return report
