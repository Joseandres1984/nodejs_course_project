from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import agent_network_runtime as _base
import agent_network_accelerator_runtime as _accelerator

VERSION = "1.0-global-a2a-sales-loop"
MAX_FOLLOWUPS_PER_TICK = 1
MAX_FOLLOWUP_HISTORY = 100
MIN_BUYER_INTENT_SCORE = 25
MACHINE_CATALOG_URL = "https://lumen-zero-a2a.lumen-b2b.workers.dev/machine/catalog"
SERVICE_CATALOG_URL = "https://lumen-zero-a2a.lumen-b2b.workers.dev/seller/catalog"

# High-intent public registry discovery only. The existing runtime/workflow caps still decide how
# many queries and handshakes may run in a cycle; this list does not increase those caps.
GLOBAL_HIGH_INTENT_QUERIES = (
    "buyer",
    "procurement",
    "rfq",
    "sourcing",
    "supplier discovery",
    "tender",
    "market intelligence",
    "due diligence",
    "x402",
)

_ORIGINAL_TICK = _base.agent_network_tick


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _card_text(card: Dict[str, Any]) -> str:
    parts = [str(card.get("name") or ""), str(card.get("description") or "")]
    for skill in _safe_list(card.get("skills")):
        if not isinstance(skill, dict):
            continue
        parts.extend([
            str(skill.get("name") or ""),
            str(skill.get("description") or ""),
            " ".join(str(x) for x in _safe_list(skill.get("tags"))),
        ])
    return " ".join(parts).lower()


def _product_fit(card: Dict[str, Any]) -> Tuple[str, str]:
    text = _card_text(card)
    rules = (
        (("rfq", "quotation", "quote", "pricing"), "quote_review", "quotation review and comparison"),
        (("tender", "bid", "procurement"), "tender_intelligence", "tender and procurement intelligence"),
        (("supplier verification", "vendor verification", "due diligence", "verify supplier"), "supplier_verification", "supplier verification and due diligence"),
        (("sourcing", "supplier discovery", "supply chain"), "supplier_sourcing", "supplier sourcing"),
        (("buyer", "lead", "prospect", "sales intelligence"), "buyer_signals", "buyer and commercial-intent signals"),
        (("export", "international trade", "market research", "market intelligence"), "market_intelligence", "market and export intelligence"),
    )
    for tokens, code, label in rules:
        if any(token in text for token in tokens):
            return code, label
    return "market_intelligence", "market and B2B intelligence"


def _eligible_card(card: Dict[str, Any]) -> bool:
    if not card:
        return False
    if card.get("securityRequirements") or card.get("securitySchemes"):
        return False
    interface = next(
        (x for x in _safe_list(card.get("supportedInterfaces")) if isinstance(x, dict) and x.get("protocolBinding") == "JSONRPC"),
        None,
    )
    return bool(interface)


def _followup_payload(card: Dict[str, Any], source_domain: str) -> Tuple[Dict[str, Any] | None, str, str]:
    if not _eligible_card(card):
        return None, "not_safe_or_supported", ""
    interface = next(
        (x for x in _safe_list(card.get("supportedInterfaces")) if isinstance(x, dict) and x.get("protocolBinding") == "JSONRPC"),
        None,
    )
    if not interface:
        return None, "no_jsonrpc_interface", ""

    product_code, product_label = _product_fit(card)
    version = str(interface.get("protocolVersion") or card.get("protocolVersion") or "1.0")
    legacy = version.startswith("0.3")
    context_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    text = (
        "LUMEN B2B commercial follow-up. Your published agent capabilities appear relevant to "
        f"{product_label}. If you have a live business need, your agent can request a focused, non-binding LUMEN service now. "
        f"Suggested service family: {product_code}. Machine catalog: {MACHINE_CATALOG_URL} . "
        f"Full service catalog: {SERVICE_CATALOG_URL} . "
        "For the shortest path, send LUMEN a request containing intent=request_quote, service, scope, country/market and any deadline. "
        "Machine services start at USD 5. Larger fixed-scope services start at USD 59. "
        "This message does not create a purchase, charge, contract or acceptance. LUMEN has zero autonomous outgoing-spend authority."
    )
    metadata = {
        "sender": "LUMEN B2B Agent",
        "purpose": "commercial_followup_nonbinding",
        "recommendedService": product_code,
        "machineCatalogUrl": MACHINE_CATALOG_URL,
        "serviceCatalogUrl": SERVICE_CATALOG_URL,
        "requestSchema": ["intent=request_quote", "service", "scope", "country_or_market", "deadline_optional"],
        "machinePriceFloorUsd": "5",
        "servicePriceFloorUsd": "59",
        "lumenAutonomousSpend": False,
        "bindingActionsHumanGated": True,
    }
    if legacy:
        message = {
            "messageId": message_id,
            "contextId": context_id,
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "metadata": metadata,
        }
        method = "message/send"
    else:
        message = {
            "messageId": message_id,
            "contextId": context_id,
            "role": "ROLE_USER",
            "parts": [{"text": text, "mediaType": "text/plain"}],
            "metadata": metadata,
        }
        method = "SendMessage"
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": {"message": message},
    }
    response, status = _base._safe_post_json(str(interface.get("url") or ""), source_domain, payload, version)
    return response, status, product_code


