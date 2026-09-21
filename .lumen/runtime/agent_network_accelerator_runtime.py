from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import agent_network_runtime as _base


VERSION = "1.6-a2a-autonomous-seller-outreach"
REPROBE_AFTER_HOURS = 72
MACHINE_CATALOG_URL = "https://lumen-zero-a2a.joseandresceol1-jac.workers.dev/machine/catalog"
SERVICE_CATALOG_URL = "https://lumen-zero-a2a.joseandresceol1-jac.workers.dev/seller/catalog"
_ORIGINAL_REGISTRY_CARD_URL = _base._registry_card_url
_ORIGINAL_AGENT_NETWORK_TICK = _base.agent_network_tick
_ORIGINAL_HANDSHAKE_SAFE = _base._autonomous_handshake_safe


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _eligible_again(probed_row: Any) -> bool:
    if not isinstance(probed_row, dict):
        return True
    status = str(probed_row.get("status") or "")
    if status == "agent_card_found":
        return False
    ts = _parse_ts(probed_row.get("ts"))
    if ts is None:
        return True
    return (_utcnow() - ts).total_seconds() >= REPROBE_AFTER_HOURS * 3600


def _account_domain(account: Dict[str, Any]) -> str:
    for value in (
        account.get("official_domain"),
        account.get("domain"),
        account.get("email_domain"),
        account.get("website"),
        account.get("source_url"),
    ):
        domain = _base._domain(value)
        if domain:
            return domain
    return ""


