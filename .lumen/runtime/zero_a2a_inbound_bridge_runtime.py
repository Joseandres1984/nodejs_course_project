from __future__ import annotations

"""Consume the public Cloudflare A2A inbox into canonical LUMEN state.

The edge Worker acknowledges non-binding A2A messages immediately and stores them in D1. This
bridge runs inside the normal LUMEN Zero cycle, applies the existing A2A commercial classifier,
creates only unverified research work, and writes the resulting task state back to D1 for polling.
It never promotes an external claim directly to a verified company/opportunity or binding deal.
"""

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

import app as lumen_app
import d1_persistence_runtime as d1
from a2a_inbound_bridge_runtime import process_inbound_record

VERSION = "1.0-zero-a2a-d1-bridge"
MAX_BATCH = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(result: Any) -> List[Dict[str, Any]]:
    statements = d1._result_statements(result)
    return d1._statement_rows(statements[0]) if statements else []


def _metadata(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(str(raw or "{}"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _safe_url(metadata: Dict[str, Any]) -> str:
    for key in ("website", "url", "companyUrl", "organizationUrl", "domain"):
        value = str(metadata.get(key) or "").strip()
        if not value:
            continue
        if value.startswith("https://") or value.startswith("http://"):
            return value[:500]
        if re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", value):
            return ("https://" + value)[:500]
    return ""


def _category(text: str) -> str:
    low = text.lower()
    groups = [
        ("bombas y válvulas", ("pump", "bomba", "valve", "válvula", "valvula")),
        ("instrumentación industrial", ("instrument", "sensor", "transmitter", "manometer", "manómetro", "manometro")),
        ("material eléctrico y electrónica", ("electrical", "eléctr", "electric", "cable", "contactor", "breaker", "connector")),
        ("repuestos y suministros industriales", ("spare", "repuesto", "bearing", "seal", "gasket", "filter", "ferreter")),
        ("logística y comercio exterior", ("logistic", "freight", "shipping", "incoterm", "import", "export", "aduana")),
    ]
    for label, tokens in groups:
        if any(token in low for token in tokens):
            return label
    return "general B2B"


def _ensure_research_lead(row: Dict[str, Any], outcome: Dict[str, Any], metadata: Dict[str, Any]) -> str | None:
    if outcome.get("status") != "candidate_unverified":
        return None
    inbound_id = str(row.get("id") or "")
    leads = lumen_app.STATE.setdefault("research_leads", [])
    existing = next((x for x in leads if str(x.get("a2a_inbound_id") or "") == inbound_id), None)
    if existing:
        return str(existing.get("id") or "") or None

    role = str(outcome.get("role_hint") or "unknown")
    if role not in {"buyer", "supplier"}:
        return None
    title = str(outcome.get("counterparty_hint") or metadata.get("organization") or metadata.get("company") or "A2A counterparty").strip()[:180]
    text = str(row.get("text") or "")[:8000]
    lead_id = f"LEAD-A2A-{len(leads)+1:05d}"
    leads.append({
        "id": lead_id,
        "type": role,
        "category": _category(text),
        "title": title,
        "url": _safe_url(metadata),
        "snippet": text[:900],
        "status": "research_required",
        "confidence": 0.84 if role == "buyer" else 0.78,
        "verified_company": False,
        "verified_contact": False,
        "source": "a2a_inbound",
        "source_kind": "external_agent_untrusted_until_verified",
        "a2a_inbound_id": inbound_id,
        "a2a_context_id": row.get("context_id"),
        "a2a_task_id": row.get("task_id"),
        "a2a_opportunity_id": outcome.get("opportunity_id"),
        "direct_inbound_demand": role == "buyer",
        "demand_signal": role == "buyer",
        "evidence_status": "external_agent_claim_unverified",
        "created_at": str(row.get("received_at") or _now()),
    })
    lumen_app.STATE["research_leads"] = leads[-2500:]
    return lead_id


def _task_json(raw: Any, outcome: Dict[str, Any], lead_id: str | None) -> str:
    try:
        task = json.loads(str(raw or "{}"))
        if not isinstance(task, dict):
            task = {}
    except Exception:
        task = {}
    metadata = task.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        task["metadata"] = metadata
    metadata.update({
        "bridgeStatus": outcome.get("status"),
        "priority": outcome.get("priority"),
        "priorityScore": outcome.get("priority_score"),
        "missingFields": list(outcome.get("missing_fields") or []),
        "opportunityId": outcome.get("opportunity_id"),
        "researchLeadId": lead_id,
        "verificationRequired": True,
        "bindingActionsHumanGated": True,
        "bridgeVersion": VERSION,
    })
    current_status = task.setdefault("status", {})
    if outcome.get("status") == "needs_clarification":
        current_status["state"] = "TASK_STATE_INPUT_REQUIRED"
    elif outcome.get("status") == "human_gate_required":
        current_status["state"] = "TASK_STATE_INPUT_REQUIRED"
    elif outcome.get("status") == "candidate_unverified":
        current_status["state"] = "TASK_STATE_WORKING"
    elif outcome.get("status") in {"handshake_or_noncommercial", "unclassified_nonbinding"}:
        current_status["state"] = "TASK_STATE_INPUT_REQUIRED"
    current_status["timestamp"] = _now()
    return json.dumps(task, ensure_ascii=False, separators=(",", ":"), default=str)


def ingest_pending() -> Dict[str, Any]:
    report = {"version": VERSION, "status": "ok", "pending_seen": 0, "processed": 0, "research_leads_created": 0, "clarifications": 0, "candidate_unverified": 0, "human_gates": 0, "errors": 0, "updated_at": _now()}
    try:
        d1._request({"batch": [
            {"sql": "CREATE TABLE IF NOT EXISTS lumen_a2a_inbound (id TEXT PRIMARY KEY, received_at TEXT NOT NULL, context_id TEXT NOT NULL, task_id TEXT NOT NULL, remote_message_id TEXT, remote_metadata TEXT, text TEXT NOT NULL, binding_intent INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT, bridge_status TEXT, opportunity_id TEXT, task_json TEXT NOT NULL)", "params": []},
            {"sql": "CREATE INDEX IF NOT EXISTS idx_lumen_a2a_pending ON lumen_a2a_inbound(processed,received_at)", "params": []},
        ]})
        result = d1._request({"sql": "SELECT id,received_at,context_id,task_id,remote_message_id,remote_metadata,text,binding_intent,status,task_json FROM lumen_a2a_inbound WHERE processed=0 ORDER BY received_at ASC LIMIT ?", "params": [MAX_BATCH]})
        pending = _rows(result)
        report["pending_seen"] = len(pending)
        if not pending:
            lumen_app.STATE["zero_a2a_inbound_bridge"] = report
            return report
        if not lumen_app.load_state():
            raise RuntimeError("state_unavailable")

        completed: list[dict[str, Any]] = []
        for row in pending:
            try:
                metadata = _metadata(row.get("remote_metadata"))
                record = {
                    "id": row.get("id"),
                    "received_at": row.get("received_at"),
                    "context_id": row.get("context_id"),
                    "task_id": row.get("task_id"),
                    "remote_message_id": row.get("remote_message_id"),
                    "remote_metadata": metadata,
                    "text": str(row.get("text") or "")[:8000],
                    "binding_intent_detected": bool(int(row.get("binding_intent") or 0)),
                    "status": row.get("status"),
                }
                outcome = process_inbound_record(lumen_app.STATE, record)
                lead_id = _ensure_research_lead(row, outcome, metadata)
                if lead_id:
                    report["research_leads_created"] += 1
                status = str(outcome.get("status") or "")
                if status == "needs_clarification": report["clarifications"] += 1
                if status == "candidate_unverified": report["candidate_unverified"] += 1
                if status == "human_gate_required": report["human_gates"] += 1
                completed.append({
                    "id": str(row.get("id") or ""),
                    "bridge_status": status,
                    "opportunity_id": str(outcome.get("opportunity_id") or ""),
                    "task_json": _task_json(row.get("task_json"), outcome, lead_id),
                })
                report["processed"] += 1
            except Exception:
                report["errors"] += 1

        lumen_app.STATE["zero_a2a_inbound_bridge"] = report
        if not lumen_app.save_state():
            raise RuntimeError("state_persistence_failed")
        if completed:
            batch = []
            for item in completed:
                batch.append({
                    "sql": "UPDATE lumen_a2a_inbound SET processed=1,processed_at=?,bridge_status=?,opportunity_id=?,task_json=? WHERE id=?",
                    "params": [_now(), item["bridge_status"], item["opportunity_id"], item["task_json"], item["id"]],
                })
            d1._request({"batch": batch})
    except Exception as exc:
        report["status"] = "degraded_fail_open"
        report["last_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        lumen_app.STATE["zero_a2a_inbound_bridge"] = report
    print({"zero_a2a_inbound_bridge": report}, flush=True)
    return report