def _global_sales_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    network = dict(_ORIGINAL_TICK(state) or {})
    discovered = [x for x in _safe_list(network.get("discovered_agents")) if isinstance(x, dict)]
    handshakes = [x for x in _safe_list(network.get("handshakes")) if isinstance(x, dict)]
    history = [x for x in _safe_list(network.get("sales_followups")) if isinstance(x, dict)]
    followed_domains = {str(x.get("domain") or "").lower() for x in history if x.get("domain")}
    cards_by_domain = {
        str(x.get("domain") or "").lower(): _safe_dict(x.get("agent"))
        for x in discovered
        if x.get("domain")
    }

    candidates: List[Dict[str, Any]] = []
    for hs in handshakes:
        domain = str(hs.get("domain") or "").lower()
        if not domain or domain in followed_domains or str(hs.get("status") or "") != "response_received":
            continue
        card = cards_by_domain.get(domain) or {}
        if not _eligible_card(card):
            continue
        buyer_score = int(_accelerator._buyer_intent_score(card))
        if buyer_score < MIN_BUYER_INTENT_SCORE:
            continue
        candidates.append({
            "domain": domain,
            "agent_name": str(card.get("name") or hs.get("agent_name") or "")[:180],
            "card": card,
            "buyer_intent_score": buyer_score,
            "remote_payment_capable": bool(_accelerator._remote_payment_capable(card)),
            "handshake_id": str(hs.get("id") or ""),
        })

    candidates.sort(
        key=lambda x: (
            1 if x.get("remote_payment_capable") else 0,
            int(x.get("buyer_intent_score") or 0),
            str(x.get("domain") or ""),
        ),
        reverse=True,
    )

    sent_this_tick = 0
    response_this_tick = 0
    failed_this_tick = 0
    selected: List[str] = []
    for candidate in candidates[:MAX_FOLLOWUPS_PER_TICK]:
        domain = str(candidate.get("domain") or "")
        response, status, product_code = _followup_payload(_safe_dict(candidate.get("card")), domain)
        record = {
            "id": f"A2ASALE-{uuid.uuid4().hex[:12].upper()}",
            "domain": domain,
            "agent_name": str(candidate.get("agent_name") or "")[:180],
            "handshake_id": str(candidate.get("handshake_id") or "")[:80],
            "ts": _now(),
            "stage": "followup_response_received" if response else "followup_attempted",
            "transport_status": status,
            "recommended_service": product_code,
            "buyer_intent_score": int(candidate.get("buyer_intent_score") or 0),
            "remote_payment_capable": bool(candidate.get("remote_payment_capable")),
            "response_received": bool(response),
            "response_summary": str(response)[:1200] if response else None,
            "commercial_intent_verified": False,
            "order_created": False,
            "payment_verified": False,
            "binding_actions_human_gated": True,
            "outgoing_spend_usd": 0,
        }
        history.append(record)
        selected.append(domain)
        sent_this_tick += 1
        if response:
            response_this_tick += 1
        else:
            failed_this_tick += 1

    history = history[-MAX_FOLLOWUP_HISTORY:]
    stages = {
        "discovered": len(discovered),
        "handshake_response_received": sum(1 for x in handshakes if str(x.get("status") or "") == "response_received"),
        "commercial_followup_attempted": len(history),
        "commercial_followup_response_received": sum(1 for x in history if bool(x.get("response_received"))),
        "explicit_quote_requests": 0,
        "orders_created": sum(1 for x in history if bool(x.get("order_created"))),
        "payments_verified": sum(1 for x in history if bool(x.get("payment_verified"))),
    }

    snap = {
        "version": VERSION,
        "status": "active",
        "scope": "global_public_a2a_registry_plus_safe_discovered_peers",
        "funnel": stages,
        "eligible_followups_now": len(candidates),
        "followups_sent_this_tick": sent_this_tick,
        "followup_responses_this_tick": response_this_tick,
        "followup_failures_this_tick": failed_this_tick,
        "selected_domains": selected,
        "priority": "payment_capable_then_buyer_intent_score",
        "registry_queries": list(GLOBAL_HIGH_INTENT_QUERIES),
        "machine_catalog_url": MACHINE_CATALOG_URL,
        "service_catalog_url": SERVICE_CATALOG_URL,
        "truth_rule": "transport_response_is_not_buying_intent; only explicit inbound quote/order/payment evidence advances commercial truth",
        "guardrails": {
            "max_followups_per_tick": MAX_FOLLOWUPS_PER_TICK,
            "authenticated_calls": False,
            "paid_remote_execution": False,
            "autonomous_purchase": False,
            "autonomous_payment": False,
            "outgoing_spend_usd": 0,
            "binding_actions_human_gated": True,
            "existing_network_caps_changed": False,
        },
        "updated_at": _now(),
    }
    network["sales_followups"] = history
    network["a2a_global_sales"] = snap
    state.setdefault("agent_network", {}).update(network)
    print({"a2a_global_sales": snap}, flush=True)
    return network


# Preserve all existing network safety/caps. We only broaden the rotating high-intent vocabulary and
# add one bounded seller-side follow-up after a real protocol response.
_base.REGISTRY_QUERIES = GLOBAL_HIGH_INTENT_QUERIES
_base.agent_network_tick = _global_sales_tick

print({
    "a2a_global_sales_runtime": {
        "version": VERSION,
        "status": "active",
        "global_high_intent_discovery": True,
        "max_followups_per_tick": MAX_FOLLOWUPS_PER_TICK,
        "commercial_truth_not_inferred_from_transport": True,
        "existing_network_caps_changed": False,
        "outgoing_spend_usd": 0,
        "binding_authority_changed": False,
    }
}, flush=True)
