from __future__ import annotations

"""LUMEN Autonomy Core.

Adds bounded shared memory, peer-help routing, outcome-based experience learning,
lesson compilation, research-gap missions, skill tracking, and safe policy promotion.
It can reallocate reversible attention and public-research work, but it never widens
binding, financial, legal, connector, paid-media, or production-deployment authority.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import hashlib

import agent_fleet
import elastic_agent_fleet

VERSION = "1.0-autonomy-core"
MAX_BLACKBOARD = 60
MAX_EXPERIENCES = 160
MAX_LESSONS = 80
MAX_HELP_REQUESTS = 40
MAX_RESEARCH_MISSIONS = 40
MAX_SKILL_AGENTS = 220
MISSION_MAX_ATTEMPTS = 3
ROLE_BOOST_CAP = 0.12

_ACTIVE_STATE: Optional[Dict[str, Any]] = None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _norm(value: Any) -> str:
    return _clean(value).lower()


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fingerprint(*parts: Any) -> str:
    raw = "|".join(_norm(x) for x in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _core(state: Dict[str, Any]) -> Dict[str, Any]:
    core = state.setdefault("autonomy_core", {})
    core.setdefault("version", VERSION)
    core.setdefault("status", "active")
    core.setdefault("goals", [])
    core.setdefault("blackboard", [])
    core.setdefault("experiences", [])
    core.setdefault("lessons", [])
    core.setdefault("peer_help", [])
    core.setdefault("research_missions", [])
    core.setdefault("skill_registry", {})
    core.setdefault("policy_hints", {})
    core.setdefault("role_attention", {})
    core.setdefault("last_metric_snapshot", {})
    return core


def _metric_snapshot(state: Dict[str, Any]) -> Dict[str, float]:
    truth = _safe_dict(state.get("canonical_revenue_truth"))
    counts = _safe_dict(truth.get("counts"))
    funnel = _safe_dict(state.get("business_funnel"))
    readiness = _safe_dict(state.get("external_market_readiness"))
    acquisition = _safe_dict(state.get("acquisition_campaigns"))
    workforce = _safe_dict(state.get("agent_workforce"))
    last_cycle = _safe_dict(workforce.get("last_cycle"))
    coo = _safe_dict(state.get("autonomous_coo"))
    engine = _safe_dict(coo.get("engine_health"))
    first_cash = _safe_dict(state.get("first_cash_mode"))
    return {
        "canonical_opportunities": _float(counts.get("canonical_opportunities")),
        "canonical_real_offers": _float(counts.get("canonical_real_offers")),
        "canonical_proposals": _float(counts.get("canonical_proposals")),
        "canonical_close_ready": _float(counts.get("canonical_close_ready")),
        "buyers_with_verified_demand": _float(counts.get("buyers_with_verified_demand")),
        "requirements_ready_for_rfq": _float(funnel.get("requirements_ready_for_rfq")),
        "verified_commercial_channels": _float(funnel.get("verified_commercial_channels")),
        "eligible_external_prospects": _float(readiness.get("eligible_external_prospects")),
        "acquisition_leads": _float(acquisition.get("leads")),
        "acquisition_clicks": _float(acquisition.get("clicks")),
        "new_research_leads": _float(last_cycle.get("new_research_leads")),
        "new_market_signals": _float(last_cycle.get("new_market_signals")),
        "engine_failures": float(len(engine.get("failed_now", []) or [])),
        "circuits_open": float(len(engine.get("circuits_open", []) or [])),
        "realized_profit_detected": 1.0 if first_cash.get("realized_profit_detected") else 0.0,
    }


def _target_metric(state: Dict[str, Any]) -> str:
    crd = _safe_dict(state.get("continuous_revenue_drive"))
    metric = _clean(crd.get("primary_success_metric"))
    truth = _safe_dict(state.get("canonical_revenue_truth"))
    for key in (
        "requirements_ready_for_rfq", "canonical_real_offers", "canonical_close_ready",
        "canonical_opportunities", "eligible_external_prospects", "buyers_with_verified_demand",
    ):
        if key in metric:
            return key
    return _clean(truth.get("target_metric")) or "realized_profit_detected"


def _goal_registry(state: Dict[str, Any], core: Dict[str, Any], metrics: Dict[str, float]) -> List[Dict[str, Any]]:
    truth = _safe_dict(state.get("canonical_revenue_truth"))
    crd = _safe_dict(state.get("continuous_revenue_drive"))
    lane = _clean(crd.get("primary_lane") or truth.get("recommended_lane") or "learning")
    target = _target_metric(state)
    goals = [
        {
            "id": "GOAL-FIRST-CASH", "priority": 100,
            "objective": "Reach verified realized profitable revenue through canonical evidence-backed commercial progress.",
            "owner_role": "revops", "metric": "realized_profit_detected",
            "current": metrics.get("realized_profit_detected", 0.0), "target": 1.0,
            "status": "achieved" if metrics.get("realized_profit_detected", 0.0) >= 1 else "active",
        },
        {
            "id": f"GOAL-LANE-{lane.upper() or 'LEARNING'}", "priority": 95,
            "objective": _clean(crd.get("primary_action") or truth.get("reason") or "Advance the current canonical revenue bottleneck."),
            "owner_role": "revops" if lane in {"quote_creation", "closing", "opportunity_building"} else "research_analyst",
            "lane": lane, "metric": target, "current": metrics.get(target, 0.0),
            "target": max(1.0, metrics.get(target, 0.0) + 1.0), "status": "active",
        },
        {
            "id": "GOAL-RELIABILITY", "priority": 85,
            "objective": "Keep the autonomous operating system healthy while commercial work continues.",
            "owner_role": "risk_quality", "metric": "engine_failures",
            "current": metrics.get("engine_failures", 0.0) + metrics.get("circuits_open", 0.0), "target": 0.0,
            "status": "achieved" if metrics.get("engine_failures", 0.0) + metrics.get("circuits_open", 0.0) <= 0 else "active",
        },
    ]
    core["goals"] = goals
    return goals


def _canonical_opportunity_context(state: Dict[str, Any]) -> Dict[str, Any]:
    truth = _safe_dict(state.get("canonical_revenue_truth"))
    ids = {str(x) for x in truth.get("canonical_opportunity_ids", []) or []}
    opp = next((x for x in state.get("market_opportunities", []) or [] if isinstance(x, dict) and str(x.get("id") or "") in ids), {})
    accounts = {str(x.get("id") or ""): x for x in state.get("candidate_accounts", []) or [] if isinstance(x, dict)}
    buyer = accounts.get(str(opp.get("buyer_account_id") or ""), {})
    supplier = accounts.get(str(opp.get("supplier_account_id") or ""), {})
    category = _clean(opp.get("category") or opp.get("product") or opp.get("title") or buyer.get("category") or supplier.get("category") or "suministro industrial")
    buyer_name = _clean(buyer.get("company") or buyer.get("name") or buyer.get("title") or buyer.get("domain") or "comprador")
    return {"opportunity_id": opp.get("id"), "category": category[:180], "buyer_name": buyer_name[:180]}


def _ensure_help(core: Dict[str, Any], code: str, requester: str, roles: List[str], task: str, metric: str, baseline: float, priority: int) -> None:
    existing = next((x for x in core.get("peer_help", []) if x.get("code") == code and x.get("status") not in {"resolved", "expired"}), None)
    if existing:
        existing.update({"priority": priority, "task": task, "target_roles": roles})
        return
    rows = core.setdefault("peer_help", [])
    rows.append({
        "id": f"HELP-{_fingerprint(code, requester, metric)}", "code": code, "created_at": _now(), "status": "open",
        "requester_role": requester, "target_roles": roles, "task": task, "success_metric": metric,
        "baseline": baseline, "priority": priority, "binding": False,
    })
    core["peer_help"] = rows[-MAX_HELP_REQUESTS:]


def _refresh_peer_help(state: Dict[str, Any], core: Dict[str, Any], metrics: Dict[str, float]) -> List[Dict[str, Any]]:
    truth = _safe_dict(state.get("canonical_revenue_truth"))
    lane = _clean(_safe_dict(state.get("continuous_revenue_drive")).get("primary_lane") or truth.get("recommended_lane"))
    opp_ctx = _canonical_opportunity_context(state)
    category = opp_ctx.get("category") or "suministro industrial"
    if lane == "quote_creation" and metrics.get("requirements_ready_for_rfq", 0) <= 0:
        _ensure_help(core, "complete_requirement_pack", "revops", ["research_analyst"], f"Complete traceable buyer requirement evidence for the strongest canonical opportunity in {category}.", "requirements_ready_for_rfq", metrics.get("requirements_ready_for_rfq", 0), 100)
        _ensure_help(core, "supplier_match_evidence", "revops", ["supplier_hunter"], f"Find verified supplier evidence for the canonical {category} opportunity so an RFQ can be prepared.", "requirements_ready_for_rfq", metrics.get("requirements_ready_for_rfq", 0), 96)
    elif lane == "quote_creation" and metrics.get("canonical_real_offers", 0) <= 0:
        _ensure_help(core, "capture_real_quote", "revops", ["supplier_hunter", "negotiator"], f"Move RFQ-ready {category} work toward at least one traceable comparable supplier quote.", "canonical_real_offers", metrics.get("canonical_real_offers", 0), 100)
    if metrics.get("eligible_external_prospects", 0) <= 0 and metrics.get("buyers_with_verified_demand", 0) > 0:
        _ensure_help(core, "verify_buyer_contact", "buyer_hunter", ["research_analyst"], "Verify an evidence-backed corporate commercial channel for a demand-verified buyer.", "eligible_external_prospects", metrics.get("eligible_external_prospects", 0), 92)
    if metrics.get("acquisition_clicks", 0) > 0 and metrics.get("acquisition_leads", 0) <= 0:
        _ensure_help(core, "analyze_acquisition_friction", "market_manager", ["research_analyst", "revops"], "Analyze observed click-to-lead friction and prepare a measurable organic conversion improvement.", "acquisition_leads", metrics.get("acquisition_leads", 0), 76)
    if metrics.get("engine_failures", 0) + metrics.get("circuits_open", 0) > 0:
        _ensure_help(core, "repair_runtime_health", "system", ["risk_quality"], "Diagnose current engine failures or open circuits without interrupting unrelated healthy work.", "engine_failures", metrics.get("engine_failures", 0), 98)
    current_cycle = _int(state.get("ticks"))
    last_results = list(_safe_dict(state.get("agent_workforce")).get("last_results", []) or [])
    for row in core.get("peer_help", []) or []:
        if row.get("status") in {"resolved", "expired"}:
            continue
        metric = _clean(row.get("success_metric"))
        current = metrics.get(metric, 0.0)
        baseline = _float(row.get("baseline"))
        resolved = (current < baseline or current <= 0) if metric == "engine_failures" else current > baseline
        if resolved:
            row["status"] = "resolved"; row["resolved_at"] = _now(); row["resolved_cycle"] = current_cycle
            row["outcome"] = {"metric": metric, "baseline": baseline, "current": current}
            continue
        matching = [x for x in last_results if _clean(x.get("role")) in set(row.get("target_roles") or []) and x.get("ok")]
        if matching:
            row["status"] = "in_progress"
            row["last_peer_evidence"] = [_clean(x.get("finding"))[:260] for x in matching[:3] if _clean(x.get("finding"))]
            row["last_peer_cycle"] = current_cycle
    return list(core.get("peer_help", []) or [])


def _ensure_mission(core: Dict[str, Any], code: str, role: str, query: str, category: str, metric: str, baseline: float, priority: int, goal_id: str) -> None:
    existing = next((x for x in core.get("research_missions", []) if x.get("code") == code and x.get("status") not in {"resolved", "expired", "failed"}), None)
    if existing:
        existing.update({"priority": priority, "query": query, "category": category, "role": role, "goal_id": goal_id})
        return
    rows = core.setdefault("research_missions", [])
    rows.append({
        "id": f"MISSION-{_fingerprint(code, role, query)}", "code": code, "created_at": _now(), "status": "pending",
        "role": role, "query": query[:500], "category": category[:180], "success_metric": metric,
        "baseline": baseline, "priority": priority, "goal_id": goal_id, "attempts": 0,
        "source_policy": "public_web_only; respect existing search budget and verification gates", "binding": False,
    })
    core["research_missions"] = rows[-MAX_RESEARCH_MISSIONS:]


def _refresh_research_missions(state: Dict[str, Any], core: Dict[str, Any], metrics: Dict[str, float]) -> List[Dict[str, Any]]:
    truth = _safe_dict(state.get("canonical_revenue_truth"))
    lane = _clean(_safe_dict(state.get("continuous_revenue_drive")).get("primary_lane") or truth.get("recommended_lane"))
    ctx = _canonical_opportunity_context(state)
    buyer = (ctx.get("buyer_name") or "comprador").replace('"', "")
    category = (ctx.get("category") or "suministro industrial").replace('"', "")
    cycle = _int(state.get("ticks"))
    if lane == "quote_creation" and metrics.get("requirements_ready_for_rfq", 0) <= 0:
        _ensure_mission(core, "buyer_requirement_evidence", "research_analyst", f'"{buyer}" (compras OR licitación OR requerimiento OR especificaciones OR abastecimiento) "{category}"', category, "requirements_ready_for_rfq", metrics.get("requirements_ready_for_rfq", 0), 100, "GOAL-LANE-QUOTE_CREATION")
        _ensure_mission(core, "supplier_evidence_for_rfq", "supplier_hunter", f'"{category}" (fabricante OR distribuidor OR mayorista OR proveedor oficial) Argentina -mercadolibre -facebook', category, "requirements_ready_for_rfq", metrics.get("requirements_ready_for_rfq", 0), 96, "GOAL-LANE-QUOTE_CREATION")
    elif lane == "quote_creation" and metrics.get("canonical_real_offers", 0) <= 0:
        _ensure_mission(core, "supplier_quote_sources", "supplier_hunter", f'"{category}" (cotización OR precio OR distribuidor OR proveedor) Argentina -mercadolibre', category, "canonical_real_offers", metrics.get("canonical_real_offers", 0), 100, "GOAL-LANE-QUOTE_CREATION")
    if metrics.get("eligible_external_prospects", 0) <= 0 and metrics.get("buyers_with_verified_demand", 0) > 0:
        _ensure_mission(core, "buyer_contact_evidence", "research_analyst", f'"{buyer}" (contacto OR compras OR abastecimiento OR email OR proveedores) sitio oficial', category, "eligible_external_prospects", metrics.get("eligible_external_prospects", 0), 92, "GOAL-CONTACT")
    for mission in core.get("research_missions", []) or []:
        if mission.get("status") in {"resolved", "expired", "failed"}:
            continue
        metric = _clean(mission.get("success_metric")); current = metrics.get(metric, 0.0); baseline = _float(mission.get("baseline"))
        if current > baseline:
            mission["status"] = "resolved"; mission["resolved_at"] = _now(); mission["outcome"] = {"metric": metric, "baseline": baseline, "current": current}
        elif mission.get("status") == "dispatched" and _int(mission.get("last_dispatched_cycle"), -1) < cycle:
            if _int(mission.get("attempts")) >= MISSION_MAX_ATTEMPTS:
                mission["status"] = "failed"; mission["failure_reason"] = "bounded_attempts_exhausted_without_target_metric_movement"
            else:
                mission["status"] = "pending"
    return list(core.get("research_missions", []) or [])


def _experience_learning(state: Dict[str, Any], core: Dict[str, Any], metrics: Dict[str, float]) -> Optional[Dict[str, Any]]:
    previous = _safe_dict(core.get("last_metric_snapshot")); core["last_metric_snapshot"] = dict(metrics)
    if not previous:
        return None
    lane = _clean(_safe_dict(state.get("continuous_revenue_drive")).get("primary_lane") or _safe_dict(state.get("canonical_revenue_truth")).get("recommended_lane") or "learning")
    metric = _target_metric(state); before = _float(previous.get(metric)); after = _float(metrics.get(metric)); delta = after - before
    verdict = "improved" if delta > 0 else "regressed" if delta < 0 else "no_effect"
    workforce = _safe_dict(state.get("agent_workforce"))
    experience = {
        "id": f"EXP-{_fingerprint(state.get('ticks'), lane, metric, before, after)}", "created_at": _now(), "cycle": _int(state.get("ticks")),
        "lane": lane, "target_metric": metric, "before": before, "after": after, "delta": delta, "verdict": verdict,
        "role_plan": dict(_safe_dict(workforce.get("role_plan"))),
        "research_missions_dispatched": [x.get("id") for x in core.get("research_missions", []) or [] if x.get("status") == "dispatched"],
        "causality_rule": "association_only; promote behavior only after repeated measurable outcomes",
    }
    rows = list(core.get("experiences", []) or [])
    if not rows or rows[-1].get("id") != experience["id"]:
        rows.append(experience)
    core["experiences"] = rows[-MAX_EXPERIENCES:]
    return experience


def _compile_lessons(state: Dict[str, Any], core: Dict[str, Any]) -> List[Dict[str, Any]]:
    experiences = list(core.get("experiences", []) or [])
    lessons_by_code = {str(x.get("code")): x for x in core.get("lessons", []) or [] if x.get("code")}
    if experiences:
        latest = experiences[-1]; lane = _clean(latest.get("lane")) or "learning"; metric = _clean(latest.get("target_metric")) or "progress"
        if latest.get("verdict") == "improved":
            code = f"progress:{lane}:{metric}"
            lesson = lessons_by_code.get(code) or {
                "id": f"LESSON-{_fingerprint(code)}", "code": code, "created_at": _now(), "support": 0,
                "audience_roles": ["revops", "research_analyst", "supplier_hunter", "negotiator"],
                "teaching": f"When working in {lane}, keep evidence-backed actions tied to {metric}; measurable movement was observed.",
                "policy_scope": "attention_and_research_only",
            }
            lesson["support"] = _int(lesson.get("support")) + 1; lesson["last_seen"] = _now()
            lesson["confidence"] = round(min(0.95, 0.55 + 0.10 * lesson["support"]), 2)
            lesson["status"] = "promoted" if lesson["support"] >= 3 else "candidate"; lessons_by_code[code] = lesson
        else:
            recent = [x for x in experiences[-6:] if _clean(x.get("lane")) == lane and _clean(x.get("target_metric")) == metric and x.get("verdict") == "no_effect"]
            if len(recent) >= 3:
                code = f"stalled:{lane}:{metric}"
                lesson = lessons_by_code.get(code) or {
                    "id": f"LESSON-{_fingerprint(code)}", "code": code, "created_at": _now(), "support": 0,
                    "audience_roles": ["revops", "research_analyst", "risk_quality"],
                    "teaching": f"Do not repeat unchanged {lane} work when {metric} stays flat; inspect the evidence gap, ask peers for help, and change the test.",
                    "policy_scope": "attention_and_research_only",
                }
                lesson["support"] = max(_int(lesson.get("support")), len(recent)); lesson["last_seen"] = _now()
                lesson["confidence"] = round(min(0.95, 0.60 + 0.08 * lesson["support"]), 2); lesson["status"] = "promoted"
                lessons_by_code[code] = lesson
    skills = _safe_dict(core.get("skill_registry"))
    for agent_id, skill in list(skills.items())[:MAX_SKILL_AGENTS]:
        if _int(skill.get("useful_searches")) < 2:
            continue
        categories = _safe_dict(skill.get("categories"))
        best = sorted(categories.items(), key=lambda kv: (_int(_safe_dict(kv[1]).get("contributions")), _int(_safe_dict(kv[1]).get("successes"))), reverse=True)
        if not best:
            continue
        category, cat = best[0]
        if _int(_safe_dict(cat).get("successes")) < 2:
            continue
        role = _clean(skill.get("role")); code = f"search_yield:{role}:{_norm(category)[:60]}"
        lesson = lessons_by_code.get(code) or {
            "id": f"LESSON-{_fingerprint(code)}", "code": code, "created_at": _now(), "support": 0,
            "audience_roles": [role] if role else ["research_analyst"],
            "teaching": f"Public research in {category} has repeatedly produced useful evidence for the {role or 'research'} team.",
            "policy_scope": "research_priority_only", "mentor_agent_id": agent_id,
        }
        lesson["support"] = max(_int(lesson.get("support")), _int(_safe_dict(cat).get("successes")))
        lesson["confidence"] = round(min(0.95, 0.55 + 0.08 * lesson["support"]), 2)
        lesson["status"] = "promoted" if lesson["support"] >= 3 else "candidate"; lesson["last_seen"] = _now(); lessons_by_code[code] = lesson
    lessons = sorted(lessons_by_code.values(), key=lambda x: (_norm(x.get("status")) != "promoted", -_float(x.get("confidence")), -_int(x.get("support"))))[:MAX_LESSONS]
    core["lessons"] = lessons
    return lessons


def _critic(state: Dict[str, Any], core: Dict[str, Any], metrics: Dict[str, float]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []; metric = _target_metric(state)
    experiences = [x for x in core.get("experiences", []) or [] if _clean(x.get("target_metric")) == metric]
    no_effect = 0
    for row in reversed(experiences):
        if row.get("verdict") != "no_effect": break
        no_effect += 1
    if no_effect >= 3:
        issues.append({"code": "stalled_target_metric", "severity": "high", "metric": metric, "streak": no_effect, "recommendation": "Use peer help and research-gap missions; do not repeat the same tactic unchanged."})
    if metrics.get("engine_failures", 0) + metrics.get("circuits_open", 0) > 0:
        issues.append({"code": "runtime_health_degraded", "severity": "critical", "recommendation": "Assign Risk & Quality to diagnose and isolate the exact failing component."})
    if metrics.get("canonical_opportunities", 0) > 0 and metrics.get("requirements_ready_for_rfq", 0) <= 0 and metrics.get("canonical_real_offers", 0) <= 0:
        issues.append({"code": "requirement_gap_blocks_quote", "severity": "high", "recommendation": "Complete requirement evidence before spending attention on broad discovery."})
    core["critic"] = {"updated_at": _now(), "issues": issues, "status": "attention_required" if issues else "healthy"}
    return issues


def _role_attention(core: Dict[str, Any]) -> Dict[str, float]:
    boosts: Dict[str, float] = {}
    for row in core.get("peer_help", []) or []:
        if row.get("status") in {"resolved", "expired"}: continue
        for role in row.get("target_roles", []) or []:
            boosts[role] = boosts.get(role, 0.0) + 0.02 + min(0.04, _int(row.get("priority")) / 2500.0)
    for row in core.get("research_missions", []) or []:
        if row.get("status") not in {"pending", "dispatched"}: continue
        role = _clean(row.get("role"))
        if role: boosts[role] = boosts.get(role, 0.0) + 0.03 + min(0.04, _int(row.get("priority")) / 2500.0)
    bounded = {role: round(min(ROLE_BOOST_CAP, value), 4) for role, value in boosts.items()}
    core["role_attention"] = bounded
    core["policy_hints"] = {
        "safe_autopromote_scope": ["role_attention", "research_mission_priority", "peer_help_routing"],
        "production_code_self_modify": False, "binding_authority_changed": False, "active_role_boosts": bounded,
    }
    return bounded


def _blackboard_and_briefings(state: Dict[str, Any], core: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    cards: List[Dict[str, Any]] = []
    for goal in core.get("goals", []) or []:
        cards.append({"kind": "goal", "priority": goal.get("priority", 0), "id": goal.get("id"), "text": goal.get("objective"), "metric": goal.get("metric")})
    for row in core.get("peer_help", []) or []:
        if row.get("status") not in {"resolved", "expired"}:
            cards.append({"kind": "peer_help", "priority": row.get("priority", 0), "id": row.get("id"), "text": row.get("task"), "roles": row.get("target_roles")})
    for row in core.get("research_missions", []) or []:
        if row.get("status") in {"pending", "dispatched"}:
            cards.append({"kind": "research_mission", "priority": row.get("priority", 0), "id": row.get("id"), "text": row.get("query"), "role": row.get("role")})
    for row in core.get("lessons", []) or []:
        if row.get("status") == "promoted":
            cards.append({"kind": "lesson", "priority": int(_float(row.get("confidence")) * 100), "id": row.get("id"), "text": row.get("teaching"), "roles": row.get("audience_roles")})
    for row in issues:
        cards.append({"kind": "critic", "priority": 100 if row.get("severity") == "critical" else 90, "id": row.get("code"), "text": row.get("recommendation")})
    cards.sort(key=lambda x: -_int(x.get("priority"))); core["blackboard"] = cards[:MAX_BLACKBOARD]
    roles = list(elastic_agent_fleet.ROLE_META.keys()); briefings: Dict[str, Any] = {}
    for role in roles:
        lessons = [x for x in core.get("lessons", []) or [] if role in (x.get("audience_roles") or [])][:5]
        help_rows = [x for x in core.get("peer_help", []) or [] if x.get("status") not in {"resolved", "expired"} and role in (x.get("target_roles") or [])][:5]
        missions = [x for x in core.get("research_missions", []) or [] if x.get("status") in {"pending", "dispatched"} and _clean(x.get("role")) == role][:4]
        briefings[role] = {
            "top_goal": (core.get("goals") or [{}])[0].get("objective"),
            "lessons": [{"id": x.get("id"), "teaching": x.get("teaching"), "confidence": x.get("confidence")} for x in lessons],
            "help_requests": [{"id": x.get("id"), "task": x.get("task"), "priority": x.get("priority")} for x in help_rows],
            "research_missions": [{"id": x.get("id"), "query": x.get("query"), "priority": x.get("priority")} for x in missions],
            "operating_rule": "Share evidence through state; do not fabricate progress; binding actions remain human-gated.",
        }
    core["role_briefings"] = briefings
    workforce = state.setdefault("agent_workforce", {}); workforce["autonomy_briefing"] = briefings; workforce["shared_blackboard"] = core["blackboard"][:30]


def autonomy_core_prepare(state: Dict[str, Any]) -> Dict[str, Any]:
    core = _core(state); metrics = _metric_snapshot(state)
    _goal_registry(state, core, metrics); _refresh_peer_help(state, core, metrics); _refresh_research_missions(state, core, metrics)
    issues = _critic(state, core, metrics); _role_attention(core); _blackboard_and_briefings(state, core, issues); core["prepared_at"] = _now()
    return core


def autonomy_core_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    core = autonomy_core_prepare(state); metrics = _metric_snapshot(state)
    experience = _experience_learning(state, core, metrics); lessons = _compile_lessons(state, core); issues = _critic(state, core, metrics); role_attention = _role_attention(core)
    _blackboard_and_briefings(state, core, issues)
    core.update({
        "version": VERSION, "status": "active", "updated_at": _now(), "mode": "bounded_self_learning_shared_workforce",
        "objective": "goal-directed autonomous execution with shared learning and evidence-first research",
        "learning_cycle": "goal -> plan -> action -> measured outcome -> critic -> lesson -> peer teaching -> next plan",
        "latest_experience_id": experience.get("id") if experience else None, "metrics": metrics,
        "counts": {
            "goals": len(core.get("goals", []) or []), "blackboard_cards": len(core.get("blackboard", []) or []),
            "experiences": len(core.get("experiences", []) or []), "lessons": len(lessons),
            "promoted_lessons": sum(1 for x in lessons if x.get("status") == "promoted"),
            "open_peer_help": sum(1 for x in core.get("peer_help", []) or [] if x.get("status") not in {"resolved", "expired"}),
            "open_research_missions": sum(1 for x in core.get("research_missions", []) or [] if x.get("status") in {"pending", "dispatched"}),
            "skill_agents": len(_safe_dict(core.get("skill_registry"))), "critic_issues": len(issues),
        },
        "role_attention": role_attention,
        "authority": {
            "binding_contracts": "human_required", "payments_orders_financial_commitments": "human_required",
            "material_legal_liability": "human_required", "production_code_changes_deploys": "human_required",
            "new_external_connectors_accounts": "human_required", "paid_media_spend": "human_required",
            "binding_authority_changed": False,
        },
    })
    state["autonomy_core"] = core
    return core


_ORIGINAL_MERGE_SEARCH_RESULTS = agent_fleet._merge_search_results
_ORIGINAL_SELECT_SEARCH_AGENTS = agent_fleet._select_search_agents
_ORIGINAL_RUN_AGENT_FLEET = agent_fleet.run_agent_fleet_cycle
_ORIGINAL_RUN_ELASTIC = elastic_agent_fleet.run_elastic_agent_fleet_cycle


def _merge_search_results_with_skill_learning(state: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, int]:
    merged = dict(_ORIGINAL_MERGE_SEARCH_RESULTS(state, result) or {})
    core = _core(state); registry = core.setdefault("skill_registry", {})
    agent_id = _clean(result.get("agent_id")) or "unknown"; role = _clean(result.get("role")) or "unknown"
    row = registry.setdefault(agent_id, {"agent_id": agent_id, "role": role, "search_attempts": 0, "useful_searches": 0, "contributions": 0, "categories": {}})
    row["role"] = role; row["search_attempts"] = _int(row.get("search_attempts")) + 1
    contributions = _int(merged.get("leads")) + _int(merged.get("signals"))
    if contributions > 0:
        row["useful_searches"] = _int(row.get("useful_searches")) + 1; row["contributions"] = _int(row.get("contributions")) + contributions
        row["last_useful_at"] = _now(); row["last_successful_query"] = _clean(result.get("query"))[:500]
    row["yield_rate"] = round(_int(row.get("useful_searches")) / max(1, _int(row.get("search_attempts"))), 3)
    category = _clean(result.get("category")) or "uncategorized"; categories = row.setdefault("categories", {})
    cat = categories.setdefault(category[:120], {"attempts": 0, "successes": 0, "contributions": 0}); cat["attempts"] = _int(cat.get("attempts")) + 1
    if contributions > 0:
        cat["successes"] = _int(cat.get("successes")) + 1; cat["contributions"] = _int(cat.get("contributions")) + contributions
    if len(registry) > MAX_SKILL_AGENTS:
        ranked = sorted(registry.items(), key=lambda kv: (_int(_safe_dict(kv[1]).get("contributions")), _float(_safe_dict(kv[1]).get("yield_rate"))), reverse=True)[:MAX_SKILL_AGENTS]
        core["skill_registry"] = dict(ranked)
    return merged


def _select_search_agents_with_missions(roster: List[Dict[str, Any]], ctx: Dict[str, Any], slots: int) -> List[Dict[str, Any]]:
    state = _ACTIVE_STATE; ranked_roster = list(roster)
    if state:
        registry = _safe_dict(_core(state).get("skill_registry"))
        ranked_roster.sort(key=lambda a: (-_float(_safe_dict(registry.get(str(a.get("id")))).get("yield_rate")), -_int(_safe_dict(registry.get(str(a.get("id")))).get("contributions")), str(a.get("id"))))
    selected = list(_ORIGINAL_SELECT_SEARCH_AGENTS(ranked_roster, ctx, slots) or [])
    if not state or not selected:
        return selected
    core = _core(state); cycle = _int(state.get("ticks"))
    pending = sorted([x for x in core.get("research_missions", []) or [] if x.get("status") == "pending" and _int(x.get("attempts")) < MISSION_MAX_ATTEMPTS], key=lambda x: (-_int(x.get("priority")), _int(x.get("attempts")), str(x.get("created_at") or "")))
    used: set[str] = set()
    for agent in selected:
        role = _clean(agent.get("role")); mission = next((m for m in pending if m.get("id") not in used and _clean(m.get("role")) == role), None)
        if not mission: continue
        agent["query"] = _clean(mission.get("query")); agent["category"] = _clean(mission.get("category")) or agent.get("category"); used.add(str(mission.get("id")))
        mission["status"] = "dispatched"; mission["attempts"] = _int(mission.get("attempts")) + 1; mission["last_dispatched_at"] = _now(); mission["last_dispatched_cycle"] = cycle; mission["agent_id"] = agent.get("id")
    return selected


def _run_agent_fleet_with_autonomy(state: Dict[str, Any]) -> Dict[str, Any]:
    global _ACTIVE_STATE
    autonomy_core_prepare(state); _ACTIVE_STATE = state
    try:
        report = dict(_ORIGINAL_RUN_AGENT_FLEET(state) or {})
    finally:
        _ACTIVE_STATE = None
    core = _core(state)
    report["autonomy_core"] = {
        "open_peer_help": sum(1 for x in core.get("peer_help", []) or [] if x.get("status") not in {"resolved", "expired"}),
        "open_research_missions": sum(1 for x in core.get("research_missions", []) or [] if x.get("status") in {"pending", "dispatched"}),
        "promoted_lessons": sum(1 for x in core.get("lessons", []) or [] if x.get("status") == "promoted"),
    }
    return report


def _run_elastic_with_autonomy(state: Dict[str, Any]) -> Dict[str, Any]:
    core = autonomy_core_prepare(state); boosts = dict(core.get("role_attention", {}) or {}); original_weights = dict(elastic_agent_fleet.BASE_WEIGHTS)
    try:
        for role, boost in boosts.items():
            if role in elastic_agent_fleet.BASE_WEIGHTS:
                elastic_agent_fleet.BASE_WEIGHTS[role] = max(0.01, original_weights.get(role, 0.0) + min(ROLE_BOOST_CAP, _float(boost)))
        report = dict(_ORIGINAL_RUN_ELASTIC(state) or {})
    finally:
        elastic_agent_fleet.BASE_WEIGHTS.clear(); elastic_agent_fleet.BASE_WEIGHTS.update(original_weights)
    report["autonomy_role_attention"] = boosts
    return report


agent_fleet._merge_search_results = _merge_search_results_with_skill_learning
agent_fleet._select_search_agents = _select_search_agents_with_missions
agent_fleet.run_agent_fleet_cycle = _run_agent_fleet_with_autonomy
elastic_agent_fleet.run_elastic_agent_fleet_cycle = _run_elastic_with_autonomy

print({
    "autonomy_core_runtime": {
        "version": VERSION, "status": "active", "shared_blackboard": True, "peer_help_router": True,
        "experience_ledger": True, "lesson_compiler": True, "research_gap_resolver": True,
        "skill_learning": True, "safe_policy_promotion": True, "production_code_self_modify": False,
        "binding_authority_changed": False,
    }
}, flush=True)
