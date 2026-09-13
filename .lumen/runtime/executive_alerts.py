from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List


MAX_ALERTS = 120
MAX_CONTROL_RESOLUTIONS = 160


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


def _stable(prefix: str, value: Any) -> str:
    raw = f"{prefix}|{value}"
    return f"ALERT-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def _task_signature(task: Dict[str, Any]) -> str:
    payload = task.get("payload", {}) or {}
    evidence = payload.get("evidence", {}) if isinstance(payload, dict) else {}
    raw = {
        "key": task.get("key"),
        "kind": task.get("kind"),
        "title": task.get("title"),
        "reason": task.get("reason"),
        "priority_score": task.get("priority_score"),
        "code": payload.get("code") if isinstance(payload, dict) else None,
        "evidence": evidence,
    }
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:24]


def _upsert(alerts: Dict[str, Dict[str, Any]], *, key: str, severity: str, kind: str,
            title: str, message: str, action_required: bool, recommendation: str,
            object_type: str | None = None, object_id: str | None = None,
            approval_id: str | None = None, metrics: Dict[str, Any] | None = None) -> Dict[str, Any]:
    alert_id = _stable(kind, key)
    now = utcnow()
    alert = alerts.setdefault(alert_id, {
        "id": alert_id,
        "key": key,
        "kind": kind,
        "first_seen_at": now,
        "status": "open",
        "seen": False,
    })
    alert.update({
        "severity": severity,
        "title": title,
        "message": message,
        "action_required": bool(action_required),
        "recommendation": recommendation,
        "object_type": object_type,
        "object_id": object_id,
        "approval_id": approval_id,
        "metrics": metrics or {},
        "last_seen_at": now,
        "status": "open",
        "resolved_at": None,
    })
    return alert


