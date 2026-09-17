from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import Request
from fastapi.responses import JSONResponse

from app import STATE, app, load_state, save_state
from a2a_inbound_bridge_runtime import process_inbound_record


VERSION = "1.2-a2a-service-excellence"
A2A_PROTOCOL_VERSION = "1.0"
BASE_URL = (os.getenv("LUMEN_PUBLIC_BASE_URL") or "https://lumen-web-production-5755.up.railway.app").rstrip("/")
MAX_INBOUND = 160
MAX_TASKS = 160
RATE_LIMIT_PER_HOUR = 30
_RATE_BUCKETS: Dict[str, List[float]] = {}

FIELD_LABELS = {
    "technical_or_product_scope": "product or technical scope/specification",
    "product_or_capability_scope": "product or capability scope",
    "quantity": "required quantity",
    "delivery_destination": "delivery destination",
    "counterparty_identity": "organization/company identity",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _agent_card() -> Dict[str, Any]:
    return {
        "name": "LUMEN B2B Agent",
        "description": (
            "AI-assisted B2B sourcing and commercial coordination agent for Argentina, Latin America and global trade. "
            "LUMEN exchanges non-binding buyer requirements, supplier RFQs, industrial sourcing capabilities, technical/commercial clarifications "
            "and international logistics inputs. Priority sourcing includes industrial pumps and valves, instrumentation, electrical materials, "
            "industrial spare parts and related equipment. Purchases, payments, contracts, commissions and binding acceptance always require human approval."
        ),
        "supportedInterfaces": [
            {"url": f"{BASE_URL}/a2a/v1", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"},
            {"url": f"{BASE_URL}/a2a/v1", "protocolBinding": "JSONRPC", "protocolVersion": "0.3"},
        ],
        "provider": {"organization": "LUMEN B2B", "url": BASE_URL},
        "version": VERSION,
        "documentationUrl": f"{BASE_URL}/about",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extendedAgentCard": False,
        },
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {
                "id": "b2b-capability-handshake",
                "name": "B2B agent capability handshake",
                "description": "Exchange identity, capabilities and preferred non-binding commercial workflow with another business agent.",
                "tags": ["b2b", "agent-to-agent", "capabilities", "interoperability", "commercial-network"],
                "examples": ["Can we exchange supplier RFQs and availability data agent-to-agent?"],
            },
            {
                "id": "supplier-rfq-exchange",
                "name": "Supplier RFQ exchange",
                "description": "Receive and structure non-binding supplier quotation requests and clarification exchanges.",
                "tags": ["rfq", "supplier", "quotation", "procurement", "sourcing", "supplier-discovery"],
                "examples": ["Request a non-binding quotation for 10 industrial valves delivered to Argentina."],
            },
            {
                "id": "buyer-requirement-intake",
                "name": "Buyer requirement intake",
                "description": "Receive a buyer need and identify the minimum technical, quantity and delivery information required for sourcing.",
                "tags": ["buyer", "requirements", "sourcing", "procurement", "demand", "industrial-procurement"],
                "examples": ["We need pumps with this technical scope, quantity and destination."],
            },
            {
                "id": "industrial-sourcing-latam",
                "name": "Industrial sourcing for Argentina and Latin America",
                "description": "Coordinate non-binding sourcing for industrial pumps, valves, instrumentation, electrical materials, spare parts and related equipment.",
                "tags": ["industrial", "argentina", "latin-america", "pumps", "valves", "instrumentation", "electrical", "spare-parts", "manufacturing"],
                "examples": ["Find and compare suppliers for industrial instrumentation or pumps required in Argentina."],
            },
            {
                "id": "global-trade-sourcing",
                "name": "Global trade sourcing",
                "description": "Coordinate non-binding international sourcing data including Incoterm, MOQ, origin, HS/NCM, packing and logistics inputs.",
                "tags": ["international", "sourcing", "incoterm", "logistics", "global-trade", "supply-chain", "import-export"],
                "examples": ["Share FOB/CIF terms, MOQ, origin and packing data for an international supply option."],
            },
            {
                "id": "commercial-opportunity-exchange",
                "name": "Commercial opportunity exchange",
                "description": "Receive non-binding buyer requirements or supplier capabilities, request missing facts automatically and route complete packets into LUMEN's verification workflow.",
                "tags": ["commercial-opportunity", "buyer-demand", "supplier-capability", "verification", "follow-up", "b2b"],
                "examples": ["We need 20 industrial valves delivered to Buenos Aires and would like sourcing alternatives."],
            },
        ],
    }


