from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


VERSION = "1.1-a2a-peer-network-registry"
MAX_PROBES_PER_TICK = 2
MAX_HANDSHAKES_PER_TICK = 1
MAX_REGISTRY_QUERIES_PER_TICK = 1
MAX_REGISTRY_RESULTS_PER_TICK = 5
MAX_DISCOVERED = 100
MAX_HANDSHAKES = 100
MAX_REGISTRY_CANDIDATES = 100
CARD_PATHS = ("/.well-known/agent-card.json", "/.well-known/agent.json")
SUPPORTED_BINDINGS = {"JSONRPC"}
SUPPORTED_VERSIONS = {"1.0", "0.3", "0.3.0"}
USER_AGENT = "LUMEN-A2A/1.1 (+nonbinding-b2b-agent)"
PUBLIC_REGISTRY_HOST = "api.a2a-registry.org"
PUBLIC_REGISTRY_URL = "https://api.a2a-registry.org/public/agents"
REGISTRY_QUERIES = (
    "procurement",
    "sourcing",
    "supplier",
    "industrial",
    "manufacturing",
    "logistics",
    "supply chain",
    "B2B",
    "RFQ",
)
RISKY_AUTONOMOUS_TAGS = (
    "payment",
    "payments",
    "wallet",
    "wallets",
    "checkout",
    "escrow",
    "x402",
    "crypto",
    "cryptocurrency",
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _domain(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    try:
        host = urllib.parse.urlparse(text).hostname or ""
        return host.lower().removeprefix("www.")
    except Exception:
        return ""


def _public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except Exception:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def _safe_https_url(url: str, source_domain: str | None = None) -> Tuple[bool, str]:
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
    except Exception:
        return False, "invalid_url"
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False, "https_required"
    host = parsed.hostname.lower().removeprefix("www.")
    if parsed.port not in (None, 443):
        return False, "nonstandard_port_blocked"
    if source_domain:
        src = source_domain.lower().removeprefix("www.")
        if not (host == src or host.endswith("." + src) or src.endswith("." + host)):
            return False, "cross_domain_interface_blocked"
    if not _public_host(host):
        return False, "nonpublic_host_blocked"
    return True, host


def _read_json_response(response, max_bytes: int) -> Dict[str, Any] | None:
    raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _read_json_any(response, max_bytes: int) -> Any:
    raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _safe_get_json(url: str, source_domain: str, max_bytes: int = 65536) -> Tuple[Dict[str, Any] | None, str]:
    ok, reason = _safe_https_url(url, source_domain)
    if not ok:
        return None, reason
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with _OPENER.open(req, timeout=4) as response:
            if int(getattr(response, "status", 200)) != 200:
                return None, f"http_{getattr(response, 'status', 'unknown')}"
            data = _read_json_response(response, max_bytes)
            return (data, "ok") if data else (None, "invalid_json_or_too_large")
    except urllib.error.HTTPError as exc:
        return None, f"http_{exc.code}"
    except Exception as exc:
        return None, f"{type(exc).__name__}"


def _safe_post_json(url: str, source_domain: str, payload: Dict[str, Any], version: str) -> Tuple[Dict[str, Any] | None, str]:
    ok, reason = _safe_https_url(url, source_domain)
    if not ok:
        return None, reason
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(body) > 32768:
        return None, "request_too_large"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "A2A-Version": version,
        },
    )
    try:
        with _OPENER.open(req, timeout=6) as response:
            if int(getattr(response, "status", 200)) not in range(200, 300):
                return None, f"http_{getattr(response, 'status', 'unknown')}"
            data = _read_json_response(response, 131072)
            return (data, "ok") if data else (None, "invalid_json_or_too_large")
    except urllib.error.HTTPError as exc:
        return None, f"http_{exc.code}"
    except Exception as exc:
        return None, f"{type(exc).__name__}"


