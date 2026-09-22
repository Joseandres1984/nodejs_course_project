from __future__ import annotations

"""Keep Deep Work focused on commercial entities instead of research platforms.

This runtime only changes attention/allocation. It preserves source evidence and never deletes
historical cases. Clearly non-commercial cases are parked for audit/research so worker capacity can
move to companies, buyers, suppliers and official procurement evidence with a credible path to an
identified counterparty.
"""

import re
import urllib.parse
from typing import Any, Dict, List

import mission_team_runtime
import professional_casework

VERSION = "1.1-casework-hygiene"

RESEARCH_ONLY_DOMAINS = {
    "google.com", "google.com.ar", "bing.com", "yahoo.com", "duckduckgo.com",
    "linkedin.com", "facebook.com", "instagram.com", "tiktok.com", "youtube.com",
    "x.com", "twitter.com", "reddit.com", "pinterest.com", "wikipedia.org",
    "indeed.com", "indeed.com.ar", "glassdoor.com", "glassdoor.com.ar",
    "zonajobs.com.ar", "computrabajo.com", "computrabajo.com.ar", "bumeran.com.ar",
    "halaxia.com",
    "catalogoindustrial.com.ar",
    "mercadolibre.com", "mercadolibre.com.ar", "amazon.com",
}

# These are signals that a search result is employment/recruiting evidence, not purchase demand.
# They are applied only to unverified research leads/cases; verified companies and verified demand
# are never discarded merely because a careers page exists.
JOB_TERMS = (
    " empleo ", " empleos ", " vacante ", " vacantes ", " puesto ", " puestos ",
    " búsqueda laboral ", " busqueda laboral ", " oportunidad laboral ", " career ", " careers ",
    " hiring ", " job ", " jobs ", " analista de compras ", " especialista de instrumentación ",
    " especialista de instrumentacion ",
)

DEMAND_TERMS = (
    "licitación", "licitacion", "cotización", "cotizacion", "solicitud de cotización",
    "solicitud de cotizacion", "solicitud de oferta", "concurso de precios", "pliego",
    "adquisición", "adquisicion", "contratación", "contratacion", "rfq", "procurement",
)