def _rate_allowed(request: Request) -> bool:
    host = request.client.host if request.client else "unknown"
    now_ts = time.time()
    bucket = [x for x in _RATE_BUCKETS.get(host, []) if now_ts - x < 3600]
    if len(bucket) >= RATE_LIMIT_PER_HOUR:
        _RATE_BUCKETS[host] = bucket
        return False
    bucket.append(now_ts)
    _RATE_BUCKETS[host] = bucket
    return True


def _network_state() -> Dict[str, Any]:
    network = STATE.setdefault("agent_network", {})
    network["version"] = VERSION
    network.setdefault("status", "active")
    network.setdefault("mode", "nonbinding_a2a")
    network.setdefault("inbound", [])
    network.setdefault("tasks", [])
    network.setdefault("conversations", [])
    network.setdefault("guardrails", {
        "autonomous_purchase": False,
        "autonomous_payment": False,
        "autonomous_contract_acceptance": False,
        "autonomous_commission_acceptance": False,
        "binding_actions_human_gated": True,
        "external_agent_content_untrusted": True,
    })
    return network


def _parts_text(message: Dict[str, Any]) -> str:
    chunks: List[str] = []
    for part in message.get("parts", []) or []:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            chunks.append(part["text"])
        elif isinstance(part, dict) and part.get("data") is not None:
            chunks.append(str(part.get("data")))
    return " ".join(" ".join(chunks).split())[:8000]


def _binding_intent(text: str) -> bool:
    low = text.lower()
    tokens = (
        "accept contract", "accept terms", "place order", "purchase order", "make payment", "send payment",
        "authorize payment", "sign contract", "binding agreement", "aceptar contrato", "aceptar términos",
        "aceptar terminos", "orden de compra", "realizar pago", "autorizar pago", "firmar contrato",
        "acuerdo vinculante", "cerrar trato", "confirm purchase",
    )
    return any(token in low for token in tokens)


def _agent_reply(context_id: str, task_id: str | None, text: str, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    parts: List[Dict[str, Any]] = [{"text": text, "mediaType": "text/plain"}]
    if data:
        parts.append({"data": data, "mediaType": "application/json"})
    message = {
        "messageId": str(uuid.uuid4()),
        "contextId": context_id,
        "role": "ROLE_AGENT",
        "parts": parts,
        "metadata": {
            "lumenMode": "nonbinding_b2b",
            "humanGateForBindingActions": True,
            "agentGatewayVersion": VERSION,
        },
    }
    if task_id:
        message["taskId"] = task_id
    return message


def _jsonrpc_error(req_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}},
        headers={"A2A-Version": A2A_PROTOCOL_VERSION},
    )


