from __future__ import annotations

import os
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import scout_connector


FLEET_SIZE = max(1, min(200, int(os.getenv("LUMEN_AGENT_FLEET_SIZE", "50"))))
MAX_PARALLEL = max(1, min(FLEET_SIZE, int(os.getenv("LUMEN_AGENT_MAX_PARALLEL", str(FLEET_SIZE)))))
SEARCHES_PER_CYCLE = max(0, min(20, int(os.getenv("LUMEN_AGENT_SEARCHES_PER_CYCLE", "4"))))
MAX_LEADS_PER_SEARCH = max(1, min(5, int(os.getenv("LUMEN_AGENT_MAX_LEADS_PER_SEARCH", "2"))))
TZ_NAME = str(os.getenv("LUMEN_SCOUT_TIMEZONE", "America/Argentina/Buenos_Aires")).strip() or "America/Argentina/Buenos_Aires"
RETAIL_RESERVED = max(1, int(os.getenv("LUMEN_RETAIL_RESERVED_BUDGET", "4")))

try:
    LOCAL_TZ = ZoneInfo(TZ_NAME)
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=-3))

ROLE_SPECS = [
    ("buyer_hunter", "Buyer Hunter", 15),
    ("supplier_hunter", "Supplier Hunter", 10),
    ("market_scout", "Market Scout", 8),
    ("research_analyst", "Research Analyst", 5),
    ("revops", "RevOps / Closer", 4),
    ("negotiator", "Negotiator", 3),
    ("market_manager", "Market Manager", 2),
    ("risk_quality", "Risk & Quality", 2),
    ("finance", "CFO / Profit", 1),
]

