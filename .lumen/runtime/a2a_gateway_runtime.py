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


VERSION = "1.1-a2a-commercial-gateway"
A2A_PROTOCOL_VERSION = "1.0"
BASE_URL = (os.getenv("LUMEN_PUBLIC_BASE_URL") or "https://lumen-web-production-5755.up.railway.app").rstrip("/")
MAX_INBOUND = 120
MAX_TASKS = 120
RATE_LIMIT_PER_HOUR = 30
_RATE_BUCKETS: Dict[str, List[float]] = {}


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
                "description": "Receive non-binding buyer requirements or supplier capabilities and route sufficiently detailed messages into LUMEN's verification workflow.",
                "tags": ["commercial-opportunity", "buyer-demand", "supplier-capability", "verification", "b2b"],
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
    network.setdefault("version", VERSION)
    network.setdefault("status", "active")
    network.setdefault("mode", "nonbinding_a2a")
    network.setdefault("inbound", [])
    network.setdefault("tasks", [])
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
    task_id = str(message.get("taskId") or uuid.uuid4())
    binding = _binding_intent(text)

    load_state()
    network = _network_state()
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

    if binding:
        state = "TASK_STATE_INPUT_REQUIRED"
        reply_text = (
            "LUMEN received the request, but any purchase, payment, contract, commission agreement or binding acceptance "
            "requires explicit human approval. We can continue exchanging non-binding technical and commercial information meanwhile."
        )
    else:
        state = "TASK_STATE_INPUT_REQUIRED"
        reply_text = (
            "LUMEN is available for non-binding B2B collaboration. For a buyer sourcing/RFQ exchange, please include your organization, product or technical scope, "
            "quantity and delivery destination. Supplier capability messages should include organization identity and the product/capability scope. "
            "For international supply, Incoterm/location, MOQ, country of origin, HS/NCM if known and packing/weight data are also useful. "
            "Binding purchases, payments, contracts, commissions and acceptance of commercial terms remain human-gated."
        )

    response_message = _agent_reply(
        context_id,
        task_id,
        reply_text,
        {
            "acceptedMode": "nonbinding",
            "acceptedCommercialMessageTypes": ["buyer_requirement", "supplier_capability", "supplier_rfq", "commercial_clarification"],
            "buyerMinimumFields": ["counterparty_identity", "product_or_technical_scope", "quantity", "delivery_destination"],
            "supplierMinimumFields": ["counterparty_identity", "product_or_capability_scope"],
            "skills": ["supplier-rfq-exchange", "buyer-requirement-intake", "industrial-sourcing-latam", "global-trade-sourcing", "commercial-opportunity-exchange"],
            "verificationRequiredBeforeCommercialPromotion": True,
            "bindingActionsHumanGated": True,
        },
    )
    task = {
        "id": task_id,
        "contextId": context_id,
        "status": {"state": state, "message": response_message, "timestamp": utcnow()},
        "history": [message, response_message],
        "metadata": {"lumen": True, "nonbinding": True, "bindingIntentDetected": binding},
    }
    tasks = network.setdefault("tasks", [])
    existing = next((i for i, row in enumerate(tasks) if str(row.get("id")) == task_id), None)
    if existing is None:
        tasks.append(task)
    else:
        tasks[existing] = task
    del tasks[:-MAX_TASKS]
    network["last_inbound_at"] = utcnow()
    network["inbound_total"] = int(network.get("inbound_total") or 0) + 1
    save_state()

    try:
        bridge_result = process_inbound_record(STATE, inbound_record)
        network["last_inbound_bridge_result"] = bridge_result
        save_state()
        print({"a2a_inbound_bridge": bridge_result}, flush=True)
    except Exception as exc:
        network["last_inbound_bridge_result"] = {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:220]}"}
        save_state()
        print({"a2a_inbound_bridge": network["last_inbound_bridge_result"]}, flush=True)

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
        "mode": "nonbinding_commercial_discovery",
        "inbound_commercial_bridge": True,
        "binding_actions_human_gated": True,
    }
}, flush=True)
