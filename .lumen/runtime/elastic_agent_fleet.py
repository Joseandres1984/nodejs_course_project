from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Tuple

import agent_fleet


ELASTIC_ENABLED = str(os.getenv("LUMEN_AGENT_ELASTIC_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
MIN_FLEET = max(9, min(100, int(os.getenv("LUMEN_AGENT_MIN_FLEET", "10"))))
MAX_FLEET = max(MIN_FLEET, min(200, int(os.getenv("LUMEN_AGENT_MAX_FLEET", "100"))))
MAX_PARALLEL = max(1, min(MAX_FLEET, int(os.getenv("LUMEN_AGENT_MAX_PARALLEL", "50"))))
MAX_SEARCHES_PER_CYCLE = max(0, min(20, int(os.getenv("LUMEN_AGENT_ELASTIC_MAX_SEARCHES", "8"))))

ROLE_META = {
    "buyer_hunter": ("Buyer Hunter", "BH"),
    "supplier_hunter": ("Supplier Hunter", "SH"),
    "market_scout": ("Market Scout", "MS"),
    "research_analyst": ("Research Analyst", "RA"),
    "revops": ("RevOps / Closer", "RV"),
    "negotiator": ("Negotiator", "NG"),
    "market_manager": ("Market Manager", "MM"),
    "risk_quality": ("Risk & Quality", "RQ"),
    "finance": ("CFO / Profit", "CF"),
}
BASE_WEIGHTS = {
    "buyer_hunter": 0.25,
    "supplier_hunter": 0.16,
    "market_scout": 0.14,
    "research_analyst": 0.12,
    "revops": 0.12,
    "negotiator": 0.07,
    "market_manager": 0.06,
    "risk_quality": 0.04,
    "finance": 0.04,
}


def _bands() -> List[int]:
    raw = str(os.getenv("LUMEN_AGENT_SCALE_BANDS", "10,25,50,75,100"))
    values: List[int] = []
    for token in raw.split(","):
        try:
            value = int(token.strip())
        except (TypeError, ValueError):
            continue
        value = max(MIN_FLEET, min(MAX_FLEET, value))
        if value not in values:
            values.append(value)
    values.extend([MIN_FLEET, MAX_FLEET])
    return sorted(set(values))


def _workload(state: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    action_queue = list(state.get("operating_action_queue", []) or [])
    active_deals = [x for x in state.get("deals", []) or [] if str(x.get("stage") or "").lower() not in {"closed", "lost", "cancelled", "canceled"}]
    pending = int(ctx.get("pending_leads") or 0)
    opportunities = int(ctx.get("opportunities") or 0)
    inquiries = int(ctx.get("inquiries") or 0)
    quotes = int(ctx.get("quotes") or 0)
    offers = int(ctx.get("offers") or 0)
    proposals = int(ctx.get("proposals") or 0)
    listings = int(ctx.get("listings") or 0)
    close_ready = int(ctx.get("close_ready") or 0)
    failures = len(ctx.get("engine_failures") or []) + len(ctx.get("circuits_open") or [])
    demand_gap = int(ctx.get("buyers_verified") or 0) == 0 or int(ctx.get("buyer_demand_verified") or 0) == 0

    parts = {
        "research_backlog": min(30.0, pending * 0.8),
        "opportunity_load": min(18.0, opportunities * 4.0),
        "inbound_load": min(20.0, inquiries * 5.0),
        "quote_offer_load": min(12.0, quotes * 2.0 + offers * 2.0 + proposals * 3.0),
        "deal_load": min(12.0, len(active_deals) * 2.0 + close_ready * 6.0),
        "market_load": min(6.0, listings * 1.5),
        "operating_queue": min(8.0, len(action_queue) * 0.75),
        "reliability_load": min(10.0, failures * 4.0),
        "demand_gap": 8.0 if demand_gap else 0.0,
    }
    score = round(min(100.0, sum(parts.values())), 1)
    return {
        "score": score,
        "parts": {k: round(v, 1) for k, v in parts.items()},
        "pending_leads": pending,
        "opportunities": opportunities,
        "inquiries": inquiries,
        "quotes": quotes,
        "offers": offers,
        "proposals": proposals,
        "listings": listings,
        "active_deals": len(active_deals),
        "close_ready": close_ready,
        "failures": failures,
        "operating_actions": len(action_queue),
        "demand_gap": demand_gap,
    }


def _raw_target(score: float, bands: List[int]) -> int:
    # Workload score maps to increasingly larger teams while keeping a meaningful quiet-mode floor.
    thresholds = [20.0, 40.0, 65.0, 85.0]
    idx = 0
    for threshold in thresholds:
        if score >= threshold:
            idx += 1
    idx = min(idx, len(bands) - 1)
    return bands[idx]


def _nearest_band(value: int, bands: List[int]) -> int:
    return min(bands, key=lambda x: abs(x - value))


def _scale_decision(state: Dict[str, Any], workload: Dict[str, Any]) -> Dict[str, Any]:
    bands = _bands()
    workforce = state.get("agent_workforce", {}) or {}
    previous = int(workforce.get("roster_count") or 50)
    previous = _nearest_band(max(MIN_FLEET, min(MAX_FLEET, previous)), bands)
    raw = _raw_target(float(workload["score"]), bands)

    urgent = bool(
        int(workload.get("inquiries") or 0) >= 5
        or int(workload.get("close_ready") or 0) >= 2
        or int(workload.get("failures") or 0) >= 3
    )
    if not ELASTIC_ENABLED:
        selected = _nearest_band(int(os.getenv("LUMEN_AGENT_FLEET_SIZE", "50")), bands)
        direction = "fixed"
    elif urgent:
        selected = raw
        direction = "surge" if selected > previous else "urgent_rebalance"
    else:
        prev_idx = bands.index(previous)
        raw_idx = bands.index(raw)
        if raw_idx > prev_idx:
            selected = bands[min(prev_idx + 1, len(bands) - 1)]
            direction = "scale_up"
        elif raw_idx < prev_idx:
            selected = bands[max(prev_idx - 1, 0)]
            direction = "scale_down"
        else:
            selected = previous
            direction = "hold"

    top_parts = sorted(workload.get("parts", {}).items(), key=lambda x: x[1], reverse=True)[:3]
    reason = ", ".join(f"{name}={value:g}" for name, value in top_parts if value > 0) or "carga operativa baja"
    return {
        "enabled": ELASTIC_ENABLED,
        "bands": bands,
        "min_fleet": MIN_FLEET,
        "max_fleet": MAX_FLEET,
        "previous_fleet_size": previous,
        "raw_target": raw,
        "selected_fleet_size": selected,
        "direction": direction,
        "urgent": urgent,
        "workload_score": workload["score"],
        "reason": reason,
    }


def _weights(ctx: Dict[str, Any], workload: Dict[str, Any]) -> Dict[str, float]:
    weights = dict(BASE_WEIGHTS)
    bottleneck = str(ctx.get("bottleneck") or "").lower()

    if any(token in bottleneck for token in ("demand", "buyer", "conversion", "value")) or workload.get("demand_gap"):
        weights["buyer_hunter"] += 0.12
        weights["market_scout"] += 0.05
        weights["revops"] += 0.04
    if any(token in bottleneck for token in ("supplier", "procurement", "abastecimiento")):
        weights["supplier_hunter"] += 0.14
        weights["negotiator"] += 0.04
    if int(workload.get("pending_leads") or 0) >= 15:
        weights["research_analyst"] += 0.10
    if int(workload.get("inquiries") or 0) > 0:
        weights["market_manager"] += 0.10
        weights["revops"] += 0.10
    if int(workload.get("quotes") or 0) + int(workload.get("offers") or 0) + int(workload.get("proposals") or 0) > 0:
        weights["negotiator"] += 0.08
        weights["revops"] += 0.05
    if int(workload.get("failures") or 0) > 0:
        weights["risk_quality"] += 0.12
    if int(ctx.get("suppliers_verified") or 0) < 2:
        weights["supplier_hunter"] += 0.08

    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def _role_counts(size: int, ctx: Dict[str, Any], workload: Dict[str, Any]) -> Dict[str, int]:
    roles = list(ROLE_META)
    counts = {role: 1 for role in roles}
    remaining = max(0, size - len(roles))
    if remaining == 0:
        return counts
    weights = _weights(ctx, workload)
    exact = {role: weights[role] * remaining for role in roles}
    for role in roles:
        add = int(math.floor(exact[role]))
        counts[role] += add
        remaining -= add
    if remaining > 0:
        order = sorted(roles, key=lambda role: exact[role] - math.floor(exact[role]), reverse=True)
        for role in order[:remaining]:
            counts[role] += 1
    return counts


def _roster(size: int, ctx: Dict[str, Any], workload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    counts = _role_counts(size, ctx, workload)
    roster: List[Dict[str, Any]] = []
    for role, count in counts.items():
        title, prefix = ROLE_META[role]
        for idx in range(1, count + 1):
            roster.append({"id": f"{prefix}-{idx:02d}", "role": role, "title": title})
    return roster, counts


def _searches_for_size(size: int) -> int:
    if MAX_SEARCHES_PER_CYCLE <= 0:
        return 0
    # Daily global search budget remains the hard cost cap; this only controls how fast unused quota can be used.
    return min(MAX_SEARCHES_PER_CYCLE, max(1, int(math.ceil(size / 12.5))))


def run_elastic_agent_fleet_cycle(state: Dict[str, Any]) -> Dict[str, Any]:
    """Run an elastic digital workforce whose size and role mix are chosen by Meta-LUMEN each cycle.

    Scaling changes only reversible compute/attention allocation. Search spend remains bounded by the
    existing shared daily budget, and all binding/financial/legal authority remains human-gated.
    """
    ctx = agent_fleet._context(state)
    workload = _workload(state, ctx)
    scale = _scale_decision(state, workload)
    size = int(scale["selected_fleet_size"])
    roster, role_plan = _roster(size, ctx, workload)
    search_cap = _searches_for_size(size)

    original_build = agent_fleet.build_roster
    original_parallel = agent_fleet.MAX_PARALLEL
    original_searches = agent_fleet.SEARCHES_PER_CYCLE
    try:
        agent_fleet.build_roster = lambda size_arg=agent_fleet.FLEET_SIZE: list(roster)
        agent_fleet.MAX_PARALLEL = min(MAX_PARALLEL, size)
        agent_fleet.SEARCHES_PER_CYCLE = search_cap
        report = dict(agent_fleet.run_agent_fleet_cycle(state) or {})
    finally:
        agent_fleet.build_roster = original_build
        agent_fleet.MAX_PARALLEL = original_parallel
        agent_fleet.SEARCHES_PER_CYCLE = original_searches

    report.update({
        "version": "2.0-elastic",
        "elastic": True,
        "workload_score": workload["score"],
        "workload": workload,
        "scale_direction": scale["direction"],
        "scale_reason": scale["reason"],
        "previous_fleet_size": scale["previous_fleet_size"],
        "raw_target_fleet_size": scale["raw_target"],
        "selected_fleet_size": size,
        "fleet_min": MIN_FLEET,
        "fleet_max": MAX_FLEET,
        "scale_bands": scale["bands"],
        "role_plan": role_plan,
        "searches_requested_cap": search_cap,
        "max_parallel": min(MAX_PARALLEL, size),
    })

    workforce = state.setdefault("agent_workforce", {})
    workforce["version"] = "2.0-elastic"
    workforce["elastic"] = True
    workforce["elastic_policy"] = {
        "enabled": ELASTIC_ENABLED,
        "min_fleet": MIN_FLEET,
        "max_fleet": MAX_FLEET,
        "bands": scale["bands"],
        "max_parallel": MAX_PARALLEL,
        "max_searches_per_cycle": MAX_SEARCHES_PER_CYCLE,
        "shared_daily_search_budget": int(agent_fleet.scout_connector.DAILY_QUERY_BUDGET),
    }
    workforce["scale_decision"] = scale
    workforce["role_plan"] = role_plan
    workforce["roster"] = roster
    workforce["roster_count"] = size
    workforce["last_cycle"] = report

    history = list(workforce.get("recent_cycles", []) or [])
    if history:
        history[-1].update({
            "workload_score": workload["score"],
            "scale_direction": scale["direction"],
            "raw_target_fleet_size": scale["raw_target"],
            "selected_fleet_size": size,
        })
        workforce["recent_cycles"] = history[-24:]

    state.setdefault("activity", []).insert(0, {
        "ts": agent_fleet.utcnow(),
        "msg": (
            f"Meta-LUMEN ajustó la plantilla {scale['previous_fleet_size']}→{size} agentes "
            f"({scale['direction']}, carga {workload['score']}/100); roles redistribuidos según cuello de botella."
        ),
    })
    state["activity"] = state["activity"][:100]
    return report
