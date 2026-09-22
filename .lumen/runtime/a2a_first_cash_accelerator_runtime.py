from __future__ import annotations

"""LUMEN Zero A2A First-Cash Accelerator v1.

Makes future seller-side A2A follow-ups materially easier to buy by replacing a generic
catalog invitation with the exact low-ticket machine product, fixed launch price and x402
checkout URL when the remote agent's published capabilities clearly fit one of the three
first-cash products. It does not change discovery, handshake or follow-up caps; it never
spends LUMEN funds, accepts terms, creates an order, or treats a transport response as
commercial intent.
"""

import os
import uuid
from typing import Any, Dict, Optional, Tuple

import a2a_global_sales_runtime as sales

VERSION = "1.0-a2a-first-cash-accelerator"
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


# Patch only the commercial message builder used by the already-bounded Global A2A Sales loop.
# Candidate selection, one-follow-up-per-tick cap, domain dedupe and all transport safety stay intact.
sales._followup_payload = accelerated_followup_payload

print(
    {
        "a2a_first_cash_accelerator_runtime": {
            "version": VERSION,
            "status": "installed",
            "focus_products": [row["id"] for row in FIRST_CASH_OFFERS],
            "direct_x402": True,
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