BAD_STATUSES = {
    "rejected_noise", "research_source_only", "quarantined_research_source",
    "identity_unresolved_max_attempts",
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _host(value: Any) -> str:
    text = _clean(value).lower()
    if not text:
        return ""
    if "://" not in text and "/" not in text:
        return text.removeprefix("www.")
    try:
        return (urllib.parse.urlparse(text).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _blocked_host(host: str) -> bool:
    host = _host(host)
    return any(host == item or host.endswith("." + item) for item in RESEARCH_ONLY_DOMAINS)


def _text(source: Dict[str, Any]) -> str:
    return " " + _clean(" ".join(str(source.get(k) or "") for k in ("title", "name_hint", "snippet", "source_url", "url"))).lower() + " "


def _job_only_source(source: Dict[str, Any]) -> bool:
    if source.get("verified_company") or source.get("demand_signal") or source.get("public_demand_hint"):
        return False
    text = _text(source)
    has_job = any(term in text for term in JOB_TERMS)
    has_demand = any(term in text for term in DEMAND_TERMS)
    return bool(has_job and not has_demand)


def _research_only(source: Dict[str, Any]) -> bool:
    if not isinstance(source, dict):
        return False
    # A first-party inbound buyer explicitly asking LUMEN for help is never suppressed by this filter.
    if source.get("direct_inbound_demand"):
        return False
    if source.get("research_source_only") or source.get("commercial_target_eligible") is False:
        return True
    if str(source.get("tier") or "").upper() == "D":
        return True
    status = str(source.get("qualification_status") or source.get("status") or "").strip().lower()
    if status in BAD_STATUSES:
        return True
    host = _host(source.get("domain") or source.get("source_url") or source.get("url"))
    if _blocked_host(host):
        return True
    return _job_only_source(source)


def _source_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for key in ("candidate_accounts", "research_leads"):
        for row in state.get(key, []) or []:
            if isinstance(row, dict) and row.get("id"):
                rows[str(row["id"])] = row
    return rows


def _park_case(case: Dict[str, Any], reason: str) -> None:
    case["status"] = "parked"
    case["research_source_only"] = True
    case["commercial_attention_eligible"] = False
    case["park_reason"] = reason
    case["next_action"] = "Conservar como evidencia de investigación; no consumir capacidad comercial hasta existir una contraparte real verificable"
    case["mission_team_priority"] = 0
    case["mission_team_ids"] = []
    history = case.setdefault("history", [])
    marker = "casework_hygiene_parked"
    if not any(str(x.get("event") or "") == marker for x in history if isinstance(x, dict)):
        history.append({
            "stage": case.get("stage"),
            "event": marker,
            "detail": reason,
        })


def sanitize_casework(state: Dict[str, Any]) -> Dict[str, int]:
    sources = _source_map(state)
    parked = 0
    leads_reclassified = 0

    # Reclassify old leads that were qualified before the stricter lead filter existed. Preserve them
    # as research evidence; this does not delete or rewrite their original URL/title/snippet.
    for lead in state.get("research_leads", []) or []:
        if not isinstance(lead, dict) or lead.get("direct_inbound_demand"):
            continue
        if not _research_only(lead):
            continue
        if str(lead.get("qualification_status") or "") != "rejected_noise" or str(lead.get("tier") or "").upper() != "D":
            leads_reclassified += 1
        lead["tier"] = "D"
        lead["qualification_status"] = "rejected_noise"
        lead["research_source_only"] = True
        lead["commercial_target_eligible"] = False
        lead["next_research_action"] = "Conservar solo como señal/contexto de investigación; no promover a contraparte comercial"

    parked_ids: set[str] = set()
    for case in state.get("professional_cases", []) or []:
        if not isinstance(case, dict):
            continue
        source = sources.get(str(case.get("source_id") or ""), {})
        case_host = _host(case.get("domain") or case.get("source_url"))
        case_is_blocked = _blocked_host(case_host)
        if source and _research_only(source):
            reason = "La fuente original es una plataforma/resultado de investigación y no una contraparte comercial accionable."
        elif case_is_blocked:
            reason = "El expediente apunta a una plataforma de investigación, red social, directorio o portal laboral, no a una contraparte comercial."
        elif not source and _job_only_source({"title": case.get("title"), "source_url": case.get("source_url")}):
            reason = "El expediente histórico representa una señal laboral, no evidencia suficiente de intención de compra."
        else:
            continue
        if case.get("status") != "parked" or not case.get("research_source_only"):
            parked += 1
        _park_case(case, reason)
        if case.get("id"):
            parked_ids.add(str(case["id"]))

    # Preserve old handoffs for audit, but make sure a quarantined source cannot be handed to RevOps.
    for row in state.get("professional_case_handoffs", []) or []:
        if isinstance(row, dict) and str(row.get("case_id") or "") in parked_ids:
            row["status"] = "quarantined_research_source"
            row["reason"] = "casework_hygiene_noncommercial_source"

    # Remove parked historical cases from active mission-team focus without deleting history.
    if parked_ids:
        focus = [str(x) for x in state.get("mission_team_focus_case_ids", []) or [] if str(x) not in parked_ids]
        state["mission_team_focus_case_ids"] = focus
        for team in state.get("mission_teams", []) or []:
            if isinstance(team, dict):
                team["focus_case_ids"] = [str(x) for x in team.get("focus_case_ids", []) or [] if str(x) not in parked_ids]

    stats = {
        "parked_this_tick": parked,
        "parked_total": sum(1 for x in state.get("professional_cases", []) or [] if isinstance(x, dict) and x.get("research_source_only")),
        "historical_leads_reclassified": leads_reclassified,
    }
    state["casework_hygiene"] = {"version": VERSION, **stats}
    return stats


_ORIGINAL_ELIGIBLE_SOURCES = professional_casework._eligible_sources


def _eligible_sources(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    sanitize_casework(state)
    rows = list(_ORIGINAL_ELIGIBLE_SOURCES(state) or [])
    return [row for row in rows if not _research_only(row.get("source") or {})]


professional_casework._eligible_sources = _eligible_sources

_ORIGINAL_SYNC_CASES = professional_casework._sync_cases


def _sync_cases(state: Dict[str, Any]) -> int:
    sanitize_casework(state)
    created = int(_ORIGINAL_SYNC_CASES(state) or 0)
    sanitize_casework(state)
    return created


professional_casework._sync_cases = _sync_cases

_ORIGINAL_WORK_CASE = professional_casework._work_case


def _work_case(state: Dict[str, Any], case: Dict[str, Any], cycle_searches: Dict[str, int]) -> str:
    source = _source_map(state).get(str(case.get("source_id") or ""), {})
    if (source and _research_only(source)) or _blocked_host(_host(case.get("domain") or case.get("source_url"))):
        _park_case(case, "Fuente no comercial detectada antes de asignar trabajo profundo.")
        return "parked"
    return _ORIGINAL_WORK_CASE(state, case, cycle_searches)


professional_casework._work_case = _work_case

_ORIGINAL_LINK_CASES = mission_team_runtime._link_professional_cases


def _link_professional_cases(state: Dict[str, Any]) -> List[str]:
    sanitize_casework(state)
    focus = list(_ORIGINAL_LINK_CASES(state) or [])
    parked = {
        str(x.get("id") or "") for x in state.get("professional_cases", []) or []
        if isinstance(x, dict) and (x.get("status") == "parked" or x.get("research_source_only"))
    }
    filtered = [str(x) for x in focus if str(x) not in parked]
    state["mission_team_focus_case_ids"] = filtered
    for case in state.get("professional_cases", []) or []:
        if isinstance(case, dict) and str(case.get("id") or "") in parked:
            case["mission_team_priority"] = 0
            case["mission_team_ids"] = []
    for team in state.get("mission_teams", []) or []:
        if isinstance(team, dict):
            team["focus_case_ids"] = [str(x) for x in team.get("focus_case_ids", []) or [] if str(x) not in parked]
    return filtered


mission_team_runtime._link_professional_cases = _link_professional_cases

print({
    "casework_hygiene_runtime": {
        "version": VERSION,
        "status": "active",
        "research_platforms_are_evidence_not_counterparties": True,
        "job_posts_are_not_purchase_demand": True,
        "official_procurement_evidence_preserved": True,
        "historical_cases_preserved_for_audit": True,
        "binding_authority_changed": False,
    }
}, flush=True)