LOW_VALUE_HOSTS = {
    "facebook.com", "instagram.com", "linkedin.com", "youtube.com", "reddit.com",
    "mercadolibre.com.ar", "mercadolibre.com", "amazon.com", "pinterest.com",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def local_day() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _unique(values: List[Any]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean(value)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def build_roster(size: int = FLEET_SIZE) -> List[Dict[str, Any]]:
    base: List[Dict[str, Any]] = []
    counters: Dict[str, int] = {}
    for role, title, count in ROLE_SPECS:
        for _ in range(count):
            counters[role] = counters.get(role, 0) + 1
            prefix = {
                "buyer_hunter": "BH", "supplier_hunter": "SH", "market_scout": "MS",
                "research_analyst": "RA", "revops": "RV", "negotiator": "NG",
                "market_manager": "MM", "risk_quality": "RQ", "finance": "CF",
            }[role]
            base.append({"id": f"{prefix}-{counters[role]:02d}", "role": role, "title": title})
    if size <= len(base):
        return base[:size]
    out = list(base)
    i = 0
    while len(out) < size:
        template = base[i % len(base)]
        n = len(out) + 1
        out.append({"id": f"X-{n:03d}", "role": template["role"], "title": template["title"]})
        i += 1
    return out


def _budget(state: Dict[str, Any]) -> Dict[str, Any]:
    today = local_day()
    daily = int(scout_connector.DAILY_QUERY_BUDGET)
    budget = state.setdefault("scout_budget", {})
    if budget.get("date") != today or budget.get("timezone") != TZ_NAME:
        budget.clear()
        budget.update({
            "date": today,
            "timezone": TZ_NAME,
            "queries_used": 0,
            "daily_budget": daily,
            "reset_reason": "agent_fleet_market_day_or_timezone_changed",
            "reset_at": scout_connector.utcnow(),
        })
    budget["daily_budget"] = daily
    budget["queries_used"] = max(0, int(budget.get("queries_used") or 0))

    retail = state.get("retail_velocity_budget", {}) or {}
    retail_used = 0
    if retail.get("date") == today and retail.get("timezone") == TZ_NAME:
        retail_used = max(0, int(retail.get("queries_used") or 0))
    reserved_daily = min(max(1, RETAIL_RESERVED), max(1, daily - 1))
    reserved_remaining = max(0, reserved_daily - min(reserved_daily, retail_used))
    total_remaining = max(0, daily - budget["queries_used"])
    general_remaining = max(0, total_remaining - reserved_remaining)

    budget["queries_remaining_total"] = total_remaining
    budget["retail_reserved_daily"] = reserved_daily
    budget["retail_reserved_used"] = min(reserved_daily, retail_used)
    budget["retail_reserved_remaining"] = reserved_remaining
    budget["general_queries_remaining"] = general_remaining
    budget["queries_remaining"] = general_remaining
    return budget


def _reserve_searches(state: Dict[str, Any], wanted: int) -> int:
    budget = _budget(state)
    count = max(0, min(int(wanted), int(budget.get("general_queries_remaining") or 0)))
    budget["queries_used"] = int(budget.get("queries_used") or 0) + count
    _budget(state)
    return count


def _focus_categories(state: Dict[str, Any]) -> List[str]:
    values: List[Any] = []
    for account in state.get("candidate_accounts", []) or []:
        if account.get("verified_company"):
            values.append(account.get("category"))
    for lead in state.get("research_leads", []) or []:
        values.append(lead.get("category"))
    for signal in state.get("retail_product_signals", []) or []:
        values.extend([signal.get("category"), signal.get("product"), signal.get("name"), signal.get("title")])
    for signal in state.get("agent_market_signals", []) or []:
        values.append(signal.get("category"))
    for listing in state.get("autonomous_listings", []) or []:
        if listing.get("status") in {"published", "active", "ready"}:
            values.append(listing.get("category"))
    out = _unique(values)
    return out[:20] or ["instrumentación industrial", "electrónica", "tecnología de consumo"]


def _bottleneck(state: Dict[str, Any]) -> str:
    meta = state.get("meta_autonomy", {}) or {}
    directive = _clean(meta.get("revenue_directive")).lower()
    if directive:
        return directive
    for container_key in ("revenue_factory", "war_room", "business_kpis"):
        row = state.get(container_key, {}) or {}
        value = row.get("bottleneck") or row.get("primary_bottleneck")
        if value:
            return _clean(value).lower()
    buyers = [x for x in state.get("candidate_accounts", []) or [] if x.get("type") == "buyer" and x.get("verified_company")]
    suppliers = [x for x in state.get("candidate_accounts", []) or [] if x.get("type") == "supplier" and x.get("verified_company")]
    if not buyers and suppliers:
        return "demand_gap"
    if buyers and not suppliers:
        return "supplier_gap"
    return "balanced_pipeline"


def _context(state: Dict[str, Any]) -> Dict[str, Any]:
    candidates = list(state.get("candidate_accounts", []) or [])
    buyers = [x for x in candidates if x.get("type") == "buyer" and x.get("verified_company")]
    suppliers = [x for x in candidates if x.get("type") == "supplier" and x.get("verified_company")]
    pending_leads = [x for x in state.get("research_leads", []) or [] if x.get("status") in {"research_required", "new", None}]
    opportunities = list(state.get("opportunities", []) or [])
    quotes = list(state.get("supplier_quotes", []) or []) + list(state.get("quotes", []) or [])
    inquiries = list(state.get("market_inquiries", []) or [])
    listings = [x for x in state.get("autonomous_listings", []) or [] if x.get("status") in {"published", "active", "ready"}]
    ledger = list(state.get("revenue_ledger", []) or [])
    commissions = 0.0
    for row in ledger:
        if row.get("kind") == "commission_settlement" and str(row.get("status") or "").lower() in {"realized", "collected", "settled", "paid"}:
            try:
                commissions += float(row.get("amount") or row.get("amount_usd") or 0)
            except (TypeError, ValueError):
                pass
    coo = state.get("autonomous_coo", {}) or {}
    engine = coo.get("engine_health", {}) or {}
    return {
        "categories": _focus_categories(state),
        "bottleneck": _bottleneck(state),
        "buyers_verified": len(buyers),
        "suppliers_verified": len(suppliers),
        "buyer_demand_verified": sum(1 for x in buyers if x.get("demand_signal")),
        "pending_leads": len(pending_leads),
        "opportunities": len(opportunities),
        "offers": len(state.get("offers", []) or []),
        "proposals": len(state.get("proposals", []) or []),
        "quotes": len(quotes),
        "inquiries": len(inquiries),
        "listings": len(listings),
        "close_ready": sum(1 for x in state.get("deals", []) or [] if str(x.get("stage") or "").lower() in {"listo para cerrar", "close_ready", "autorizado para cierre"}),
        "commission_collected": round(commissions, 2),
        "engine_failures": list(engine.get("failed_now", []) or []),
        "circuits_open": list(engine.get("circuits_open", []) or []),
    }


def _query(role: str, category: str, variant: int) -> str:
    cat = category.replace('"', "")
    if role == "buyer_hunter":
        variants = [
            f'"{cat}" compras abastecimiento industria empresa Argentina -proveedor -distribuidor -venta',
            f'"{cat}" (licitación OR cotización OR compras) empresa Argentina -proveedor -distribuidor',
            f'"{cat}" mantenimiento planta abastecimiento Argentina -venta -tienda',
        ]
    elif role == "supplier_hunter":
        variants = [
            f'"{cat}" fabricante distribuidor mayorista importador Argentina -mercadolibre',
            f'"{cat}" proveedor oficial distribuidor Argentina -mercadolibre -facebook',
            f'"{cat}" mayorista importador stock Argentina -mercadolibre',
        ]
    else:
        variants = [
            f'site:mitiendanube.com "{cat}" Argentina',
            f'"{cat}" tienda online Argentina -mercadolibre',
            f'"{cat}" precio comprar Argentina -mercadolibre',
        ]
    return variants[variant % len(variants)]


def _select_search_agents(roster: List[Dict[str, Any]], ctx: Dict[str, Any], slots: int) -> List[Dict[str, Any]]:
    if slots <= 0:
        return []
    bottleneck = str(ctx.get("bottleneck") or "")
    if any(x in bottleneck for x in ("demand", "buyer", "conversion", "value")):
        role_order = ["buyer_hunter", "market_scout", "supplier_hunter"]
    elif "supplier" in bottleneck or "procurement" in bottleneck:
        role_order = ["supplier_hunter", "buyer_hunter", "market_scout"]
    else:
        role_order = ["buyer_hunter", "supplier_hunter", "market_scout"]
    ordered: List[Dict[str, Any]] = []
    for role in role_order:
        ordered.extend([x for x in roster if x["role"] == role])
    chosen: List[Dict[str, Any]] = []
    queries: set[str] = set()
    cats = list(ctx.get("categories") or ["industria"])
    cursor = int(datetime.now(LOCAL_TZ).strftime("%H%M"))
    for idx, agent in enumerate(ordered):
        if len(chosen) >= slots:
            break
        category = cats[(cursor + idx) % len(cats)]
        q = _query(agent["role"], category, idx)
        if q in queries:
            continue
        queries.add(q)
        chosen.append({**agent, "category": category, "query": q})
    return chosen


def _local_finding(role: str, ctx: Dict[str, Any]) -> str:
    if role == "buyer_hunter":
        return f"Demanda: {ctx['buyers_verified']} compradores verificados; {ctx['buyer_demand_verified']} con señal pública confirmada."
    if role == "supplier_hunter":
        return f"Abastecimiento: {ctx['suppliers_verified']} proveedores verificados para sostener oportunidades y Market."
    if role == "market_scout":
        return f"Market: {ctx['listings']} publicaciones activas y {ctx['inquiries']} consultas captadas; revisar señales multicanal."
    if role == "research_analyst":
        return f"Investigación: {ctx['pending_leads']} leads pendientes para validar y convertir en cuentas útiles."
    if role == "revops":
        return f"RevOps: {ctx['opportunities']} oportunidades, {ctx['offers']} ofertas y {ctx['proposals']} propuestas en el embudo."
    if role == "negotiator":
        return f"Negociación: {ctx['quotes']} cotizaciones registradas; priorizar comparabilidad y mejores condiciones no vinculantes."
    if role == "market_manager":
        return f"Gestión Market: {ctx['inquiries']} consultas y {ctx['listings']} publicaciones activas para convertir en conversación comercial."
    if role == "risk_quality":
        return f"Control: {len(ctx['engine_failures'])} fallas de motor y {len(ctx['circuits_open'])} circuitos abiertos detectados."
    if role == "finance":
        return f"Rentabilidad: comisión cobrada registrada USD {ctx['commission_collected']:,.2f}; close-ready {ctx['close_ready']}."
    return "Revisión operativa completada."


def _execute(assignment: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    if assignment.get("kind") != "web_search":
        return {
            "agent_id": assignment["agent_id"], "role": assignment["role"], "kind": "analysis",
            "ok": True, "finding": _local_finding(assignment["role"], ctx), "results": [],
        }
    try:
        results = scout_connector.search(str(assignment.get("query") or ""))
        return {
            "agent_id": assignment["agent_id"], "role": assignment["role"], "kind": "web_search",
            "category": assignment.get("category"), "query": assignment.get("query"), "ok": True,
            "finding": f"Búsqueda web completada: {len(results)} resultados públicos para {assignment.get('category') or 'foco comercial'}.",
            "results": list(results or [])[:8],
        }
    except Exception as exc:
        return {
            "agent_id": assignment["agent_id"], "role": assignment["role"], "kind": "web_search",
            "category": assignment.get("category"), "query": assignment.get("query"), "ok": False,
            "finding": f"Búsqueda falló: {type(exc).__name__}: {str(exc)[:160]}", "results": [],
        }


def _merge_search_results(state: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, int]:
    created_leads = 0
    created_signals = 0
    known_leads = {str(x.get("url") or "") for x in state.get("research_leads", []) or [] if x.get("url")}
    known_signals = {str(x.get("url") or "") for x in state.get("agent_market_signals", []) or [] if x.get("url")}
    role = str(result.get("role") or "")
    category = _clean(result.get("category"))

    for item in result.get("results", []) or []:
        url = _clean(item.get("url"))
        if not url:
            continue
        host = _host(url)
        if role == "market_scout":
            if url in known_signals:
                continue
            signals = state.setdefault("agent_market_signals", [])
            signals.append({
                "id": f"AMS-{len(signals)+1:05d}", "agent_id": result.get("agent_id"),
                "category": category, "title": _clean(item.get("title"))[:300], "url": url,
                "snippet": _clean(item.get("snippet"))[:700], "host": host,
                "source": "parallel_agent_public_search", "created_at": utcnow(),
            })
            known_signals.add(url)
            created_signals += 1
            if created_signals >= MAX_LEADS_PER_SEARCH:
                break
            continue

        if host in LOW_VALUE_HOSTS or url in known_leads:
            continue
        lead_type = "buyer" if role == "buyer_hunter" else "supplier"
        leads = state.setdefault("research_leads", [])
        leads.append({
            "id": f"LEAD-{len(leads)+1:05d}", "type": lead_type, "category": category,
            "title": _clean(item.get("title"))[:300], "url": url,
            "snippet": _clean(item.get("snippet"))[:700], "query": result.get("query"),
            "market": scout_connector.MARKET, "status": "research_required", "confidence": 0.45,
            "verified_company": False, "verified_contact": False,
            "source": "parallel_agent_public_search", "agent_id": result.get("agent_id"),
            "created_at": utcnow(),
        })
        known_leads.add(url)
        created_leads += 1
        if created_leads >= MAX_LEADS_PER_SEARCH:
            break

    if state.get("agent_market_signals"):
        state["agent_market_signals"] = list(state["agent_market_signals"])[-300:]
    return {"leads": created_leads, "signals": created_signals}


def run_agent_fleet_cycle(state: Dict[str, Any]) -> Dict[str, Any]:
    """Run a 50-person digital workforce as parallel, bounded assignments.

    All agents share LUMEN's state, search budget and constitutional authority. They never sign,
    pay, order, or create binding commitments. Parallel search results are evidence only; normal
    verification and commercial engines decide what becomes a real account or opportunity.
    """
    started = utcnow()
    roster = build_roster()
    ctx = _context(state)
    scout_status = scout_connector.status()
    budget_before = dict(_budget(state))
    available = int(budget_before.get("general_queries_remaining") or 0)
    wanted = min(SEARCHES_PER_CYCLE, available) if scout_status.get("configured") else 0
    search_slots = _reserve_searches(state, wanted)
    selected = _select_search_agents(roster, ctx, search_slots)
    selected_by_id = {x["id"]: x for x in selected}

    assignments: List[Dict[str, Any]] = []
    for agent in roster:
        selected_row = selected_by_id.get(agent["id"])
        if selected_row:
            assignments.append({
                "agent_id": agent["id"], "role": agent["role"], "title": agent["title"],
                "kind": "web_search", "category": selected_row["category"], "query": selected_row["query"],
            })
        else:
            assignments.append({
                "agent_id": agent["id"], "role": agent["role"], "title": agent["title"],
                "kind": "analysis",
            })

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(assignments))) as pool:
        futures = {pool.submit(_execute, assignment, ctx): assignment for assignment in assignments}
        for future in as_completed(futures):
            assignment = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({
                    "agent_id": assignment["agent_id"], "role": assignment["role"], "kind": assignment["kind"],
                    "ok": False, "finding": f"Agente falló: {type(exc).__name__}: {str(exc)[:160]}", "results": [],
                })

    new_leads = 0
    market_signals = 0
    for result in results:
        if result.get("kind") == "web_search" and result.get("ok"):
            merged = _merge_search_results(state, result)
            new_leads += merged["leads"]
            market_signals += merged["signals"]

    by_role: Dict[str, Dict[str, int]] = {}
    for agent in roster:
        row = by_role.setdefault(agent["role"], {"recruited": 0, "assignments": 0, "web_searches": 0, "errors": 0})
        row["recruited"] += 1
        row["assignments"] += 1
    for result in results:
        row = by_role.setdefault(result["role"], {"recruited": 0, "assignments": 0, "web_searches": 0, "errors": 0})
        if result.get("kind") == "web_search":
            row["web_searches"] += 1
        if not result.get("ok"):
            row["errors"] += 1

    findings: List[str] = []
    seen: set[str] = set()
    for result in sorted(results, key=lambda x: (x.get("kind") != "web_search", x.get("agent_id") or "")):
        finding = _clean(result.get("finding"))
        if finding and finding not in seen:
            seen.add(finding)
            findings.append(finding)
        if len(findings) >= 12:
            break

    budget_after = dict(_budget(state))
    errors = sum(1 for x in results if not x.get("ok"))
    report = {
        "version": "1.0",
        "started_at": started,
        "completed_at": utcnow(),
        "company_cycle": int(state.get("ticks") or 0),
        "status": "healthy" if errors == 0 else "degraded",
        "fleet_size": len(roster),
        "max_parallel": MAX_PARALLEL,
        "assignments_created": len(assignments),
        "assignments_completed": len(results),
        "web_searches": sum(1 for x in results if x.get("kind") == "web_search"),
        "new_research_leads": new_leads,
        "new_market_signals": market_signals,
        "errors": errors,
        "bottleneck": ctx["bottleneck"],
        "search_provider_configured": bool(scout_status.get("configured")),
        "search_budget_before_general": int(budget_before.get("general_queries_remaining") or 0),
        "search_budget_after_general": int(budget_after.get("general_queries_remaining") or 0),
        "search_budget_total_remaining": int(budget_after.get("queries_remaining_total") or 0),
        "retail_reserved_remaining": int(budget_after.get("retail_reserved_remaining") or 0),
        "by_role": by_role,
        "top_findings": findings,
        "autonomy_boundary": "nonbinding research, analysis and commercial preparation only",
    }

    workforce = state.setdefault("agent_workforce", {})
    workforce["version"] = "1.0"
    workforce["roster"] = roster
    workforce["roster_count"] = len(roster)
    workforce["last_cycle"] = report
    workforce["last_results"] = [
        {k: row.get(k) for k in ("agent_id", "role", "kind", "ok", "category", "finding") if row.get(k) is not None}
        for row in sorted(results, key=lambda x: x.get("agent_id") or "")
    ][:len(roster)]
    history = list(workforce.get("recent_cycles", []) or [])
    history.append({k: report.get(k) for k in (
        "completed_at", "company_cycle", "status", "fleet_size", "assignments_completed", "web_searches",
        "new_research_leads", "new_market_signals", "errors", "bottleneck"
    )})
    workforce["recent_cycles"] = history[-24:]

    state.setdefault("activity", []).insert(0, {
        "ts": utcnow(),
        "msg": (
            f"Workforce digital: {len(roster)} agentes completaron {len(results)} asignaciones en paralelo; "
            f"{report['web_searches']} búsquedas web, {new_leads} leads nuevos y {market_signals} señales Market."
        ),
    })
    state["activity"] = state["activity"][:100]
    return report
