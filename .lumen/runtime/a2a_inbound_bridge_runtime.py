from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List


VERSION = "1.0-a2a-inbound-commercial-bridge"
MAX_PROCESSED = 300
MAX_OPPORTUNITIES = 120
MAX_CLARIFICATIONS = 120

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
    metrics.setdefault("version", VERSION)
    metrics.setdefault("processed_total", 0)
    metrics.setdefault("candidates_created_total", 0)
    metrics.setdefault("clarifications_total", 0)
    metrics.setdefault("human_gate_total", 0)
    metrics.setdefault("handshake_only_total", 0)
    metrics.setdefault("verified_opportunities", 0)
    return metrics


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

    base = {
        "source": "a2a_inbound",
        "inbound_id": inbound_id,
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

    if binding:
        metrics["human_gate_total"] = int(metrics.get("human_gate_total") or 0) + 1
        network["last_inbound_bridge"] = {**base, "status": "human_gate_required", "processed_at": utcnow()}
        return {"version": VERSION, "status": "human_gate_required", "inbound_id": inbound_id}

    if _generic_handshake(text) or (role == "unknown" and not product_signal):
        metrics["handshake_only_total"] = int(metrics.get("handshake_only_total") or 0) + 1
        network["last_inbound_bridge"] = {**base, "status": "handshake_or_noncommercial", "processed_at": utcnow()}
        return {"version": VERSION, "status": "handshake_or_noncommercial", "inbound_id": inbound_id}

    # Buyer requirements are not promoted to a commercial candidate until the minimum
    # sourcing packet exists. Missing facts become a clarification queue item instead.
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
        row = {
            "id": f"A2ACL-{uuid.uuid4().hex[:12].upper()}",
            **base,
            "status": "needs_clarification",
            "missing_fields": missing,
            "created_at": utcnow(),
        }
        clarifications.append(row)
        del clarifications[:-MAX_CLARIFICATIONS]
        metrics["clarifications_total"] = int(metrics.get("clarifications_total") or 0) + 1
        network["last_inbound_bridge"] = row
        return {"version": VERSION, "status": "needs_clarification", "inbound_id": inbound_id, "missing_fields": missing}

    # Supplier capability messages can become candidates with identity + a real product signal;
    # they are still unverified and never create a canonical deal by themselves.
    if role == "supplier" and (not product_signal or not counterparty):
        missing = []
        if not product_signal:
            missing.append("product_or_capability_scope")
        if not counterparty:
            missing.append("counterparty_identity")
        row = {
            "id": f"A2ACL-{uuid.uuid4().hex[:12].upper()}",
            **base,
            "status": "needs_clarification",
            "missing_fields": missing,
            "created_at": utcnow(),
        }
        clarifications.append(row)
        del clarifications[:-MAX_CLARIFICATIONS]
        metrics["clarifications_total"] = int(metrics.get("clarifications_total") or 0) + 1
        network["last_inbound_bridge"] = row
        return {"version": VERSION, "status": "needs_clarification", "inbound_id": inbound_id, "missing_fields": missing}

    if role not in {"buyer", "supplier"}:
        metrics["handshake_only_total"] = int(metrics.get("handshake_only_total") or 0) + 1
        network["last_inbound_bridge"] = {**base, "status": "unclassified_nonbinding", "processed_at": utcnow()}
        return {"version": VERSION, "status": "unclassified_nonbinding", "inbound_id": inbound_id}

    opportunity = {
        "id": f"A2AOP-{uuid.uuid4().hex[:12].upper()}",
        **base,
        "opportunity_kind": "buyer_requirement" if role == "buyer" else "supplier_capability",
        "status": "candidate_unverified",
        "canonical_deal": False,
        "verified_opportunity": False,
        "next_action": "verify_counterparty_and_evidence_before_commercial_promotion",
        "created_at": utcnow(),
    }
    opportunities.append(opportunity)
    del opportunities[:-MAX_OPPORTUNITIES]
    metrics["candidates_created_total"] = int(metrics.get("candidates_created_total") or 0) + 1
    network["last_inbound_bridge"] = opportunity
    network["inbound_bridge_updated_at"] = utcnow()
    return {
        "version": VERSION,
        "status": "candidate_unverified",
        "inbound_id": inbound_id,
        "opportunity_id": opportunity["id"],
        "opportunity_kind": opportunity["opportunity_kind"],
        "verification_required": True,
    }


print({
    "a2a_inbound_bridge_runtime": {
        "version": VERSION,
        "status": "loaded",
        "external_content_untrusted": True,
        "canonical_deal_auto_promotion": False,
        "binding_actions_human_gated": True,
    }
}, flush=True)
