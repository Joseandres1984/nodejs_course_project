from __future__ import annotations

"""Process owner decisions for commercial close approvals.

The Decision Center writes commands to D1. This runtime consumes only commercial_close commands.
Approval reuses LUMEN's existing safe/simulated close routine: it records a simulated transaction
and expected revenue but does not execute a financial commitment, payment, purchase, or contract.
Rejection marks the approval rejected and removes the close from the pending human-decision queue.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

import app as lumen_app
import d1_persistence_runtime as d1
from commerce import approve_and_close

VERSION = "1.0-commercial-owner-decisions"
MAX_COMMANDS = 25
MAX_AUDIT = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(result: Any) -> List[Dict[str, Any]]:
    statements = d1._result_statements(result)
    if not statements:
        return []
    return d1._statement_rows(statements[0])


def _ensure_schema() -> None:
    d1._request({"batch": [
        {
            "sql": "CREATE TABLE IF NOT EXISTS lumen_owner_decision_commands (command_id TEXT PRIMARY KEY, decision_key TEXT NOT NULL UNIQUE, action TEXT NOT NULL, decision_type TEXT NOT NULL, object_id TEXT, actor TEXT NOT NULL, scope TEXT NOT NULL, payload_json TEXT, created_at TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT, result TEXT)",
            "params": [],
        },
        {
            "sql": "CREATE INDEX IF NOT EXISTS idx_lumen_owner_decision_pending ON lumen_owner_decision_commands(processed, created_at)",
            "params": [],
        },
    ]})


def _append_audit(state: Dict[str, Any], row: Dict[str, Any]) -> None:
    audit = state.get("commercial_owner_decisions")
    audit = list(audit or []) if isinstance(audit, list) else []
    key = str(row.get("decision_key") or "")
    audit = [x for x in audit if not (isinstance(x, dict) and str(x.get("decision_key") or "") == key)]
    audit.append(row)
    state["commercial_owner_decisions"] = audit[-MAX_AUDIT:]


def _reject_close(state: Dict[str, Any], approval: Dict[str, Any]) -> None:
    now = _now()
    approval["status"] = "rejected"
    approval["rejected_at"] = now
    approval["owner_decision"] = "reject"
    approval["owner_decided_at"] = now
    approval["financial_commitment_executed"] = False
    approval["actual_payment_executed"] = False
    approval["contract_executed"] = False

    deal_id = str(approval.get("deal_id") or "")
    deal = next((d for d in state.get("deals", []) if isinstance(d, dict) and str(d.get("id") or "") == deal_id), None)
    if deal:
        deal["stage"] = "cierre rechazado"
        deal["next_action"] = "Revisar condiciones antes de solicitar una nueva decisión de cierre"
        deal["owner_close_decision"] = "rejected"
        deal["owner_close_decided_at"] = now

    try:
        lumen_app.log(f"Owner desestimó el cierre de {deal_id or approval.get('id')}; no se ejecutó pago ni contrato real.")
    except Exception:
        pass


def consume_commands() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "version": VERSION,
        "status": "ok",
        "commands_seen": 0,
        "approved": 0,
        "rejected": 0,
        "stale": 0,
        "errors": 0,
        "scope": "COMMERCIAL_CLOSE_SIMULATED",
        "financial_commitment_executed": False,
        "actual_payment_executed": False,
        "contract_execution": False,
        "autonomous_spend_usd": 0,
        "updated_at": _now(),
    }
    try:
        _ensure_schema()
        result = d1._request({
            "sql": "SELECT command_id,decision_key,action,decision_type,object_id,actor,scope,payload_json,created_at FROM lumen_owner_decision_commands WHERE processed=0 AND decision_type='commercial_close' ORDER BY created_at ASC LIMIT ?",
            "params": [MAX_COMMANDS],
        })
        commands = _rows(result)
        report["commands_seen"] = len(commands)
        if not commands:
            print({"commercial_owner_decision_bridge": report}, flush=True)
            return report
        if not lumen_app.load_state():
            raise RuntimeError("state_unavailable")

        acknowledgements: List[tuple[str, str]] = []
        changed = False

        for command in commands:
            cid = str(command.get("command_id") or "")
            decision_key = str(command.get("decision_key") or "")
            action = str(command.get("action") or "").lower()
            decision_type = str(command.get("decision_type") or "")
            scope = str(command.get("scope") or "")
            approval_id = str(command.get("object_id") or "")
            result_label = "ignored"

            approval = next(
                (a for a in lumen_app.STATE.get("approvals", []) if isinstance(a, dict) and str(a.get("id") or "") == approval_id),
                None,
            )

            if decision_type != "commercial_close" or scope != "COMMERCIAL_CLOSE_SIMULATED" or action not in {"approve", "reject"}:
                result_label = "invalid_scope_or_action"
                report["stale"] += 1
            elif not approval:
                result_label = "approval_missing"
                report["stale"] += 1
            elif str(approval.get("status") or "").lower() != "pending":
                result_label = "approval_not_pending"
                report["stale"] += 1
            else:
                decided_at = _now()
                audit = {
                    "decision_key": decision_key,
                    "decision_type": "commercial_close",
                    "approval_id": approval_id,
                    "deal_id": approval.get("deal_id"),
                    "action": action,
                    "scope": "COMMERCIAL_CLOSE_SIMULATED",
                    "decided_at": decided_at,
                    "actor": "authenticated_dashboard_owner",
                    "financial_commitment_executed": False,
                    "actual_payment_executed": False,
                    "contract_executed": False,
                    "autonomous_spend_usd": 0,
                }

                if action == "approve":
                    txn = approve_and_close(lumen_app.STATE, approval_id)
                    if bool(txn.get("financial_commitment_executed")):
                        raise RuntimeError("unsafe_financial_commitment_detected")
                    approval["owner_decision"] = "approve"
                    approval["owner_decided_at"] = decided_at
                    approval["actual_payment_executed"] = False
                    approval["contract_executed"] = False
                    audit["transaction_id"] = txn.get("id")
                    audit["transaction_status"] = txn.get("status")
                    report["approved"] += 1
                    result_label = "approved_simulated_close_only"
                else:
                    _reject_close(lumen_app.STATE, approval)
                    report["rejected"] += 1
                    result_label = "rejected_no_execution"

                _append_audit(lumen_app.STATE, audit)
                changed = True

            acknowledgements.append((cid, result_label))

        lumen_app.STATE["commercial_owner_decision_center"] = report
        if changed and not lumen_app.save_state():
            raise RuntimeError("state_persistence_failed")

        for cid, label in acknowledgements:
            d1._request({
                "sql": "UPDATE lumen_owner_decision_commands SET processed=1, processed_at=?, result=? WHERE command_id=?",
                "params": [_now(), label, cid],
            })
    except Exception as exc:
        report["status"] = "degraded_fail_closed"
        report["errors"] += 1
        report["last_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"

    print({"commercial_owner_decision_bridge": report}, flush=True)
    return report
