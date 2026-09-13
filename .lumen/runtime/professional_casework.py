from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import agent_fleet
import scout_connector


MAX_ACTIVE_CASES = max(10, min(150, int(os.getenv("LUMEN_DEEP_WORK_MAX_ACTIVE_CASES", "60"))))
MAX_CASES_PER_CYCLE = max(1, min(60, int(os.getenv("LUMEN_DEEP_WORK_CASES_PER_CYCLE", "18"))))
MAX_NEW_CASES_PER_CYCLE = max(1, min(30, int(os.getenv("LUMEN_DEEP_WORK_NEW_CASES_PER_CYCLE", "12"))))
MAX_SEARCHES_PER_CYCLE = max(0, min(12, int(os.getenv("LUMEN_DEEP_WORK_SEARCHES_PER_CYCLE", "6"))))
DAILY_SEARCH_CAP = max(0, min(100, int(os.getenv("LUMEN_DEEP_WORK_DAILY_SEARCH_CAP", "14"))))
MAX_EVIDENCE_PER_CASE = max(8, min(80, int(os.getenv("LUMEN_DEEP_WORK_MAX_EVIDENCE", "30"))))

BUYER_STAGES = ["triage", "identity", "demand", "contact", "supplier_match", "thesis"]
SUPPLIER_STAGES = ["triage", "identity", "capability", "contact", "buyer_fit", "thesis"]
DEMAND_TERMS = (
    "compras", "abastecimiento", "licitación", "licitacion", "cotización", "cotizacion",
    "pliego", "adquisición", "adquisicion", "mantenimiento", "proveedores", "rfq",
)
SUPPLY_TERMS = (
    "fabricante", "distribuidor", "distribuidora", "representante", "importador", "mayorista",
    "stock", "catálogo", "catalogo", "productos", "proveedor",
)
CONTACT_TERMS = ("contacto", "ventas", "compras", "abastecimiento", "comercial", "email", "correo", "teléfono", "telefono")
LOW_VALUE_HOSTS = {
    "facebook.com", "instagram.com", "linkedin.com", "youtube.com", "reddit.com",
    "mercadolibre.com.ar", "mercadolibre.com", "amazon.com", "pinterest.com",
}
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _norm(value: Any) -> str:
    return _clean(value).lower()


def _tokens(value: Any) -> set[str]:
    return {
        x.lower() for x in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]+", str(value or ""))
        if len(x) >= 4
    }


def _stage_list(kind: str) -> List[str]:
    return BUYER_STAGES if kind == "buyer" else SUPPLIER_STAGES


def _source_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for account in state.get("candidate_accounts", []) or []:
        if account.get("id"):
            rows[str(account["id"])] = account
    for lead in state.get("research_leads", []) or []:
        if lead.get("id"):
            rows[str(lead["id"])] = lead
    return rows