def _candidate_domains_accelerated(state: Dict[str, Any], probed: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    rows: List[Tuple[str, Dict[str, Any], float]] = []
    seen: set[str] = set()
    for account in state.get("candidate_accounts", []) or []:
        if not isinstance(account, dict):
            continue
        if account.get("type") != "supplier" or not account.get("verified_company"):
            continue
        domain = _account_domain(account)
        if not domain or domain in seen:
            continue
        if domain in probed and not _eligible_again(probed.get(domain)):
            continue
        seen.add(domain)
        try:
            score = float(account.get("score") or account.get("outbound_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        contact_bonus = 25.0 if account.get("verified_contact") else 0.0
        official_bonus = 10.0 if account.get("official_domain") else 0.0
        rows.append((domain, account, score + contact_bonus + official_bonus))
    rows.sort(key=lambda row: row[2], reverse=True)
    return [(domain, account) for domain, account, _ in rows[: _base.MAX_PROBES_PER_TICK]]


def _registry_card_url_current(row: Dict[str, Any]) -> str:
    for key in ("manifestUrl", "manifest_url"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return _ORIGINAL_REGISTRY_CARD_URL(row)


def _card_text(card: Dict[str, Any]) -> str:
    return " ".join([
        str(card.get("name") or ""),
        str(card.get("description") or ""),
        " ".join(
            str(skill.get("name") or "") + " " + str(skill.get("description") or "") + " " + " ".join(skill.get("tags") or [])
            for skill in card.get("skills", []) or []
            if isinstance(skill, dict)
        ),
    ]).lower()


def _remote_payment_capable(card: Dict[str, Any]) -> bool:
    text = _card_text(card)
    return any(token in text for token in _base.RISKY_AUTONOMOUS_TAGS)


def _buyer_intent_score(card: Dict[str, Any]) -> int:
    text = _card_text(card)
    score = 0
    for token, points in (
        ("procurement", 30),
        ("buyer", 30),
        ("buying", 25),
        ("rfq", 25),
        ("sourcing", 20),
        ("purchase", 15),
        ("supplier discovery", 15),
        ("mcp", 10),
        ("x402", 15),
        ("payment", 8),
    ):
        if token in text:
            score += points
    return min(100, score)


def _seller_only_handshake_safe(card: Dict[str, Any]) -> Tuple[bool, str]:
    if card.get("securityRequirements") or card.get("securitySchemes"):
        return False, "auth_required"
    if _remote_payment_capable(card):
        return True, "seller_only_payment_capable_peer"
    return _ORIGINAL_HANDSHAKE_SAFE(card)


def _seller_handshake(card: Dict[str, Any], source_domain: str, account: Dict[str, Any] | None = None, discovery_source: str = "verified_supplier_domain") -> Tuple[Dict[str, Any] | None, str]:
    safe, safe_reason = _seller_only_handshake_safe(card)
    if not safe:
        return None, safe_reason
    interface = next((x for x in card.get("supportedInterfaces", []) if x.get("protocolBinding") == "JSONRPC"), None)
    if not interface:
        return None, "no_jsonrpc_interface"

    account = account or {}
    version = str(interface.get("protocolVersion") or card.get("protocolVersion") or "1.0")
    legacy = version.startswith("0.3")
    context_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    text = (
        "Hello. We are LUMEN B2B, a seller-side sourcing and commercial-intelligence agent. "
        "We offer machine-consumable B2B services for procurement, supplier verification, quotation review, tender discovery, sourcing, buyer signals and export research. "
        "Our current Machine Store starts at USD 5 per focused request, while larger fixed-scope services start at USD 59. "
        f"Machine catalog: {MACHINE_CATALOG_URL} . Full service catalog: {SERVICE_CATALOG_URL} . "
        "If your agent has a current procurement, sourcing, RFQ, supplier-verification or market-research need, it can inspect the catalogs and request a non-binding quote through LUMEN's A2A endpoint. "
        "No purchase or payment is authorized by this message, and LUMEN has no autonomous outgoing-spend authority."
    )
    metadata = {
        "sender": "LUMEN B2B Agent",
        "purpose": "seller_capability_offer",
        "discoverySource": discovery_source,
        "machineCatalogUrl": MACHINE_CATALOG_URL,
        "serviceCatalogUrl": SERVICE_CATALOG_URL,
        "machinePriceFloorUsd": "5",
        "servicePriceFloorUsd": "59",
        "sellerMode": "receive_revenue_only",
        "bindingActionsHumanGated": True,
        "lumenAutonomousSpend": False,
    }
    if account:
        metadata["supplierCompany"] = str(account.get("company_name") or account.get("name_hint") or "")[:180]

    if legacy:
        message = {"messageId": message_id, "contextId": context_id, "role": "user", "parts": [{"kind": "text", "text": text}], "metadata": metadata}
        method = "message/send"
    else:
        message = {"messageId": message_id, "contextId": context_id, "role": "ROLE_USER", "parts": [{"text": text, "mediaType": "text/plain"}], "metadata": metadata}
        method = "SendMessage"
    payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": {"message": message}}
    return _base._safe_post_json(interface["url"], source_domain, payload, version)


def _safe_diagnostic_row(row: Dict[str, Any]) -> Dict[str, Any]:
    agent = row.get("agent") if isinstance(row.get("agent"), dict) else {}
    return {
        "domain": str(row.get("domain") or "")[:180],
        "agent_name": str(row.get("agent_name") or row.get("name") or "")[:180],
        "status": str(row.get("status") or "")[:120],
        "handshake_status": str(row.get("handshake_status") or "")[:120] or None,
        "detail": str(row.get("detail") or "")[:160] or None,
        "query": str(row.get("query") or "")[:80] or None,
        "remote_payment_capable": _remote_payment_capable(agent) if agent else None,
        "buyer_intent_score": _buyer_intent_score(agent) if agent else None,
    }


def _agent_network_tick_with_diagnostics(state: Dict[str, Any]) -> Dict[str, Any]:
    network = dict(_ORIGINAL_AGENT_NETWORK_TICK(state) or {})
    candidate_rows = [x for x in (network.get("registry_candidates") or []) if isinstance(x, dict)]
    handshake_rows = [x for x in (network.get("handshakes") or []) if isinstance(x, dict)]
    discovered_rows = [x for x in (network.get("discovered_agents") or []) if isinstance(x, dict)]

    seller_targets = []
    payment_capable = 0
    for row in discovered_rows:
        card = row.get("agent") if isinstance(row.get("agent"), dict) else {}
        score = _buyer_intent_score(card)
        can_pay = _remote_payment_capable(card)
        if can_pay:
            payment_capable += 1
        row["seller_mode"] = {
            "buyer_intent_score": score,
            "remote_payment_capable": can_pay,
            "eligible_for_nonbinding_service_offer": score >= 25,
            "lumen_spend_authority": False,
        }
        if score >= 25:
            seller_targets.append({
                "domain": str(row.get("domain") or "")[:180],
                "agent_name": str(card.get("name") or row.get("company") or "")[:180],
                "buyer_intent_score": score,
                "remote_payment_capable": can_pay,
            })

    reason_counts: Dict[str, int] = {}
    for row in candidate_rows[-20:]:
        reason = str(row.get("handshake_status") or row.get("detail") or row.get("status") or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    diagnostic = {
        "version": VERSION,
        "registry_candidates_total": len(candidate_rows),
        "discovered_total": len(discovered_rows),
        "handshakes_total": len(handshake_rows),
        "seller_targets_total": len(seller_targets),
        "remote_payment_capable_total": payment_capable,
        "recent_candidate_reasons": reason_counts,
        "recent_candidates": [_safe_diagnostic_row(x) for x in candidate_rows[-5:]],
        "recent_handshakes": [
            {
                "domain": str(x.get("domain") or "")[:180],
                "agent_name": str(x.get("agent_name") or "")[:180],
                "status": str(x.get("status") or "")[:120],
                "transport_status": str(x.get("transport_status") or "")[:120],
                "discovery_source": str(x.get("discovery_source") or "")[:120],
            }
            for x in handshake_rows[-5:]
        ],
        "seller_mode": True,
        "autonomous_nonbinding_offer": True,
        "machine_catalog_url": MACHINE_CATALOG_URL,
        "payment_capable_peer_discovery_allowed": True,
        "remote_payment_capability_does_not_grant_spend_authority": True,
        "paid_remote_execution_blocked": True,
        "authenticated_agent_calls_blocked": True,
        "autonomous_purchase": False,
        "autonomous_payment": False,
        "binding_actions_human_gated": True,
    }
    network["seller_mode"] = {
        "status": "active",
        "mode": "discover_offer_quote_receive_revenue",
        "seller_targets": seller_targets[-20:],
        "seller_targets_total": len(seller_targets),
        "remote_payment_capable_total": payment_capable,
        "machine_catalog_url": MACHINE_CATALOG_URL,
        "service_catalog_url": SERVICE_CATALOG_URL,
        "autonomous_nonbinding_offer": True,
        "autonomous_spend": False,
        "autonomous_purchase": False,
        "binding_acceptance": False,
        "objective": "find machine buyers and sell productized LUMEN services while preserving zero outgoing-spend authority",
    }
    guardrails = network.setdefault("guardrails", {})
    guardrails.update({
        "seller_mode": True,
        "autonomous_nonbinding_offer": True,
        "payment_capable_peer_discovery_allowed": True,
        "paid_remote_execution_blocked": True,
        "autonomous_purchase": False,
        "autonomous_payment": False,
        "binding_actions_human_gated": True,
    })
    network["a2a_discovery_diagnostic"] = diagnostic
    state.setdefault("agent_network", {}).update(network)
    print({"a2a_discovery_diagnostic": diagnostic}, flush=True)
    return network


_base._candidate_domains = _candidate_domains_accelerated
_base._registry_card_url = _registry_card_url_current
_base._autonomous_handshake_safe = _seller_only_handshake_safe
_base._handshake = _seller_handshake
_base.REGISTRY_QUERIES = ("procurement", "sourcing", "buyer", "x402")
_base.agent_network_tick = _agent_network_tick_with_diagnostics

print({
    "agent_network_accelerator_runtime": {
        "version": VERSION,
        "status": "active",
        "seller_mode": True,
        "autonomous_nonbinding_offer": True,
        "machine_catalog": MACHINE_CATALOG_URL,
        "registry_keyword_mode": "rotating_high_intent",
        "registry_manifest_url_compat": True,
        "handshake_diagnostics": True,
        "reprobe_after_hours": REPROBE_AFTER_HOURS,
        "probe_cap_changed": False,
        "handshake_cap_changed": False,
        "binding_authority_changed": False,
        "paid_spend_authority_changed": False,
    }
}, flush=True)