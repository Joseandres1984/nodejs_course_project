from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision
from portfolio_optimizer import portfolio_optimizer_tick as base_portfolio_tick

RESOURCE_KEYS = ("core_research_pct", "deep_dive_pct", "expansion_pct", "exploration_pct")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _engine_for_kind(kind: str) -> str:
    return {
        "COLLECT_CASH": "Commission Settlement",
        "REQUEST_CLOSE_APPROVAL": "Closing Orchestrator",
        "COMPLETE_CLOSE_PACK": "Closing Orchestrator",
        "REPAIR_CLOSE_RISK": "Deal Safeguards",
        "ACCELERATE_DEAL": "Capital & Margin Intelligence",
        "IMPROVE_MARGIN": "Capital & Margin Intelligence",
        "IMPROVE_CONVERSION": "Capital & Margin Intelligence",
        "REPAIR_TERMS": "Capital & Margin Intelligence",
        "COMPLETE_ECONOMICS": "Capital & Margin Intelligence",
        "REPAIR_OR_PARK_RISK": "Capital & Margin Intelligence",
        "PARK_DEAL": "Capital & Margin Intelligence",
        "BUILD_PIPELINE": "Autonomous Revenue Factory",
        "VALIDATE_VENTURE": "Autonomous Venture Builder",
    }.get(kind, "Autonomous Portfolio Optimizer")