def _candidate_domains(state: Dict[str, Any], probed: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    rows: List[Tuple[str, Dict[str, Any]]] = []
    for account in state.get("candidate_accounts", []) or []:
        if account.get("type") != "supplier" or not account.get("verified_company"):
            continue
        domain = _domain(account.get("domain") or account.get("source_url") or account.get("website"))
        if not domain or domain in probed:
            continue
        rows.append((domain, account))
    return rows[:MAX_PROBES_PER_TICK]


def _validate_card(card: Dict[str, Any], source_domain: str) -> Tuple[Dict[str, Any] | None, str]:
    name = " ".join(str(card.get("name") or "").split())[:180]
    interfaces = card.get("supportedInterfaces") or []
    skills = card.get("skills") or []

    # Compatibility with common pre-1.0 cards that expose url + preferredTransport.
    if not interfaces and card.get("url"):
        interfaces = [{
            "url": card.get("url"),
            "protocolBinding": "JSONRPC" if str(card.get("preferredTransport") or "JSONRPC").upper() in {"JSONRPC", "JSON-RPC"} else str(card.get("preferredTransport") or "").upper(),
            "protocolVersion": str(card.get("protocolVersion") or "0.3.0"),
        }]

    if not name or not isinstance(interfaces, list) or not interfaces:
        return None, "missing_identity_or_interfaces"

    safe_interfaces: List[Dict[str, str]] = []
    for item in interfaces[:8]:
        if not isinstance(item, dict):
            continue
        binding = str(item.get("protocolBinding") or "").upper().replace("JSON-RPC", "JSONRPC")
        version = str(item.get("protocolVersion") or card.get("protocolVersion") or "")
        url = str(item.get("url") or "")
        if binding not in SUPPORTED_BINDINGS or version not in SUPPORTED_VERSIONS:
            continue
        ok, _ = _safe_https_url(url, source_domain)
        if ok:
            safe_interfaces.append({"url": url, "protocolBinding": binding, "protocolVersion": version})
    if not safe_interfaces:
        return None, "no_safe_supported_interface"

    clean_skills = []
    for skill in skills[:20] if isinstance(skills, list) else []:
        if not isinstance(skill, dict):
            continue
        clean_skills.append({
            "id": str(skill.get("id") or "")[:120],
            "name": str(skill.get("name") or "")[:180],
            "description": str(skill.get("description") or "")[:500],
            "tags": [str(x)[:80] for x in (skill.get("tags") or [])[:12]],
        })

    security_requirements = card.get("securityRequirements") if isinstance(card.get("securityRequirements"), list) else []
    if not security_requirements and isinstance(card.get("security"), list):
        security_requirements = card.get("security") or []

    return {
        "name": name,
        "description": str(card.get("description") or "")[:800],
        "version": str(card.get("version") or "")[:80],
        "protocolVersion": str(card.get("protocolVersion") or "")[:40],
        "provider": card.get("provider") if isinstance(card.get("provider"), dict) else {},
        "supportedInterfaces": safe_interfaces,
        "skills": clean_skills,
        "securityRequirements": security_requirements,
        "securitySchemes": card.get("securitySchemes") if isinstance(card.get("securitySchemes"), dict) else {},
        "capabilities": card.get("capabilities") if isinstance(card.get("capabilities"), dict) else {},
    }, "ok"


def _autonomous_handshake_safe(card: Dict[str, Any]) -> Tuple[bool, str]:
    if card.get("securityRequirements") or card.get("securitySchemes"):
        return False, "auth_required"
    text = " ".join([
        str(card.get("name") or ""),
        str(card.get("description") or ""),
        " ".join(str(skill.get("name") or "") + " " + str(skill.get("description") or "") + " " + " ".join(skill.get("tags") or []) for skill in card.get("skills", []) or []),
    ]).lower()
    if any(token in text for token in RISKY_AUTONOMOUS_TAGS):
        return False, "financial_execution_capability_blocked"
    return True, "ok"


def _handshake(card: Dict[str, Any], source_domain: str, account: Dict[str, Any] | None = None, discovery_source: str = "verified_supplier_domain") -> Tuple[Dict[str, Any] | None, str]:
    safe, safe_reason = _autonomous_handshake_safe(card)
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
        "Hello. We are LUMEN B2B, an AI-assisted commercial sourcing intermediary. "
        "We are exploring non-binding agent-to-agent cooperation for B2B sourcing, procurement and international trade. "
        "Can your agent exchange capabilities, supplier/RFQ data, availability, lead times or sourcing terms? "
        "Please describe the non-binding collaboration your agent can support. "
        "Any purchase, payment, contract, commission or binding acceptance on our side requires explicit human approval."
    )

    if legacy:
        message = {
            "messageId": message_id,
            "contextId": context_id,
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "metadata": {
                "sender": "LUMEN B2B Agent",
                "purpose": "nonbinding_capability_handshake",
                "discoverySource": discovery_source,
                "bindingActionsHumanGated": True,
            },
        }
        method = "message/send"
    else:
        message = {
            "messageId": message_id,
            "contextId": context_id,
            "role": "ROLE_USER",
            "parts": [{"text": text, "mediaType": "text/plain"}],
            "metadata": {
                "sender": "LUMEN B2B Agent",
                "purpose": "nonbinding_capability_handshake",
                "discoverySource": discovery_source,
                "supplierCompany": str(account.get("company_name") or account.get("name_hint") or "")[:180],
                "bindingActionsHumanGated": True,
            },
        }
        method = "SendMessage"

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": {"message": message},
    }
    return _safe_post_json(interface["url"], source_domain, payload, version)


