from __future__ import annotations

"""LUMEN Zero A2A First-Cash Accelerator v1.1.

Makes seller-side A2A follow-ups materially easier to buy by replacing a generic
catalog invitation with the exact low-ticket machine product, fixed launch price and x402
checkout URL when the remote agent's published capabilities clearly fit one of the three
first-cash products.

v1.1 also gives previously contacted peers exactly one controlled upgrade message when
all of the following are true: their earlier generic follow-up received a transport response,
they still meet the buyer-intent/safety gates, they have never received an MP-* first-cash
offer, and the normal one-follow-up-per-tick budget was not already used. This allows the
new checkout-aware offer to reach pre-existing peers without widening network throughput,
creating charges, spending LUMEN funds, accepting terms, or treating transport responses as
commercial intent.
"""

import os
import uuid
from typing import Any, Dict, Optional, Tuple

import a2a_global_sales_runtime as sales

VERSION = "1.1-a2a-first-cash-reengagement"
MAX_REENGAGEMENTS_PER_TICK = 1
X402_BASE_URL = (
    os.getenv("LUMEN_X402_BASE_URL")
    or "https://lumen-zero-x402.lumen-b2b.workers.dev"
).strip().rstrip("/")

FIRST_CASH_OFFERS = (
    {
        "id": "MP-QUOTE-SANITY",
        "slug": "quote-sanity",
        "name": "Quote Sanity Check",
        "price_usd": 7,
        "service_id": "SRV-QUOTECHECK",
        "label": "quotation / RFQ review",
        "tokens": ("rfq", "quotation", "quote", "pricing"),
    },
    {
        "id": "MP-TENDER-SCAN",
        "slug": "tender-scan",
        "name": "Tender Quick Scan",
        "price_usd": 9,
        "service_id": "SRV-TENDER-HUNTER",
        "label": "tender / procurement intelligence",
        "tokens": ("tender", "bid", "procurement", "public opportunity"),
    },
    {
        "id": "MP-SUPPLIER-SNAPSHOT",
        "slug": "supplier-snapshot",
        "name": "Supplier Snapshot",
        "price_usd": 5,
        "service_id": "SRV-SUPPLIERCHECK",
        "label": "supplier verification / due diligence",
        "tokens": ("supplier verification", "vendor verification", "due diligence", "verify supplier"),
    },
)

