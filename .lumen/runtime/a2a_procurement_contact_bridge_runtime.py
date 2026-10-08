from __future__ import annotations

"""Bridge official public-procurement buyer contacts from the A2A Source Intelligence worker
into the zero-cost commercial runtime.

Only contact fields published by official procurement sources are accepted. No addresses are
guessed. A buyer is marked contact-ready automatically only when an official buyer website and
published email share the same domain. Imported rows remain one-time controlled-outbound only;
suppression, cooldown, risk, quality and owner approval gates still apply downstream.
"""

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List

import scout_connector

VERSION = "1.0-a2a-procurement-contact-bridge"
BASE_URL = (os.getenv("LUMEN_A2A_BASE_URL") or "https://lumen-zero-a2a.lumen-b2b.workers.dev").strip().rstrip("/")
ADMIN_TOKEN = os.getenv("LUMEN_A2A_ADMIN_TOKEN", "").strip()
MAX_IMPORTS_PER_CYCLE = max(1, min(5, int(os.getenv("LUMEN_PROCUREMENT_CONTACT_IMPORT_MAX", "3"))))
FREE_DOMAINS = {"gmail.com","hotmail.com","outlook.com","yahoo.com","icloud.com","live.com","proton.me","protonmail.com"}
_ORIGINAL_SCOUT_TICK = scout_connector.scout_tick


