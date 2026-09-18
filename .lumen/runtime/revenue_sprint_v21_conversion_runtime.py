from __future__ import annotations

"""LUMEN Revenue Sprint 2.1 conversion engine.

Closes three verified conversion gaps without widening commercial authority or spend:
1. Requirement Completion 2.1 may assemble the RFQ minimum from multiple *exactly linked*
   current official procurement sources, preserving source evidence per field and never inferring
   a missing value.
2. First Cash Case Binding gives each active First Cash mission team one concrete professional
   case linked by the team's exact buyer account id.
3. Reply Engine queues at most the existing follow-up cap and only after verified delivery,
   using one concrete question instead of a generic follow-up.

No contracts, purchases, payments, discounts, fabricated requirements or increased send/search
caps are authorized here.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import re

import commercial_truth_repair_runtime as truth
import mission_team_runtime
import outbound_engine
import professional_casework
import revenue_sprint_v2_runtime as sprint

VERSION = "2.1-conversion-focus"
MAX_FIRST_CASH_CASES = 3

_ORIGINAL_REQUIREMENT_BRIDGE = truth._apply_procurement_requirement_evidence
_ORIGINAL_LINK_CASES = mission_team_runtime._link_professional_cases
_ORIGINAL_QUEUE_FOLLOWUPS = outbound_engine._queue_followups


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _norm(value: Any) -> str:
    return _clean(value).lower()


def _short_evidence(text: Any, value: Any, limit: int = 420) -> str:
    raw = _clean(text)
    needle = _clean(value)
    if not raw:
        return needle[:limit]
    if needle:
        pos = raw.lower().find(needle.lower()[:80])
        if pos >= 0:
            start = max(0, pos - 120)
            return raw[start:start + limit]
    return raw[:limit]


def _accounts(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(x.get("id") or ""): x
        for x in state.get("candidate_accounts", []) or []
        if isinstance(x, dict) and x.get("id")
    }


def _opportunities(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(x.get("id") or ""): x
        for x in state.get("market_opportunities", []) or []
        if isinstance(x, dict) and x.get("id")
    }


def _interlocution_by_opp(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(x.get("opportunity_id") or ""): x
        for x in state.get("interlocution_cases", []) or []
        if isinstance(x, dict) and x.get("opportunity_id")
    }


def _exact_source_urls(state: Dict[str, Any], case: Dict[str, Any], opp: Dict[str, Any]) -> List[str]:
    """Only URLs already lineage-linked to this buyer/opportunity are eligible to fill fields."""
    urls = list(truth._candidate_urls(state, case, opp) or [])
    requirement = case.get("requirement", {}) or {}
    for value in requirement.get("public_procurement_evidence_urls", []) or []:
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            urls.append(value)
    value = opp.get("requirement_evidence_url")
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        urls.append(value)
    return list(dict.fromkeys(urls))


def _source_payload(signal: Dict[str, Any], cached: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    document_text = _clean(cached.get("text_excerpt"))
    signal_text = truth._signal_text(signal)
    combined = " ".join(x for x in (signal_text, document_text) if x)
    augmented = dict(signal)
    if document_text:
        base = _clean(signal.get("summary") or signal.get("snippet"))
        augmented["summary"] = (base + " " + document_text).strip()[:14000]
    return augmented, combined


def _extract_field(field: str, signal: Dict[str, Any], text: str) -> Optional[str]:
    if field == "technical_scope":
        # A scope must come from procurement language in the official source/document.
        return truth._extract_technical_scope(signal)
    if field == "quantity":
        return truth._extract_quantity(text)
    if field == "delivery_location":
        return truth._extract_delivery_location(text)
    return None


def _mark_ready(case: Dict[str, Any], opp: Dict[str, Any], urls: List[str]) -> None:
    requirement = case.setdefault("requirement", {})
    missing = [
        field for field in ("technical_scope", "quantity", "delivery_location")
        if requirement.get(field) in (None, "", [], {})
    ]
    case["missing_required_fields"] = missing
    if missing:
        return
    case["supplier_rfq_ready"] = True
    case["status"] = "ready_for_supplier_rfq"
    case["requirement_confirmation_basis"] = "multi_source_exact_official_procurement_evidence"
    case["next_action"] = "Solicitar ofertas comparables a proveedores validados"
    opp["requirement_confirmed"] = True
    opp["requirements_ready_for_rfq"] = True
    opp["requirement_confirmation_basis"] = "multi_source_exact_official_procurement_evidence"
    opp["requirement_evidence_urls"] = urls[-8:]
    opp["next_action"] = "Solicitar/normalizar ofertas comparables y completar economía real"
    opp["updated_at"] = _now()


def _multi_source_requirement_bridge(state: Dict[str, Any]) -> Dict[str, int]:
    base = dict(_ORIGINAL_REQUIREMENT_BRIDGE(state) or {})
    signals = truth._signal_map(state)
    cache = {
        str(x.get("url") or ""): x
        for x in state.get("procurement_document_cache", []) or []
        if isinstance(x, dict) and x.get("url")
    }
    opps = _opportunities(state)
    fields_added = 0
    cases_ready = 0
    sources_used: set[str] = set()
    cases_reviewed = 0

    for case in state.get("interlocution_cases", []) or []:
        if not isinstance(case, dict):
            continue
        opp = opps.get(str(case.get("opportunity_id") or ""), {})
        if not opp:
            continue
        urls = [url for url in _exact_source_urls(state, case, opp) if url in signals]
        if not urls:
            continue
        cases_reviewed += 1
        requirement = case.setdefault("requirement", {})
        field_evidence = requirement.setdefault("field_evidence", {})
        was_ready = bool(case.get("supplier_rfq_ready"))

        for field in ("technical_scope", "quantity", "delivery_location"):
            if requirement.get(field) not in (None, "", [], {}):
                continue
            for url in urls:
                signal = signals.get(url) or {}
                cached = cache.get(url) or {}
                augmented, text = _source_payload(signal, cached)
                value = _extract_field(field, augmented, text)
                if value in (None, ""):
                    continue
                requirement[field] = value
                field_evidence[field] = {
                    "source": "exact_linked_current_official_procurement",
                    "url": url,
                    "signal_id": signal.get("id"),
                    "value": value,
                    "evidence_excerpt": _short_evidence(text, value),
                    "document_text_used": bool(cached.get("text_excerpt")),
                    "captured_at": _now(),
                    "inference": False,
                }
                fields_added += 1
                sources_used.add(url)
                break

        requirement["public_procurement_evidence_urls"] = list(dict.fromkeys(
            list(requirement.get("public_procurement_evidence_urls", []) or []) + urls
        ))[-8:]
        requirement["multi_source_exact_evidence"] = True
        _mark_ready(case, opp, requirement["public_procurement_evidence_urls"])
        if case.get("supplier_rfq_ready") and not was_ready:
            cases_ready += 1

    report = {
        "version": VERSION,
        "status": "active",
        "cases_reviewed": cases_reviewed,
        "exact_fields_added": fields_added,
        "rfq_ready_delta": cases_ready,
        "exact_sources_used": len(sources_used),
        "base_matched": int(base.get("matched") or 0),
        "base_fields_added": int(base.get("fields_added") or 0),
        "base_rfq_ready": int(base.get("rfq_ready_from_official_evidence") or 0),
        "truth_rule": "each_field_requires_exact_linked_current_official_source_no_inference",
        "updated_at": _now(),
    }
    state["requirement_completion_v21"] = report
    # Preserve the legacy shape expected by reporting while including the new exact additions.
    return {
        "matched": max(int(base.get("matched") or 0), cases_reviewed),
        "fields_added": int(base.get("fields_added") or 0) + fields_added,
        "rfq_ready_from_official_evidence": int(base.get("rfq_ready_from_official_evidence") or 0) + cases_ready,
    }


def _first_cash_focus_ids(state: Dict[str, Any]) -> List[str]:
    return list(sprint._focus_opportunity_ids(state) or [])[:MAX_FIRST_CASH_CASES]


def _source_url_for_case(buyer: Dict[str, Any], opp: Dict[str, Any]) -> str:
    for value in list(opp.get("evidence_refs", []) or []) + list(buyer.get("demand_evidence_urls", []) or []):
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    for key in ("demand_evidence_url", "source_url", "official_url", "url"):
        value = buyer.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return ""


def _seed_first_cash_cases(state: Dict[str, Any]) -> int:
    focus = set(_first_cash_focus_ids(state))
    if not focus:
        return 0
    cases = state.setdefault("professional_cases", [])
    existing = {
        str(x.get("first_cash_opportunity_id") or ""): x
        for x in cases if isinstance(x, dict) and x.get("first_cash_opportunity_id")
    }
    opps = _opportunities(state)
    accounts = _accounts(state)
    teams = {
        str(x.get("opportunity_id") or ""): x
        for x in state.get("mission_teams", []) or []
        if isinstance(x, dict) and str(x.get("opportunity_id") or "") in focus
    }
    interlocution = _interlocution_by_opp(state)
    created = 0

    for oid in _first_cash_focus_ids(state):
        opp = opps.get(oid) or {}
        team = teams.get(oid) or {}
        buyer_id = str(opp.get("buyer_account_id") or team.get("buyer_account_id") or "")
        buyer = accounts.get(buyer_id) or {}
        if not buyer_id or not buyer:
            continue
        case = existing.get(oid)
        requirement_case = interlocution.get(oid) or {}
        requirement = requirement_case.get("requirement", {}) or {}
        if case is None:
            owner_id = str(team.get("lead_agent_id") or "")
            owner_role = "revops" if owner_id else "research_analyst"
            if not owner_id:
                member = next((m for m in team.get("members", []) or [] if m.get("role") == "research_analyst"), {})
                owner_id = str(member.get("agent_id") or "")
            title = _clean(team.get("buyer_name") or buyer.get("name_hint") or buyer.get("company") or buyer.get("domain") or buyer_id)
            category = _clean(team.get("category") or opp.get("category") or buyer.get("category") or "suministro industrial")
            source_url = _source_url_for_case(buyer, opp)
            case = {
                "id": f"CASE-FIRSTCASH-{oid}",
                "case_key": f"first_cash|{oid}",
                "subject_kind": "buyer",
                "source_kind": "first_cash_requirement",
                "source_id": buyer_id,
                "first_cash_opportunity_id": oid,
                "first_cash": True,
                "title": f"FIRST CASH · {title}"[:300],
                "category": category,
                "domain": _clean(buyer.get("domain")),
                "source_url": source_url,
                "owner_agent_id": owner_id,
                "owner_role": owner_role,
                "status": "active",
                "stage": "triage",
                "stage_index": 0,
                "progress_pct": 0,
                "cycles_worked": 0,
                "searches_used": 0,
                "evidence": [],
                "facts": {},
                "history": [],
                "missing": [],
                "next_action": "Completar alcance técnico, cantidad y lugar de entrega con evidencia exacta",
                "created_at": _now(),
                "last_worked_at": None,
            }
            cases.append(case)
            existing[oid] = case
            created += 1

        checklist = {
            "technical_scope": requirement.get("technical_scope") not in (None, "", [], {}),
            "quantity": requirement.get("quantity") not in (None, "", [], {}),
            "delivery_location": requirement.get("delivery_location") not in (None, "", [], {}),
            "supplier_rfq_ready": bool(requirement_case.get("supplier_rfq_ready")),
        }
        case["first_cash_requirement_checklist"] = checklist
        case["first_cash_missing_fields"] = [k for k in ("technical_scope", "quantity", "delivery_location") if not checklist[k]]
        case["opportunity_id"] = oid
        case["priority"] = 100
        case["updated_at"] = _now()
        # Seed traceable official evidence into the case without treating it as a completed requirement.
        known_urls = {str(x.get("url") or "") for x in case.get("evidence", []) or [] if isinstance(x, dict)}
        for url in list(opp.get("evidence_refs", []) or [])[:8]:
            if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in known_urls:
                case.setdefault("evidence", []).append({
                    "kind": "first_cash_official_procurement_link",
                    "url": url,
                    "captured_at": _now(),
                    "truth": "evidence_only_not_requirement_completion",
                })
                known_urls.add(url)

    state["first_cash_case_binding"] = {
        "version": VERSION,
        "status": "active",
        "focus_opportunities": _first_cash_focus_ids(state),
        "cases_created_this_tick": created,
        "cases_total": sum(1 for x in cases if isinstance(x, dict) and x.get("first_cash")),
        "authority_changed": False,
        "spend_changed": False,
        "updated_at": _now(),
    }
    return created


def _link_cases_with_first_cash(state: Dict[str, Any]) -> List[str]:
    _seed_first_cash_cases(state)
    focus_ids = list(_ORIGINAL_LINK_CASES(state) or [])
    first_cash_case_ids = {
        str(x.get("id") or "")
        for x in state.get("professional_cases", []) or []
        if isinstance(x, dict) and x.get("first_cash")
    }
    linked = [cid for cid in focus_ids if cid in first_cash_case_ids]
    binding = state.setdefault("first_cash_case_binding", {})
    binding["linked_focus_cases"] = len(linked)
    binding["linked_focus_case_ids"] = linked
    binding["updated_at"] = _now()
    return focus_ids


def _account_for_message(state: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    aid = str(source.get("counterparty_account_id") or "")
    return _accounts(state).get(aid, {})


def _reply_body(account: Dict[str, Any], source: Dict[str, Any]) -> str:
    kind = _norm(account.get("type"))
    category = _clean(source.get("category") or account.get("category") or "esta necesidad")
    if kind == "supplier":
        question = (
            f"¿Podrían confirmar si pueden cotizar {category} e indicar plazo de entrega? "
            "Con esa respuesta podemos evaluar el encaje comercial."
        )
    else:
        question = (
            f"¿Podrían confirmar especificación, cantidad y lugar de entrega para {category}? "
            "Con esos tres datos podemos preparar alternativas comparables."
        )
    return (
        "Hola, retomo con una sola consulta para no quitarles tiempo:\n\n"
        + question
        + "\n\nSi no corresponde o prefieren no recibir más mensajes de LUMEN, avísennos y lo cerramos de inmediato."
    )


def _queue_delivered_only_followups(state: Dict[str, Any]) -> int:
    if not outbound_engine.LIVE or outbound_engine.MAX_FOLLOWUPS_PER_CYCLE <= 0:
        return 0
    queued = 0
    skipped_not_delivered = 0
    eligible_delivered = 0
    outbox = state.setdefault("outbox", [])
    seq_index = {str(x.get("id") or ""): x for x in state.setdefault("outbound_sequences", [])}

    for rel in state.get("commercial_relationships", []) or []:
        if queued >= outbound_engine.MAX_FOLLOWUPS_PER_CYCLE:
            break
        if not rel.get("follow_up_due") or rel.get("opted_out") or rel.get("relationship_state") != "follow_up_due":
            continue
        contact = str(rel.get("commercial_email") or "").strip().lower()
        if not contact or outbound_engine._suppressed(state, contact) or outbound_engine._pending_followup(state, contact):
            continue
        source = outbound_engine._latest_engine_sent(state, contact)
        if not source:
            continue
        delivered = bool(source.get("delivery_verified") or source.get("delivered_at"))
        if not delivered:
            skipped_not_delivered += 1
            continue
        if rel.get("last_inbound_at") or rel.get("replied") or source.get("reply_detected"):
            continue
        eligible_delivered += 1
        seq_id = str(source.get("outbound_sequence_id") or "")
        seq = seq_index.get(seq_id, {})
        step = min(3, int(rel.get("follow_up_count") or 0) + 2)
        msg_id = f"OUT-{len(outbox)+1:05d}"
        account = _account_for_message(state, source)
        outbox.append({
            "id": msg_id,
            "kind": "follow_up",
            "counterparty": source.get("counterparty"),
            "counterparty_account_id": source.get("counterparty_account_id"),
            "channel": "email",
            "contact": contact,
            "contact_verified": True,
            "subject": ("Consulta puntual · " + str(source.get("category") or source.get("subject") or "LUMEN"))[:180],
            "body": _reply_body(account, source),
            "category": source.get("category"),
            "status": "ready",
            "source": "outbound_engine",
            "outbound_sequence_id": seq_id,
            "sequence_step": step,
            "parent_outbox_id": source.get("id"),
            "campaign_id": source.get("campaign_id"),
            "variant_id": source.get("variant_id"),
            "tracking_url": source.get("tracking_url"),
            "reply_engine_version": VERSION,
            "followup_basis": "verified_delivery_no_reply",
            "outbound_local_day": outbound_engine.local_day(),
            "created_at": outbound_engine.utcnow(),
        })
        if seq:
            seq.setdefault("message_ids", []).append(msg_id)
            seq["status"] = "follow_up_queued"
            seq["updated_at"] = outbound_engine.utcnow()
        queued += 1

    state["reply_engine_v21"] = {
        "version": VERSION,
        "status": "active",
        "eligible_verified_delivered_no_reply": eligible_delivered,
        "queued_this_tick": queued,
        "skipped_not_verified_delivered": skipped_not_delivered,
        "max_followups_per_cycle_unchanged": outbound_engine.MAX_FOLLOWUPS_PER_CYCLE,
        "new_message_cap_unchanged": outbound_engine.MAX_NEW_PER_CYCLE,
        "paid_spend": False,
        "updated_at": _now(),
    }
    return queued


# Install patches once. They are deliberately narrow and preserve the surrounding engines/gates.
if not getattr(truth, "_lumen_requirement_completion_v21_installed", False):
    truth._apply_procurement_requirement_evidence = _multi_source_requirement_bridge
    truth._lumen_requirement_completion_v21_installed = True

if not getattr(mission_team_runtime, "_lumen_first_cash_case_binding_installed", False):
    mission_team_runtime._link_professional_cases = _link_cases_with_first_cash
    mission_team_runtime._lumen_first_cash_case_binding_installed = True

if not getattr(outbound_engine, "_lumen_reply_engine_v21_installed", False):
    outbound_engine._queue_followups = _queue_delivered_only_followups
    outbound_engine._lumen_reply_engine_v21_installed = True

print({
    "revenue_sprint_v21_conversion_runtime": {
        "version": VERSION,
        "status": "installed",
        "multi_source_exact_requirement_completion": True,
        "first_cash_case_binding": True,
        "verified_delivery_only_followups": True,
        "search_spend_increased": False,
        "outbound_caps_increased": False,
        "binding_authority_changed": False,
    }
}, flush=True)
