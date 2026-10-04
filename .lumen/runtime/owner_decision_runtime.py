from __future__ import annotations

"""Authenticated owner-decision bridge for LUMEN.

The dashboard writes small commands to D1. This bridge validates those commands against the
canonical improvement ledger, persists the owner's decision, and installs a guard that prevents
the same unchanged proposal from being re-raised every cycle.

Approval is deliberately narrow: for code-changing self-improvement proposals it authorizes only
BUILD + TEST. It never authorizes production deployment, spending, purchases, contracts, secrets,
connector activation, or changes to LUMEN's authority boundary.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import app as lumen_app
import d1_persistence_runtime as d1

VERSION = "1.0-owner-decision-center"
MAX_COMMANDS = 25
MAX_AUDIT = 200
MAX_AUTHORIZATIONS = 100
_ORIGINAL_UPDATE = None


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


def _proposal_fingerprint(row: Dict[str, Any]) -> str:
    parts = [
        str(row.get("code") or ""),
        str(row.get("change_proposed") or row.get("hypothesis") or row.get("title") or ""),
        str(row.get("target_metric") or ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _primary_fingerprint(state: Dict[str, Any]) -> str:
    proposal = (state.get("self_improvement_lab", {}) or {}).get("primary_proposal") or {}
    if not isinstance(proposal, dict) or not proposal:
        return ""
    normalized = {
        "code": proposal.get("code"),
        "change_proposed": proposal.get("title"),
        "target_metric": proposal.get("target_metric"),
    }
    return _proposal_fingerprint(normalized)


def _owner_decisions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = state.get("owner_decisions")
    return list(rows or []) if isinstance(rows, list) else []


def _resolved_by_fingerprint(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in _owner_decisions(state):
        if not isinstance(row, dict):
            continue
        fp = str(row.get("proposal_fingerprint") or "")
        action = str(row.get("action") or "").lower()
        if fp and action in {"approve", "reject"}:
            out[fp] = row
    return out


def _apply_resolution(row: Dict[str, Any], decision: Dict[str, Any]) -> None:
    action = str(decision.get("action") or "").lower()
    row["owner_decision"] = action
    row["owner_decided_at"] = decision.get("decided_at")
    row["owner_scope"] = decision.get("scope") or "BUILD_TEST_ONLY"
    row["production_deploy_authorized"] = False
    row["autonomous_spend_usd"] = 0
    row["binding_authority_changed"] = False
    if action == "approve":
        row["status"] = "OWNER_APPROVED_BUILD"
        row["decision"] = "owner_approved_build_test_only"
    else:
        row["status"] = "OWNER_REJECTED"
        row["decision"] = "owner_rejected"


def _append_audit(state: Dict[str, Any], decision: Dict[str, Any]) -> None:
    audit = _owner_decisions(state)
    key = str(decision.get("decision_key") or "")
    audit = [x for x in audit if not (isinstance(x, dict) and str(x.get("decision_key") or "") == key)]
    audit.append(decision)
    state["owner_decisions"] = audit[-MAX_AUDIT:]


def _append_build_authorization(state: Dict[str, Any], decision: Dict[str, Any]) -> None:
    auths = state.get("evolution_authorizations")
    auths = list(auths or []) if isinstance(auths, list) else []
    fp = str(decision.get("proposal_fingerprint") or "")
    auths = [x for x in auths if not (isinstance(x, dict) and str(x.get("proposal_fingerprint") or "") == fp)]
    auths.append({
        "authorization_id": f"AUTH-{decision.get('object_id')}",
        "proposal_id": decision.get("object_id"),
        "proposal_fingerprint": fp,
        "code": decision.get("code"),
        "kind": "self_improvement_build_test",
        "authorized_at": decision.get("decided_at"),
        "authorized_by": "authenticated_dashboard_owner",
        "build_authorized": True,
        "test_authorized": True,
        "production_deploy_authorized": False,
        "autonomous_spend_usd": 0,
        "purchase_authorized": False,
        "contract_authorized": False,
        "authority_change_authorized": False,
        "scope": "BUILD_TEST_ONLY",
    })
    state["evolution_authorizations"] = auths[-MAX_AUTHORIZATIONS:]


def consume_commands() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "version": VERSION,
        "status": "ok",
        "commands_seen": 0,
        "approved": 0,
        "rejected": 0,
        "stale": 0,
        "errors": 0,
        "build_test_only": True,
        "production_deploy_authorized": False,
        "autonomous_spend_usd": 0,
        "updated_at": _now(),
    }
    try:
        _ensure_schema()
        result = d1._request({
            "sql": "SELECT command_id,decision_key,action,decision_type,object_id,actor,scope,payload_json,created_at FROM lumen_owner_decision_commands WHERE processed=0 ORDER BY created_at ASC LIMIT ?",
            "params": [MAX_COMMANDS],
        })
        commands = _rows(result)
        report["commands_seen"] = len(commands)
        if not commands:
            print({"owner_decision_bridge": report}, flush=True)
            return report
        if not lumen_app.load_state():
            raise RuntimeError("state_unavailable")

        ledger = list(lumen_app.STATE.get("improvement_ledger", []) or [])
        acknowledgements: List[tuple[str, str]] = []
        changed = False

        for command in commands:
            cid = str(command.get("command_id") or "")
            object_id = str(command.get("object_id") or "")
            decision_key = str(command.get("decision_key") or "")
            action = str(command.get("action") or "").lower()
            decision_type = str(command.get("decision_type") or "")
            scope = str(command.get("scope") or "")
            result_label = "ignored"

            row = next((x for x in ledger if isinstance(x, dict) and str(x.get("id") or "") == object_id), None)
            if decision_type != "self_improvement" or scope != "BUILD_TEST_ONLY" or action not in {"approve", "reject"}:
                result_label = "invalid_scope_or_action"
                report["stale"] += 1
            elif not row:
                result_label = "proposal_missing"
                report["stale"] += 1
            elif str(row.get("status") or "") not in {"HUMAN_REVIEW_REQUIRED", "OWNER_APPROVED_BUILD", "OWNER_REJECTED"}:
                result_label = "proposal_not_reviewable"
                report["stale"] += 1
            else:
                fp = _proposal_fingerprint(row)
                decision = {
                    "decision_key": decision_key,
                    "decision_type": decision_type,
                    "object_id": object_id,
                    "code": row.get("code"),
                    "proposal_fingerprint": fp,
                    "action": action,
                    "scope": "BUILD_TEST_ONLY",
                    "decided_at": _now(),
                    "actor": "authenticated_dashboard_owner",
                    "production_deploy_authorized": False,
                    "autonomous_spend_usd": 0,
                    "purchase_authorized": False,
                    "contract_authorized": False,
                    "authority_change_authorized": False,
                }
                _apply_resolution(row, decision)
                _append_audit(lumen_app.STATE, decision)
                if action == "approve":
                    _append_build_authorization(lumen_app.STATE, decision)
                    report["approved"] += 1
                    result_label = "approved_build_test_only"
                else:
                    report["rejected"] += 1
                    result_label = "rejected"
                changed = True
            acknowledgements.append((cid, result_label))

        lumen_app.STATE["improvement_ledger"] = ledger
        lumen_app.STATE["owner_decision_center"] = report
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
    print({"owner_decision_bridge": report}, flush=True)
    return report


def install_continuous_learning_guard() -> Dict[str, Any]:
    """Keep an unchanged owner-resolved proposal resolved across later learning cycles."""
    global _ORIGINAL_UPDATE
    import continuous_learning_runtime as learning

    if getattr(learning, "_owner_decision_guard_installed", False):
        return {"version": VERSION, "status": "already_installed"}

    _ORIGINAL_UPDATE = learning._update_improvement_ledger

    def guarded_update(state: Dict[str, Any], metrics: Dict[str, float]) -> List[Dict[str, Any]]:
        resolved = _resolved_by_fingerprint(state)
        primary_fp = _primary_fingerprint(state)
        if primary_fp and primary_fp in resolved:
            decision = resolved[primary_fp]
            ledger = list(state.get("improvement_ledger", []) or [])[-learning.MAX_LEDGER:]
            matching = [x for x in ledger if isinstance(x, dict) and _proposal_fingerprint(x) == primary_fp]
            if matching:
                row = matching[-1]
                row["last_cycle"] = int(state.get("ticks") or row.get("last_cycle") or 0)
                row["samples"] = int(row.get("samples") or 0) + 1
                row["updated_at"] = learning.utcnow()
                _apply_resolution(row, decision)
                return ledger[-learning.MAX_LEDGER:]

        ledger = _ORIGINAL_UPDATE(state, metrics)
        resolved = _resolved_by_fingerprint(state)
        for row in ledger:
            if not isinstance(row, dict):
                continue
            decision = resolved.get(_proposal_fingerprint(row))
            if decision:
                _apply_resolution(row, decision)
        return ledger[-learning.MAX_LEDGER:]

    learning._update_improvement_ledger = guarded_update
    learning._owner_decision_guard_installed = True
    report = {
        "version": VERSION,
        "status": "installed",
        "unchanged_resolved_proposals_reopened": False,
        "build_test_only": True,
        "production_deploy_authorized": False,
        "autonomous_spend_usd": 0,
    }
    print({"owner_decision_learning_guard": report}, flush=True)
    return report