def _registry_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("agents", "items", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            for nested in ("agents", "items", "results"):
                nested_value = value.get(nested)
                if isinstance(nested_value, list):
                    return [x for x in nested_value if isinstance(x, dict)]
    return []


def _registry_search(query: str) -> Tuple[List[Dict[str, Any]], str]:
    if not _public_host(PUBLIC_REGISTRY_HOST):
        return [], "registry_host_not_public"
    url = PUBLIC_REGISTRY_URL + "?" + urllib.parse.urlencode({"q": query, "target": "Business"})
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with _OPENER.open(req, timeout=5) as response:
            if int(getattr(response, "status", 200)) != 200:
                return [], f"http_{getattr(response, 'status', 'unknown')}"
            payload = _read_json_any(response, 196608)
            rows = _registry_rows(payload)
            return rows[:MAX_REGISTRY_RESULTS_PER_TICK], "ok"
    except urllib.error.HTTPError as exc:
        return [], f"http_{exc.code}"
    except Exception as exc:
        return [], f"{type(exc).__name__}"


def _registry_card_url(row: Dict[str, Any]) -> str:
    candidates = [
        row.get("wellKnownURI"), row.get("well_known_uri"), row.get("agentCardUrl"), row.get("agent_card_url"),
        row.get("cardUrl"), row.get("card_url"), row.get("canonicalCard"), row.get("canonical_card"),
    ]
    for value in candidates:
        text = str(value or "").strip()
        if text.startswith("https://"):
            return text
    embedded = row.get("agentCard") if isinstance(row.get("agentCard"), dict) else row.get("card") if isinstance(row.get("card"), dict) else None
    if embedded:
        interfaces = embedded.get("supportedInterfaces") or []
        if interfaces and isinstance(interfaces, list) and isinstance(interfaces[0], dict):
            domain = _domain(interfaces[0].get("url"))
            if domain:
                return f"https://{domain}/.well-known/agent-card.json"
        if embedded.get("url"):
            domain = _domain(embedded.get("url"))
            if domain:
                return f"https://{domain}/.well-known/agent-card.json"
    return ""


def _registry_discovery(state: Dict[str, Any], network: Dict[str, Any], handshakes_this_tick: int) -> Tuple[int, int, int, str, str]:
    registry_candidates = network.setdefault("registry_candidates", [])
    discovered = network.setdefault("discovered_agents", [])
    handshakes = network.setdefault("handshakes", [])
    seen = network.setdefault("registry_seen", {})

    tick = max(0, int(state.get("ticks") or 0))
    query = REGISTRY_QUERIES[tick % len(REGISTRY_QUERIES)]
    rows, status = _registry_search(query)
    candidates_this_tick = 0
    discovered_this_tick = 0
    registry_handshakes = 0

    for row in rows:
        card_url = _registry_card_url(row)
        if not card_url:
            continue
        domain = _domain(card_url)
        if not domain or domain in seen:
            continue
        seen[domain] = {"ts": utcnow(), "query": query, "registry": PUBLIC_REGISTRY_HOST}
        candidates_this_tick += 1

        candidate = {
            "domain": domain,
            "name": str(row.get("name") or row.get("agentName") or row.get("title") or domain)[:180],
            "description": str(row.get("description") or "")[:600],
            "agent_card_url": card_url,
            "registry": PUBLIC_REGISTRY_HOST,
            "query": query,
            "conformance": row.get("conformance"),
            "pricing": row.get("pricing"),
            "discovered_at": utcnow(),
            "status": "registry_candidate",
        }
        registry_candidates.append(candidate)
        del registry_candidates[:-MAX_REGISTRY_CANDIDATES]

        raw_card, get_status = _safe_get_json(card_url, domain)
        if not raw_card:
            candidate["status"] = "card_unavailable"
            candidate["detail"] = get_status
            continue
        clean_card, valid_status = _validate_card(raw_card, domain)
        if not clean_card:
            candidate["status"] = "incompatible_card"
            candidate["detail"] = valid_status
            continue

        candidate["status"] = "compatible_agent_discovered"
        candidate["agent_name"] = clean_card.get("name")
        existing = next((x for x in discovered if x.get("domain") == domain), None)
        discovered_row = {
            "domain": domain,
            "company": candidate["name"],
            "account_id": None,
            "agent_card_url": card_url,
            "agent": clean_card,
            "discovered_at": utcnow(),
            "status": "compatible_agent_discovered",
            "discovery_source": "public_a2a_registry",
            "registry_query": query,
        }
        if existing:
            existing.update(discovered_row)
        else:
            discovered.append(discovered_row)
            discovered_this_tick += 1
        del discovered[:-MAX_DISCOVERED]

        if handshakes_this_tick + registry_handshakes >= MAX_HANDSHAKES_PER_TICK:
            continue
        if any(x.get("domain") == domain and x.get("status") in {"sent", "response_received"} for x in handshakes):
            continue

        safe, safe_reason = _autonomous_handshake_safe(clean_card)
        if not safe:
            candidate["handshake_status"] = safe_reason
            continue

        response, hs_status = _handshake(clean_card, domain, None, "public_a2a_registry")
        record = {
            "id": f"A2AHS-{uuid.uuid4().hex[:12].upper()}",
            "domain": domain,
            "company": candidate["name"],
            "agent_name": clean_card.get("name"),
            "ts": utcnow(),
            "status": "response_received" if response else ("auth_required" if hs_status == "auth_required" else "failed_or_unavailable"),
            "transport_status": hs_status,
            "response_summary": str(response)[:1800] if response else None,
            "binding_actions_human_gated": True,
            "discovery_source": "public_a2a_registry",
        }
        handshakes.append(record)
        del handshakes[:-MAX_HANDSHAKES]
        registry_handshakes += 1
        candidate["handshake_status"] = record["status"]

    if len(seen) > 400:
        for key in list(seen.keys())[:-400]:
            seen.pop(key, None)

    return candidates_this_tick, discovered_this_tick, registry_handshakes, status, query


def agent_network_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    network = state.setdefault("agent_network", {})
    network.setdefault("version", VERSION)
    network.setdefault("status", "active")
    network.setdefault("mode", "discover_and_nonbinding_handshake")
    network.setdefault("discovered_agents", [])
    network.setdefault("handshakes", [])
    network.setdefault("probed_domains", {})
    network.setdefault("guardrails", {
        "autonomous_purchase": False,
        "autonomous_payment": False,
        "autonomous_contract_acceptance": False,
        "autonomous_commission_acceptance": False,
        "binding_actions_human_gated": True,
        "probe_verified_suppliers_only": True,
        "https_only": True,
        "private_network_access_blocked": True,
        "cross_domain_agent_endpoint_blocked": True,
        "paid_agent_execution_blocked": True,
        "authenticated_agent_calls_blocked": True,
        "max_probes_per_tick": MAX_PROBES_PER_TICK,
        "max_handshakes_per_tick": MAX_HANDSHAKES_PER_TICK,
        "max_registry_queries_per_tick": MAX_REGISTRY_QUERIES_PER_TICK,
    })

    discovered = network.setdefault("discovered_agents", [])
    handshakes = network.setdefault("handshakes", [])
    probed = network.setdefault("probed_domains", {})
    probes_this_tick = 0
    discovered_this_tick = 0
    handshakes_this_tick = 0

    for domain, account in _candidate_domains(state, probed):
        probes_this_tick += 1
        found = None
        probe_status = "not_found"
        card_url = None
        for path in CARD_PATHS:
            url = f"https://{domain}{path}"
            raw_card, status = _safe_get_json(url, domain)
            probe_status = status
            if raw_card:
                clean_card, valid_status = _validate_card(raw_card, domain)
                if clean_card:
                    found = clean_card
                    card_url = url
                    probe_status = "agent_card_found"
                    break
                probe_status = valid_status
        probed[domain] = {"ts": utcnow(), "status": probe_status}

        if not found:
            continue

        existing = next((x for x in discovered if x.get("domain") == domain), None)
        row = {
            "domain": domain,
            "company": str(account.get("company_name") or account.get("name_hint") or account.get("site_title") or domain)[:180],
            "account_id": account.get("id"),
            "agent_card_url": card_url,
            "agent": found,
            "discovered_at": utcnow(),
            "status": "compatible_agent_discovered",
            "discovery_source": "verified_supplier_domain",
        }
        if existing:
            existing.update(row)
        else:
            discovered.append(row)
            discovered_this_tick += 1
        del discovered[:-MAX_DISCOVERED]

        already_handshaken = any(x.get("domain") == domain and x.get("status") in {"sent", "response_received"} for x in handshakes)
        if handshakes_this_tick >= MAX_HANDSHAKES_PER_TICK or already_handshaken:
            continue

        response, hs_status = _handshake(found, domain, account, "verified_supplier_domain")
        record = {
            "id": f"A2AHS-{uuid.uuid4().hex[:12].upper()}",
            "domain": domain,
            "company": row["company"],
            "agent_name": found.get("name"),
            "ts": utcnow(),
            "status": "response_received" if response else ("auth_required" if hs_status == "auth_required" else "failed_or_unavailable"),
            "transport_status": hs_status,
            "response_summary": str(response)[:1800] if response else None,
            "binding_actions_human_gated": True,
            "discovery_source": "verified_supplier_domain",
        }
        handshakes.append(record)
        del handshakes[:-MAX_HANDSHAKES]
        handshakes_this_tick += 1

    registry_candidates, registry_discovered, registry_handshakes, registry_status, registry_query = _registry_discovery(
        state, network, handshakes_this_tick
    )
    discovered_this_tick += registry_discovered
    handshakes_this_tick += registry_handshakes

    # Keep probe history bounded without re-probing the same domain every cycle.
    if len(probed) > 300:
        for key in list(probed.keys())[:-300]:
            probed.pop(key, None)

    network.update({
        "version": VERSION,
        "status": "active",
        "mode": "verified_supplier_domains_plus_public_registry",
        "updated_at": utcnow(),
        "probes_this_tick": probes_this_tick,
        "registry_candidates_this_tick": registry_candidates,
        "registry_status": registry_status,
        "registry_query": registry_query,
        "discovered_this_tick": discovered_this_tick,
        "handshakes_this_tick": handshakes_this_tick,
        "discovered_total": len(discovered),
        "handshakes_total": len(handshakes),
        "registry_candidates_total": len(network.get("registry_candidates", [])),
        "objective": "build_trusted_machine_to_machine_b2b_relationships_without_binding_authority",
    })
    return network


print({
    "agent_network_runtime": {
        "version": VERSION,
        "status": "loaded",
        "mode": "verified_supplier_domains_plus_public_registry",
        "max_probes_per_tick": MAX_PROBES_PER_TICK,
        "max_registry_queries_per_tick": MAX_REGISTRY_QUERIES_PER_TICK,
        "max_handshakes_per_tick": MAX_HANDSHAKES_PER_TICK,
        "verified_suppliers_only_for_direct_domain_probe": True,
        "public_registry_bootstrap": True,
        "paid_or_authenticated_agent_calls_blocked": True,
        "binding_actions_human_gated": True,
    }
}, flush=True)
