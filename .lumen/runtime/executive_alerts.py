from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List


MAX_ALERTS = 120


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stable(prefix: str, value: Any) -> str:
    raw = f"{prefix}|{value}"
    return f"ALERT-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


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


def executive_alert_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    existing = {
        str(x.get("id")): x
        for x in state.setdefault("executive_alerts", [])
        if x.get("id")
    }
    active_ids: set[str] = set()

    deals = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}

    # 1) Binding approvals: these are the highest-value human interruptions.
    for brief in state.get("approval_briefs", []) or []:
        if brief.get("status") != "human_decision_required":
            continue
        approval_id = str(brief.get("approval_id") or "")
        deal_id = str(brief.get("deal_id") or "")
        if not approval_id:
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
        alert = _upsert(
            existing,
            key=key,
            severity="high" if priority >= 90 else "medium",
            kind="human_control",
            title=str(task.get("title") or "Control humano requerido"),
            message=str(task.get("reason") or "La política de autonomía requiere intervención humana."),
            action_required=True,
            recommendation="Resolver el control indicado; LUMEN debe continuar autónomamente con el resto del portfolio.",
            object_type=str(task.get("object_type") or "task"),
            object_id=object_id,
            metrics={"priority_score": priority},
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
