from __future__ import annotations

from typing import Any, Dict, List, Tuple

import master_orchestrator as _master
from cognitive_engine import CognitiveEngine


_ORIGINAL_MASTER_TICK = _master.master_orchestrator_tick
_ENGINE = CognitiveEngine()
_MAX_COMPARISON_HISTORY = 240
_MODES = (
    "RECOVERY",
    "PROTECT_CASH",
    "CLOSE_REVENUE",
    "REVENUE_EXECUTION",
    "PIPELINE_EXECUTION",
    "CONTROLLED_GROWTH",
    "BUILD_FOUNDATION",
    "BALANCED",
)


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


def _independent_signals(state: Dict[str, Any], db_status: Dict[str, Any]) -> Dict[str, Any]:
    cfo = state.get("cfo", {}) or {}
    finance = cfo.get("financial_snapshot", {}) or state.get("financial_snapshot", {}) or {}
    revenue = state.get("revenue_factory", {}) or {}
    directive = revenue.get("directive", {}) or {}
    reverse_plan = revenue.get("reverse_plan", {}) or {}
    corporate = state.get("strategic_directive", {}) or (state.get("corporate_brain", {}) or {}).get("strategy", {}) or {}
    growth = state.get("growth_expansion", {}) or {}
    growth_readiness = growth.get("readiness", {}) or {}
    operations = state.get("operations_memory", {}) or {}
    engines = operations.get("engines", {}) or {}
    operation_cycle = _i(operations.get("cycle"))
    critical_circuits = [
        str(name)
        for name, rec in engines.items()
        if isinstance(rec, dict)
        and rec.get("critical")
        and _i(rec.get("circuit_until_cycle")) > operation_cycle
    ]

    accounts = state.get("candidate_accounts", []) or []
    verified = [x for x in accounts if isinstance(x, dict) and x.get("verified_company")]
    verified_buyers = sum(1 for x in verified if x.get("type") == "buyer")
    verified_suppliers = sum(1 for x in verified if x.get("type") == "supplier")
    evidence_opportunities = len(state.get("market_opportunities", []) or [])

    deals = {str(x.get("id")): x for x in state.get("deals", []) or [] if isinstance(x, dict) and x.get("id")}
    pending_approvals = [
        x for x in state.get("approvals", []) or []
        if isinstance(x, dict) and x.get("status") == "pending"
    ]
    ready_approvals = 0
    for approval in pending_approvals:
        deal = deals.get(str(approval.get("deal_id") or ""), {})
        if deal and not list(deal.get("preclose_missing") or []):
            ready_approvals += 1

    warnings = [str(x) for x in cfo.get("warnings", []) or []]
    collection_warning = any("collection" in x.lower() or "receivable" in x.lower() or "cobro" in x.lower() for x in warnings)

    return {
        "persistence_connected": bool(db_status.get("connected")),
        "critical_engine_circuits": critical_circuits,
        "gross_unsettled_receivable_usd": _f(finance.get("gross_unsettled_receivable_usd")),
        "risk_adjusted_expected_profit_usd": _f(finance.get("risk_adjusted_expected_profit_usd")),
        "collection_warning": collection_warning,
        "ready_approvals": ready_approvals,
        "revenue_directive": str(directive.get("code") or ""),
        "revenue_priority": _f(directive.get("priority")),
        "revenue_profit_gap_usd": _f(reverse_plan.get("profit_gap_usd")),
        "strategy_mode": str(corporate.get("mode") or ""),
        "growth_ready": bool(growth_readiness.get("ready")),
        "growth_readiness_score": _f(growth_readiness.get("score")),
        "verified_buyers": verified_buyers,
        "verified_suppliers": verified_suppliers,
        "evidence_backed_opportunities": evidence_opportunities,
    }