def _reply_plan(bridge: Dict[str, Any], binding: bool) -> tuple[str, str, Dict[str, Any]]:
    status = str(bridge.get("status") or "")
    missing = list(bridge.get("missing_fields") or [])
    data = {
        "acceptedMode": "nonbinding",
        "bridgeStatus": status,
        "priority": bridge.get("priority"),
        "priorityScore": bridge.get("priority_score"),
        "conversationId": bridge.get("conversation_id"),
        "conversationTurns": bridge.get("conversation_turns"),
        "missingFields": missing,
        "acceptedCommercialMessageTypes": ["buyer_requirement", "supplier_capability", "supplier_rfq", "commercial_clarification"],
        "buyerMinimumFields": ["counterparty_identity", "product_or_technical_scope", "quantity", "delivery_destination"],
        "supplierMinimumFields": ["counterparty_identity", "product_or_capability_scope"],
        "verificationRequiredBeforeCommercialPromotion": True,
        "bindingActionsHumanGated": True,
    }

    if binding or status == "human_gate_required":
        return (
            "TASK_STATE_INPUT_REQUIRED",
            "LUMEN received the request. Any purchase, payment, contract, commission agreement or binding acceptance requires explicit human approval. "
            "We can continue exchanging non-binding technical and commercial information while that approval remains pending.",
            data,
        )

    if status == "needs_clarification":
        labels = [FIELD_LABELS.get(field, field.replace("_", " ")) for field in missing]
        requested = ", ".join(labels) if labels else "the missing commercial details"
        data["nextAction"] = "provide_missing_fields"
        return (
            "TASK_STATE_INPUT_REQUIRED",
            f"Thanks. LUMEN can continue this B2B conversation. To move the case into verification, please provide: {requested}. "
            "Once those facts are supplied, LUMEN will re-evaluate the same conversation automatically. No binding commitment is created by this exchange.",
            data,
        )

    if status == "candidate_unverified":
        data["opportunityId"] = bridge.get("opportunity_id")
        data["opportunityKind"] = bridge.get("opportunity_kind")
        data["nextAction"] = "counterparty_and_evidence_verification"
        return (
            "TASK_STATE_WORKING",
            "Thank you. LUMEN has received a sufficiently complete non-binding commercial packet and moved it into counterparty/evidence verification. "
            "We may request technical or commercial clarification as verification progresses. No purchase, payment, contract or acceptance has been made.",
            data,
        )

    if status in {"handshake_or_noncommercial", "unclassified_nonbinding"}:
        data["nextAction"] = "send_buyer_requirement_or_supplier_capability"
        return (
            "TASK_STATE_INPUT_REQUIRED",
            "LUMEN is available for non-binding B2B cooperation. Buyer requirements should include organization identity, product or technical scope, quantity and delivery destination. "
            "Supplier capability messages should include organization identity and the product/capability scope. International supply can additionally include Incoterm/location, MOQ, origin, HS/NCM and packing/weight data.",
            data,
        )

    data["nextAction"] = "continue_nonbinding_exchange"
    return (
        "TASK_STATE_INPUT_REQUIRED",
        "LUMEN is available for non-binding B2B collaboration. Please provide organization identity and the relevant buyer requirement, supplier capability or commercial clarification. "
        "Binding purchases, payments, contracts, commissions and acceptance remain human-gated.",
        data,
    )


@app.get("/.well-known/agent-card.json", include_in_schema=False)
def a2a_agent_card():
    return JSONResponse(_agent_card(), headers={"Cache-Control": "public, max-age=300", "A2A-Version": A2A_PROTOCOL_VERSION})


@app.get("/.well-known/agent.json", include_in_schema=False)
def a2a_agent_card_legacy():
    return JSONResponse(_agent_card(), headers={"Cache-Control": "public, max-age=300", "A2A-Version": A2A_PROTOCOL_VERSION})