def _host(value: Any) -> str:
    try:
        return (urllib.parse.urlparse(str(value or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _email(value: Any) -> str:
    text = str(value or "").strip().lower().strip(".,;:()[]<>")
    return text if re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", text) else ""


def _email_domain(value: Any) -> str:
    email = _email(value)
    return email.rsplit("@",1)[-1].removeprefix("www.") if email else ""


def _same_domain(email: str, website: str) -> bool:
    ed = _email_domain(email)
    wd = _host(website)
    if not ed or not wd or ed in FREE_DOMAINS:
        return False
    return ed == wd or ed.endswith("." + wd) or wd.endswith("." + ed)


def _fetch_candidates() -> List[Dict[str, Any]]:
    if not ADMIN_TOKEN:
        return []
    req = urllib.request.Request(
        f"{BASE_URL}/source-intelligence/contact-candidates?limit=30",
        headers={
            "accept": "application/json",
            "cache-control": "no-cache",
            "x-lumen-admin": ADMIN_TOKEN,
            "user-agent": f"LUMEN-Zero/{VERSION}",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read(250_000).decode("utf-8", errors="replace"))
    return [x for x in payload.get("candidates", []) if isinstance(x, dict)]


def _account_id(opportunity_id: str) -> str:
    digest = hashlib.sha256(opportunity_id.encode("utf-8")).hexdigest()[:12].upper()
    return f"ACC-PROC-{digest}"


def _find_account(accounts: List[Dict[str, Any]], opportunity_id: str, email: str, domain: str) -> Dict[str, Any] | None:
    target_email = _email(email)
    for row in accounts:
        if str(row.get("procurement_opportunity_id") or "") == opportunity_id:
            return row
        if target_email and _email(row.get("commercial_email")) == target_email:
            return row
        if domain and str(row.get("domain") or "").lower().removeprefix("www.") == domain:
            if row.get("type") == "buyer":
                return row
    return None


def import_procurement_contacts(state: Dict[str, Any], rows: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    candidates = list(rows if rows is not None else _fetch_candidates())
    accounts = state.setdefault("candidate_accounts", [])
    stats = {"version": VERSION, "fetched": len(candidates), "eligible": 0, "created": 0, "updated": 0, "contact_ready": 0, "skipped": 0}
    ranked = sorted(candidates, key=lambda x: (int(x.get("demandSignal") or 0), int(x.get("score") or 0)), reverse=True)

    for row in ranked:
        if stats["created"] + stats["updated"] >= MAX_IMPORTS_PER_CYCLE:
            break
        if str(row.get("sourceId") or "") not in {"ted_eu_public_procurement", "uk_contracts_finder"}:
            stats["skipped"] += 1
            continue
        if int(row.get("demandSignal") or 0) != 1:
            stats["skipped"] += 1
            continue
        evidence = str(row.get("evidenceUrl") or "").strip()
        buyer = " ".join(str(row.get("buyer") or "").split())[:220]
        email = _email(row.get("buyerEmail"))
        website = str(row.get("buyerWebsite") or "").strip()
        if not evidence.startswith("https://") or not buyer or (not email and not website):
            stats["skipped"] += 1
            continue

        domain = _host(website) or _email_domain(email)
        contact_ready = bool(email and website and _same_domain(email, website))
        verified_company = bool(buyer and website and domain)
        stats["eligible"] += 1
        account = _find_account(accounts, str(row.get("opportunityId") or ""), email, domain)
        created = account is None
        if created:
            account = {
                "id": _account_id(str(row.get("opportunityId") or evidence)),
                "type": "buyer",
                "created_at": scout_connector.utcnow(),
            }
            accounts.append(account)

        evidence_refs = list(dict.fromkeys([
            evidence,
            website if website.startswith(("http://","https://")) else "",
            *list(account.get("commercial_contact_evidence") or []),
        ]))
        account.update({
            "name_hint": buyer,
            "company_name": buyer,
            "domain": domain,
            "official_url": website or account.get("official_url"),
            "category": str(row.get("fit") or "public procurement"),
            "source_url": website or evidence,
            "source_kind": "a2a_public_procurement_contact_bridge",
            "procurement_opportunity_id": row.get("opportunityId"),
            "procurement_remote_id": row.get("remoteId"),
            "procurement_source_id": row.get("sourceId"),
            "buyer_identifier": row.get("buyerIdentifier"),
            "buyer_contact_point": row.get("buyerContactPoint"),
            "buyer_country": row.get("buyerCountry"),
            "public_demand_hint": True,
            "demand_signal": True,
            "demand_status": "official_public_procurement_notice",
            "demand_score": max(90, int(row.get("score") or 0)),
            "demand_evidence_url": evidence,
            "demand_evidence_urls": [evidence],
            "high_intent_public_demand": True,
            "buyer_identity_resolved": True,
            "verified_company": verified_company,
            "verification_status": "verified_company_from_official_procurement_identity" if verified_company else "verification_required",
            "verification_score": max(int(account.get("verification_score") or 0), 92 if verified_company else 0),
            "commercial_email": email or account.get("commercial_email"),
            "commercial_channel_verified": contact_ready,
            "verified_contact": contact_ready,
            "contact_channel": "email" if contact_ready else account.get("contact_channel"),
            "contact_source_url": evidence,
            "commercial_contact_evidence": [x for x in evidence_refs if x][:8],
            "contact_policy": "public_corporate_channels_only",
            "contact_scope": "exact_public_procurement_notice_only",
            "controlled_outbound_only": True,
            "verified_public_procurement_contact": contact_ready,
            "direct_inbound_demand": False,
            "status": "demand_verified" if verified_company else "verification_required",
            "next_action": (
                "Preparar un único contacto no vinculante referido exclusivamente a la licitación pública verificada"
                if contact_ready else
                "Verificar identidad corporativa/canal antes de cualquier contacto"
            ),
            "updated_at": scout_connector.utcnow(),
        })
        if contact_ready:
            stats["contact_ready"] += 1
        stats["created" if created else "updated"] += 1

    state["a2a_procurement_contact_bridge"] = {
        **stats,
        "policy": "official_published_procurement_contacts_only_no_email_inference_one_time_controlled_outbound",
        "updated_at": scout_connector.utcnow(),
    }
    return stats


def _tick(state: Dict[str, Any]) -> Dict[str, Any]:
    base = dict(_ORIGINAL_SCOUT_TICK(state) or {})
    try:
        bridge = import_procurement_contacts(state)
    except Exception as exc:
        bridge = {"version": VERSION, "status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:220]}"}
    base["a2a_procurement_contact_bridge"] = bridge
    return base


scout_connector.scout_tick = _tick

print({
    "a2a_procurement_contact_bridge_runtime": {
        "version": VERSION,
        "status": "installed",
        "max_imports_per_cycle": MAX_IMPORTS_PER_CYCLE,
        "official_published_contacts_only": True,
        "creates_messages": False,
        "one_time_controlled_outbound_only": True,
        "binding_actions_human_gated": True,
    }
}, flush=True)