def recommend_company_mode(state: Dict[str, Any], db_status: Dict[str, Any]) -> Dict[str, Any]:
    """Independent deterministic recommendation.

    This deliberately does not read Master Orchestrator output. It scores the underlying
    business state before the authoritative Master tick runs, so agreement/disagreement is measurable.
    """
    s = _independent_signals(state, db_status)
    scores = {mode: 0.0 for mode in _MODES}
    reasons: Dict[str, List[str]] = {mode: [] for mode in _MODES}

    scores["BALANCED"] = 20.0
    reasons["BALANCED"].append("baseline balanced operating posture")

    if not s["persistence_connected"]:
        scores["RECOVERY"] += 120.0
        reasons["RECOVERY"].append("persistence unavailable")
    if s["critical_engine_circuits"]:
        scores["RECOVERY"] += 100.0 + 5.0 * len(s["critical_engine_circuits"])
        reasons["RECOVERY"].append("critical engine circuit open")

    receivable = s["gross_unsettled_receivable_usd"]
    expected_profit = s["risk_adjusted_expected_profit_usd"]
    if receivable > max(1000.0, expected_profit * 1.5):
        scores["PROTECT_CASH"] += 95.0
        reasons["PROTECT_CASH"].append("receivables materially exceed risk-adjusted profit")
    if s["collection_warning"]:
        scores["PROTECT_CASH"] += 55.0
        reasons["PROTECT_CASH"].append("collection warning present")

    if s["ready_approvals"] > 0:
        scores["CLOSE_REVENUE"] += 90.0 + min(20.0, 5.0 * s["ready_approvals"])
        reasons["CLOSE_REVENUE"].append("binding-ready deal awaits human approval")

    revenue_code = s["revenue_directive"]
    if revenue_code and revenue_code != "maintain_factory":
        scores["REVENUE_EXECUTION"] += 35.0 + min(60.0, s["revenue_priority"] * 0.6)
        reasons["REVENUE_EXECUTION"].append(f"active revenue directive:{revenue_code}")
    if s["revenue_profit_gap_usd"] > 0:
        scores["REVENUE_EXECUTION"] += 25.0
        reasons["REVENUE_EXECUTION"].append("positive profit gap remains")

    if s["strategy_mode"] in {"convert_pipeline", "repair_funnel"}:
        scores["PIPELINE_EXECUTION"] += 75.0
        reasons["PIPELINE_EXECUTION"].append(f"strategy requests {s['strategy_mode']}")

    if s["growth_ready"]:
        scores["CONTROLLED_GROWTH"] += 35.0 + min(55.0, s["growth_readiness_score"] * 0.55)
        reasons["CONTROLLED_GROWTH"].append("growth readiness gate is open")
    if s["strategy_mode"] in {"scale_winner", "balanced_growth"}:
        scores["CONTROLLED_GROWTH"] += 35.0
        reasons["CONTROLLED_GROWTH"].append(f"strategy requests {s['strategy_mode']}")

    foundation_gaps = []
    if s["verified_buyers"] == 0:
        foundation_gaps.append("buyers")
    if s["verified_suppliers"] == 0:
        foundation_gaps.append("suppliers")
    if s["evidence_backed_opportunities"] == 0:
        foundation_gaps.append("opportunities")
    if foundation_gaps:
        scores["BUILD_FOUNDATION"] += 45.0 + 18.0 * len(foundation_gaps)
        reasons["BUILD_FOUNDATION"].append("missing foundation:" + ",".join(foundation_gaps))

    ordered: List[Tuple[str, float]] = sorted(scores.items(), key=lambda item: (-item[1], _MODES.index(item[0])))
    winner, winner_score = ordered[0]
    runner_up, runner_up_score = ordered[1]
    margin = max(0.0, winner_score - runner_up_score)
    confidence = max(0.50, min(0.99, 0.58 + margin / 180.0))

    evidence = [
        f"score:{mode}:{round(score, 2)}"
        for mode, score in ordered[:4]
    ]
    evidence.extend([
        f"persistence_connected:{s['persistence_connected']}",
        f"ready_approvals:{s['ready_approvals']}",
        f"revenue_directive:{s['revenue_directive'] or 'none'}",
        f"strategy_mode:{s['strategy_mode'] or 'none'}",
    ])

    return {
        "recommended_mode": winner,
        "score": round(winner_score, 2),
        "runner_up": runner_up,
        "runner_up_score": round(runner_up_score, 2),
        "margin": round(margin, 2),
        "confidence": round(confidence, 3),
        "reason": "; ".join(reasons[winner]) or "highest independent operating score",
        "scores": {mode: round(score, 2) for mode, score in ordered},
        "signals": s,
        "evidence_refs": evidence[:8],
    }


