from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlparse

import continuous_learning_runtime

VERSION = "1.0-commercial-learning-v2"
_ORIGINAL_TICK = continuous_learning_runtime.continuous_learning_tick
MAX_SOURCE_PROFILES = 120
MAX_EXPERIMENTS = 40
MAX_TTR_CASES = 120

STAGE_RANK = {
    "DEMANDA": 0, "COMPRADOR": 1, "REQUISITOS": 2, "PROVEEDORES": 3,
    "COTIZACION": 4, "OFERTA": 5, "NEGOCIACION": 6, "CIERRE": 7, "COBRO": 8,
}


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


def _domain(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text and "/" not in text:
        return text.lower().removeprefix("www.")
    try:
        return (urlparse(text).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _source_reputation(state: Dict[str, Any]) -> Dict[str, Any]:
    buckets: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "observations": 0, "high_intent": 0, "tier_a": 0, "verified_accounts": 0,
        "opportunity_refs": 0, "responses": 0, "outbound": 0,
    })
    lead_domain: Dict[str, str] = {}

    for lead in state.get("research_leads", []) or []:
        domain = _domain(lead.get("source_url") or lead.get("url") or lead.get("evidence_url"))
        if not domain:
            continue
        row = buckets[domain]
        row["observations"] += 1
        if lead.get("tier") == "A":
            row["tier_a"] += 1
        if lead.get("demand_signal") or lead.get("direct_inbound_demand"):
            row["high_intent"] += 1
        if lead.get("id"):
            lead_domain[str(lead.get("id"))] = domain

    for obs in state.get("market_intelligence_observations", []) or []:
        domain = _domain(obs.get("source_domain") or obs.get("source_url"))
        if domain:
            buckets[domain]["observations"] += 1

    for sig in state.get("public_procurement_signals", []) or []:
        domain = _domain(sig.get("source") or sig.get("url") or sig.get("source_url"))
        if domain:
            buckets[domain]["observations"] += 1
            if _f(sig.get("score")) >= 80:
                buckets[domain]["high_intent"] += 1

    accounts = {str(x.get("id")): x for x in state.get("candidate_accounts", []) or [] if x.get("id")}
    for account in accounts.values():
        domain = lead_domain.get(str(account.get("source_lead_id") or "")) or _domain(account.get("official_url") or account.get("domain"))
        if domain and account.get("verified_company"):
            buckets[domain]["verified_accounts"] += 1

    for opp in state.get("market_opportunities", []) or []:
        for ref in opp.get("evidence_refs", []) or []:
            domain = _domain(ref)
            if domain:
                buckets[domain]["opportunity_refs"] += 1

    relations = {str(x.get("account_id")): x for x in state.get("commercial_relationships", []) or [] if x.get("account_id")}
    for aid, relation in relations.items():
        account = accounts.get(aid, {})
        domain = _domain(account.get("official_url") or account.get("domain"))
        if not domain:
            continue
        buckets[domain]["responses"] += _i(relation.get("response_count"))
        buckets[domain]["outbound"] += _i(relation.get("outbound_count"))

    profiles: List[Dict[str, Any]] = []
    for domain, raw in buckets.items():
        obs = max(1, raw["observations"])
        evidence_yield = min(1.0, (raw["tier_a"] + raw["high_intent"] * 1.5) / obs)
        verification_yield = min(1.0, raw["verified_accounts"] / obs)
        opportunity_yield = min(1.0, raw["opportunity_refs"] / obs)
        response_rate = (raw["responses"] + 1.0) / (raw["outbound"] + 3.0) if raw["outbound"] or raw["responses"] else 0.33
        raw_score = (evidence_yield * 35 + verification_yield * 25 + opportunity_yield * 25 + response_rate * 15)
        confidence = min(1.0, (raw["observations"] + raw["verified_accounts"] * 2 + raw["opportunity_refs"] * 3) / 24.0)
        score = 55.0 * (1.0 - confidence) + raw_score * confidence
        status = "champion" if score >= 72 and confidence >= 0.4 else "weak" if score <= 34 and confidence >= 0.5 else "learning"
        profiles.append({
            "domain": domain, "score": round(score, 1), "confidence": round(confidence, 2),
            "status": status, **raw,
            "evidence_yield": round(evidence_yield, 3),
            "verification_yield": round(verification_yield, 3),
            "opportunity_yield": round(opportunity_yield, 3),
            "response_rate_shrunk": round(response_rate, 3),
        })
    profiles.sort(key=lambda x: (x["score"], x["confidence"], x["observations"]), reverse=True)
    report = {
        "version": VERSION,
        "profiles": profiles[:MAX_SOURCE_PROFILES],
        "champions": [x for x in profiles if x["status"] == "champion"][:10],
        "weak_sources": [x for x in profiles if x["status"] == "weak"][:10],
        "rule": "source_weight_changes_only_after_observed_yield_with_confidence_shrinkage",
    }
    state["source_reputation"] = report
    return report


