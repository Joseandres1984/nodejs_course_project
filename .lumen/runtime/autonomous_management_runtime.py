from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from autonomous_management import autonomous_management_tick


RESOURCE_KEYS = ("core_research_pct", "deep_dive_pct", "expansion_pct", "exploration_pct")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _apply_resource_overlay(state: Dict[str, Any], management: Dict[str, Any]) -> Dict[str, Any]:
    governance = state.get("master_governance", {}) or {}
    base = dict(governance.get("resource_plan", {}) or state.get("master_resource_plan", {}) or {})
    adjustments = dict(management.get("resource_adjustment", {}) or {})
    switches = governance.get("kill_switches", {}) or {}
    mode = str(governance.get("company_mode") or "")

    result = {
        "updated_at": utcnow(),
        "applied": False,
        "reason": "no_management_adjustment",
        "base_resource_plan": base,
        "adjustments": adjustments,
    }
    if not base or not adjustments:
        state["executive_management_overlay"] = result
        return result
    if mode in {"RECOVERY", "PROTECT_CASH"} or switches.get("global_pause"):
        result["reason"] = f"constitutional_mode_blocks_management_overlay:{mode}"
        state["executive_management_overlay"] = result
        return result

    adjusted = dict(base)
    for key in RESOURCE_KEYS:
        adjusted[key] = max(0.0, min(100.0, _f(base.get(key)) + _f(adjustments.get(key))))

    if switches.get("expansion_pause"):
        adjusted["expansion_pct"] = 0.0

    total = sum(_f(adjusted.get(key)) for key in RESOURCE_KEYS)
    if total > 0:
        for key in RESOURCE_KEYS:
            adjusted[key] = round(_f(adjusted.get(key)) / total * 100.0, 1)

    # Executive Management may only reallocate reversible attention. It cannot widen caps or spending authority.
    for key in ("outbound_cap", "mission_queries_cap", "expansion_queries_cap", "daily_queries_remaining", "resource_type", "authorizes_spending"):
        if key in base:
            adjusted[key] = base[key]

    governance["resource_plan"] = adjusted
    governance["executive_management_overlay"] = {
        "updated_at": utcnow(),
        "primary_priority": management.get("primary_management_priority"),
        "adjustments": adjustments,
        "rule": "bounded attention reallocation below Constitution, Orchestrator and safety gates",
    }
    state["master_governance"] = governance
    state["master_resource_plan"] = adjusted
    result.update({"applied": True, "reason": "bounded_reversible_management_allocation", "adjusted_resource_plan": adjusted})
    state["executive_management_overlay"] = result
    return result


def _materialize_management_task(state: Dict[str, Any], management: Dict[str, Any]) -> Dict[str, Any] | None:
    primary = management.get("primary_management_priority", {}) or {}
    if not primary.get("code"):
        return None
    task = {
        "key": f"executive_management|{primary.get('code')}|{primary.get('department')}",
        "kind": "executive_management",
        "title": f"CEO operativo: {primary.get('title') or primary.get('code')}",
        "reason": str(primary.get("reason") or "Prioridad de mejora continua"),
        "impact": min(100.0, max(70.0, _f(primary.get("priority"), 80.0))),
        "urgency": min(100.0, max(68.0, _f(primary.get("priority"), 80.0))),
        "confidence": 0.90,
        "effort": 1.0,
        "risk": "high" if not primary.get("autonomous", True) else "low",
        "autonomous": bool(primary.get("autonomous", True)),
        "object_type": "deal" if primary.get("deal_id") else "company",
        "object_id": str(primary.get("deal_id") or "LUMEN"),
        "payload": {
            "department": primary.get("department"),
            "code": primary.get("code"),
            "company_management_score": management.get("company_management_score"),
        },
        "priority_score": round(_f(primary.get("priority"), 80.0), 2),
        "created_at": utcnow(),
    }
    queue = list(state.get("operating_action_queue", []) or [])
    by_key = {str(x.get("key")): x for x in queue if x.get("key")}
    current = by_key.get(task["key"])
    if current is None or _f(task["priority_score"]) > _f(current.get("priority_score")):
        by_key[task["key"]] = task
    queue = sorted(by_key.values(), key=lambda x: _f(x.get("priority_score")), reverse=True)[:80]
    state["operating_action_queue"] = queue
    chief = state.setdefault("chief_of_staff", {})
    chief["top_actions"] = queue[:12]
    chief["executive_management_priority"] = primary.get("code")
    chief["executive_management_department"] = primary.get("department")
    return task


def _annotate_portfolio(state: Dict[str, Any], management: Dict[str, Any]) -> None:
    deal_index = {str(x.get("deal_id")): x for x in management.get("deal_portfolio", []) or [] if x.get("deal_id")}
    for deal in state.get("deals", []) or []:
        row = deal_index.get(str(deal.get("id") or ""))
        if row:
            deal["management_disposition"] = row.get("disposition")
            deal["management_reason"] = row.get("reason")
            deal["management_reviewed_at"] = utcnow()
    state["management_category_directives"] = [
        {
            "category": x.get("category"),
            "action": x.get("management_action"),
            "score": x.get("learned_score"),
            "confidence": x.get("confidence"),
            "observations": x.get("observations"),
        }
        for x in management.get("category_portfolio", []) or []
    ]


def executive_management_cycle(state: Dict[str, Any]) -> Dict[str, Any]:
    governance = state.get("master_governance", {}) or {}
    management = autonomous_management_tick(state, governance)
    _annotate_portfolio(state, management)
    overlay = _apply_resource_overlay(state, management)
    task = _materialize_management_task(state, management)
    management["resource_overlay"] = overlay
    management["operating_task"] = task
    state["autonomous_management"] = management
    return management