def _record_comparison(state: Dict[str, Any], recommendation: Dict[str, Any], master_mode: str) -> Dict[str, Any]:
    memory = state.setdefault("cognitive_shadow_comparison", {})
    memory.setdefault("cycles", 0)
    memory.setdefault("agreements", 0)
    memory.setdefault("disagreements", 0)
    memory.setdefault("agreement_streak", 0)
    memory.setdefault("disagreement_streak", 0)
    memory.setdefault("history", [])

    recommended = str(recommendation.get("recommended_mode") or "BALANCED")
    agreed = recommended == master_mode
    memory["cycles"] += 1
    if agreed:
        memory["agreements"] += 1
        memory["agreement_streak"] += 1
        memory["disagreement_streak"] = 0
    else:
        memory["disagreements"] += 1
        memory["disagreement_streak"] += 1
        memory["agreement_streak"] = 0
        memory["last_disagreement"] = {
            "cognitive_mode": recommended,
            "master_mode": master_mode,
            "cognitive_confidence": recommendation.get("confidence"),
            "reason": recommendation.get("reason"),
        }

    cycles = max(1, _i(memory["cycles"], 1))
    memory["agreement_rate_pct"] = round(memory["agreements"] / cycles * 100.0, 2)
    row = {
        "cycle": memory["cycles"],
        "agreed": agreed,
        "cognitive_mode": recommended,
        "master_mode": master_mode,
        "confidence": recommendation.get("confidence"),
        "score_margin": recommendation.get("margin"),
    }
    memory["history"].append(row)
    memory["history"] = memory["history"][-_MAX_COMPARISON_HISTORY:]
    return {
        "agreed": agreed,
        "cycles": memory["cycles"],
        "agreements": memory["agreements"],
        "disagreements": memory["disagreements"],
        "agreement_rate_pct": memory["agreement_rate_pct"],
        "agreement_streak": memory["agreement_streak"],
        "disagreement_streak": memory["disagreement_streak"],
    }


def master_orchestrator_with_cognitive_shadow(
    state: Dict[str, Any],
    db_status: Dict[str, Any],
    preflight: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    try:
        recommendation = recommend_company_mode(state, db_status)
    except Exception as exc:
        recommendation = {
            "recommended_mode": "UNAVAILABLE",
            "confidence": 0.0,
            "reason": f"independent_recommendation_failed:{type(exc).__name__}",
            "evidence_refs": [],
            "error": f"{type(exc).__name__}: {str(exc)[:260]}",
        }

    report = dict(_ORIGINAL_MASTER_TICK(state, db_status, preflight=preflight) or {})
    master_mode = str(report.get("company_mode") or "BALANCED")

    try:
        if recommendation.get("recommended_mode") == "UNAVAILABLE":
            raise RuntimeError(str(recommendation.get("error") or "independent recommendation unavailable"))

        cognitive = _ENGINE.decide(
            state,
            {
                "kind": "strategy",
                "object_type": "company",
                "object_id": "LUMEN",
                "action": "score_opportunity",
                "decision": f"shadow_recommend_company_mode:{str(recommendation['recommended_mode']).lower()}",
                "reason": str(recommendation.get("reason") or "Independent cognitive recommendation"),
                "confidence": recommendation.get("confidence"),
                "evidence_refs": recommendation.get("evidence_refs") or [],
            },
            context={
                "live_outbound": False,
                "shadow_mode": True,
                "master_company_mode": master_mode,
            },
        )
        comparison = _record_comparison(state, recommendation, master_mode)
        shadow = {
            "status": cognitive.get("status"),
            "source": cognitive.get("source"),
            "advisor_status": cognitive.get("advisor_status"),
            "specialist": cognitive.get("specialist"),
            "ledger_id": cognitive.get("ledger_id"),
            "side_effect_executed": cognitive.get("side_effect_executed"),
            "hard_ai_monetary_budget_usd": cognitive.get("hard_ai_monetary_budget_usd"),
            "recommended_company_mode": recommendation.get("recommended_mode"),
            "recommendation_confidence": recommendation.get("confidence"),
            "recommendation_score": recommendation.get("score"),
            "recommendation_runner_up": recommendation.get("runner_up"),
            "recommendation_margin": recommendation.get("margin"),
            "recommendation_reason": recommendation.get("reason"),
            "mode_scores": recommendation.get("scores"),
            "master_company_mode": master_mode,
            "comparison": comparison,
            "authoritative": False,
        }
        state["cognitive_shadow"] = shadow
        report["cognitive_shadow"] = shadow
    except Exception as exc:
        shadow = {
            "status": "degraded_fail_open",
            "error": f"{type(exc).__name__}: {str(exc)[:260]}",
            "master_company_mode": master_mode,
            "recommended_company_mode": recommendation.get("recommended_mode"),
            "authoritative": False,
            "side_effect_executed": False,
        }
        state["cognitive_shadow"] = shadow
        report["cognitive_shadow"] = shadow
    return report


_master.master_orchestrator_tick = master_orchestrator_with_cognitive_shadow

print({
    "cognitive_shadow_runtime": {
        "status": "active",
        "mode": "independent_recommendation_and_comparison",
        "authoritative": False,
        "fail_open_to_master": True,
        "hard_ai_monetary_budget_usd": 0.0,
    }
}, flush=True)