def _time_to_revenue(state: Dict[str, Any]) -> Dict[str, Any]:
    cycle = _i(state.get("ticks"))
    memory = state.setdefault("time_to_revenue_memory", {})
    rows = memory.setdefault("cases", {})
    current_ids: set[str] = set()
    scored: List[Dict[str, Any]] = []
    for case in state.get("autonomy_cases", []) or []:
        cid = str(case.get("id") or "")
        if not cid:
            continue
        current_ids.add(cid)
        stage = str(case.get("stage") or "DEMANDA")
        rank = STAGE_RANK.get(stage, 0)
        row = rows.setdefault(cid, {
            "first_seen_cycle": cycle, "last_advanced_cycle": cycle, "last_stage": stage,
            "highest_stage_rank": rank, "first_seen_at": utcnow(),
        })
        if rank > _i(row.get("highest_stage_rank")):
            row["highest_stage_rank"] = rank
            row["last_advanced_cycle"] = cycle
            row["last_stage"] = stage
            row["last_advanced_at"] = utcnow()
        elif stage != row.get("last_stage"):
            row["last_stage"] = stage
        age = max(0, cycle - _i(row.get("first_seen_cycle"), cycle))
        stagnant = max(0, cycle - _i(row.get("last_advanced_cycle"), cycle))
        score = min(100.0, _f(case.get("priority"), 50.0) + min(24, stagnant * 2.5) + rank * 1.5)
        scored.append({
            "case_id": cid, "title": case.get("title"), "stage": stage, "stage_rank": rank,
            "age_cycles": age, "stagnant_cycles": stagnant, "priority": case.get("priority"),
            "time_pressure_score": round(score, 1), "next_action": case.get("next_action"),
            "human_required": bool(case.get("human_required")),
        })
    if len(rows) > MAX_TTR_CASES:
        keep = set(current_ids)
        for key in list(rows):
            if key not in keep:
                rows.pop(key, None)
            if len(rows) <= MAX_TTR_CASES:
                break
    scored.sort(key=lambda x: (x["time_pressure_score"], x["stagnant_cycles"], x["stage_rank"]), reverse=True)
    stale = [x for x in scored if x["stagnant_cycles"] >= 4 and not x["human_required"] and x["stage"] != "COBRO"]
    report = {
        "cycle": cycle, "cases_tracked": len(scored), "stale_cases": len(stale),
        "top_time_pressure": scored[:8], "top_stale": stale[:8],
        "rule": "older_high_value_cases_gain_attention_but_never_bypass_evidence_or_human_gates",
    }
    state["time_to_revenue"] = report
    return report


def _anti_drift(state: Dict[str, Any]) -> Dict[str, Any]:
    history = list(state.get("revenue_funnel_history", []) or [])[-8:]
    movement_keys = ("market_opportunities", "rfq_ready", "quotes", "real_offers", "proposals", "close_ready", "realized_events")
    meaningful = 0
    for row in history[-6:]:
        deltas = row.get("deltas", {}) or {}
        meaningful += sum(max(0, _i(deltas.get(k))) for k in movement_keys)
    current_lane = str((state.get("revenue_allocator", {}) or {}).get("lane") or (state.get("continuous_revenue_drive", {}) or {}).get("primary_lane") or "")
    funnel = state.get("revenue_funnel", {}) or {}
    bottleneck = str((funnel.get("bottleneck", {}) or {}).get("lane") or "")
    triggered = len(history) >= 5 and meaningful == 0
    recommendation = None
    if triggered:
        recommendation = {
            "quote": "quote_creation",
            "opportunity": "opportunity_building",
            "verification": "verification_contact",
            "contact": "verification_contact",
            "demand": "demand_discovery",
            "close": "closing",
        }.get(bottleneck, "verification_contact" if current_lane == "closing" else "opportunity_building")
        if recommendation == current_lane:
            recommendation = "quote_creation" if current_lane == "closing" else "verification_contact"
    report = {
        "status": "triggered" if triggered else "stable",
        "window_cycles": min(6, len(history)),
        "verified_stage_movements": meaningful,
        "current_lane": current_lane,
        "funnel_bottleneck": bottleneck,
        "recommended_lane": recommendation,
        "reason": "No hubo transiciones comerciales verificadas en la ventana; desafiar la estrategia actual de forma reversible." if triggered else "Existe movimiento verificable o todavía falta muestra.",
    }
    return report


