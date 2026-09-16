from __future__ import annotations

"""LUMEN conversion unblocking runtime.

Keeps truth/evidence gates intact while removing three avoidable stalls:
- research/discovery platforms becoming commercial counterparties;
- requiring closing-level fields before an exploratory supplier RFQ;
- one-shot buyer requirement outreach that can leave a case idle forever.

All actions remain non-binding. No requirement, quote, reply, delivery or revenue is fabricated.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import company_verifier
import commercial_execution
import interlocutor_engine
import lead_intelligence
import mission_team_runtime

VERSION = "1.0-conversion-unblock"
RFQ_MINIMUM_FIELDS = ["technical_scope", "quantity", "delivery_location"]
RFQ_OPTIONAL_FIELDS = [
    "delivery_target",
    "commercial_terms",
    "accepted_alternatives",
    "required_documentation",
    "warranty_requirement",
    "budget_reference",
    "currency",
]
BUYER_REQUIREMENT_MAX_ATTEMPTS = 2
BUYER_REQUIREMENT_FOLLOWUP_HOURS = 72

RESEARCH_ONLY_DOMAINS = {
    "google.com", "google.com.ar", "bing.com", "yahoo.com", "duckduckgo.com",
    "linkedin.com", "facebook.com", "instagram.com", "tiktok.com", "youtube.com",
    "x.com", "twitter.com", "reddit.com", "pinterest.com", "wikipedia.org",
    "indeed.com", "glassdoor.com", "zonajobs.com.ar", "computrabajo.com",
    "bumeran.com.ar", "mercadolibre.com", "mercadolibre.com.ar", "amazon.com",
}


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _is_research_only_domain(domain: Any) -> bool:
    host = str(domain or "").strip().lower().removeprefix("www.")
    return any(host == blocked or host.endswith("." + blocked) for blocked in RESEARCH_ONLY_DOMAINS)


def _quarantine_research_sources(state: Dict[str, Any]) -> int:
    quarantined: set[str] = set()
    for account in state.get("candidate_accounts", []) or []:
        if not isinstance(account, dict) or not _is_research_only_domain(account.get("domain")):
            continue
        aid = str(account.get("id") or "")
        if aid:
            quarantined.add(aid)
        account.update({
            "commercial_target_eligible": False,
            "status": "research_source_only",
            "verification_status": "research_source_only",
            "verified_company": False,
            "verified_contact": False,
            "commercial_channel_verified": False,
            "next_action": "Conservar como fuente de investigación; no tratar como contraparte comercial",
            "research_source_only": True,
            "research_source_quarantined_at": account.get("research_source_quarantined_at") or _now(),
        })

    if quarantined:
        for opp in state.get("market_opportunities", []) or []:
            if not isinstance(opp, dict):
                continue
            if str(opp.get("buyer_account_id") or "") in quarantined or str(opp.get("supplier_account_id") or "") in quarantined:
                opp.update({
                    "status": "quarantined_research_source",
                    "ready_for_deal": False,
                    "requirement_confirmed": False,
                    "portfolio_priority_score": 0.0,
                    "next_action": "Descartar como objetivo comercial; conservar solamente la evidencia de investigación",
                    "truth_quarantine_reason": "research_source_is_not_commercial_counterparty",
                })
    return len(quarantined)


# 1) Prevent discovery/search/social/job platforms from becoming new commercial accounts.
_ORIGINAL_SCORE_LEAD = lead_intelligence.score_lead
lead_intelligence.LOW_QUALITY_HOST_HINTS.update(RESEARCH_ONLY_DOMAINS)


def _score_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(_ORIGINAL_SCORE_LEAD(lead))
    domain = str(result.get("domain") or "").lower()
    if _is_research_only_domain(domain):
        result.update({
            "lead_score": 0,
            "tier": "D",
            "qualification_status": "rejected_noise",
            "next_research_action": "Usar como fuente de descubrimiento, nunca como empresa objetivo",
            "confidence": 0.95,
        })
        reasons = ["Plataforma de investigación/descubrimiento; no es una contraparte comercial objetivo"]
        reasons.extend(list(result.get("qualification_reasons") or []))
        result["qualification_reasons"] = reasons[:8]
    return result


lead_intelligence.score_lead = _score_lead
_ORIGINAL_QUALIFY_TICK = lead_intelligence.qualify_tick


def _qualify_tick(state: Dict[str, Any]) -> Dict[str, int]:
    before = _quarantine_research_sources(state)
    report = dict(_ORIGINAL_QUALIFY_TICK(state) or {})
    after = _quarantine_research_sources(state)
    report["research_sources_quarantined"] = max(before, after)
    return report


lead_intelligence.qualify_tick = _qualify_tick


# 2) Do not waste verification fetches on accounts already known to be research-only platforms.
_ORIGINAL_VERIFICATION_TICK = company_verifier.verification_tick


def _verification_tick(state: Dict[str, Any]) -> Dict[str, int]:
    _quarantine_research_sources(state)
    report = dict(_ORIGINAL_VERIFICATION_TICK(state) or {})
    report["research_sources_quarantined"] = _quarantine_research_sources(state)
    return report


company_verifier.verification_tick = _verification_tick


# 3) Separate the minimum evidence needed to ask suppliers for a quote from closing-level fields.
# Technical scope + quantity + destination are mandatory for an exploratory comparable RFQ.
# Delivery target and commercial terms remain desirable and are requested/normalized from suppliers,
# but no longer block the RFQ itself.
interlocutor_engine.REQUIRED_REQUIREMENT_FIELDS = list(RFQ_MINIMUM_FIELDS)
interlocutor_engine.OPTIONAL_REQUIREMENT_FIELDS = list(RFQ_OPTIONAL_FIELDS)


def _buyer_evidence_satisfies_rfq(requirement: Dict[str, Any]) -> bool:
    has_buyer_evidence = bool(
        requirement.get("confirmed_by_buyer")
        or requirement.get("evidence_message_ids")
        or str(requirement.get("source") or "").startswith("buyer_")
    )
    return has_buyer_evidence and all(requirement.get(k) not in (None, "", [], {}) for k in RFQ_MINIMUM_FIELDS)


def _promote_existing_buyer_evidence(state: Dict[str, Any]) -> int:
    promoted = 0
    opportunities = commercial_execution._opportunities(state)
    for case in state.get("interlocution_cases", []) or []:
        if not isinstance(case, dict):
            continue
        requirement = case.setdefault("requirement", {})
        if not _buyer_evidence_satisfies_rfq(requirement):
            continue
        if not requirement.get("confirmed_by_buyer"):
            promoted += 1
        requirement["confirmed_by_buyer"] = True
        requirement["confirmed_at"] = requirement.get("confirmed_at") or requirement.get("last_buyer_evidence_at") or _now()
        missing = interlocutor_engine._missing(requirement)
        case["missing_required_fields"] = missing
        case["requirement_completeness"] = interlocutor_engine._completeness(requirement)
        case["buyer_questions"] = interlocutor_engine._questions(missing)
        case["supplier_rfq_ready"] = not missing
        if not missing:
            case["status"] = "ready_for_supplier_rfq"
            case["next_action"] = "Solicitar ofertas comparables a proveedores validados"
            opp = opportunities.get(str(case.get("opportunity_id") or ""), {})
            if opp:
                opp["requirement_confirmed"] = True
                opp["requirements_ready_for_rfq"] = True
                opp["next_action"] = "Solicitar/normalizar ofertas comparables y completar economía real"
                opp["updated_at"] = _now()
    return promoted


_ORIGINAL_INTERLOCUTOR_TICK = interlocutor_engine.interlocutor_tick


def _interlocutor_tick(state: Dict[str, Any]) -> Dict[str, int]:
    promoted_before = _promote_existing_buyer_evidence(state)
    report = dict(_ORIGINAL_INTERLOCUTOR_TICK(state) or {})
    promoted_after = _promote_existing_buyer_evidence(state)
    report["buyer_evidence_promoted_to_rfq"] = max(promoted_before, promoted_after)
    report["requirement_ready"] = sum(1 for x in state.get("interlocution_cases", []) or [] if x.get("supplier_rfq_ready"))
    report["awaiting_details"] = sum(1 for x in state.get("interlocution_cases", []) or [] if not x.get("supplier_rfq_ready"))
    return report


interlocutor_engine.interlocutor_tick = _interlocutor_tick


# Commercial Execution has a historical hard-coded five-field gate; reconcile it to the same
# evidence-preserving RFQ minimum after parsing a real buyer reply.
_ORIGINAL_APPLY_BUYER_REPLY = commercial_execution._apply_buyer_reply_to_requirement


def _apply_buyer_reply_to_requirement(state: Dict[str, Any], incoming: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(_ORIGINAL_APPLY_BUYER_REPLY(state, incoming, source) or {})
    case_id = str(source.get("interlocution_case_id") or "")
    case = next((x for x in state.get("interlocution_cases", []) or [] if str(x.get("id") or "") == case_id), None)
    if not case:
        return result
    requirement = case.setdefault("requirement", {})
    missing = [k for k in RFQ_MINIMUM_FIELDS if requirement.get(k) in (None, "", [], {})]
    case["missing_required_fields"] = missing
    case["requirement_completeness"] = interlocutor_engine._completeness(requirement)
    case["buyer_questions"] = interlocutor_engine._questions(missing)
    if not missing and _buyer_evidence_satisfies_rfq(requirement):
        requirement["confirmed_by_buyer"] = True
        requirement["confirmed_at"] = requirement.get("confirmed_at") or incoming.get("received_at") or _now()
        case["supplier_rfq_ready"] = True
        case["status"] = "ready_for_supplier_rfq"
        case["next_action"] = "Solicitar ofertas comparables a proveedores validados"
        opportunity = commercial_execution._opportunities(state).get(str(case.get("opportunity_id") or ""), {})
        if opportunity:
            opportunity["requirement_confirmed"] = True
            opportunity["requirements_ready_for_rfq"] = True
            opportunity["next_action"] = "Solicitar/normalizar ofertas comparables y completar economía real"
            opportunity["updated_at"] = _now()
        result["requirement_ready"] = True
    else:
        result["requirement_ready"] = False
    return result


commercial_execution._apply_buyer_reply_to_requirement = _apply_buyer_reply_to_requirement


# 4) Replace the one-shot requirement request dead-end with one bounded, delayed follow-up.
# If a buyer is still silent after that, the case is kept truthful but marked for rotation instead
# of burning every cycle on the same no-op.
_ORIGINAL_DRIVE_CASE = commercial_execution._drive_case


def _buyer_requirement_rows(state: Dict[str, Any], revops_id: str) -> List[Dict[str, Any]]:
    return [
        x for x in state.get("outbox", []) or []
        if str(x.get("revops_case_id") or "") == str(revops_id)
        and str(x.get("kind") or "") == "buyer_requirement_request"
    ]


def _drive_case(state: Dict[str, Any], revops: Dict[str, Any], message_budget: List[int]) -> Dict[str, Any]:
    interlocution = next((x for x in state.get("interlocution_cases", []) or [] if str(x.get("id") or "") == str(revops.get("interlocution_case_id") or "")), {})
    if not interlocution or interlocution.get("supplier_rfq_ready"):
        return _ORIGINAL_DRIVE_CASE(state, revops, message_budget)

    buyer = commercial_execution._buyer_account_for_case(state, interlocution)
    contact, verified, channel = commercial_execution._account_contact(buyer)
    opportunity_id = str(interlocution.get("opportunity_id") or "")
    opportunity = commercial_execution._opportunities(state).get(opportunity_id, {})
    rows = _buyer_requirement_rows(state, str(revops.get("id") or ""))

    if channel != "email" or not verified or not contact:
        revops["status"] = "requirement_blocked_contact"
        revops["next_action"] = "verify_buyer_contact_or_rotate_focus"
        revops["conversion_blocker"] = "buyer_verified_email_unavailable"
        opportunity["conversion_blocker"] = "buyer_verified_email_unavailable"
        opportunity["next_action"] = "Validar un canal corporativo del comprador o rotar foco a una oportunidad accionable"
        return {"action": revops["next_action"], "created": 0}

    if not rows:
        return _ORIGINAL_DRIVE_CASE(state, revops, message_budget)

    last = rows[-1]
    last_status = str(last.get("status") or "").lower()
    sent_at = _parse(last.get("sent_at") or last.get("delivered_at"))
    revops["buyer_requirement_attempts"] = len(rows)

    # Do not stack follow-ups behind an unsent/failed first request; transport/recovery owns that.
    if last_status not in {"sent", "delivered", "delivery_verified", "replied"} or not sent_at:
        revops["status"] = "waiting_requirement_delivery"
        revops["next_action"] = "wait_for_requirement_request_delivery"
        return {"action": revops["next_action"], "created": 0}

    age = _now_dt() - sent_at
    if len(rows) < BUYER_REQUIREMENT_MAX_ATTEMPTS and age >= timedelta(hours=BUYER_REQUIREMENT_FOLLOWUP_HOURS) and message_budget[0] > 0:
        attempt = len(rows) + 1
        deal = commercial_execution._deal_for_opportunity(state, opportunity_id)
        deal_id = str(deal.get("id") or revops.get("deal_id") or "") or None
        body = (
            "Retomamos esta consulta para no avanzar con supuestos. Si el requerimiento sigue vigente, "
            "con confirmar los puntos pendientes de abajo alcanza para pedir cotizaciones comparables.\n\n"
            + commercial_execution._buyer_requirement_body(interlocution)
        )
        key = f"buyer_requirement|{revops['id']}|v{attempt}"
        created = commercial_execution._message(
            state,
            execution_key=key,
            kind="buyer_requirement_request",
            counterparty=commercial_execution._counterparty_name(buyer),
            contact=str(contact),
            contact_verified=True,
            subject=f"Seguimiento breve — requerimiento de {interlocution.get('category') or 'suministro'}",
            body=body,
            deal_id=deal_id,
            revops_case_id=str(revops.get("id") or ""),
            interlocution_case_id=str(interlocution.get("id") or ""),
            opportunity_id=opportunity_id,
            counterparty_account_id=str(buyer.get("id") or "") or None,
            purpose="requirement_discovery_followup",
        )
        if created:
            message_budget[0] -= 1
            commercial_execution._case_history(
                revops,
                "buyer_requirement_followup_prepared",
                f"Seguimiento {attempt}/{BUYER_REQUIREMENT_MAX_ATTEMPTS} preparado tras {BUYER_REQUIREMENT_FOLLOWUP_HOURS}h sin completar requisitos mínimos.",
            )
            revops["status"] = "requirement_followup"
            revops["next_action"] = "deliver_bounded_requirement_followup"
            return {"action": revops["next_action"], "created": 1}

    if len(rows) >= BUYER_REQUIREMENT_MAX_ATTEMPTS:
        revops["status"] = "waiting_buyer_response_rotatable"
        revops["next_action"] = "rotate_focus_until_buyer_reply"
        revops["conversion_blocker"] = "buyer_response_pending_after_bounded_followup"
        opportunity["conversion_blocker"] = "buyer_response_pending_after_bounded_followup"
        opportunity["next_action"] = "Mantener seguimiento pasivo y priorizar otra oportunidad accionable hasta recibir respuesta"
        return {"action": revops["next_action"], "created": 0}

    revops["status"] = "waiting_buyer_response"
    revops["next_action"] = "wait_before_bounded_followup"
    return {"action": revops["next_action"], "created": 0}


commercial_execution._drive_case = _drive_case
_ORIGINAL_COMMERCIAL_TICK = commercial_execution.commercial_execution_tick


def _commercial_execution_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    quarantined = _quarantine_research_sources(state)
    promoted = _promote_existing_buyer_evidence(state)
    report = dict(_ORIGINAL_COMMERCIAL_TICK(state) or {})
    report["research_sources_quarantined"] = quarantined
    report["existing_buyer_evidence_promoted"] = promoted
    report["conversion_unblock_version"] = VERSION
    return report


commercial_execution.commercial_execution_tick = _commercial_execution_tick


# 5) Mission Teams should prefer actionable opportunities instead of keeping the same silent/no-contact
# cases in all active slots. Evidence score is still the tie-breaker; truth gates are unchanged.
_ORIGINAL_CANONICAL_OPPORTUNITIES = mission_team_runtime._canonical_opportunities


def _canonical_opportunities(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = list(_ORIGINAL_CANONICAL_OPPORTUNITIES(state))
    accounts = {
        str(x.get("id") or ""): x
        for x in state.get("candidate_accounts", []) or []
        if isinstance(x, dict) and x.get("id")
    }
    teams = {
        str(x.get("opportunity_id") or ""): x
        for x in state.get("mission_teams", []) or []
        if isinstance(x, dict) and x.get("opportunity_id")
    }

    def key(opp: Dict[str, Any]):
        oid = str(opp.get("id") or "")
        if mission_team_runtime._requirement_ready(state, opp):
            bucket = 0
        else:
            buyer = accounts.get(str(opp.get("buyer_account_id") or ""), {})
            has_contact = bool(buyer.get("verified_contact") and buyer.get("commercial_email"))
            requests = [
                x for x in state.get("outbox", []) or []
                if str(x.get("opportunity_id") or "") == oid
                and str(x.get("kind") or "") == "buyer_requirement_request"
            ]
            if has_contact and not requests:
                bucket = 1  # immediately actionable: request has not been made yet
            elif has_contact and requests:
                bucket = 2  # waiting/follow-up path; keep, but rotate behind untouched actionable work
            else:
                bucket = 3  # contact verification required
        stagnant = int((teams.get(oid) or {}).get("stagnant_cycles") or 0)
        score = float(opp.get("portfolio_priority_score") or opp.get("score") or 0)
        return (bucket, stagnant, -score, oid)

    rows.sort(key=key)
    return rows


mission_team_runtime._canonical_opportunities = _canonical_opportunities
_ORIGINAL_MISSION_TEAM_TICK = mission_team_runtime.mission_team_tick


def _mission_team_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_MISSION_TEAM_TICK(state) or {})
    general_remaining = int(((state.get("search_budget") or {}).get("general_queries_remaining") or 0))
    if general_remaining <= 0:
        for team in state.get("mission_teams", []) or []:
            if team.get("status") == "active" and int(team.get("stagnant_cycles") or 0) >= mission_team_runtime.STAGNATION_ESCALATION_CYCLES:
                team["escalation"] = {
                    "status": "auto_escalated_nonbinding",
                    "at": _now(),
                    "reason": "stage stalled while public search budget is unavailable",
                    "action": "use stored evidence, execute bounded contact/follow-up, and rotate attention rather than repeat no-op research",
                }
        report["budget_exhausted_rotation_policy"] = True
    report["conversion_unblock_version"] = VERSION
    state["mission_team_control"] = report
    return report


mission_team_runtime.mission_team_tick = _mission_team_tick

print({
    "conversion_unblock_runtime": {
        "version": VERSION,
        "status": "active",
        "rfq_minimum_fields": RFQ_MINIMUM_FIELDS,
        "buyer_requirement_max_attempts": BUYER_REQUIREMENT_MAX_ATTEMPTS,
        "buyer_requirement_followup_hours": BUYER_REQUIREMENT_FOLLOWUP_HOURS,
        "research_source_quarantine": True,
        "mission_rotation": True,
        "truth_gates_preserved": True,
        "binding_authority_changed": False,
    }
}, flush=True)