def _resolution_store(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = state.setdefault("executive_control_resolutions", {})
    if not isinstance(raw, dict):
        raw = {}
        state["executive_control_resolutions"] = raw
    if len(raw) > MAX_CONTROL_RESOLUTIONS:
        rows = sorted(raw.items(), key=lambda item: str((item[1] or {}).get("resolved_at") or ""), reverse=True)
        state["executive_control_resolutions"] = dict(rows[:MAX_CONTROL_RESOLUTIONS])
        raw = state["executive_control_resolutions"]
    return raw


def _append_activity(state: Dict[str, Any], message: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": message})
    state["activity"] = state.get("activity", [])[:100]


def _controller_horizon_fix(state: Dict[str, Any], *, signature: str, source: str) -> Dict[str, Any]:
    memory = state.setdefault("business_controller_memory", {})
    active = memory.get("active_intervention")
    if not isinstance(active, dict) or active.get("status") != "running":
        return {"applied": False, "reason": "no_running_controller_intervention"}

    cycle = _i(memory.get("cycle"))
    started = _i(active.get("started_cycle"), cycle)
    old_hold = _i(active.get("hold_until_cycle"), cycle)
    # Extend the current evaluation window without widening financial, contractual or outbound authority.
    new_hold = max(old_hold + 8, started + 16, cycle + 8)
    new_hold = min(new_hold, cycle + 24)
    if new_hold <= old_hold:
        return {"applied": False, "reason": "controller_horizon_already_extended", "old_hold": old_hold, "new_hold": old_hold}

    active["hold_until_cycle"] = new_hold
    active["evaluation_horizon_adjusted"] = True
    active["evaluation_horizon_adjusted_at"] = utcnow()
    active["evaluation_horizon_adjustment_source"] = source
    memory["active_intervention"] = active

    row = {
        "ts": utcnow(),
        "signature": signature,
        "intervention_id": active.get("id"),
        "cycle": cycle,
        "old_hold_until_cycle": old_hold,
        "new_hold_until_cycle": new_hold,
        "extension_cycles": new_hold - old_hold,
        "source": source,
    }
    state.setdefault("controller_horizon_adjustments", []).append(row)
    state["controller_horizon_adjustments"] = state["controller_horizon_adjustments"][-40:]
    _append_activity(
        state,
        f"LUMEN amplió automáticamente el horizonte de evaluación del Controller para {active.get('id') or 'la intervención activa'}: ciclo {old_hold} → {new_hold}. No cambió autoridad, gasto ni límites de salida.",
    )
    return {"applied": True, **row}


def _record_resolution(state: Dict[str, Any], signature: str, *, alert_id: str | None,
                       task_key: str | None, action: str, details: Dict[str, Any] | None = None) -> Dict[str, Any]:
    row = {
        "signature": signature,
        "alert_id": alert_id,
        "task_key": task_key,
        "action": action,
        "status": "resolved",
        "resolved_at": utcnow(),
        "details": details or {},
    }
    _resolution_store(state)[signature] = row
    return row


def resolve_executive_alert(state: Dict[str, Any], alert_id: str, action: str) -> Dict[str, Any]:
    alert = next((x for x in state.get("executive_alerts", []) or [] if str(x.get("id")) == str(alert_id)), None)
    if not alert:
        raise ValueError("Alerta inexistente")
    if alert.get("status") != "open":
        raise ValueError("La alerta ya fue resuelta")

    action = str(action or "").strip().lower()
    if action == "recheck":
        alert["seen"] = False
        alert["last_manual_recheck_at"] = utcnow()
        return {"ok": True, "action": "recheck", "alert_id": alert_id}

    if alert.get("kind") != "human_control":
        raise ValueError("Esta alerta no admite descarte manual; solo puede reevaluarse o desaparecer al resolver su causa")

    metrics = alert.get("metrics", {}) or {}
    signature = str(metrics.get("task_signature") or "")
    task_key = str(metrics.get("task_key") or alert.get("key") or "")
    if not signature:
        raise ValueError("La alerta no contiene una firma de control válida")

    if action == "apply":
        if not metrics.get("auto_action_available"):
            raise ValueError("Esta alerta requiere una decisión humana específica y no admite corrección automática")
        result = _controller_horizon_fix(state, signature=signature, source="executive_cockpit")
        if not result.get("applied"):
            raise ValueError("No hay una intervención activa del Controller que pueda ajustarse ahora")
        resolution = _record_resolution(state, signature, alert_id=alert_id, task_key=task_key, action="auto_fix_applied", details=result)
    elif action == "snooze":
        resolution = _record_resolution(
            state, signature, alert_id=alert_id, task_key=task_key, action="snoozed_until_signal_changes",
            details={"rule": "La misma señal queda silenciada; reaparecerá si cambia la evidencia que la originó."},
        )
        _append_activity(state, f"Panel de Aprobaciones pospuso la señal {alert.get('title') or alert_id}; reaparecerá si cambia la evidencia.")
    else:
        raise ValueError("Acción inválida; usar apply, snooze o recheck")

    alert["status"] = "resolved"
    alert["resolved_at"] = utcnow()
    alert["resolution_action"] = resolution.get("action")
    return {"ok": True, "alert_id": alert_id, "resolution": resolution}


def executive_alert_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    existing = {
        str(x.get("id")): x
        for x in state.setdefault("executive_alerts", [])
        if x.get("id")
    }
    active_ids: set[str] = set()
    approvals = {str(x.get("id")): x for x in state.get("approvals", []) if x.get("id")}
    resolutions = _resolution_store(state)

    # 1) Binding approvals: only a still-pending real approval may interrupt the executive.
    for brief in state.get("approval_briefs", []) or []:
        if brief.get("status") != "human_decision_required":
            continue
        approval_id = str(brief.get("approval_id") or "")
        deal_id = str(brief.get("deal_id") or "")
        approval = approvals.get(approval_id)
        if not approval_id or not approval or approval.get("status") != "pending":
            continue
        missing = list(brief.get("preclose_missing") or [])
        profit = _f(brief.get("company_profit"))
        margin = _f(brief.get("company_share_pct"))
        close_prob = _f(brief.get("close_probability"))
        if close_prob <= 1:
            close_prob *= 100
        ready = not missing
        alert = _upsert(
            existing,
            key=approval_id,
            severity="critical" if ready else "high",
            kind="binding_approval",
            title=f"Decisión de cierre — {deal_id or approval_id}",
            message=(
                f"Beneficio estimado USD {profit:,.0f}; margen {margin:.1f}%; probabilidad de cierre {close_prob:.0f}%. "
                + ("Todos los controles previos reportados están completos." if ready else f"Todavía faltan controles: {', '.join(str(x) for x in missing[:6])}.")
            ),
            action_required=True,
            recommendation=(
                "Aprobar solo si la documentación y términos visibles coinciden con lo esperado; la aprobación no ejecuta pagos ni compromisos financieros reales."
                if ready else
                "No aprobar todavía. Completar los controles faltantes y volver a presentar el caso."
            ),
            object_type="deal",
            object_id=deal_id,
            approval_id=approval_id,
            metrics={
                "company_profit": profit,
                "company_share_pct": margin,
                "close_probability_pct": close_prob,
                "sale_price": brief.get("sale_price"),
                "supplier_cost": brief.get("supplier_cost"),
                "preclose_missing": missing,
                "risk_flags": list(brief.get("risk_flags") or []),
                "ready_to_decide": ready,
            },
        )
        active_ids.add(alert["id"])

    # 2) Critical operations failures. These should interrupt expansion/commercial execution.
    coo = state.get("autonomous_coo", {}) or (state.get("connector_telemetry", {}) or {}).get("autonomous_coo", {}) or {}
    guard = coo.get("operational_guard", {}) or {}
    for blocker in list(guard.get("blockers", []) or [])[:12]:
        text = str(blocker)
        alert = _upsert(
            existing,
            key=text,
            severity="critical",
            kind="operational_blocker",
            title="LUMEN requiere recuperación operativa",
            message=text,
            action_required=True,
            recommendation="Mantener outbound bloqueado y resolver la causa antes de reanudar ejecución comercial.",
            object_type="system",
            object_id="autonomous_coo",
            metrics={"manual_recheck_available": True},
        )
        active_ids.add(alert["id"])

    failures = list((coo.get("engine_health", {}) or {}).get("failed_now", []) or [])
    for failure in failures[:10]:
        text = str(failure)
        alert = _upsert(
            existing,
            key=text,
            severity="high",
            kind="engine_failure",
            title="Motor degradado",
            message=text,
            action_required=False,
            recommendation="Autonomous COO mantiene aislamiento/circuit breaker; escalar solo si el fallo persiste o afecta salida comercial.",
            object_type="engine",
            object_id=text[:120],
            metrics={"manual_recheck_available": True},
        )
        active_ids.add(alert["id"])

    # 3) High-authority tasks from Professional OS not already represented by an approval.
    for task in state.get("operating_action_queue", []) or []:
        if task.get("autonomous", True):
            continue
        object_id = str(task.get("object_id") or "")
        if task.get("kind") == "human_approval":
            continue
        priority = _f(task.get("priority_score"))
        if priority < 70:
            continue
        key = str(task.get("key") or f"{task.get('kind')}|{object_id}")
        signature = _task_signature(task)
        if signature in resolutions:
            continue

        payload = task.get("payload", {}) or {}
        code = str(payload.get("code") or "") if isinstance(payload, dict) else ""
        auto_action_available = key == "self_improvement|CTRL-HORIZON" or code == "CTRL-HORIZON"

        # This specific recommendation is bounded and reversible: extend only the current Controller
        # evaluation window. It does not widen spending, contracting, payment or outbound authority.
        if auto_action_available:
            auto_result = _controller_horizon_fix(state, signature=signature, source="executive_alert_autoremediation")
            if auto_result.get("applied"):
                _record_resolution(
                    state, signature, alert_id=None, task_key=key,
                    action="auto_fix_applied", details=auto_result,
                )
                resolutions = _resolution_store(state)
                continue

        alert = _upsert(
            existing,
            key=key,
            severity="high" if priority >= 90 else "medium",
            kind="human_control",
            title=str(task.get("title") or "Control humano requerido"),
            message=str(task.get("reason") or "La política de autonomía requiere intervención humana."),
            action_required=True,
            recommendation=(
                "LUMEN puede aplicar un ajuste reversible del horizonte de evaluación y volver a medir el resultado."
                if auto_action_available else
                "Resolver el control indicado; LUMEN debe continuar autónomamente con el resto del portfolio."
            ),
            object_type=str(task.get("object_type") or "task"),
            object_id=object_id,
            metrics={
                "priority_score": priority,
                "task_key": key,
                "task_signature": signature,
                "task_kind": task.get("kind"),
                "task_code": code,
                "auto_action_available": bool(auto_action_available),
            },
        )
        active_ids.add(alert["id"])

    # Resolve alerts whose triggering condition disappeared. Keep history for auditability.
    for alert_id, alert in existing.items():
        if alert_id not in active_ids and alert.get("status") == "open":
            alert["status"] = "resolved"
            alert["resolved_at"] = utcnow()

    rows = sorted(
        existing.values(),
        key=lambda x: (
            1 if x.get("status") == "open" else 0,
            {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(x.get("severity")), 0),
            str(x.get("last_seen_at") or ""),
        ),
        reverse=True,
    )[:MAX_ALERTS]
    state["executive_alerts"] = rows

    open_alerts = [x for x in rows if x.get("status") == "open"]
    unseen = [x for x in open_alerts if not x.get("seen")]
    report = {
        "updated_at": utcnow(),
        "open": len(open_alerts),
        "unseen": len(unseen),
        "critical": sum(1 for x in open_alerts if x.get("severity") == "critical"),
        "action_required": sum(1 for x in open_alerts if x.get("action_required")),
        "top": open_alerts[:8],
    }
    state["executive_alert_report"] = report
    return report


def mark_alerts_seen(state: Dict[str, Any]) -> int:
    changed = 0
    for alert in state.get("executive_alerts", []) or []:
        if alert.get("status") == "open" and not alert.get("seen"):
            alert["seen"] = True
            alert["seen_at"] = utcnow()
            changed += 1
    return changed


def reject_approval(state: Dict[str, Any], approval_id: str, reason: str = "Rechazado por dirección") -> Dict[str, Any]:
    approval = next((x for x in state.get("approvals", []) if str(x.get("id")) == str(approval_id)), None)
    if not approval:
        raise ValueError("Aprobación inexistente")
    if approval.get("status") != "pending":
        raise ValueError("La aprobación ya fue procesada")
    approval["status"] = "rejected"
    approval["rejected_at"] = utcnow()
    approval["rejection_reason"] = str(reason)[:500]
    deal = next((x for x in state.get("deals", []) if x.get("id") == approval.get("deal_id")), None)
    if deal:
        deal["stage"] = "revisión ejecutiva"
        deal["next_action"] = "Revisar economía, términos o riesgos antes de volver a solicitar autorización"
        deal.setdefault("executive_decisions", []).append({
            "ts": utcnow(), "decision": "rejected", "approval_id": approval_id, "reason": str(reason)[:500]
        })
    return approval