def _eligible_sources(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    for account in state.get("candidate_accounts", []) or []:
        kind = str(account.get("type") or "")
        if kind not in {"buyer", "supplier"}:
            continue
        sources.append({"source_kind": "candidate_account", "source": account})
    for lead in state.get("research_leads", []) or []:
        kind = str(lead.get("type") or "")
        if kind not in {"buyer", "supplier"}:
            continue
        status = str(lead.get("qualification_status") or lead.get("status") or "").lower()
        tier = str(lead.get("tier") or "").upper()
        if tier == "D" or status in {"rejected_noise", "duplicate"}:
            continue
        if not (lead.get("url") or lead.get("domain")):
            continue
        sources.append({"source_kind": "research_lead", "source": lead})

    def priority(row: Dict[str, Any]) -> tuple:
        src = row["source"]
        direct = 1 if src.get("direct_inbound_demand") else 0
        verified = 1 if src.get("verified_company") else 0
        tier = {"A": 3, "B": 2, "C": 1}.get(str(src.get("tier") or "").upper(), 0)
        score = float(src.get("lead_score") or src.get("verification_score") or 0)
        return (-direct, -verified, -tier, -score, str(src.get("id") or ""))

    return sorted(sources, key=priority)


def _roster(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = list((state.get("agent_workforce", {}) or {}).get("roster", []) or [])
    return rows or agent_fleet.build_roster()


def _owner_for(kind: str, roster: List[Dict[str, Any]], used: Dict[str, int]) -> Dict[str, Any]:
    preferred = ["buyer_hunter", "research_analyst"] if kind == "buyer" else ["supplier_hunter", "research_analyst"]
    candidates = [x for role in preferred for x in roster if x.get("role") == role]
    candidates = candidates or roster
    return min(candidates, key=lambda x: (used.get(str(x.get("id")), 0), str(x.get("id"))))


def _case_key(source: Dict[str, Any]) -> str:
    kind = str(source.get("type") or "")
    domain = _norm(source.get("domain"))
    category = _norm(source.get("category"))
    if domain:
        return f"{kind}|{domain}|{category}"
    return f"{kind}|{source.get('id')}"


def _make_case(state: Dict[str, Any], source_kind: str, source: Dict[str, Any], owner: Dict[str, Any]) -> Dict[str, Any]:
    cases = state.setdefault("professional_cases", [])
    kind = str(source.get("type") or "buyer")
    url = _clean(source.get("source_url") or source.get("url"))
    domain = _clean(source.get("domain")) or agent_fleet._host(url)
    title = _clean(source.get("name_hint") or source.get("title") or domain or source.get("id"))
    return {
        "id": f"CASE-{len(cases)+1:05d}",
        "case_key": _case_key(source),
        "subject_kind": kind,
        "source_kind": source_kind,
        "source_id": source.get("id"),
        "title": title,
        "category": _clean(source.get("category")),
        "domain": domain,
        "source_url": url,
        "owner_agent_id": owner.get("id"),
        "owner_role": owner.get("role"),
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
        "next_action": "Revisar evidencia inicial y definir plan de investigación",
        "created_at": utcnow(),
        "last_worked_at": None,
    }


def _sync_cases(state: Dict[str, Any]) -> int:
    cases = state.setdefault("professional_cases", [])
    active_keys = {str(x.get("case_key") or "") for x in cases if x.get("status") in {"active", "waiting_budget", "ready_for_handoff"}}
    roster = _roster(state)
    used: Dict[str, int] = {}
    for case in cases:
        owner = str(case.get("owner_agent_id") or "")
        if owner:
            used[owner] = used.get(owner, 0) + 1

    created = 0
    active_count = sum(1 for x in cases if x.get("status") in {"active", "waiting_budget", "ready_for_handoff"})
    for row in _eligible_sources(state):
        if created >= MAX_NEW_CASES_PER_CYCLE or active_count >= MAX_ACTIVE_CASES:
            break
        source = row["source"]
        key = _case_key(source)
        if key in active_keys:
            continue
        owner = _owner_for(str(source.get("type") or "buyer"), roster, used)
        case = _make_case(state, row["source_kind"], source, owner)
        cases.append(case)
        active_keys.add(key)
        used[str(owner.get("id"))] = used.get(str(owner.get("id")), 0) + 1
        created += 1
        active_count += 1
    return created


def _deep_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    today = agent_fleet.local_day()
    row = state.setdefault("professional_casework_budget", {})
    if row.get("date") != today:
        row.clear()
        row.update({"date": today, "searches_used": 0, "daily_cap": DAILY_SEARCH_CAP, "reset_at": utcnow()})
    row["daily_cap"] = DAILY_SEARCH_CAP
    row["searches_used"] = max(0, int(row.get("searches_used") or 0))
    row["searches_remaining"] = max(0, DAILY_SEARCH_CAP - row["searches_used"])
    return row


def _consume_search(state: Dict[str, Any]) -> bool:
    deep = _deep_budget(state)
    global_budget = agent_fleet._budget(state)
    if int(deep.get("searches_remaining") or 0) <= 0:
        return False
    if int(global_budget.get("general_queries_remaining") or 0) <= 0:
        return False
    deep["searches_used"] = int(deep.get("searches_used") or 0) + 1
    global_budget["queries_used"] = int(global_budget.get("queries_used") or 0) + 1
    _deep_budget(state)
    agent_fleet._budget(state)
    return True


def _add_evidence(case: Dict[str, Any], kind: str, item: Dict[str, Any], query: Optional[str] = None) -> None:
    url = _clean(item.get("url"))
    if not url:
        return
    existing = {str(x.get("url") or "") for x in case.setdefault("evidence", [])}
    if url in existing:
        return
    case["evidence"].append({
        "kind": kind,
        "url": url,
        "title": _clean(item.get("title"))[:300],
        "snippet": _clean(item.get("snippet"))[:700],
        "host": agent_fleet._host(url),
        "query": query,
        "observed_at": utcnow(),
    })
    case["evidence"] = case["evidence"][-MAX_EVIDENCE_PER_CASE:]


def _search(state: Dict[str, Any], case: Dict[str, Any], query: str, kind: str, cycle_searches: Dict[str, int]) -> List[Dict[str, str]]:
    if cycle_searches["used"] >= MAX_SEARCHES_PER_CYCLE:
        return []
    if not _consume_search(state):
        return []
    cycle_searches["used"] += 1
    case["searches_used"] = int(case.get("searches_used") or 0) + 1
    try:
        results = list(scout_connector.search(query) or [])[:8]
    except Exception as exc:
        case.setdefault("history", []).append({"ts": utcnow(), "stage": case.get("stage"), "event": "search_error", "detail": f"{type(exc).__name__}: {str(exc)[:180]}"})
        return []
    for item in results:
        _add_evidence(case, kind, item, query)
    return results


def _source_for_case(state: Dict[str, Any], case: Dict[str, Any]) -> Dict[str, Any]:
    return _source_map(state).get(str(case.get("source_id") or ""), {})


def _official_results(case: Dict[str, Any], results: List[Dict[str, str]]) -> List[Dict[str, str]]:
    domain = _norm(case.get("domain"))
    if not domain:
        return results
    official = [x for x in results if agent_fleet._host(str(x.get("url") or "")) == domain or agent_fleet._host(str(x.get("url") or "")).endswith("." + domain)]
    return official or results


def _advance(case: Dict[str, Any], note: str) -> None:
    stages = _stage_list(str(case.get("subject_kind") or "buyer"))
    idx = int(case.get("stage_index") or 0)
    case.setdefault("history", []).append({"ts": utcnow(), "stage": case.get("stage"), "event": "advanced", "detail": note})
    if idx < len(stages) - 1:
        idx += 1
        case["stage_index"] = idx
        case["stage"] = stages[idx]
        case["progress_pct"] = int(round(100 * idx / len(stages)))
    else:
        case["progress_pct"] = 100


def _triage(case: Dict[str, Any], source: Dict[str, Any]) -> str:
    facts = case.setdefault("facts", {})
    facts["source_summary"] = _clean(source.get("snippet") or source.get("name_hint") or source.get("title"))[:600]
    facts["source_tier"] = source.get("tier")
    facts["source_score"] = source.get("lead_score") or source.get("verification_score")
    if case.get("source_url"):
        _add_evidence(case, "seed", {"url": case.get("source_url"), "title": case.get("title"), "snippet": facts["source_summary"]})
    _advance(case, "Evidencia inicial organizada; se abre investigación corporativa.")
    case["next_action"] = "Confirmar identidad, sitio oficial y encaje de la empresa"
    return "advanced"


def _identity(state: Dict[str, Any], case: Dict[str, Any], source: Dict[str, Any], cycle_searches: Dict[str, int]) -> str:
    if source.get("verified_company"):
        case.setdefault("facts", {})["identity"] = "verified_by_existing_company_verification"
        _advance(case, "La identidad corporativa ya estaba verificada por LUMEN.")
        case["next_action"] = "Investigar demanda pública" if case["subject_kind"] == "buyer" else "Investigar capacidad de abastecimiento"
        return "advanced"

    domain = _clean(case.get("domain"))
    title = _clean(case.get("title"))
    category = _clean(case.get("category"))
    query = f'site:{domain} "{category}"' if domain else f'"{title}" "{category}" empresa Argentina'
    results = _search(state, case, query, "identity", cycle_searches)
    if not results:
        case["status"] = "waiting_budget" if not _deep_budget(state).get("searches_remaining") or not agent_fleet._budget(state).get("general_queries_remaining") else "active"
        case["next_action"] = "Profundizar identidad corporativa con evidencia pública"
        return "waiting"
    official = _official_results(case, results)
    best = official[0]
    host = agent_fleet._host(str(best.get("url") or ""))
    case.setdefault("facts", {})["identity"] = {
        "domain": domain or host,
        "evidence_url": best.get("url"),
        "official_domain_match": bool(domain and (host == domain or host.endswith("." + domain))),
    }
    if not case.get("domain") and host and host not in LOW_VALUE_HOSTS:
        case["domain"] = host
    _advance(case, "Se obtuvo evidencia pública de identidad y actividad corporativa.")
    case["status"] = "active"
    case["next_action"] = "Buscar evidencia concreta de necesidad" if case["subject_kind"] == "buyer" else "Confirmar productos/capacidad del proveedor"
    return "advanced"


def _demand(state: Dict[str, Any], case: Dict[str, Any], source: Dict[str, Any], cycle_searches: Dict[str, int]) -> str:
    if source.get("demand_signal"):
        case.setdefault("facts", {})["demand"] = {"verified_existing": True, "score": source.get("demand_score")}
        _advance(case, "La cuenta ya posee señal pública de demanda verificada.")
        case["next_action"] = "Encontrar vía de contacto comercial adecuada"
        return "advanced"
    domain, category = _clean(case.get("domain")), _clean(case.get("category"))
    query = f'site:{domain} "{category}" (compras OR abastecimiento OR licitación OR cotización OR mantenimiento OR proveedores)' if domain else f'"{case.get("title")}" "{category}" (compras OR abastecimiento OR licitación OR cotización)'
    results = _search(state, case, query, "demand", cycle_searches)
    if not results:
        case["status"] = "waiting_budget" if not _deep_budget(state).get("searches_remaining") or not agent_fleet._budget(state).get("general_queries_remaining") else "active"
        case["next_action"] = "Seguir buscando evidencia pública de demanda real"
        return "waiting"
    text = " ".join(f"{x.get('title','')} {x.get('snippet','')}" for x in results).lower()
    hits = sorted({term for term in DEMAND_TERMS if term in text})
    category_hits = [tok for tok in _tokens(category) if tok in text]
    score = min(100, len(hits) * 15 + len(category_hits) * 10 + (20 if domain and any(agent_fleet._host(str(x.get('url') or '')) == domain for x in results) else 0))
    case.setdefault("facts", {})["demand"] = {"public_hint": score >= 45, "score": score, "terms": hits[:8], "category_hits": category_hits[:8]}
    source["deep_public_demand_hint"] = bool(score >= 45)
    source["deep_public_demand_score"] = score
    _advance(case, f"Investigación de demanda completada con score {score}/100; la verificación formal sigue en los motores normales.")
    case["status"] = "active"
    case["next_action"] = "Identificar contacto de compras/abastecimiento/mantenimiento"
    return "advanced"


def _capability(state: Dict[str, Any], case: Dict[str, Any], source: Dict[str, Any], cycle_searches: Dict[str, int]) -> str:
    domain, category = _clean(case.get("domain")), _clean(case.get("category"))
    query = f'site:{domain} "{category}" (fabricante OR distribuidor OR representante OR catálogo OR stock OR productos)' if domain else f'"{case.get("title")}" "{category}" fabricante distribuidor proveedor Argentina'
    results = _search(state, case, query, "capability", cycle_searches)
    if not results:
        case["status"] = "waiting_budget" if not _deep_budget(state).get("searches_remaining") or not agent_fleet._budget(state).get("general_queries_remaining") else "active"
        case["next_action"] = "Profundizar capacidad real de abastecimiento"
        return "waiting"
    text = " ".join(f"{x.get('title','')} {x.get('snippet','')}" for x in results).lower()
    hits = sorted({term for term in SUPPLY_TERMS if term in text})
    category_hits = [tok for tok in _tokens(category) if tok in text]
    score = min(100, len(hits) * 14 + len(category_hits) * 10)
    case.setdefault("facts", {})["capability"] = {"public_hint": score >= 40, "score": score, "terms": hits[:8], "category_hits": category_hits[:8]}
    source["deep_supply_capability_hint"] = bool(score >= 40)
    source["deep_supply_capability_score"] = score
    _advance(case, f"Capacidad comercial investigada con score {score}/100.")
    case["status"] = "active"
    case["next_action"] = "Identificar vía comercial pública del proveedor"
    return "advanced"


def _contact(state: Dict[str, Any], case: Dict[str, Any], source: Dict[str, Any], cycle_searches: Dict[str, int]) -> str:
    existing = _clean(source.get("verified_email") or source.get("email") or source.get("contact_email"))
    if source.get("verified_contact") or existing:
        case.setdefault("facts", {})["contact"] = {"existing": True, "email": existing or None}
        _advance(case, "La cuenta ya tiene una vía de contacto disponible en LUMEN.")
        case["next_action"] = "Construir contraparte comercial y encaje"
        return "advanced"
    domain = _clean(case.get("domain"))
    query = f'site:{domain} (contacto OR compras OR abastecimiento OR ventas OR comercial OR "@{domain}")' if domain else f'"{case.get("title")}" contacto comercial compras Argentina'
    results = _search(state, case, query, "contact", cycle_searches)
    if not results:
        case["status"] = "waiting_budget" if not _deep_budget(state).get("searches_remaining") or not agent_fleet._budget(state).get("general_queries_remaining") else "active"
        case["next_action"] = "Buscar una vía pública de contacto corporativo"
        return "waiting"
    emails: List[str] = []
    routes: List[str] = []
    for item in results:
        text = f"{item.get('title','')} {item.get('snippet','')}"
        for email in EMAIL_RE.findall(text):
            if email.lower() not in {x.lower() for x in emails}:
                emails.append(email)
        low = text.lower()
        if any(term in low for term in CONTACT_TERMS):
            routes.append(str(item.get("url") or ""))
    official_emails = [x for x in emails if domain and x.lower().endswith("@" + domain.lower())]
    case.setdefault("facts", {})["contact"] = {"emails": official_emails[:5] or emails[:5], "routes": routes[:5], "public_hint": bool(emails or routes)}
    if official_emails:
        source["deep_contact_email_hint"] = official_emails[0]
    if routes:
        source["deep_contact_route_hint"] = routes[0]
    _advance(case, "Se investigaron vías públicas de contacto; cualquier contacto sigue sujeto a validación y quality gate.")
    case["status"] = "active"
    case["next_action"] = "Encontrar proveedor compatible" if case["subject_kind"] == "buyer" else "Encontrar compradores/mercados compatibles"
    return "advanced"


def _category_match(a: Any, b: Any) -> int:
    aa, bb = _tokens(a), _tokens(b)
    if not aa or not bb:
        return 0
    return len(aa & bb)


def _counterpart_existing(state: Dict[str, Any], case: Dict[str, Any], wanted: str) -> List[Dict[str, Any]]:
    category = case.get("category")
    rows = [
        x for x in state.get("candidate_accounts", []) or []
        if x.get("type") == wanted and x.get("verified_company") and _category_match(category, x.get("category")) > 0
    ]
    return sorted(rows, key=lambda x: float(x.get("verification_score") or x.get("lead_score") or 0), reverse=True)[:5]


def _add_counterpart_leads(state: Dict[str, Any], case: Dict[str, Any], results: List[Dict[str, str]], lead_type: str) -> int:
    known = {str(x.get("url") or "") for x in state.get("research_leads", []) or [] if x.get("url")}
    created = 0
    for item in results:
        url = _clean(item.get("url"))
        host = agent_fleet._host(url)
        if not url or url in known or host in LOW_VALUE_HOSTS:
            continue
        leads = state.setdefault("research_leads", [])
        leads.append({
            "id": f"LEAD-{len(leads)+1:05d}", "type": lead_type, "category": case.get("category"),
            "title": _clean(item.get("title"))[:300], "url": url, "snippet": _clean(item.get("snippet"))[:700],
            "market": scout_connector.MARKET, "status": "research_required", "confidence": 0.45,
            "verified_company": False, "verified_contact": False,
            "source": "professional_casework_counterpart_search", "parent_case_id": case.get("id"),
            "created_at": utcnow(),
        })
        known.add(url)
        created += 1
        if created >= 2:
            break
    return created


def _counterpart_stage(state: Dict[str, Any], case: Dict[str, Any], cycle_searches: Dict[str, int]) -> str:
    buyer_case = case.get("subject_kind") == "buyer"
    wanted = "supplier" if buyer_case else "buyer"
    existing = _counterpart_existing(state, case, wanted)
    facts = case.setdefault("facts", {})
    if existing:
        facts["counterparts"] = [{"id": x.get("id"), "name": x.get("name_hint"), "domain": x.get("domain"), "category": x.get("category")} for x in existing]
        _advance(case, f"Se encontraron {len(existing)} contrapartes verificadas compatibles dentro de LUMEN.")
        case["next_action"] = "Construir tesis comercial y criterio de handoff"
        return "advanced"

    category = _clean(case.get("category"))
    if buyer_case:
        query = f'"{category}" fabricante distribuidor mayorista proveedor Argentina -mercadolibre'
        kind = "supplier_match"
    else:
        query = f'"{category}" compras abastecimiento industria empresa Argentina -proveedor -distribuidor -venta'
        kind = "buyer_fit"
    results = _search(state, case, query, kind, cycle_searches)
    if not results:
        case["status"] = "waiting_budget" if not _deep_budget(state).get("searches_remaining") or not agent_fleet._budget(state).get("general_queries_remaining") else "active"
        case["next_action"] = "Buscar contrapartes compatibles para completar la tesis comercial"
        return "waiting"
    created = _add_counterpart_leads(state, case, results, wanted)
    facts["counterpart_research"] = {"results": len(results), "new_research_leads": created, "wanted": wanted}
    _advance(case, f"Se abrió investigación de contraparte: {created} nuevos leads derivados del caso.")
    case["status"] = "active"
    case["next_action"] = "Construir tesis comercial y criterio de handoff"
    return "advanced"


def _thesis(state: Dict[str, Any], case: Dict[str, Any], source: Dict[str, Any]) -> str:
    facts = case.setdefault("facts", {})
    identity = bool(facts.get("identity"))
    contact = bool((facts.get("contact") or {}).get("public_hint") or (facts.get("contact") or {}).get("existing") or (facts.get("contact") or {}).get("emails"))
    if case.get("subject_kind") == "buyer":
        core = facts.get("demand") or {}
        core_score = int(core.get("score") or (100 if core.get("verified_existing") else 0))
        commercial_core = bool(core.get("verified_existing") or core.get("public_hint"))
    else:
        core = facts.get("capability") or {}
        core_score = int(core.get("score") or 0)
        commercial_core = bool(core.get("public_hint") or source.get("verified_company"))
    counterpart = bool(facts.get("counterparts") or (facts.get("counterpart_research") or {}).get("new_research_leads"))
    evidence_count = len(case.get("evidence", []) or [])
    readiness = min(100, (25 if identity else 0) + (35 if commercial_core else min(20, core_score // 4)) + (20 if contact else 0) + (15 if counterpart else 0) + min(5, evidence_count))
    missing = []
    if not identity: missing.append("identity")
    if not commercial_core: missing.append("demand" if case.get("subject_kind") == "buyer" else "capability")
    if not contact: missing.append("contact")
    if not counterpart: missing.append("counterpart")

    thesis = {
        "readiness_score": readiness,
        "identity_evidence": identity,
        "commercial_core_evidence": commercial_core,
        "contact_route": contact,
        "counterpart_path": counterpart,
        "evidence_count": evidence_count,
        "missing": missing,
        "statement": (
            f"{case.get('title')} · {case.get('category')}: expediente con {evidence_count} evidencias, "
            f"readiness {readiness}/100 y {len(missing)} brechas pendientes."
        ),
    }
    facts["commercial_thesis"] = thesis
    case["missing"] = missing
    case["progress_pct"] = 100
    case.setdefault("history", []).append({"ts": utcnow(), "stage": "thesis", "event": "thesis_built", "detail": thesis["statement"]})

    if readiness >= 70 and identity and commercial_core:
        case["status"] = "ready_for_handoff"
        case["next_action"] = "Entregar expediente a RevOps/verificación normal sin saltear gates"
        handoffs = state.setdefault("professional_case_handoffs", [])
        if not any(x.get("case_id") == case.get("id") for x in handoffs):
            handoffs.append({
                "case_id": case.get("id"), "subject_kind": case.get("subject_kind"), "source_id": case.get("source_id"),
                "category": case.get("category"), "readiness_score": readiness, "created_at": utcnow(),
                "status": "pending_normal_gates",
            })
        source["deep_work_case_id"] = case.get("id")
        source["deep_work_ready"] = True
        source["deep_work_readiness_score"] = readiness
        return "ready"

    # Persist the case instead of abandoning it. Re-open the first missing research stage.
    stages = _stage_list(str(case.get("subject_kind") or "buyer"))
    target = None
    mapping = {"identity": "identity", "demand": "demand", "capability": "capability", "contact": "contact", "counterpart": "supplier_match" if case.get("subject_kind") == "buyer" else "buyer_fit"}
    for item in missing:
        if mapping[item] in stages:
            target = mapping[item]
            break
    if target:
        case["stage"] = target
        case["stage_index"] = stages.index(target)
        case["progress_pct"] = int(round(100 * case["stage_index"] / len(stages)))
    case["status"] = "active"
    case["next_action"] = "Cerrar brechas del expediente: " + ", ".join(missing)
    return "reopened"


def _work_case(state: Dict[str, Any], case: Dict[str, Any], cycle_searches: Dict[str, int]) -> str:
    source = _source_for_case(state, case)
    if not source:
        case["status"] = "parked"
        case["next_action"] = "Fuente original no disponible; requiere revisión"
        return "parked"
    case["cycles_worked"] = int(case.get("cycles_worked") or 0) + 1
    case["last_worked_at"] = utcnow()
    stage = str(case.get("stage") or "triage")
    if stage == "triage": return _triage(case, source)
    if stage == "identity": return _identity(state, case, source, cycle_searches)
    if stage == "demand": return _demand(state, case, source, cycle_searches)
    if stage == "capability": return _capability(state, case, source, cycle_searches)
    if stage == "contact": return _contact(state, case, source, cycle_searches)
    if stage in {"supplier_match", "buyer_fit"}: return _counterpart_stage(state, case, cycle_searches)
    if stage == "thesis": return _thesis(state, case, source)
    case["status"] = "parked"
    case["next_action"] = "Etapa desconocida; requiere revisión"
    return "parked"


def professional_casework_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    created = _sync_cases(state)
    cases = state.setdefault("professional_cases", [])
    active = [x for x in cases if x.get("status") in {"active", "waiting_budget"}]
    active.sort(key=lambda x: (str(x.get("last_worked_at") or ""), -int(x.get("cycles_worked") or 0), str(x.get("id") or "")))
    queue = active[:MAX_CASES_PER_CYCLE]
    cycle_searches = {"used": 0}
    outcomes = {"advanced": 0, "waiting": 0, "ready": 0, "reopened": 0, "parked": 0}
    worked_cases: List[Dict[str, Any]] = []

    for case in queue:
        result = _work_case(state, case, cycle_searches)
        outcomes[result] = outcomes.get(result, 0) + 1
        worked_cases.append({
            "case_id": case.get("id"), "owner": case.get("owner_agent_id"), "subject": case.get("title"),
            "kind": case.get("subject_kind"), "stage": case.get("stage"), "status": case.get("status"),
            "progress_pct": case.get("progress_pct"), "next_action": case.get("next_action"),
            "evidence_count": len(case.get("evidence", []) or []),
        })

    status_counts: Dict[str, int] = {}
    stage_counts: Dict[str, int] = {}
    for case in cases:
        status_counts[str(case.get("status") or "unknown")] = status_counts.get(str(case.get("status") or "unknown"), 0) + 1
        stage_counts[str(case.get("stage") or "unknown")] = stage_counts.get(str(case.get("stage") or "unknown"), 0) + 1

    budget = _deep_budget(state)
    global_budget = agent_fleet._budget(state)
    report = {
        "version": "1.0-professional-deep-work",
        "updated_at": utcnow(),
        "cases_total": len(cases),
        "cases_created": created,
        "cases_worked": len(worked_cases),
        "searches_used": cycle_searches["used"],
        "deep_search_budget_used_today": int(budget.get("searches_used") or 0),
        "deep_search_budget_remaining": int(budget.get("searches_remaining") or 0),
        "global_general_search_remaining": int(global_budget.get("general_queries_remaining") or 0),
        "status_counts": status_counts,
        "stage_counts": stage_counts,
        "outcomes": outcomes,
        "ready_for_handoff": status_counts.get("ready_for_handoff", 0),
        "waiting_budget": status_counts.get("waiting_budget", 0),
        "worked_cases": worked_cases,
        "operating_model": "persistent_owned_cases_multistage_research_no_one-shot-abandonment",
        "authority": "research_and_nonbinding_commercial_preparation_only",
    }
    state["professional_casework"] = report
    history = list(state.get("professional_casework_history", []) or [])
    history.append({k: report[k] for k in ("updated_at", "cases_total", "cases_worked", "searches_used", "ready_for_handoff", "waiting_budget")})
    state["professional_casework_history"] = history[-48:]
    state.setdefault("activity", []).insert(0, {
        "ts": utcnow(),
        "msg": (
            f"Deep Work profesional: {len(worked_cases)} expedientes trabajados, {cycle_searches['used']} búsquedas, "
            f"{outcomes.get('advanced',0)} avances y {status_counts.get('ready_for_handoff',0)} listos para handoff."
        ),
    })
    state["activity"] = state["activity"][:100]
    return report
