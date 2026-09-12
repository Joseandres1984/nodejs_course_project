from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from autonomy_governor import record_decision, register_incident


FAILURE_THRESHOLD = 3
CIRCUIT_COOLDOWN_CYCLES = 4
MAX_ENGINE_HISTORY = 20
MAX_CYCLE_HISTORY = 80
MAX_RECOVERY_QUEUE = 80


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ensure(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("operations_memory", {})
    memory.setdefault("cycle", 0)
    memory.setdefault("engines", {})
    memory.setdefault("cycle_history", [])
    memory.setdefault("recovery_queue", [])
    memory.setdefault("last_healthy_cycle", None)
    memory.setdefault("last_degraded_cycle", None)
    memory.setdefault("outbound_block_streak", 0)
    state.setdefault("operational_guard", {"outbound_allowed": False, "reason": "not_evaluated"})
    return memory


def begin_operations_cycle(state: Dict[str, Any], db_status: Dict[str, Any], live_outbound: bool) -> Dict[str, Any]:
    memory = _ensure(state)
    memory["cycle"] = int(memory.get("cycle") or 0) + 1
    cycle = memory["cycle"]
    memory["current_cycle_started_at"] = utcnow()

    # Fail closed for outbound at the beginning of every cycle. It is explicitly reopened only after health review.
    state["operational_guard"] = {
        "updated_at": utcnow(),
        "cycle": cycle,
        "outbound_allowed": False,
        "reason": "preflight_pending",
        "live_outbound_requested": bool(live_outbound),
        "persistence_connected": bool(db_status.get("connected")),
    }
    return {"cycle": cycle, "started_at": memory["current_cycle_started_at"]}


def _engine_record(memory: Dict[str, Any], engine: str) -> Dict[str, Any]:
    engines = memory.setdefault("engines", {})
    rec = engines.setdefault(engine, {
        "runs": 0,
        "successes": 0,
        "failures": 0,
        "consecutive_failures": 0,
        "circuit_until_cycle": 0,
        "history": [],
    })
    return rec


def _push_history(rec: Dict[str, Any], entry: Dict[str, Any]) -> None:
    rec.setdefault("history", []).append(entry)
    if len(rec["history"]) > MAX_ENGINE_HISTORY:
        del rec["history"][:-MAX_ENGINE_HISTORY]


def run_guarded(
    state: Dict[str, Any],
    engine: str,
    fn: Callable[[], Any],
    *,
    default: Any = None,
    critical: bool = False,
) -> Any:
    memory = _ensure(state)
    cycle = int(memory.get("cycle") or 0)
    rec = _engine_record(memory, engine)

    circuit_until = int(rec.get("circuit_until_cycle") or 0)
    if circuit_until and cycle < circuit_until:
        rec["last_status"] = "circuit_open"
        rec["last_skipped_at"] = utcnow()
        _push_history(rec, {"ts": utcnow(), "cycle": cycle, "status": "circuit_open"})
        return default if default is not None else {
            "ok": False,
            "engine": engine,
            "status": "circuit_open",
            "retry_cycle": circuit_until,
        }

    rec["runs"] = int(rec.get("runs") or 0) + 1
    try:
        result = fn()
        rec["successes"] = int(rec.get("successes") or 0) + 1
        rec["consecutive_failures"] = 0
        rec["circuit_until_cycle"] = 0
        rec["last_status"] = "success"
        rec["last_success_at"] = utcnow()
        rec["last_error"] = None
        _push_history(rec, {"ts": utcnow(), "cycle": cycle, "status": "success"})
        return result
    except Exception as exc:
        detail = str(exc)[:500]
        rec["failures"] = int(rec.get("failures") or 0) + 1
        rec["consecutive_failures"] = int(rec.get("consecutive_failures") or 0) + 1
        rec["last_status"] = "failed"
        rec["last_failure_at"] = utcnow()
        rec["last_error"] = detail
        rec["critical"] = bool(critical)
        if rec["consecutive_failures"] >= FAILURE_THRESHOLD:
            rec["circuit_until_cycle"] = cycle + CIRCUIT_COOLDOWN_CYCLES
        register_incident(state, engine, "guarded_engine_exception", detail)
        _push_history(rec, {
            "ts": utcnow(),
            "cycle": cycle,
            "status": "failed",
            "error": detail,
            "critical": bool(critical),
        })
        return default if default is not None else {
            "ok": False,
            "engine": engine,
            "status": "failed",
            "error": detail,
        }


def _ids(items: List[Dict[str, Any]]) -> List[str]:
    return [str(x.get("id")) for x in items if x.get("id")]


def _duplicates(values: List[str]) -> List[str]:
    seen = set()
    dup = []
    for value in values:
        if value in seen and value not in dup:
            dup.append(value)
        seen.add(value)
    return dup


def _data_integrity(state: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    auto_remediations: List[str] = []

    collections = [
        "research_leads", "candidate_accounts", "market_opportunities", "interlocution_cases",
        "deep_dive_cases", "deals", "offers", "outbox", "inbox", "transactions", "approvals",
    ]
    for name in collections:
        if not isinstance(state.get(name), list):
            state[name] = []
            auto_remediations.append(f"initialized_{name}_list")

    for name in collections:
        dup = _duplicates(_ids(state.get(name, [])))
        if dup:
            issues.append({"severity": "critical", "kind": "duplicate_ids", "collection": name, "ids": dup[:8]})

    deal_ids = set(_ids(state.get("deals", [])))
    opp_ids = set(_ids(state.get("opportunities", []))) | set(_ids(state.get("market_opportunities", [])))

    for deal in state.get("deals", []):
        opp_id = str(deal.get("opportunity_id") or "")
        if opp_id and opp_ids and opp_id not in opp_ids:
            deal["operational_status"] = "orphan_opportunity_reference"
            issues.append({"severity": "high", "kind": "orphan_deal_opportunity", "deal_id": deal.get("id"), "opportunity_id": opp_id})

    for offer in state.get("offers", []):
        deal_id = str(offer.get("deal_id") or "")
        if deal_id and deal_id not in deal_ids:
            offer["operational_status"] = "orphan_deal_reference"
            issues.append({"severity": "high", "kind": "orphan_offer", "offer_id": offer.get("id"), "deal_id": deal_id})

    for item in state.get("outbox", []):
        deal_id = str(item.get("deal_id") or "")
        if deal_id and deal_id not in deal_ids and item.get("status") in {"ready", "draft", "pending_review"}:
            item["status"] = "blocked_orphan_reference"
            item["last_error"] = "Autonomous COO bloqueó salida: deal referenciado inexistente"
            auto_remediations.append(f"blocked_orphan_outbox:{item.get('id')}")
            issues.append({"severity": "critical", "kind": "orphan_outbox", "outbox_id": item.get("id"), "deal_id": deal_id})

    return {
        "issues": issues,
        "critical": sum(1 for x in issues if x.get("severity") == "critical"),
        "high": sum(1 for x in issues if x.get("severity") == "high"),
        "auto_remediations": auto_remediations,
    }


def _backlogs(state: Dict[str, Any]) -> Dict[str, int]:
    accounts = state.get("candidate_accounts", [])
    outbox = state.get("outbox", [])
    offers = state.get("offers", [])
    approvals = state.get("approvals", [])
    return {
        "verification_required": sum(1 for x in accounts if x.get("status") == "verification_required" or x.get("verification_status") == "retry_required"),
        "contact_research_required": sum(1 for x in accounts if x.get("verified_company") and not x.get("commercial_channel_verified")),
        "outbound_ready": sum(1 for x in outbox if x.get("status") == "ready"),
        "outbound_failed": sum(1 for x in outbox if x.get("status") == "send_failed"),
        "outbound_blocked": sum(1 for x in outbox if str(x.get("status") or "").startswith("blocked")),
        "offers_need_clarification": sum(1 for x in offers if x.get("source") != "demo/simulación" and x.get("normalization_status") == "clarification_required"),
        "pending_approvals": sum(1 for x in approvals if x.get("status") == "pending"),
    }


def _engine_health(memory: Dict[str, Any]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for name, rec in memory.get("engines", {}).items():
        runs = int(rec.get("runs") or 0)
        successes = int(rec.get("successes") or 0)
        success_rate = successes / runs * 100.0 if runs else 100.0
        rows.append({
            "engine": name,
            "status": rec.get("last_status"),
            "success_rate_pct": round(success_rate, 1),
            "consecutive_failures": int(rec.get("consecutive_failures") or 0),
            "circuit_until_cycle": int(rec.get("circuit_until_cycle") or 0),
            "critical": bool(rec.get("critical")),
            "last_error": rec.get("last_error"),
        })
    rows.sort(key=lambda x: (x["critical"], x["consecutive_failures"], -x["success_rate_pct"]), reverse=True)
    return {
        "engines": rows,
        "failed_now": [x for x in rows if x.get("status") == "failed"],
        "circuits_open": [x for x in rows if x.get("status") == "circuit_open" or x.get("circuit_until_cycle", 0) > int(memory.get("cycle") or 0)],
    }


def _recovery_actions(state: Dict[str, Any], integrity: Dict[str, Any], engine_health: Dict[str, Any], backlogs: Dict[str, int]) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []

    for row in engine_health.get("failed_now", [])[:8]:
        actions.append({
            "kind": "engine_recovery",
            "engine": row.get("engine"),
            "priority": 100 if row.get("critical") else 85,
            "action": "retry_after_circuit_cooldown" if row.get("consecutive_failures", 0) >= FAILURE_THRESHOLD else "retry_next_cycle",
            "autonomous": True,
            "reason": row.get("last_error"),
        })

    if integrity.get("critical"):
        actions.append({
            "kind": "data_integrity",
            "priority": 100,
            "action": "block_risky_actions_and_require_repair",
            "autonomous": False,
            "reason": f"{integrity.get('critical')} problema(s) críticos de integridad detectados",
        })

    if backlogs.get("outbound_failed", 0):
        actions.append({
            "kind": "mail_recovery",
            "priority": 88,
            "action": "inspect_failed_delivery_before_retry",
            "autonomous": False,
            "reason": "Un error SMTP puede ser ambiguo; no se reintenta automáticamente para evitar duplicados.",
        })

    if backlogs.get("offers_need_clarification", 0):
        actions.append({
            "kind": "commercial_data",
            "priority": 78,
            "action": "complete_quote_fields",
            "autonomous": True,
            "reason": f"{backlogs.get('offers_need_clarification')} oferta(s) requieren datos antes de comparación",
        })

    actions.sort(key=lambda x: int(x.get("priority") or 0), reverse=True)
    return actions[:MAX_RECOVERY_QUEUE]


def operations_control_tick(
    state: Dict[str, Any],
    db_status: Dict[str, Any],
    *,
    live_outbound: bool,
    persistence_result: bool | None = None,
) -> Dict[str, Any]:
    memory = _ensure(state)
    cycle = int(memory.get("cycle") or 0)
    integrity = _data_integrity(state)
    backlogs = _backlogs(state)
    engine_health = _engine_health(memory)

    blockers: List[str] = []
    warnings: List[str] = []

    if not db_status.get("connected"):
        blockers.append("persistence_unhealthy")
    if persistence_result is False:
        blockers.append("cycle_persistence_failed")
    if integrity.get("critical"):
        blockers.append("critical_data_integrity")
    if any(x.get("critical") and x.get("status") in {"failed", "circuit_open"} for x in engine_health.get("engines", [])):
        blockers.append("critical_engine_unhealthy")
    if any(x.get("engine") in {"Communication Director", "Quality Gate"} and x.get("status") != "success" for x in engine_health.get("engines", [])):
        blockers.append("outbound_safety_engine_unhealthy")

    if backlogs.get("outbound_failed", 0):
        warnings.append("failed_outbound_requires_manual_delivery_check")
    if backlogs.get("verification_required", 0) >= 20:
        warnings.append("verification_backlog_high")
    if backlogs.get("pending_approvals", 0) >= 5:
        warnings.append("approval_backlog_high")
    if engine_health.get("circuits_open"):
        warnings.append("engine_circuit_breaker_active")

    outbound_allowed = bool(live_outbound) and not blockers
    if outbound_allowed:
        memory["outbound_block_streak"] = 0
    else:
        memory["outbound_block_streak"] = int(memory.get("outbound_block_streak") or 0) + 1

    recovery_actions = _recovery_actions(state, integrity, engine_health, backlogs)
    memory["recovery_queue"] = recovery_actions

    health_score = 100.0
    health_score -= min(45.0, len(blockers) * 18.0)
    health_score -= min(20.0, len(warnings) * 5.0)
    health_score -= min(20.0, integrity.get("high", 0) * 5.0)
    health_score -= min(15.0, len(engine_health.get("failed_now", [])) * 4.0)
    health_score = max(0.0, health_score)
    status = "healthy" if health_score >= 90 and not blockers else "degraded" if health_score >= 60 else "critical"

    if status == "healthy":
        memory["last_healthy_cycle"] = cycle
    else:
        memory["last_degraded_cycle"] = cycle

    guard = {
        "updated_at": utcnow(),
        "cycle": cycle,
        "status": status,
        "health_score": round(health_score, 1),
        "outbound_allowed": outbound_allowed,
        "live_outbound_requested": bool(live_outbound),
        "blockers": list(dict.fromkeys(blockers)),
        "warnings": list(dict.fromkeys(warnings)),
        "persistence_connected": bool(db_status.get("connected")),
    }
    state["operational_guard"] = guard

    directive = {
        "updated_at": utcnow(),
        "status": status,
        "priority": 100 if status == "critical" else 94 if status == "degraded" else 55,
        "recommended_action": recovery_actions[0].get("action") if recovery_actions else "continue_normal_operations",
        "reason": recovery_actions[0].get("reason") if recovery_actions else "Operación estable",
        "outbound_allowed": outbound_allowed,
    }
    state["operations_directive"] = directive

    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_coo_reliability_brain",
        "cycle": cycle,
        "status": status,
        "health_score": round(health_score, 1),
        "operational_guard": guard,
        "engine_health": engine_health,
        "data_integrity": integrity,
        "backlogs": backlogs,
        "recovery_actions": recovery_actions,
        "governance": {
            "engine_failure_isolation": True,
            "circuit_breaker_after_failures": FAILURE_THRESHOLD,
            "circuit_cooldown_cycles": CIRCUIT_COOLDOWN_CYCLES,
            "outbound_fail_closed": True,
            "ambiguous_send_failure_auto_retry": False,
            "persistence_failure_rule": "nunca continuar outbound si no existe persistencia confiable",
            "data_rule": "no borrar ni reescribir referencias ambiguas automáticamente; bloquear acción riesgosa y conservar evidencia",
        },
    }
    state["autonomous_coo"] = report

    cycle_entry = {
        "ts": utcnow(),
        "cycle": cycle,
        "status": status,
        "health_score": round(health_score, 1),
        "blockers": guard["blockers"],
        "warnings": guard["warnings"],
        "outbound_allowed": outbound_allowed,
    }
    memory["cycle_history"].append(cycle_entry)
    if len(memory["cycle_history"]) > MAX_CYCLE_HISTORY:
        del memory["cycle_history"][:-MAX_CYCLE_HISTORY]

    record_decision(
        state,
        engine="Autonomous COO",
        object_type="company",
        object_id="LUMEN",
        decision=f"operations_{status}",
        reason=(
            f"Health {health_score:.1f}; blockers: {', '.join(guard['blockers']) or 'none'}; "
            f"warnings: {', '.join(guard['warnings']) or 'none'}."
        ),
        action="score_opportunity",
        confidence=0.98 if status == "healthy" else 0.92,
        evidence_refs=[],
        allowed=not bool(blockers),
    )
    return report