def _experiments(state: Dict[str, Any], anti: Dict[str, Any]) -> Dict[str, Any]:
    cycle = _i(state.get("ticks"))
    experiments = list(state.get("revenue_experiments", []) or [])[-MAX_EXPERIMENTS:]
    active = next((x for x in reversed(experiments) if x.get("status") == "TESTING"), None)
    funnel_counts = (state.get("revenue_funnel", {}) or {}).get("counts", {}) or {}
    allocator = state.get("revenue_allocator", {}) or {}
    lane = str(allocator.get("lane") or "balanced")
    metric = str(allocator.get("success_metric") or "close_ready > 0").split()[0]
    current_value = _f(funnel_counts.get(metric))

    if active is None:
        active = {
            "id": f"EXP-{cycle}-{lane}", "kind": "reversible_attention_allocation",
            "hypothesis": f"Asignar más atención al carril {lane} mejorará {metric}.",
            "lane": lane, "target_metric": metric, "baseline": current_value, "current": current_value,
            "start_cycle": cycle, "samples": 1, "status": "TESTING", "decision": "keep_testing",
            "created_at": utcnow(), "updated_at": utcnow(),
            "authority_change": False, "spend_increase": False, "code_change": False,
        }
        experiments.append(active)
    else:
        active["samples"] = _i(active.get("samples"), 1) + 1
        active["current"] = _f(funnel_counts.get(str(active.get("target_metric") or "")))
        active["updated_at"] = utcnow()
        improvement = _f(active.get("current")) - _f(active.get("baseline"))
        if improvement > 0 and active["samples"] >= 3:
            active["status"] = "PROMOTED"
            active["decision"] = "promote"
        elif active["samples"] >= 6 and improvement <= 0:
            active["status"] = "DEMOTED"
            active["decision"] = "demote_and_rotate"
        else:
            active["decision"] = "keep_testing"

    return {
        "active": active if active.get("status") == "TESTING" else None,
        "latest": experiments[-1] if experiments else None,
        "promoted": sum(1 for x in experiments if x.get("status") == "PROMOTED"),
        "demoted": sum(1 for x in experiments if x.get("status") == "DEMOTED"),
        "total": len(experiments),
        "anti_drift_triggered": anti.get("status") == "triggered",
        "policy": "small_reversible_tests_with_metric_baseline_sample_and_promote_or_demote_decision",
        "_rows": experiments[-MAX_EXPERIMENTS:],
    }


def _business_memory(state: Dict[str, Any], source_rep: Dict[str, Any]) -> Dict[str, Any]:
    learning = state.get("profit_learning", {}) or {}
    supplier_profiles = list(state.get("supplier_network_profiles", []) or [])
    if not supplier_profiles:
        supplier_profiles = list((state.get("supplier_network", {}) or {}).get("profiles", []) or [])
    relations = list(state.get("commercial_relationships", []) or [])
    responsive = sorted(
        [x for x in relations if _i(x.get("outbound_count")) > 0],
        key=lambda x: ((_i(x.get("response_count")) + 1) / (_i(x.get("outbound_count")) + 3)),
        reverse=True,
    )[:8]
    return {
        "best_categories": [
            {"category": x.get("category"), "learned_score": x.get("learned_score"), "confidence": x.get("confidence")}
            for x in (learning.get("category_rankings", []) or [])[:8]
        ],
        "best_queries": list(learning.get("best_queries", []) or [])[:8],
        "source_champions": list(source_rep.get("champions", []) or [])[:8],
        "weak_sources": list(source_rep.get("weak_sources", []) or [])[:8],
        "responsive_relationships": [
            {"account_id": x.get("account_id"), "counterparty": x.get("counterparty"), "outbound": x.get("outbound_count"), "responses": x.get("response_count"), "state": x.get("relationship_state")}
            for x in responsive
        ],
        "top_suppliers": [
            {"account_id": x.get("account_id"), "supplier": x.get("supplier"), "score": x.get("network_score"), "confidence": x.get("confidence"), "tier": x.get("tier")}
            for x in supplier_profiles[:8]
        ],
        "principle": "remember_observed_conversion_response_quote_margin_and_dead_end_patterns_not_unverified_assumptions",
    }