_ORIGINAL_FOLLOWUP = sales._followup_payload
_ORIGINAL_NETWORK_TICK = sales._base.agent_network_tick


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _select_first_cash_offer(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    text = sales._card_text(card)
    for offer in FIRST_CASH_OFFERS:
        if any(token in text for token in offer["tokens"]):
            return dict(offer)
    return None


def _checkout_url(offer: Dict[str, Any]) -> str:
    return f"{X402_BASE_URL}/buy/{offer['slug']}"


def _jsonrpc_interface(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return next(
        (
            row
            for row in _safe_list(card.get("supportedInterfaces"))
            if isinstance(row, dict)
            and row.get("protocolBinding") == "JSONRPC"
            and str(row.get("url") or "").startswith("https://")
        ),
        None,
    )


def accelerated_followup_payload(
    card: Dict[str, Any], source_domain: str
) -> Tuple[Dict[str, Any] | None, str, str]:
    offer = _select_first_cash_offer(card)
    if offer is None:
        return _ORIGINAL_FOLLOWUP(card, source_domain)
    if not sales._eligible_card(card):
        return None, "not_safe_or_supported", ""

    interface = _jsonrpc_interface(card)
    if not interface:
        return None, "no_jsonrpc_interface", ""

    checkout = _checkout_url(offer)
    version = str(interface.get("protocolVersion") or card.get("protocolVersion") or "1.0")
    legacy = version.startswith("0.3")
    context_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    text = (
        "LUMEN B2B first-cash offer. Your published capabilities appear relevant to "
        f"{offer['label']}. The closest fixed-scope machine product is {offer['name']} "
        f"({offer['id']}) at USD {offer['price_usd']} per request. "
        f"Direct x402 checkout: {checkout} . Machine catalog: {sales.MACHINE_CATALOG_URL} . "
        "If you prefer a non-binding request before payment, send LUMEN intent=request_quote, "
        f"productId={offer['id']}, serviceId={offer['service_id']}, scope, country_or_market and optional deadline. "
        "Opening the checkout or receiving this message creates no charge, order, contract or acceptance. "
        "A buyer-side agent chooses whether to settle x402; LUMEN has zero autonomous outgoing-spend authority."
    )
    metadata = {
        "sender": "LUMEN B2B Agent",
        "purpose": "first_cash_machine_offer_nonbinding",
        "recommendedMachineProduct": offer["id"],
        "recommendedService": offer["service_id"],
        "productName": offer["name"],
        "priceUsd": str(offer["price_usd"]),
        "x402CheckoutUrl": checkout,
        "machineCatalogUrl": sales.MACHINE_CATALOG_URL,
        "requestSchema": [
            "intent=request_quote",
            f"productId={offer['id']}",
            f"serviceId={offer['service_id']}",
            "scope",
            "country_or_market",
            "deadline_optional",
        ],
        "chargeCreated": False,
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
    response, status = sales._base._safe_post_json(
        str(interface.get("url") or ""), source_domain, payload, version
    )
    return response, status, str(offer["id"])


def _domain(value: Any) -> str:
    return str(value or "").strip().lower()


def _has_machine_offer(history: list[Dict[str, Any]], domain: str) -> bool:
    return any(
        _domain(row.get("domain")) == domain
        and str(row.get("recommended_service") or "").startswith("MP-")
        for row in history
        if isinstance(row, dict)
    )


def _has_successful_generic_followup(history: list[Dict[str, Any]], domain: str) -> bool:
    return any(
        _domain(row.get("domain")) == domain
        and bool(row.get("response_received"))
        and not str(row.get("recommended_service") or "").startswith("MP-")
        for row in history
        if isinstance(row, dict)
    )


def _reengagement_candidates(network: Dict[str, Any]) -> list[Dict[str, Any]]:
    discovered = [row for row in _safe_list(network.get("discovered_agents")) if isinstance(row, dict)]
    handshakes = [row for row in _safe_list(network.get("handshakes")) if isinstance(row, dict)]
    history = [row for row in _safe_list(network.get("sales_followups")) if isinstance(row, dict)]
    cards_by_domain = {
        _domain(row.get("domain")): row.get("agent") if isinstance(row.get("agent"), dict) else {}
        for row in discovered
        if row.get("domain")
    }

    rows: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for hs in handshakes:
        domain = _domain(hs.get("domain"))
        if not domain or domain in seen or str(hs.get("status") or "") != "response_received":
            continue
        if not _has_successful_generic_followup(history, domain) or _has_machine_offer(history, domain):
            continue
        card = cards_by_domain.get(domain) or {}
        offer = _select_first_cash_offer(card)
        if offer is None or not sales._eligible_card(card):
            continue
        score = int(sales._accelerator._buyer_intent_score(card))
        if score < sales.MIN_BUYER_INTENT_SCORE:
            continue
        rows.append({
            "domain": domain,
            "agent_name": str(card.get("name") or hs.get("agent_name") or "")[:180],
            "card": card,
            "offer": offer,
            "buyer_intent_score": score,
            "remote_payment_capable": bool(sales._accelerator._remote_payment_capable(card)),
            "handshake_id": str(hs.get("id") or "")[:80],
        })
        seen.add(domain)

    rows.sort(
        key=lambda row: (
            1 if row.get("remote_payment_capable") else 0,
            int(row.get("buyer_intent_score") or 0),
            str(row.get("domain") or ""),
        ),
        reverse=True,
    )
    return rows


def first_cash_reengagement_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    network = dict(_ORIGINAL_NETWORK_TICK(state) or {})
    snap = dict(network.get("a2a_global_sales") or {})
    history = [row for row in _safe_list(network.get("sales_followups")) if isinstance(row, dict)]

    # Preserve the original global one-follow-up-per-tick throughput. A re-engagement can use
    # that slot only when the normal sales tick did not send a new follow-up in this cycle.
    already_sent = int(snap.get("followups_sent_this_tick") or 0)
    candidates = _reengagement_candidates(network)
    sent = 0
    responses = 0
    failures = 0
    selected: list[str] = []

    if already_sent < sales.MAX_FOLLOWUPS_PER_TICK:
        remaining = min(
            MAX_REENGAGEMENTS_PER_TICK,
            max(0, sales.MAX_FOLLOWUPS_PER_TICK - already_sent),
        )
        for candidate in candidates[:remaining]:
            domain = str(candidate.get("domain") or "")
            response, status, product_id = accelerated_followup_payload(
                candidate.get("card") if isinstance(candidate.get("card"), dict) else {},
                domain,
            )
            history.append({
                "id": f"A2AUPGRADE-{uuid.uuid4().hex[:12].upper()}",
                "domain": domain,
                "agent_name": str(candidate.get("agent_name") or "")[:180],
                "handshake_id": str(candidate.get("handshake_id") or "")[:80],
                "ts": sales._now(),
                "stage": "first_cash_reengagement_response_received" if response else "first_cash_reengagement_attempted",
                "transport_status": status,
                "recommended_service": product_id,
                "buyer_intent_score": int(candidate.get("buyer_intent_score") or 0),
                "remote_payment_capable": bool(candidate.get("remote_payment_capable")),
                "response_received": bool(response),
                "response_summary": str(response)[:1200] if response else None,
                "first_cash_reengagement": True,
                "commercial_intent_verified": False,
                "order_created": False,
                "payment_verified": False,
                "binding_actions_human_gated": True,
                "outgoing_spend_usd": 0,
            })
            selected.append(domain)
            sent += 1
            if response:
                responses += 1
            else:
                failures += 1

    history = history[-sales.MAX_FOLLOWUP_HISTORY:]
    network["sales_followups"] = history

    funnel = dict(snap.get("funnel") or {})
    funnel["commercial_followup_attempted"] = len(history)
    funnel["commercial_followup_response_received"] = sum(
        1 for row in history if bool(row.get("response_received"))
    )
    funnel["first_cash_reengagements"] = sum(
        1 for row in history if bool(row.get("first_cash_reengagement"))
    )
    snap["funnel"] = funnel
    snap["followups_sent_this_tick"] = already_sent + sent
    snap["followup_responses_this_tick"] = int(snap.get("followup_responses_this_tick") or 0) + responses
    snap["followup_failures_this_tick"] = int(snap.get("followup_failures_this_tick") or 0) + failures
    snap["eligible_first_cash_reengagements_now"] = len(candidates)
    snap["first_cash_reengagements_sent_this_tick"] = sent
    snap["first_cash_reengagement_selected_domains"] = selected
    snap["first_cash_reengagement_rule"] = (
        "one-time exact MP-* offer only after a prior generic transport response; never after an MP-* offer"
    )
    guardrails = dict(snap.get("guardrails") or {})
    guardrails.update({
        "max_followups_per_tick": sales.MAX_FOLLOWUPS_PER_TICK,
        "max_first_cash_reengagements_per_tick": MAX_REENGAGEMENTS_PER_TICK,
        "max_first_cash_upgrades_per_domain": 1,
        "outgoing_spend_usd": 0,
        "autonomous_purchase": False,
        "autonomous_payment": False,
        "binding_actions_human_gated": True,
        "transport_response_is_commercial_intent": False,
    })
    snap["guardrails"] = guardrails
    snap["updated_at"] = sales._now()
    network["a2a_global_sales"] = snap
    state.setdefault("agent_network", {}).update(network)
    return network


# Patch the commercial message builder used by the bounded Global A2A Sales loop.
# Candidate selection, domain safety, protocol validation and outgoing-spend controls stay intact.
sales._followup_payload = accelerated_followup_payload

# Wrap the already-installed global sales tick. The wrapper does not add throughput: it only uses
# an otherwise-unused existing follow-up slot to give qualified historical responders one exact
# first-cash checkout message. Once an MP-* offer exists for a domain it is permanently deduped.
sales._base.agent_network_tick = first_cash_reengagement_tick

print(
    {
        "a2a_first_cash_accelerator_runtime": {
            "version": VERSION,
            "status": "installed",
            "focus_products": [row["id"] for row in FIRST_CASH_OFFERS],
            "direct_x402": True,
            "historical_responder_reengagement": True,
            "max_first_cash_reengagements_per_tick": MAX_REENGAGEMENTS_PER_TICK,
            "existing_followup_cap_changed": False,
            "registry_caps_changed": False,
            "outgoing_spend_usd": 0,
            "autonomous_purchase": False,
            "binding_authority_changed": False,
            "transport_response_is_commercial_intent": False,
        }
    },
    flush=True,
)
