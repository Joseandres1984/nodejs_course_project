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


VERSION = "1.0-a2a-peer-network"
MAX_PROBES_PER_TICK = 2
MAX_HANDSHAKES_PER_TICK = 1
MAX_DISCOVERED = 80
MAX_HANDSHAKES = 80
CARD_PATHS = ("/.well-known/agent-card.json", "/.well-known/agent.json")
SUPPORTED_BINDINGS = {"JSONRPC"}
SUPPORTED_VERSIONS = {"1.0", "0.3"}
USER_AGENT = "LUMEN-A2A/1.0 (+nonbinding-b2b-agent)"


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
    if not name or not isinstance(interfaces, list) or not interfaces:
        return None, "missing_identity_or_interfaces"

    safe_interfaces: List[Dict[str, str]] = []
    for item in interfaces[:8]:
        if not isinstance(item, dict):
            continue
        binding = str(item.get("protocolBinding") or "").upper()
        version = str(item.get("protocolVersion") or "")
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

    return {
        "name": name,
        "description": str(card.get("description") or "")[:800],
        "version": str(card.get("version") or "")[:80],
        "provider": card.get("provider") if isinstance(card.get("provider"), dict) else {},
        "supportedInterfaces": safe_interfaces,
        "skills": clean_skills,
        "securityRequirements": card.get("securityRequirements") if isinstance(card.get("securityRequirements"), list) else [],
        "capabilities": card.get("capabilities") if isinstance(card.get("capabilities"), dict) else {},
    }, "ok"


def _handshake(card: Dict[str, Any], source_domain: str, account: Dict[str, Any]) -> Tuple[Dict[str, Any] | None, str]:
    if card.get("securityRequirements"):
        return None, "auth_required"
    interface = next((x for x in card.get("supportedInterfaces", []) if x.get("protocolBinding") == "JSONRPC"), None)
    if not interface:
        return None, "no_jsonrpc_interface"

    context_id = str(uuid.uuid4())
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "contextId": context_id,
                "role": "ROLE_USER",
                "parts": [{
                    "text": (
                        "Hello. We are LUMEN B2B, an AI-assisted commercial sourcing intermediary. "
                        "We are exploring non-binding agent-to-agent cooperation with verified suppliers. "
                        "Can your agent exchange product capabilities, RFQ data, availability, lead times and international sourcing terms? "
                        "Any purchase, payment, contract, commission or binding acceptance on our side requires explicit human approval."
                    ),
                    "mediaType": "text/plain",
                }],
                "metadata": {
                    "sender": "LUMEN B2B Agent",
                    "purpose": "nonbinding_capability_handshake",
                    "supplierCompany": str(account.get("company_name") or account.get("name_hint") or "")[:180],
                    "bindingActionsHumanGated": True,
                },
            }
        },
    }
    return _safe_post_json(interface["url"], source_domain, payload, interface.get("protocolVersion") or "1.0")


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
        "max_probes_per_tick": MAX_PROBES_PER_TICK,
        "max_handshakes_per_tick": MAX_HANDSHAKES_PER_TICK,
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

        response, hs_status = _handshake(found, domain, account)
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
        }
        handshakes.append(record)
        del handshakes[:-MAX_HANDSHAKES]
        handshakes_this_tick += 1

    # Keep probe history bounded without re-probing the same domain every cycle.
    if len(probed) > 300:
        for key in list(probed.keys())[:-300]:
            probed.pop(key, None)

    network.update({
        "version": VERSION,
        "status": "active",
        "mode": "discover_and_nonbinding_handshake",
        "updated_at": utcnow(),
        "probes_this_tick": probes_this_tick,
        "discovered_this_tick": discovered_this_tick,
        "handshakes_this_tick": handshakes_this_tick,
        "discovered_total": len(discovered),
        "handshakes_total": len(handshakes),
        "objective": "build_trusted_machine_to_machine_b2b_relationships_without_binding_authority",
    })
    return network


print({
    "agent_network_runtime": {
        "version": VERSION,
        "status": "loaded",
        "max_probes_per_tick": MAX_PROBES_PER_TICK,
        "max_handshakes_per_tick": MAX_HANDSHAKES_PER_TICK,
        "verified_suppliers_only": True,
        "binding_actions_human_gated": True,
    }
}, flush=True)