def _two_brains(state: Dict[str, Any], anti: Dict[str, Any], ttr: Dict[str, Any]) -> Dict[str, Any]:
    learning = state.get("profit_learning", {}) or {}
    explore = _i(learning.get("explore_pct"), 25)
    if anti.get("status") == "triggered":
        explore = max(explore, 30)
    explore = max(15, min(35, explore))
    execute = 100 - explore
    return {
        "execution_brain": {
            "attention_pct": execute,
            "objective": "advance existing verified cases toward quote close and cash",
            "protected_cases": list(ttr.get("top_time_pressure", []) or [])[:6],
        },
        "exploration_brain": {
            "attention_pct": explore,
            "objective": "test new sources queries categories and market hypotheses without stealing majority attention from near-revenue work",
        },
    }


def _review_board(state: Dict[str, Any], anti: Dict[str, Any]) -> Dict[str, Any]:
    proposal = anti.get("recommended_lane")
    if not proposal:
        return {"status": "no_major_change_proposed", "human_required": False}
    reviews = {
        "commercial": {"pass": True, "reason": "Cambio responde a falta de transiciones verificadas."},
        "finance": {"pass": True, "reason": "No aumenta presupuesto ni autoriza gasto."},
        "quality_risk": {"pass": True, "reason": "Es reasignación reversible de atención y no baja gates de evidencia."},
    }
    approved = all(x["pass"] for x in reviews.values())
    return {
        "status": "AUTO_APPROVED_REVERSIBLE" if approved else "HUMAN_REVIEW_REQUIRED",
        "proposal": {"rotate_revenue_lane_to": proposal},
        "reviews": reviews,
        "human_required": not approved,
        "authority_change": False,
        "production_code_change": False,
    }


def _inject_time_actions(state: Dict[str, Any], ttr: Dict[str, Any]) -> int:
    queue = [x for x in state.get("operating_action_queue", []) or [] if not str(x.get("key") or "").startswith("time_to_revenue|")]
    created = 0
    for row in list(ttr.get("top_stale", []) or [])[:4]:
        queue.append({
            "key": f"time_to_revenue|{row.get('case_id')}",
            "kind": "time_to_revenue_recovery",
            "title": f"Destrabar caso estancado: {row.get('title')}",
            "reason": f"{row.get('stagnant_cycles')} ciclos sin avanzar desde {row.get('stage')}. {row.get('next_action') or ''}",
            "impact": row.get("time_pressure_score"), "urgency": row.get("time_pressure_score"),
            "confidence": 0.86, "effort": 1.0, "risk": "low", "autonomous": True,
            "object_type": "autonomy_case", "object_id": row.get("case_id"),
            "priority_score": row.get("time_pressure_score"), "created_at": utcnow(),
        })
        created += 1
    queue.sort(key=lambda x: _f(x.get("priority_score")), reverse=True)
    state["operating_action_queue"] = queue[:120]
    return created


def _tick_v2(state: Dict[str, Any]) -> Dict[str, Any]:
    base = dict(_ORIGINAL_TICK(state) or {})
    source_rep = _source_reputation(state)
    ttr = _time_to_revenue(state)
    anti = _anti_drift(state)
    experiments = _experiments(state, anti)
    state["revenue_experiments"] = experiments.pop("_rows")
    memory = _business_memory(state, source_rep)
    brains = _two_brains(state, anti, ttr)
    board = _review_board(state, anti)
    actions = _inject_time_actions(state, ttr)

    report = {
        "version": VERSION,
        "status": "active",
        "updated_at": utcnow(),
        "source_reputation": {"profiles": len(source_rep.get("profiles", [])), "champions": len(source_rep.get("champions", [])), "weak_sources": len(source_rep.get("weak_sources", []))},
        "experiments": experiments,
        "anti_drift": anti,
        "time_to_revenue": {**ttr, "actions_injected": actions},
        "business_memory": memory,
        "two_brain": brains,
        "review_board": board,
        "governance": {
            "may_change_attention_reversibly": True,
            "may_increase_search_total_cap": False,
            "may_self_modify_production_code": False,
            "may_bind_contract_or_spend": False,
        },
    }
    state["commercial_learning_v2"] = report
    base["commercial_learning_v2"] = report
    state["continuous_learning"] = base
    return base


continuous_learning_runtime.continuous_learning_tick = _tick_v2
print({"commercial_learning_v2_runtime": {"version": VERSION, "status": "active"}}, flush=True)
