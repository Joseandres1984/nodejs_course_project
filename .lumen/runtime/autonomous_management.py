from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

MAX_HISTORY = 160
MAX_PROGRAMS = 6
PROGRAM_HOLD_CYCLES = 16
MAX_PORTFOLIO_ROWS = 40
RESOURCE_KEYS = ("core_research_pct", "deep_dive_pct", "expansion_pct", "exploration_pct")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _pct(num: float, den: float) -> float:
    return 0.0 if den <= 0 else max(0.0, min(100.0, num / den * 100.0))


def _ensure(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("autonomous_management_memory", {})
    memory.setdefault("cycle", 0)
    memory.setdefault("department_history", [])
    memory.setdefault("programs", [])
    memory.setdefault("program_history", [])
    memory.setdefault("portfolio_history", [])
    memory.setdefault("last_primary_department", None)
    memory.setdefault("primary_streak", 0)
    return memory


def _department_scorecards(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    accounts = state.get("candidate_accounts", []) or []
    verified = [x for x in accounts if x.get("verified_company")]
    buyers = [x for x in verified if x.get("type") == "buyer"]
    suppliers = [x for x in verified if x.get("type") == "supplier"]
    demand = [x for x in buyers if x.get("demand_signal")]
    opps = state.get("market_opportunities", []) or []
    cases = state.get("interlocution_cases", []) or []
    requirements = [x for x in cases if x.get("supplier_rfq_ready")]
    offers = [x for x in state.get("offers", []) or [] if x.get("source") != "demo/simulación"]
    comparable = [x for x in state.get("quote_comparisons", []) or [] if x.get("status") == "comparable"]
    proposals = state.get("proposals", []) or []
    real_tx = [
        x for x in state.get("transactions", []) or []
        if str(x.get("status") or "") in {"closed", "settled", "paid", "completed", "delivered", "invoiced"}
        and str(x.get("status") or "") not in {"closed_simulated", "simulated"}
    ]

    supplier_network = state.get("supplier_network", {}) or {}
    revops = state.get("commercial_execution", {}) or {}
    cfo = state.get("cfo", {}) or {}
    finance = cfo.get("financial_snapshot", {}) or {}
    growth = state.get("growth_expansion", {}) or {}
    trade = state.get("trade_logistics", {}) or {}
    safeguards = state.get("deal_safeguards_report", {}) or {}
    operations = state.get("operations_control", {}) or (state.get("connector_telemetry", {}) or {}).get("autonomous_coo", {}) or {}
    document = state.get("document_intelligence_report", {}) or (state.get("connector_telemetry", {}) or {}).get("document_intelligence", {}) or {}
    knowledge = state.get("enterprise_knowledge_graph", {}) or {}

    market_score = (
        min(100.0, len(verified) * 6.0) * 0.20
        + min(100.0, len(demand) * 12.0) * 0.25
        + min(100.0, len(opps) * 10.0) * 0.25
        + min(100.0, _pct(len(requirements), max(1, len(opps)))) * 0.30
    )
    procurement_score = (
        min(100.0, _i(supplier_network.get("supplier_profiles")) * 5.0) * 0.20
        + min(100.0, _i(supplier_network.get("tier_a")) * 18.0) * 0.20
        + min(100.0, _i(supplier_network.get("squads_ready")) * 20.0) * 0.30
        + max(0.0, 100.0 - _i(supplier_network.get("network_gaps")) * 18.0) * 0.30
    )
    active_revops = _i(revops.get("active_cases"))
    revops_score = (
        min(100.0, active_revops * 15.0) * 0.20
        + min(100.0, _pct(len(comparable), max(1, len(offers)))) * 0.25
        + min(100.0, _pct(len(proposals), max(1, len(comparable)))) * 0.25
        + min(100.0, _pct(len(real_tx), max(1, len(proposals)))) * 0.30
    )
    risk_profit = max(0.0, _f(finance.get("risk_adjusted_expected_profit_usd")))
    realized = max(0.0, _f(finance.get("realized_profit_usd")))
    warnings = len(cfo.get("warnings", []) or [])
    finance_score = min(100.0, risk_profit / 30.0) * 0.45 + min(100.0, realized / 20.0) * 0.35 + max(0.0, 100.0 - warnings * 14.0) * 0.20

    growth_ready = bool((growth.get("readiness", {}) or {}).get("ready"))
    growth_score = min(100.0, _f((growth.get("readiness", {}) or {}).get("score"))) * 0.60 + (100.0 if growth_ready else 35.0) * 0.40

    cross_border = _i(trade.get("cross_border_cases"))
    route_ready = _i(trade.get("route_comparisons_ready"))
    incomplete = _i(trade.get("trade_data_incomplete"))
    trade_score = (
        (70.0 if cross_border == 0 else min(100.0, _pct(route_ready, max(1, cross_border)))) * 0.70
        + max(0.0, 100.0 - incomplete * 15.0) * 0.30
    )

    reviewed = _i(safeguards.get("deals_reviewed"))
    cleared = _i(safeguards.get("cleared"))
    incidents = _i(safeguards.get("open_incidents"))
    legal = _i(safeguards.get("mandatory_legal_review"))
    safeguards_score = (
        (85.0 if reviewed == 0 else _pct(cleared, reviewed)) * 0.55
        + max(0.0, 100.0 - incidents * 25.0 - legal * 20.0) * 0.45
    )

    health = _f(operations.get("health_score"), 100.0)
    failed = len((operations.get("engine_health", {}) or {}).get("failed_now", []) or [])
    circuits = len((operations.get("engine_health", {}) or {}).get("circuits_open", []) or [])
    reliability_score = max(0.0, min(100.0, health - failed * 12.0 - circuits * 15.0))

    docs = _i(document.get("documents"))
    extracted = _i(document.get("extracted"))
    ocr = _i(document.get("ocr_required"))
    nodes = len(knowledge.get("nodes", []) or [])
    knowledge_score = (
        (75.0 if docs == 0 else _pct(extracted, docs)) * 0.45
        + max(0.0, 100.0 - ocr * 12.0) * 0.20
        + min(100.0, nodes * 2.5) * 0.35
    )

    rows = [
        {"department": "Market Intelligence", "score": market_score, "owner_engine": "Scout / Lead / Demand / Pipeline", "economic_role": "crear demanda verificable y oportunidades"},
        {"department": "Procurement", "score": procurement_score, "owner_engine": "Supplier Network / Deep Dive", "economic_role": "crear competencia real y mejores condiciones"},
        {"department": "RevOps", "score": revops_score, "owner_engine": "Commercial Execution", "economic_role": "convertir conversaciones en ofertas y cierres"},
        {"department": "Finance", "score": finance_score, "owner_engine": "CFO / War Room", "economic_role": "maximizar beneficio ajustado por riesgo y proteger caja"},
        {"department": "Growth", "score": growth_score, "owner_engine": "Growth & Expansion", "economic_role": "crear nuevas fuentes de beneficio sin romper el core"},
        {"department": "Trade", "score": trade_score, "owner_engine": "Trade & Logistics", "economic_role": "hacer viable el abastecimiento internacional total"},
        {"department": "Safeguards", "score": safeguards_score, "owner_engine": "Deal Safeguards", "economic_role": "evitar beneficio aparente con exposición postventa/contractual"},
        {"department": "Reliability", "score": reliability_score, "owner_engine": "Autonomous COO", "economic_role": "mantener la empresa operativa y recuperable"},
        {"department": "Knowledge", "score": knowledge_score, "owner_engine": "Document Intelligence / Knowledge Graph", "economic_role": "convertir cada operación en ventaja acumulativa"},
    ]
    for row in rows:
        row["score"] = round(max(0.0, min(100.0, _f(row["score"]))), 1)
        row["status"] = "strong" if row["score"] >= 78 else "healthy" if row["score"] >= 62 else "repair" if row["score"] >= 42 else "critical"
    rows.sort(key=lambda x: x["score"])
    return rows


def _deal_portfolio(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    cfo_rows = {str(x.get("deal_id")): x for x in (state.get("cfo", {}) or {}).get("deal_financial_rankings", []) or [] if x.get("deal_id")}
    safeguard = state.get("deal_safeguard_index", {}) or {}
    rows: List[Dict[str, Any]] = []
    for deal in state.get("deals", []) or []:
        deal_id = str(deal.get("id") or "")
        if not deal_id or deal.get("source") == "demo" or str(deal.get("stage") or "") in {"cerrado (simulación)", "closed_simulated"}:
            continue
        money = cfo_rows.get(deal_id, {})
        safe = safeguard.get(deal_id, {}) or deal.get("deal_safeguards", {}) or {}
        money_score = _f(money.get("money_score"))
        ra_profit = _f(money.get("risk_adjusted_expected_profit_usd"))
        safe_score = _f(safe.get("safe_close_score"), 100.0)
        incident = bool(deal.get("incident_hold"))
        legal = bool(deal.get("legal_review_required"))
        econ = bool((deal.get("economics") or {}).get("viable"))
        if incident or legal:
            disposition = "HOLD_RISK"
            reason = "Incidente o revisión legal pendiente; preservar valor evitando nueva exposición."
        elif safe and not safe.get("cleared") and safe_score < 65:
            disposition = "REPAIR_RISK"
            reason = "El beneficio no compensa avanzar sin corregir exposición comercial/postventa."
        elif money_score >= 72 and ra_profit > 0 and safe_score >= 80:
            disposition = "PURSUE"
            reason = "Buen valor económico ajustado por riesgo y estructura de cierre saludable."
        elif econ and money_score >= 50:
            disposition = "IMPROVE"
            reason = "Economía viable, pero todavía hay que mejorar probabilidad, términos o competencia."
        elif not econ and str(deal.get("stage") or "") not in {"descubrimiento", "contacto preparado"}:
            disposition = "PARK"
            reason = "No hay economía viable suficiente; no consumir atención premium hasta que aparezca nueva evidencia."
        else:
            disposition = "DISCOVER"
            reason = "Todavía falta evidencia para decidir si escalar o descartar."
        rows.append({
            "deal_id": deal_id,
            "category": deal.get("need") or deal.get("category"),
            "buyer": deal.get("buyer"),
            "stage": deal.get("stage"),
            "money_score": round(money_score, 1),
            "risk_adjusted_expected_profit_usd": round(ra_profit, 2),
            "safe_close_score": round(safe_score, 1),
            "disposition": disposition,
            "reason": reason,
        })
    priority = {"PURSUE": 6, "IMPROVE": 5, "REPAIR_RISK": 4, "DISCOVER": 3, "HOLD_RISK": 2, "PARK": 1}
    rows.sort(key=lambda x: (priority.get(x["disposition"], 0), x["money_score"], x["risk_adjusted_expected_profit_usd"]), reverse=True)
    return rows[:MAX_PORTFOLIO_ROWS]


def _category_portfolio(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    learning = state.get("profit_learning", {}) or {}
    rankings = learning.get("category_rankings", []) or learning.get("rankings", []) or []
    if not rankings:
        rankings = (state.get("profit_learning_memory", {}) or {}).get("category_scores", {}).values()
    rows: List[Dict[str, Any]] = []
    for raw in rankings:
        category = raw.get("category")
        if not category:
            continue
        score = _f(raw.get("learned_score"), _f(raw.get("score"), _f(raw.get("ema"), 50.0)))
        confidence = _f(raw.get("confidence"))
        observations = _i(raw.get("observations"))
        tx = _i(raw.get("transactions"))
        profit = _f(raw.get("transaction_profit_usd"), _f(raw.get("company_profit_usd")))
        if observations >= 15 and confidence >= 0.65 and score >= 70:
            action = "SCALE"
        elif observations >= 15 and confidence >= 0.65 and score < 35:
            action = "PAUSE"
        elif score >= 58 and confidence >= 0.35:
            action = "INVEST"
        elif observations >= 8 and score < 45:
            action = "REPAIR"
        else:
            action = "EXPLORE"
        rows.append({
            "category": category,
            "learned_score": round(score, 1),
            "confidence": round(confidence, 2),
            "observations": observations,
            "real_transactions": tx,
            "observed_profit_usd": round(profit, 2),
            "management_action": action,
        })
    order = {"SCALE": 5, "INVEST": 4, "EXPLORE": 3, "REPAIR": 2, "PAUSE": 1}
    rows.sort(key=lambda x: (order.get(x["management_action"], 0), x["learned_score"], x["confidence"]), reverse=True)
    return rows[:20]


def _primary_priority(state: Dict[str, Any], departments: List[Dict[str, Any]], deals: List[Dict[str, Any]], categories: List[Dict[str, Any]]) -> Dict[str, Any]:
    governance = state.get("master_governance", {}) or {}
    mode = str(governance.get("company_mode") or "")
    if mode == "RECOVERY":
        return {"department": "Reliability", "code": "restore_operations", "title": "Recuperar salud operativa", "priority": 100, "autonomous": True, "reason": "La Constitución no permite optimizar crecimiento sobre una base operativa degradada."}

    legal_hold = next((x for x in deals if x.get("disposition") == "HOLD_RISK"), None)
    if legal_hold:
        return {"department": "Safeguards", "code": "protect_high_value_deal", "title": f"Resolver exposición de {legal_hold.get('deal_id')}", "priority": 99, "autonomous": False, "reason": legal_hold.get("reason"), "deal_id": legal_hold.get("deal_id")}

    pursue = next((x for x in deals if x.get("disposition") == "PURSUE"), None)
    weakest = departments[0] if departments else {"department": "Company", "score": 50}
    if pursue and _f(pursue.get("money_score")) >= 78:
        return {"department": "RevOps", "code": "close_best_safe_deal", "title": f"Concentrar ejecución en {pursue.get('deal_id')}", "priority": 96, "autonomous": True, "reason": f"Money score {pursue.get('money_score')} con Safe Close {pursue.get('safe_close_score')}."}

    scale = next((x for x in categories if x.get("management_action") == "SCALE"), None)
    if scale and mode in {"CONTROLLED_GROWTH", "BALANCED"}:
        return {"department": "Growth", "code": "compound_category_winner", "title": f"Escalar ganador: {scale.get('category')}", "priority": 90, "autonomous": True, "reason": f"Evidencia suficiente: score {scale.get('learned_score')}, confianza {scale.get('confidence')}."}

    return {
        "department": weakest.get("department"),
        "code": "repair_weakest_department",
        "title": f"Mejorar {weakest.get('department')}",
        "priority": min(92, round(70 + max(0.0, 70 - _f(weakest.get("score"))) * 0.45)),
        "autonomous": weakest.get("department") not in {"Safeguards"},
        "reason": f"Es el área más débil actualmente ({weakest.get('score')}/100); mejorar el cuello de botella aumenta el rendimiento del sistema completo.",
    }


def _resource_adjustment(primary: Dict[str, Any], governance: Dict[str, Any]) -> Dict[str, float]:
    department = str(primary.get("department") or "")
    mapping = {
        "Market Intelligence": {"core_research_pct": 8, "deep_dive_pct": -3, "exploration_pct": -5},
        "Procurement": {"deep_dive_pct": 8, "core_research_pct": -4, "exploration_pct": -4},
        "RevOps": {"deep_dive_pct": 8, "core_research_pct": -3, "exploration_pct": -5},
        "Growth": {"expansion_pct": 8, "core_research_pct": -4, "exploration_pct": -4},
        "Trade": {"expansion_pct": 5, "deep_dive_pct": 3, "exploration_pct": -5, "core_research_pct": -3},
        "Knowledge": {"core_research_pct": 4, "exploration_pct": 4, "deep_dive_pct": -4, "expansion_pct": -4},
    }
    raw = dict(mapping.get(department, {}))
    switches = governance.get("kill_switches", {}) or {}
    if switches.get("expansion_pause"):
        raw.pop("expansion_pct", None)
    if str(governance.get("company_mode") or "") in {"RECOVERY", "PROTECT_CASH"}:
        return {}
    return {k: max(-8.0, min(8.0, _f(v))) for k, v in raw.items() if k in RESOURCE_KEYS}


def _program_metric(department: str, departments: List[Dict[str, Any]]) -> float:
    row = next((x for x in departments if x.get("department") == department), {})
    return _f(row.get("score"))


def _update_programs(state: Dict[str, Any], memory: Dict[str, Any], departments: List[Dict[str, Any]], primary: Dict[str, Any]) -> List[Dict[str, Any]]:
    cycle = _i(memory.get("cycle"))
    active: List[Dict[str, Any]] = []
    for program in memory.get("programs", []) or []:
        if program.get("status") != "active":
            continue
        current = _program_metric(str(program.get("department")), departments)
        program["current_score"] = round(current, 1)
        if cycle >= _i(program.get("review_cycle")):
            delta = current - _f(program.get("baseline_score"))
            program["status"] = "completed"
            program["completed_at"] = utcnow()
            program["delta"] = round(delta, 1)
            program["outcome"] = "supported" if delta >= 7 else "negative" if delta <= -5 else "inconclusive"
            memory.setdefault("program_history", []).append(dict(program))
        else:
            active.append(program)

    target_department = str(primary.get("department") or "")
    existing = next((x for x in active if x.get("department") == target_department), None)
    if target_department and not existing and len(active) < MAX_PROGRAMS and primary.get("autonomous", True):
        baseline = _program_metric(target_department, departments)
        program = {
            "id": f"MGMT-{cycle:05d}-{target_department.lower().replace(' ', '-')[:20]}",
            "department": target_department,
            "status": "active",
            "started_cycle": cycle,
            "review_cycle": cycle + PROGRAM_HOLD_CYCLES,
            "started_at": utcnow(),
            "baseline_score": round(baseline, 1),
            "target_score": round(min(100.0, baseline + 12.0), 1),
            "objective": primary.get("title"),
            "reason": primary.get("reason"),
            "autonomous": True,
            "binding": False,
        }
        active.append(program)
    memory["programs"] = active
    memory["program_history"] = (memory.get("program_history", []) or [])[-MAX_HISTORY:]
    return active


def autonomous_management_tick(state: Dict[str, Any], governance: Dict[str, Any]) -> Dict[str, Any]:
    memory = _ensure(state)
    memory["cycle"] = _i(memory.get("cycle")) + 1
    departments = _department_scorecards(state)
    deals = _deal_portfolio(state)
    categories = _category_portfolio(state)
    primary = _primary_priority(state, departments, deals, categories)
    programs = _update_programs(state, memory, departments, primary)
    adjustments = _resource_adjustment(primary, governance)

    prev = str(memory.get("last_primary_department") or "")
    current = str(primary.get("department") or "")
    memory["primary_streak"] = _i(memory.get("primary_streak")) + 1 if current and current == prev else 1
    memory["last_primary_department"] = current
    memory.setdefault("department_history", []).append({
        "ts": utcnow(),
        "cycle": memory["cycle"],
        "primary_department": current,
        "company_mode": governance.get("company_mode"),
        "department_scores": {x["department"]: x["score"] for x in departments},
    })
    memory["department_history"] = memory["department_history"][-MAX_HISTORY:]
    memory.setdefault("portfolio_history", []).append({
        "ts": utcnow(),
        "pursue": sum(1 for x in deals if x.get("disposition") == "PURSUE"),
        "repair_risk": sum(1 for x in deals if x.get("disposition") == "REPAIR_RISK"),
        "park": sum(1 for x in deals if x.get("disposition") == "PARK"),
        "scale_categories": [x.get("category") for x in categories if x.get("management_action") == "SCALE"][:5],
        "pause_categories": [x.get("category") for x in categories if x.get("management_action") == "PAUSE"][:5],
    })
    memory["portfolio_history"] = memory["portfolio_history"][-MAX_HISTORY:]

    company_score = round(sum(_f(x.get("score")) for x in departments) / max(1, len(departments)), 1)
    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_executive_management",
        "cycle": memory["cycle"],
        "north_star": "durable_risk_adjusted_realized_profit_and_compounding_business_quality",
        "company_management_score": company_score,
        "department_scorecards": departments,
        "deal_portfolio": deals,
        "category_portfolio": categories,
        "primary_management_priority": primary,
        "active_improvement_programs": programs,
        "completed_programs": (memory.get("program_history", []) or [])[-12:],
        "resource_adjustment": adjustments,
        "governance": {
            "may_decide": [
                "attention allocation", "research mix", "deal pursuit/repair/park priority",
                "category scale/invest/explore/repair/pause recommendation", "reversible improvement programs",
            ],
            "may_not_decide": [
                "contracts", "payments", "binding legal terms", "refund admissions", "orders",
                "financial commitments", "unsafe policy overrides", "self-modifying production code",
            ],
            "anti_thrash": f"improvement programs hold for {PROGRAM_HOLD_CYCLES} cycles before outcome evaluation",
            "evidence_rule": "weak evidence leads to explore/repair rather than aggressive scale/pause",
        },
    }
    state["autonomous_management"] = report

    record_decision(
        state,
        engine="Autonomous Executive Management",
        object_type="company",
        object_id="LUMEN",
        decision=str(primary.get("code") or "manage_company"),
        reason=str(primary.get("reason") or "Continuous management"),
        action="score_opportunity",
        confidence=0.9,
        evidence_refs=[],
        allowed=True,
        requires_approval=not bool(primary.get("autonomous", True)),
    )
    return report
