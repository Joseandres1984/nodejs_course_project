from __future__ import annotations

from typing import Any, Dict, List

import a2a_gateway_runtime as _gateway
from a2a_inbound_bridge_runtime import process_inbound_record as _base_process


VERSION = "1.0-a2a-multiturn-commercial-memory"
MAX_CONTEXT_MESSAGES = 8
MAX_COMBINED_TEXT = 12000


def _same_context(row: Dict[str, Any], record: Dict[str, Any]) -> bool:
    context_id = str(record.get("context_id") or "")
    task_id = str(record.get("task_id") or "")
    if context_id and str(row.get("context_id") or "") == context_id:
        return True
    if task_id and str(row.get("task_id") or "") == task_id:
        return True
    return False


def _merged_metadata(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for row in rows:
        metadata = row.get("remote_metadata")
        if isinstance(metadata, dict):
            for key, value in metadata.items():
                if value not in (None, "", [], {}):
                    merged[key] = value
    return merged


def process_inbound_record_multiturn(state: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
    network = state.setdefault("agent_network", {})
    inbound = [x for x in (network.get("inbound") or []) if isinstance(x, dict)]
    context_rows = [x for x in inbound if _same_context(x, record)][-MAX_CONTEXT_MESSAGES:]

    if not any(str(x.get("id") or "") == str(record.get("id") or "") for x in context_rows):
        context_rows.append(record)
        context_rows = context_rows[-MAX_CONTEXT_MESSAGES:]

    combined_parts: List[str] = []
    for row in context_rows:
        text = " ".join(str(row.get("text") or "").split())
        if text:
            combined_parts.append(text)
    combined_text = " | ".join(combined_parts)[:MAX_COMBINED_TEXT]

    enriched = dict(record)
    enriched["text"] = combined_text or str(record.get("text") or "")
    enriched["remote_metadata"] = _merged_metadata(context_rows) or record.get("remote_metadata") or {}
    enriched["conversation_turns"] = len(context_rows)
    enriched["multiturn_context_applied"] = len(context_rows) > 1

    result = dict(_base_process(state, enriched) or {})
    result["conversation_turns"] = len(context_rows)
    result["multiturn_context_applied"] = len(context_rows) > 1

    metrics = network.setdefault("inbound_bridge_metrics", {})
    metrics["multiturn_memory_version"] = VERSION
    metrics["last_conversation_turns"] = len(context_rows)
    if len(context_rows) > 1:
        metrics["multiturn_messages_total"] = int(metrics.get("multiturn_messages_total") or 0) + 1
    if result.get("status") == "candidate_unverified":
        metrics["commercial_candidates_from_a2a"] = int(metrics.get("commercial_candidates_from_a2a") or 0) + 1
    network["last_multiturn_result"] = result
    return result


# The FastAPI route resolves this module global at request time, so replacing it here
# upgrades classification without redefining the public A2A endpoint.
_gateway.process_inbound_record = process_inbound_record_multiturn

print({
    "a2a_inbound_accelerator_runtime": {
        "version": VERSION,
        "status": "active",
        "max_context_messages": MAX_CONTEXT_MESSAGES,
        "binding_authority_changed": False,
        "canonical_deal_auto_promotion": False,
        "external_content_untrusted": True,
    }
}, flush=True)