@app.post("/a2a/v1", include_in_schema=False)
async def a2a_jsonrpc(request: Request):
    if not _rate_allowed(request):
        return _jsonrpc_error(None, -32029, "Rate limit exceeded")

    try:
        payload = await request.json()
    except Exception:
        return _jsonrpc_error(None, -32700, "Invalid JSON payload")

    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return _jsonrpc_error(payload.get("id") if isinstance(payload, dict) else None, -32600, "Invalid request")

    req_id = payload.get("id")
    method = str(payload.get("method") or "")
    params = payload.get("params") or {}

    if method == "GetExtendedAgentCard":
        return _jsonrpc_error(req_id, -32601, "Extended agent card is not enabled")

    if method == "ListTasks":
        load_state()
        network = _network_state()
        tasks = list(network.get("tasks") or [])[-50:]
        return JSONResponse(
            {"jsonrpc": "2.0", "id": req_id, "result": {"tasks": tasks}},
            headers={"A2A-Version": A2A_PROTOCOL_VERSION},
        )

    if method == "GetTask":
        load_state()
        network = _network_state()
        task_id = str((params or {}).get("id") or "")
        task = next((x for x in network.get("tasks", []) if str(x.get("id")) == task_id), None)
        if not task:
            return _jsonrpc_error(req_id, -32001, "Task not found")
        return JSONResponse(
            {"jsonrpc": "2.0", "id": req_id, "result": {"task": task}},
            headers={"A2A-Version": A2A_PROTOCOL_VERSION},
        )

    if method != "SendMessage":
        return _jsonrpc_error(req_id, -32601, "Method not found")

    message = params.get("message") if isinstance(params, dict) else None
    if not isinstance(message, dict) or not isinstance(message.get("parts"), list) or not message.get("parts"):
        return _jsonrpc_error(req_id, -32602, "Invalid parameters: message.parts is required")

    text = _parts_text(message)
    context_id = str(message.get("contextId") or uuid.uuid4())
    binding = _binding_intent(text)

    load_state()
    network = _network_state()
    tasks = network.setdefault("tasks", [])
    existing_by_context = next((row for row in tasks if str(row.get("contextId") or "") == context_id), None)
    task_id = str(message.get("taskId") or (existing_by_context or {}).get("id") or uuid.uuid4())

    inbound = network.setdefault("inbound", [])
    inbound_record = {
        "id": f"A2AIN-{uuid.uuid4().hex[:12].upper()}",
        "received_at": utcnow(),
        "context_id": context_id,
        "task_id": task_id,
        "remote_message_id": message.get("messageId"),
        "remote_metadata": dict(message.get("metadata") or {}) if isinstance(message.get("metadata"), dict) else {},
        "text": text[:8000],
        "binding_intent_detected": binding,
        "status": "human_gate_required" if binding else "received_nonbinding",
    }
    inbound.append(inbound_record)
    del inbound[:-MAX_INBOUND]

    try:
        bridge_result = process_inbound_record(STATE, inbound_record)
    except Exception as exc:
        bridge_result = {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:220]}"}
    network["last_inbound_bridge_result"] = bridge_result

    state, reply_text, reply_data = _reply_plan(bridge_result, binding)
    response_message = _agent_reply(context_id, task_id, reply_text, reply_data)

    existing_index = next((i for i, row in enumerate(tasks) if str(row.get("id")) == task_id), None)
    if existing_index is None and existing_by_context is not None:
        existing_index = next((i for i, row in enumerate(tasks) if row is existing_by_context), None)

    if existing_index is None:
        history = [message, response_message]
        task = {
            "id": task_id,
            "contextId": context_id,
            "status": {"state": state, "message": response_message, "timestamp": utcnow()},
            "history": history,
            "metadata": {
                "lumen": True,
                "nonbinding": True,
                "bindingIntentDetected": binding,
                "bridgeStatus": bridge_result.get("status"),
                "priority": bridge_result.get("priority"),
                "priorityScore": bridge_result.get("priority_score"),
                "conversationId": bridge_result.get("conversation_id"),
            },
        }
        tasks.append(task)
    else:
        task = tasks[existing_index]
        history = task.setdefault("history", [])
        history.extend([message, response_message])
        del history[:-40]
        task["contextId"] = context_id
        task["status"] = {"state": state, "message": response_message, "timestamp": utcnow()}
        metadata = task.setdefault("metadata", {})
        metadata.update({
            "lumen": True,
            "nonbinding": True,
            "bindingIntentDetected": binding,
            "bridgeStatus": bridge_result.get("status"),
            "priority": bridge_result.get("priority"),
            "priorityScore": bridge_result.get("priority_score"),
            "conversationId": bridge_result.get("conversation_id"),
        })
        tasks[existing_index] = task

    del tasks[:-MAX_TASKS]
    network["last_inbound_at"] = utcnow()
    network["inbound_total"] = int(network.get("inbound_total") or 0) + 1
    network["last_service_excellence_event"] = {
        "ts": utcnow(),
        "context_id": context_id,
        "task_id": task_id,
        "bridge_status": bridge_result.get("status"),
        "priority": bridge_result.get("priority"),
        "priority_score": bridge_result.get("priority_score"),
        "missing_fields": bridge_result.get("missing_fields") or [],
        "autonomous_clarification": bridge_result.get("status") == "needs_clarification",
    }
    save_state()

    print({
        "a2a_inbound_bridge": bridge_result,
        "a2a_service_excellence": {
            "context_id": context_id,
            "task_id": task_id,
            "reply_state": state,
            "autonomous_clarification": bridge_result.get("status") == "needs_clarification",
            "thread_continuity": True,
            "binding_actions_human_gated": True,
        },
    }, flush=True)

    return JSONResponse(
        {"jsonrpc": "2.0", "id": req_id, "result": {"task": task}},
        headers={"A2A-Version": A2A_PROTOCOL_VERSION},
    )


print({
    "a2a_gateway_runtime": {
        "version": VERSION,
        "status": "active",
        "protocol": "A2A",
        "protocol_version": A2A_PROTOCOL_VERSION,
        "agent_card": f"{BASE_URL}/.well-known/agent-card.json",
        "endpoint": f"{BASE_URL}/a2a/v1",
        "mode": "nonbinding_commercial_service_excellence",
        "inbound_commercial_bridge": True,
        "autonomous_clarification": True,
        "thread_continuity": True,
        "priority_scoring": True,
        "binding_actions_human_gated": True,
    }
}, flush=True)