def _truth_for_row(state: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    deal_id = str(row.get("deal_id") or "")
    if not deal_id and row.get("object_type") == "transaction":
        txn = next((x for x in state.get("transactions", []) or [] if str(x.get("id") or "") == str(row.get("object_id") or "")), {})
        deal_id = str(txn.get("deal_id") or "")
    return dict((state.get("data_truth_index", {}) or {}).get(deal_id, {}) or {})


def _quality_rerank(state: Dict[str, Any], selected: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    multipliers = state.get("engine_confidence_multiplier", {}) or {}
    out: List[Dict[str, Any]] = []
    for row in selected:
        item = dict(row)
        base_score = _f(item.get("portfolio_priority_score"))
        truth = _truth_for_row(state, item)
        truth_score = _f(truth.get("score"), 100.0)
        truth_factor = 0.60 + 0.40 * max(0.0, min(100.0, truth_score)) / 100.0
        engine = _engine_for_kind(str(item.get("kind") or ""))
        calibration_multiplier = max(0.65, min(1.05, _f(multipliers.get(engine), 1.0)))
        evidence = max(0.0, min(1.0, _f(item.get("evidence_confidence"), 0.7)))
        calibrated_evidence = max(0.15, min(0.99, evidence * calibration_multiplier))
        score = base_score * truth_factor * calibration_multiplier
        truth_hold = bool(truth.get("critical_refresh")) and str(item.get("kind") or "") in {
            "REQUEST_CLOSE_APPROVAL", "ACCELERATE_DEAL", "COMPLETE_CLOSE_PACK", "IMPROVE_CONVERSION"
        }
        if truth_hold:
            score = min(score, 34.0)
            item["blocking"] = True
            item["recommended_action"] = "refresh_critical_evidence_before_progress"
            item["reason"] = (str(item.get("reason") or "") + " | Evidencia crítica vencida/faltante: " + ", ".join(truth.get("critical_refresh") or [])).strip()
        item["base_portfolio_priority_score"] = round(base_score, 2)
        item["data_truth_score"] = round(truth_score, 2) if truth else None
        item["data_truth_class"] = truth.get("truth_class") if truth else None
        item["calibration_engine"] = engine
        item["calibration_multiplier"] = round(calibration_multiplier, 3)
        item["calibrated_evidence_confidence"] = round(calibrated_evidence, 3)
        item["portfolio_priority_score"] = round(max(0.0, min(100.0, score)), 2)
        item["truth_hold"] = truth_hold
        out.append(item)

    out.sort(key=lambda x: (_f(x.get("portfolio_priority_score")), _f(x.get("economic_value_usd"))), reverse=True)
    for rank, item in enumerate(out, start=1):
        item["rank"] = rank
        if item.get("truth_hold") or (item.get("blocking") and _f(item.get("portfolio_priority_score")) < 40):
            item["portfolio_decision"] = "HOLD"
        elif rank <= 3 and _f(item.get("portfolio_priority_score")) >= 55:
            item["portfolio_decision"] = "PURSUE_NOW"
        elif _f(item.get("portfolio_priority_score")) >= 40:
            item["portfolio_decision"] = "NEXT"
        else:
            item["portfolio_decision"] = "PARK"
    return out


def _resource_overlay(state: Dict[str, Any], primary: Dict[str, Any] | None, base_report: Dict[str, Any]) -> Dict[str, Any]:
    old_overlay = base_report.get("resource_overlay", {}) or {}
    base = dict(old_overlay.get("base_resource_plan", {}) or (state.get("master_governance", {}) or {}).get("resource_plan", {}) or {})
    governance = state.get("master_governance", {}) or {}
    switches = governance.get("kill_switches", {}) or {}
    mode = str(governance.get("company_mode") or "")
    result = {"applied": False, "reason": "no_quality_primary", "base_resource_plan": base}
    if not primary or not base:
        state["portfolio_optimizer_overlay"] = result
        return result
    if mode == "RECOVERY" or switches.get("global_pause"):
        result["reason"] = "constitutional_recovery_blocks_quality_overlay"
        state["portfolio_optimizer_overlay"] = result
        return result
    kind = str(primary.get("kind") or "")
    changes = {
        "COLLECT_CASH": {"deep_dive_pct": 12, "core_research_pct": -6, "exploration_pct": -6},
        "REQUEST_CLOSE_APPROVAL": {"deep_dive_pct": 12, "core_research_pct": -6, "exploration_pct": -6},
        "COMPLETE_CLOSE_PACK": {"deep_dive_pct": 10, "core_research_pct": -5, "exploration_pct": -5},
        "ACCELERATE_DEAL": {"deep_dive_pct": 10, "core_research_pct": -5, "exploration_pct": -5},
        "IMPROVE_MARGIN": {"deep_dive_pct": 10, "expansion_pct": -5, "exploration_pct": -5},
        "REPAIR_CLOSE_RISK": {"deep_dive_pct": 10, "expansion_pct": -5, "exploration_pct": -5},
        "BUILD_PIPELINE": {"core_research_pct": 8, "deep_dive_pct": -4, "exploration_pct": -4},
        "VALIDATE_VENTURE": {"exploration_pct": 6, "core_research_pct": -3, "expansion_pct": -3},
    }.get(kind, {})
    if not changes:
        result["reason"] = f"no_quality_overlay_for:{kind}"
        state["portfolio_optimizer_overlay"] = result
        return result
    adjusted = dict(base)
    for key in RESOURCE_KEYS:
        adjusted[key] = max(0.0, min(100.0, _f(base.get(key)) + _f(changes.get(key))))
    if switches.get("expansion_pause"):
        adjusted["expansion_pct"] = 0.0
    total = sum(_f(adjusted.get(k)) for k in RESOURCE_KEYS)
    if total > 0:
        for key in RESOURCE_KEYS:
            adjusted[key] = round(_f(adjusted.get(key)) / total * 100.0, 1)
    for key in ("outbound_cap", "mission_queries_cap", "expansion_queries_cap", "daily_queries_remaining", "resource_type", "authorizes_spending"):
        if key in base:
            adjusted[key] = base[key]
    governance["resource_plan"] = adjusted
    state["master_governance"] = governance
    state["master_resource_plan"] = adjusted
    result.update({"applied": True, "reason": f"quality_focus_on:{kind}", "adjustments": changes, "adjusted_resource_plan": adjusted})
    state["portfolio_optimizer_overlay"] = result
    return result


def _sync_queue(state: Dict[str, Any], selected: List[Dict[str, Any]]) -> None:
    queue = list(state.get("operating_action_queue", []) or [])
    selected_by_key = {
        f"portfolio_optimizer|{x.get('kind')}|{x.get('object_type')}|{x.get('object_id')}": x for x in selected
    }
    for task in queue:
        row = selected_by_key.get(str(task.get("key") or ""))
        if not row:
            continue
        task["priority_score"] = row.get("portfolio_priority_score")
        task["confidence"] = row.get("calibrated_evidence_confidence")
        task["autonomous"] = bool(row.get("autonomous")) and not bool(row.get("blocking")) and not bool(row.get("truth_hold"))
        task["risk"] = "high" if row.get("blocking") or row.get("truth_hold") else task.get("risk")
        task["payload"] = dict(row)
    state["operating_action_queue"] = sorted(queue, key=lambda x: _f(x.get("priority_score")), reverse=True)[:120]


def _sync_deals(state: Dict[str, Any], selected: List[Dict[str, Any]]) -> None:
    best: Dict[str, Dict[str, Any]] = {}
    for row in selected:
        deal_id = str(row.get("deal_id") or "")
        if deal_id and (deal_id not in best or _f(row.get("portfolio_priority_score")) > _f(best[deal_id].get("portfolio_priority_score"))):
            best[deal_id] = row
    for deal in state.get("deals", []) or []:
        row = best.get(str(deal.get("id") or ""))
        if not row:
            continue
        deal["portfolio_priority_score"] = row.get("portfolio_priority_score")
        deal["portfolio_action"] = row.get("kind")
        deal["portfolio_truth_adjusted"] = True
        deal["portfolio_calibration_multiplier"] = row.get("calibration_multiplier")
        deal["portfolio_ranked_at"] = utcnow()


def portfolio_optimizer_v2_tick(state: Dict[str, Any], goal_plan: Dict[str, Any] | None = None) -> Dict[str, Any]:
    base = base_portfolio_tick(state, goal_plan)
    selected = _quality_rerank(state, list(base.get("selected_actions", []) or []))
    primary = selected[0] if selected else None
    overlay = _resource_overlay(state, primary, base)
    _sync_queue(state, selected)
    _sync_deals(state, selected)

    report = dict(base)
    report.update({
        "updated_at": utcnow(),
        "mode": "truth_aware_calibrated_opportunity_cost_optimization",
        "primary_action": primary,
        "selected_actions": selected,
        "pursue_now": sum(1 for x in selected if x.get("portfolio_decision") == "PURSUE_NOW"),
        "next": sum(1 for x in selected if x.get("portfolio_decision") == "NEXT"),
        "hold": sum(1 for x in selected if x.get("portfolio_decision") == "HOLD"),
        "park": sum(1 for x in selected if x.get("portfolio_decision") == "PARK"),
        "resource_overlay": overlay,
        "quality_layer": {
            "truth_engine_applied": bool(state.get("data_truth_engine")),
            "decision_calibration_applied": bool(state.get("decision_calibration")),
            "rule": "La prioridad económica se degrada cuando la evidencia está vencida o el motor que la produjo mostró sobreconfianza histórica.",
        },
    })
    state["portfolio_optimizer"] = report
    state["portfolio_action_plan"] = selected
    state["portfolio_optimizer_v2"] = report

    if primary:
        record_decision(
            state,
            engine="Autonomous Portfolio Optimizer v2",
            object_type=str(primary.get("object_type") or "company"),
            object_id=str(primary.get("object_id") or "LUMEN"),
            decision=f"quality_portfolio:{str(primary.get('kind') or '').lower()}",
            reason=(
                f"Score final {primary.get('portfolio_priority_score')} desde base {primary.get('base_portfolio_priority_score')}; "
                f"truth {primary.get('data_truth_score')}; calibración {primary.get('calibration_multiplier')}."
            ),
            action="score_opportunity" if primary.get("autonomous") and not primary.get("truth_hold") else "prepare_draft",
            confidence=max(0.35, min(0.99, _f(primary.get("calibrated_evidence_confidence"), 0.65))),
            evidence_refs=[],
            allowed=not bool(primary.get("blocking")) and not bool(primary.get("truth_hold")),
            requires_approval=not bool(primary.get("autonomous")) or bool(primary.get("blocking")) or bool(primary.get("truth_hold")),
        )
    return report
