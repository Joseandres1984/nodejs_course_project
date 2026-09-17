from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List


VERSION = "1.1-a2a-inbound-commercial-orchestrator"
MAX_PROCESSED = 400
MAX_OPPORTUNITIES = 160
MAX_CLARIFICATIONS = 160
MAX_CONVERSATIONS = 160

BUYER_TOKENS = (
    "we need", "we require", "looking for", "request quote", "request a quote", "rfq", "procure", "purchase requirement",
    "need quotation", "source for", "buscamos", "necesitamos", "requerimos", "solicitud de cotización", "solicitud de cotizacion",
    "cotizar", "requerimiento", "comprar",
)
SUPPLIER_TOKENS = (
    "we supply", "we manufacture", "we offer", "manufacturer", "distributor", "available stock", "our catalog", "our catalogue",
    "supplier", "proveemos", "fabricamos", "ofrecemos", "distribuidor", "fabricante", "stock disponible", "catálogo", "catalogo",
)
GENERIC_HANDSHAKE_TOKENS = (
    "capability handshake", "agent-to-agent cooperation", "agent to agent cooperation", "can your agent exchange",
    "what can you do", "your capabilities", "interoperability", "hello agent", "hello. we are",
)
PRODUCT_TOKENS = (
    "valve", "válvula", "valvula", "pump", "bomba", "instrument", "instrumentación", "instrumentacion", "sensor", "transmitter",
    "manometer", "manómetro", "manometro", "motor", "generator", "electrical", "eléctrico", "electrico", "contactor", "breaker",
    "bearing", "seal", "gasket", "filter", "cable", "connector", "industrial", "spare", "repuesto", "equipment", "equipo",
    "material", "component", "part", "pieza",
)
QUANTITY_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(units?|pcs?|pieces?|ea|unidades?|uds?|u\.?|sets?|lotes?|kg|kgs|meters?|metres?|metros?)\b", re.I)
DESTINATION_RE = re.compile(
    r"(?:deliver(?:y|ed)?\s+(?:to|in)|ship(?:ped|ping)?\s+to|destination\s*[:=-]?|entrega(?:r)?\s+(?:en|a)|destino\s*[:=-]?)\s*([^.;\n]{2,100})",
    re.I,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _counterparty_hint(record: Dict[str, Any]) -> str:
    metadata = record.get("remote_metadata") if isinstance(record.get("remote_metadata"), dict) else {}
    for key in ("organization", "company", "supplierCompany", "buyerCompany", "agentName", "sender", "provider"):
        value = _clean(metadata.get(key), 180)
        if value and value.lower() not in {"lumen", "lumen b2b", "lumen b2b agent"}:
            return value
    return ""


def _role(text: str) -> str:
    low = text.lower()
    buyer = sum(1 for token in BUYER_TOKENS if token in low)
    supplier = sum(1 for token in SUPPLIER_TOKENS if token in low)
    if buyer > supplier and buyer:
        return "buyer"
    if supplier > buyer and supplier:
        return "supplier"
    return "unknown"


def _generic_handshake(text: str) -> bool:
    low = text.lower()
    return any(token in low for token in GENERIC_HANDSHAKE_TOKENS) and not any(token in low for token in PRODUCT_TOKENS)


def _quantity(text: str) -> str:
    match = QUANTITY_RE.search(text)
    return _clean(match.group(0), 80) if match else ""


def _destination(text: str) -> str:
    match = DESTINATION_RE.search(text)
    return _clean(match.group(1), 120) if match else ""


def _product_signal(text: str) -> bool:
    low = text.lower()
    return any(token in low for token in PRODUCT_TOKENS)


def _metrics(network: Dict[str, Any]) -> Dict[str, Any]:
    metrics = network.setdefault("inbound_bridge_metrics", {})
    metrics["version"] = VERSION
    metrics.setdefault("processed_total", 0)
    metrics.setdefault("candidates_created_total", 0)
    metrics.setdefault("clarifications_total", 0)
    metrics.setdefault("human_gate_total", 0)
    metrics.setdefault("handshake_only_total", 0)
    metrics.setdefault("verified_opportunities", 0)
    metrics.setdefault("conversations_total", 0)
    metrics.setdefault("commercial_messages_total", 0)
    return metrics


def _priority_score(*, role: str, product_signal: bool, quantity: str, destination: str, counterparty: str, binding: bool, status: str) -> int:
    if binding or status == "human_gate_required":
        return 100
    score = 15
    if role == "buyer":
        score += 25
    elif role == "supplier":
        score += 15
    if product_signal:
        score += 15
    if counterparty:
        score += 15
    if quantity:
        score += 10
    if destination:
        score += 10
    if status == "candidate_unverified":
        score += 10
    return min(99, score)


def _priority_label(score: int) -> str:
    if score >= 85:
        return "urgent"
    if score >= 65:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _upsert_conversation(network: Dict[str, Any], record: Dict[str, Any], outcome: Dict[str, Any]) -> Dict[str, Any]:
    conversations: List[Dict[str, Any]] = network.setdefault("conversations", [])
    context_id = _clean(record.get("context_id"), 160) or _clean(record.get("task_id"), 160)
    task_id = _clean(record.get("task_id"), 160)
    existing = next((row for row in conversations if row.get("context_id") == context_id), None)
    if existing is None:
        existing = {
            "id": f"A2ACONV-{uuid.uuid4().hex[:12].upper()}",
            "context_id": context_id,
            "task_id": task_id or None,
            "created_at": record.get("received_at") or utcnow(),
            "turns": 0,
            "commercial_turns": 0,
            "status_history": [],
        }
        conversations.append(existing)
        del conversations[:-MAX_CONVERSATIONS]
        _metrics(network)["conversations_total"] = int(_metrics(network).get("conversations_total") or 0) + 1

    existing["task_id"] = task_id or existing.get("task_id")
    existing["last_seen_at"] = record.get("received_at") or utcnow()
    existing["turns"] = int(existing.get("turns") or 0) + 1
    existing["latest_status"] = outcome.get("status")
    existing["role_hint"] = outcome.get("role_hint")
    existing["counterparty_hint"] = outcome.get("counterparty_hint")
    existing["missing_fields"] = list(outcome.get("missing_fields") or [])
    existing["priority_score"] = int(outcome.get("priority_score") or 0)
    existing["priority"] = outcome.get("priority")
    existing["opportunity_id"] = outcome.get("opportunity_id") or existing.get("opportunity_id")
    if outcome.get("status") in {"needs_clarification", "candidate_unverified", "human_gate_required"}:
        existing["commercial_turns"] = int(existing.get("commercial_turns") or 0) + 1
    history = existing.setdefault("status_history", [])
    history.append({"ts": utcnow(), "status": outcome.get("status"), "inbound_id": outcome.get("inbound_id")})
    del history[:-20]
    return existing


def _upsert_clarification(clarifications: List[Dict[str, Any]], row: Dict[str, Any]) -> None:
    context_id = row.get("context_id")
    existing = next((item for item in clarifications if item.get("context_id") == context_id and item.get("status") == "needs_clarification"), None)
    if existing:
        existing.update(row)
        existing["updated_at"] = utcnow()
    else:
        clarifications.append(row)
    del clarifications[:-MAX_CLARIFICATIONS]


def _upsert_opportunity(opportunities: List[Dict[str, Any]], row: Dict[str, Any]) -> bool:
    context_id = row.get("context_id")
    existing = next((item for item in opportunities if item.get("context_id") == context_id and item.get("status") == "candidate_unverified"), None)
    if existing:
        existing.update(row)
        existing["updated_at"] = utcnow()
        row["id"] = existing.get("id")
        return False
    opportunities.append(row)
    del opportunities[:-MAX_OPPORTUNITIES]
    return True


def process_inbound_record(state: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
    network = state.setdefault("agent_network", {})
    processed: List[str] = network.setdefault("processed_inbound_ids", [])
    opportunities: List[Dict[str, Any]] = network.setdefault("opportunities", [])
    clarifications: List[Dict[str, Any]] = network.setdefault("clarification_queue", [])
    metrics = _metrics(network)

    inbound_id = _clean(record.get("id"), 100)
    if not inbound_id or inbound_id in processed:
        return {"version": VERSION, "status": "already_processed", "inbound_id": inbound_id}

    processed.append(inbound_id)
    del processed[:-MAX_PROCESSED]
    metrics["processed_total"] = int(metrics.get("processed_total") or 0) + 1

    text = _clean(record.get("text"), 8000)
    counterparty = _counterparty_hint(record)
    role = _role(text)
    quantity = _quantity(text)
    destination = _destination(text)
    product_signal = _product_signal(text)
    binding = bool(record.get("binding_intent_detected"))
    context_id = _clean(record.get("context_id"), 160)
    task_id = _clean(record.get("task_id"), 160)

    base = {
        "source": "a2a_inbound",
        "inbound_id": inbound_id,
        "context_id": context_id or None,
        "task_id": task_id or None,
        "received_at": record.get("received_at") or utcnow(),
        "counterparty_hint": counterparty or None,
        "role_hint": role,
        "quantity_hint": quantity or None,
        "delivery_hint": destination or None,
        "summary": text[:1200],
        "external_content_untrusted": True,
        "verification_required": True,
        "binding": binding,
    }

    def finalize(result: Dict[str, Any]) -> Dict[str, Any]:
        score = _priority_score(
            role=role,
            product_signal=product_signal,
            quantity=quantity,
            destination=destination,
            counterparty=counterparty,
            binding=binding,
            status=str(result.get("status") or ""),
        )
        result["version"] = VERSION
        result["inbound_id"] = inbound_id
        result["role_hint"] = role
        result["counterparty_hint"] = counterparty or None
        result["priority_score"] = score
        result["priority"] = _priority_label(score)
        conversation = _upsert_conversation(network, record, result)
        result["conversation_id"] = conversation.get("id")
        result["conversation_turns"] = conversation.get("turns")
        network["last_inbound_bridge_result"] = result
        network["inbound_bridge_updated_at"] = utcnow()
        return result

    if binding:
        metrics["human_gate_total"] = int(metrics.get("human_gate_total") or 0) + 1
        result = finalize({"status": "human_gate_required", "missing_fields": []})
        network["last_inbound_bridge"] = {**base, **result, "processed_at": utcnow()}
        return result

    if _generic_handshake(text) or (role == "unknown" and not product_signal):
        metrics["handshake_only_total"] = int(metrics.get("handshake_only_total") or 0) + 1
        result = finalize({"status": "handshake_or_noncommercial", "missing_fields": []})
        network["last_inbound_bridge"] = {**base, **result, "processed_at": utcnow()}
        return result

    metrics["commercial_messages_total"] = int(metrics.get("commercial_messages_total") or 0) + 1

    if role == "buyer" and (not product_signal or not quantity or not destination or not counterparty):
        missing = []
        if not product_signal:
            missing.append("technical_or_product_scope")
        if not quantity:
            missing.append("quantity")
        if not destination:
            missing.append("delivery_destination")
        if not counterparty:
            missing.append("counterparty_identity")
        result = finalize({"status": "needs_clarification", "missing_fields": missing})
        row = {
            "id": f"A2ACL-{uuid.uuid4().hex[:12].upper()}",
            **base,
            **result,
            "created_at": utcnow(),
        }
        _upsert_clarification(clarifications, row)
        metrics["clarifications_total"] = int(metrics.get("clarifications_total") or 0) + 1
        network["last_inbound_bridge"] = row
        return result

    if role == "supplier" and (not product_signal or not counterparty):
        missing = []
        if not product_signal:
            missing.append("product_or_capability_scope")
        if not counterparty:
            missing.append("counterparty_identity")
        result = finalize({"status": "needs_clarification", "missing_fields": missing})
        row = {
            "id": f"A2ACL-{uuid.uuid4().hex[:12].upper()}",
            **base,
            **result,
            "created_at": utcnow(),
        }
        _upsert_clarification(clarifications, row)
        metrics["clarifications_total"] = int(metrics.get("clarifications_total") or 0) + 1
        network["last_inbound_bridge"] = row
        return result

    if role not in {"buyer", "supplier"}:
        metrics["handshake_only_total"] = int(metrics.get("handshake_only_total") or 0) + 1
        result = finalize({"status": "unclassified_nonbinding", "missing_fields": []})
        network["last_inbound_bridge"] = {**base, **result, "processed_at": utcnow()}
        return result

    opportunity_id = f"A2AOP-{uuid.uuid4().hex[:12].upper()}"
    result = finalize({
        "status": "candidate_unverified",
        "missing_fields": [],
        "opportunity_id": opportunity_id,
        "opportunity_kind": "buyer_requirement" if role == "buyer" else "supplier_capability",
        "verification_required": True,
    })
    opportunity = {
        "id": opportunity_id,
        **base,
        **result,
        "status": "candidate_unverified",
        "canonical_deal": False,
        "verified_opportunity": False,
        "next_action": "verify_counterparty_and_evidence_before_commercial_promotion",
        "created_at": utcnow(),
    }
    created = _upsert_opportunity(opportunities, opportunity)
    result["opportunity_id"] = opportunity.get("id")
    if created:
        metrics["candidates_created_total"] = int(metrics.get("candidates_created_total") or 0) + 1
    network["last_inbound_bridge"] = opportunity
    return result


print({
    "a2a_inbound_bridge_runtime": {
        "version": VERSION,
        "status": "loaded",
        "conversation_tracking": True,
        "priority_scoring": True,
        "clarification_deduplication": True,
        "external_content_untrusted": True,
        "canonical_deal_auto_promotion": False,
        "binding_actions_human_gated": True,
    }
}, flush=True)