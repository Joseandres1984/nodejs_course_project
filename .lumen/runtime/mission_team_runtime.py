from __future__ import annotations

"""LUMEN Mission Teams.

Creates small temporary, evidence-led teams around the strongest canonical commercial
objectives. Teams share context, hand work across specialist roles, prioritize related
professional cases, ask peers for help, create bounded research missions, and compile
successful handoff patterns into reusable lessons.

This runtime coordinates reversible attention and non-binding preparation only. It does
not authorize contracts, payments, orders, legal commitments, new connectors, paid media,
or production code/deployments.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import re

import autonomy_core_runtime
import continuous_learning_runtime
import professional_casework

VERSION = "1.0-mission-teams"
MAX_ACTIVE_TEAMS = 3
MAX_TEAM_MEMBERS = 6
MAX_FOCUS_CASES = 12
STAGNATION_ESCALATION_CYCLES = 4
MAX_TEAM_EVENTS = 120
MAX_TEAM_PLAYBOOK = 40

_STAGE_ORDER = {
    "REQUIREMENT": 0,
    "RFQ_READY": 1,
    "QUOTE_CAPTURED": 2,
    "PROPOSAL_READY": 3,
    "CLOSE_PATH": 4,
    "COMPLETED": 5,
}

_ROLE_BY_STAGE = {
    "REQUIREMENT": ["research_analyst", "revops"],
    "RFQ_READY": ["supplier_hunter", "negotiator", "revops"],
    "QUOTE_CAPTURED": ["negotiator", "revops", "risk_quality", "finance"],
    "PROPOSAL_READY": ["revops", "risk_quality", "finance"],
    "CLOSE_PATH": ["revops", "risk_quality", "finance"],
}

_ORIGINAL_PROFESSIONAL_TICK = professional_casework.professional_casework_tick
_ORIGINAL_BLACKBOARD = autonomy_core_runtime._blackboard_and_briefings
_ORIGINAL_CONTINUOUS_LEARNING = continuous_learning_runtime.continuous_learning_tick


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


def _tokens(value: Any) -> set[str]:
    return {
        x.lower() for x in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]+", str(value or ""))
        if len(x) >= 4
    }


def _linked(row: Dict[str, Any], opportunity_id: str, deal_ids: set[str]) -> bool:
    return bool(
        (opportunity_id and str(row.get("opportunity_id") or "") == opportunity_id)
        or (str(row.get("deal_id") or "") in deal_ids if deal_ids else False)
    )


def _real_offer(row: Dict[str, Any]) -> bool:
    if _norm(row.get("source")) in {"demo", "demo/simulación", "simulation", "simulated"}:
        return False
    if row.get("simulation") or row.get("probe"):
        return False
    return bool(
        row.get("amount") not in (None, "")
        or row.get("document_id")
        or row.get("source_message_id")
        or row.get("quote_id")
        or row.get("normalized_quote_id")
    )


def _accounts(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(x.get("id") or ""): x
        for x in state.get("candidate_accounts", []) or []
        if isinstance(x, dict) and x.get("id")
    }


def _canonical_opportunities(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    truth = _safe_dict(state.get("canonical_revenue_truth"))
    ids = {str(x) for x in truth.get("canonical_opportunity_ids", []) or []}
    rows = [
        x for x in state.get("market_opportunities", []) or []
        if isinstance(x, dict) and str(x.get("id") or "") in ids
    ]
    rows.sort(
        key=lambda x: (
            -_float(x.get("score") or x.get("portfolio_priority_score")),
            str(x.get("id") or ""),
        )
    )
    return rows


def _deal_ids_for_opportunity(state: Dict[str, Any], opportunity_id: str) -> set[str]:
    return {
        str(x.get("id")) for x in state.get("deals", []) or []
        if isinstance(x, dict) and str(x.get("opportunity_id") or "") == opportunity_id and x.get("id")
    }


def _requirement_ready(state: Dict[str, Any], opp: Dict[str, Any]) -> bool:
    if any(
        opp.get(k)
        for k in (
            "requirement_confirmed", "requirements_ready_for_rfq", "ready_for_rfq",
            "requirement_pack_ready", "buyer_requirement_confirmed",
        )
    ):
        return True
    oid = str(opp.get("id") or "")
    ready_statuses = {"ready_for_rfq", "requirement_complete", "requirements_complete", "rfq_ready"}
    for row in state.get("interlocution_cases", []) or []:
        if not isinstance(row, dict):
            continue
        linked = str(row.get("opportunity_id") or row.get("market_opportunity_id") or "") == oid
        if not linked:
            continue
        if any(row.get(k) for k in ("requirement_ready", "requirements_ready", "ready_for_rfq")):
            return True
        if _norm(row.get("status")) in ready_statuses:
            return True
    return False


def _opportunity_stage(state: Dict[str, Any], opp: Dict[str, Any]) -> str:
    oid = str(opp.get("id") or "")
    deal_ids = _deal_ids_for_opportunity(state, oid)
    deals = [
        x for x in state.get("deals", []) or []
        if isinstance(x, dict) and str(x.get("id") or "") in deal_ids
    ]
    if any(_norm(x.get("stage")) in {"closed", "cerrado", "paid", "settled", "collected", "cobrado"} for x in deals):
        return "COMPLETED"
    if any(_norm(x.get("stage")) in {"close_ready", "listo para cerrar", "autorizado para cierre", "negotiation", "negociacion", "negociación"} for x in deals):
        return "CLOSE_PATH"
    proposals = [
        x for x in state.get("proposals", []) or []
        if isinstance(x, dict) and _linked(x, oid, deal_ids) and not x.get("simulation")
    ]
    if proposals:
        return "PROPOSAL_READY"
    offers = [
        x for x in state.get("offers", []) or []
        if isinstance(x, dict) and _linked(x, oid, deal_ids) and _real_offer(x)
    ]
    if offers:
        return "QUOTE_CAPTURED"
    if _requirement_ready(state, opp):
        return "RFQ_READY"
    return "REQUIREMENT"


def _team_objective(stage: str, category: str, buyer_name: str) -> Tuple[str, str]:
    if stage == "REQUIREMENT":
        return (
            f"Complete the evidence-backed buyer requirement pack for {buyer_name} · {category}.",
            "requirements_ready_for_rfq",
        )
    if stage == "RFQ_READY":
        return (
            f"Prepare comparable supplier RFQs and capture a traceable quote for {category}.",
            "canonical_real_offers",
        )
    if stage == "QUOTE_CAPTURED":
        return (
            f"Validate quote comparability, economics and prepare a non-binding buyer proposal for {buyer_name}.",
            "canonical_proposals",
        )
    if stage == "PROPOSAL_READY":
        return (
            f"Advance the evidence-backed proposal toward a safe close path without making binding commitments.",
            "canonical_close_ready",
        )
    if stage == "CLOSE_PATH":
        return (
            f"Prepare the strongest safe-close package and surface only the binding decision that requires a human.",
            "canonical_close_ready",
        )
    return (f"Preserve evidence and capture realized outcome for {buyer_name} · {category}.", "realized_profit_detected")


def _stage_task(stage: str, category: str, buyer_name: str) -> str:
    if stage == "REQUIREMENT":
        return f"Research and structure specification, quantity, delivery, documentation and commercial conditions for {buyer_name} · {category}."
    if stage == "RFQ_READY":
        return f"Validate supplier fit and prepare comparable RFQ inputs for {category}; do not fabricate a quote."
    if stage == "QUOTE_CAPTURED":
        return f"Compare traceable supplier quote evidence, flag gaps and prepare a proposal package for RevOps."
    if stage == "PROPOSAL_READY":
        return "Audit proposal evidence, objections and close-path conditions; escalate binding acceptance to a human."
    if stage == "CLOSE_PATH":
        return "Prepare non-binding close support and identify the exact human decision required, if any."
    return "Record outcome and reusable evidence for the shared playbook."


def _roster(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = list(_safe_dict(state.get("agent_workforce")).get("roster", []) or [])
    return rows or autonomy_core_runtime.agent_fleet.build_roster()


def _member_score(core: Dict[str, Any], agent: Dict[str, Any], category: str, load: int) -> float:
    registry = _safe_dict(core.get("skill_registry"))
    skill = _safe_dict(registry.get(str(agent.get("id") or "")))
    categories = _safe_dict(skill.get("categories"))
    category_skill = _safe_dict(categories.get(category))
    return (
        2.0 * _float(skill.get("yield_rate"))
        + min(2.0, _int(skill.get("contributions")) / 5.0)
        + min(1.5, _int(category_skill.get("successes")) / 2.0)
        - load * 0.75
    )


def _assign_members(state: Dict[str, Any], team: Dict[str, Any], stage: str, load: Dict[str, int]) -> List[Dict[str, Any]]:
    roster = _roster(state)
    core = _safe_dict(state.get("autonomy_core"))
    category = _clean(team.get("category"))
    required = list(dict.fromkeys(_ROLE_BY_STAGE.get(stage, ["revops", "risk_quality"])))
    # Keep Research + Supplier represented in early commercial work so handoffs have continuity.
    if stage in {"REQUIREMENT", "RFQ_READY", "QUOTE_CAPTURED"}:
        for role in ("research_analyst", "supplier_hunter"):
            if role not in required:
                required.append(role)
    required = required[:MAX_TEAM_MEMBERS]
    previous = {str(x.get("role")): x for x in team.get("members", []) or [] if isinstance(x, dict)}
    roster_by_id = {str(x.get("id")): x for x in roster}
    members: List[Dict[str, Any]] = []
    for role in required:
        old = previous.get(role)
        if old and str(old.get("agent_id") or "") in roster_by_id and roster_by_id[str(old.get("agent_id"))].get("role") == role:
            agent = roster_by_id[str(old.get("agent_id"))]
        else:
            candidates = [x for x in roster if x.get("role") == role]
            if not candidates:
                continue
            agent = max(candidates, key=lambda x: (_member_score(core, x, category, load.get(str(x.get("id")), 0)), str(x.get("id"))))
        aid = str(agent.get("id") or "")
        load[aid] = load.get(aid, 0) + 1
        members.append({
            "agent_id": aid,
            "role": role,
            "title": agent.get("title"),
            "team_role": "lead" if role == "revops" else "specialist",
        })
    return members


def _ensure_team_peer_help(state: Dict[str, Any], team: Dict[str, Any]) -> None:
    core = autonomy_core_runtime._core(state)
    rows = core.setdefault("peer_help", [])
    code = f"mission_team:{team.get('id')}:{team.get('stage')}"
    existing = next((x for x in rows if x.get("code") == code and x.get("status") not in {"resolved", "expired"}), None)
    roles = _ROLE_BY_STAGE.get(str(team.get("stage")), ["revops"])
    if existing:
        existing.update({
            "task": team.get("current_task"), "target_roles": roles,
            "priority": team.get("priority"), "team_id": team.get("id"),
        })
    else:
        rows.append({
            "id": f"HELP-{_fingerprint(code)}", "code": code, "created_at": _now(), "status": "open",
            "requester_role": "mission_team", "target_roles": roles,
            "task": team.get("current_task"), "success_metric": team.get("success_metric"),
            "baseline": _float(team.get("baseline_metric")), "priority": team.get("priority", 90),
            "binding": False, "team_id": team.get("id"),
        })
    core["peer_help"] = rows[-autonomy_core_runtime.MAX_HELP_REQUESTS:]


def _ensure_team_research_mission(state: Dict[str, Any], team: Dict[str, Any]) -> None:
    stage = str(team.get("stage") or "")
    if stage not in {"REQUIREMENT", "RFQ_READY"}:
        return
    core = autonomy_core_runtime._core(state)
    rows = core.setdefault("research_missions", [])
    code = f"team_research:{team.get('id')}:{stage}"
    existing = next((x for x in rows if x.get("code") == code and x.get("status") not in {"resolved", "expired", "failed"}), None)
    buyer_name = str(team.get("buyer_name") or "comprador").replace('"', "")
    category = str(team.get("category") or "suministro industrial").replace('"', "")
    if stage == "REQUIREMENT":
        role = "research_analyst"
        query = f'"{buyer_name}" "{category}" (compras OR licitación OR requerimiento OR especificaciones OR abastecimiento)'
    else:
        role = "supplier_hunter"
        query = f'"{category}" (fabricante OR distribuidor OR proveedor oficial OR mayorista) Argentina -mercadolibre -facebook'
    if existing:
        existing.update({"query": query[:500], "category": category[:180], "role": role, "priority": team.get("priority", 90)})
    else:
        rows.append({
            "id": f"MISSION-{_fingerprint(code, query)}", "code": code, "created_at": _now(), "status": "pending",
            "role": role, "query": query[:500], "category": category[:180],
            "success_metric": team.get("success_metric"), "baseline": _float(team.get("baseline_metric")),
            "priority": team.get("priority", 90), "goal_id": team.get("goal_id"), "attempts": 0,
            "source_policy": "public_web_only; respect existing search budget and verification gates",
            "binding": False, "team_id": team.get("id"),
        })
    core["research_missions"] = rows[-autonomy_core_runtime.MAX_RESEARCH_MISSIONS:]


def _team_metric_value(state: Dict[str, Any], metric: str) -> float:
    metrics = autonomy_core_runtime._metric_snapshot(state)
    return _float(metrics.get(metric))


def _record_stage_event(state: Dict[str, Any], team: Dict[str, Any], previous: str, current: str) -> None:
    events = list(state.get("mission_team_events", []) or [])
    events.append({
        "ts": _now(), "cycle": _int(state.get("ticks")), "team_id": team.get("id"),
        "opportunity_id": team.get("opportunity_id"), "from_stage": previous, "to_stage": current,
        "category": team.get("category"), "event": "stage_advanced" if _STAGE_ORDER.get(current, 0) > _STAGE_ORDER.get(previous, 0) else "stage_changed",
    })
    state["mission_team_events"] = events[-MAX_TEAM_EVENTS:]


def _compile_team_playbook(state: Dict[str, Any], team: Dict[str, Any], previous: str, current: str) -> None:
    if _STAGE_ORDER.get(current, 0) <= _STAGE_ORDER.get(previous, 0):
        return
    playbook = list(state.get("mission_team_playbook", []) or [])
    code = f"handoff:{previous}->{current}"
    row = next((x for x in playbook if x.get("code") == code), None)
    if row is None:
        row = {
            "id": f"PLAY-{_fingerprint(code)}", "code": code, "created_at": _now(), "support": 0,
            "teaching": f"A mission team advanced from {previous} to {current} by preserving traceable evidence and handing context to the next specialist role.",
            "policy_scope": "team_coordination_and_attention_only",
        }
        playbook.append(row)
    row["support"] = _int(row.get("support")) + 1
    row["last_seen"] = _now()
    row["last_team_id"] = team.get("id")
    row["confidence"] = round(min(0.95, 0.55 + 0.10 * _int(row.get("support"))), 2)
    row["status"] = "promoted" if _int(row.get("support")) >= 2 else "candidate"
    state["mission_team_playbook"] = playbook[-MAX_TEAM_PLAYBOOK:]

    core = autonomy_core_runtime._core(state)
    lessons = list(core.get("lessons", []) or [])
    lesson_code = f"mission_team:{code}"
    lesson = next((x for x in lessons if x.get("code") == lesson_code), None)
    if lesson is None:
        lesson = {
            "id": f"LESSON-{_fingerprint(lesson_code)}", "code": lesson_code, "created_at": _now(),
            "audience_roles": ["research_analyst", "supplier_hunter", "negotiator", "revops", "risk_quality"],
            "teaching": row["teaching"], "policy_scope": "team_coordination_and_attention_only",
        }
        lessons.append(lesson)
    lesson["support"] = row["support"]
    lesson["confidence"] = row["confidence"]
    lesson["status"] = row["status"]
    lesson["last_seen"] = _now()
    core["lessons"] = lessons[-autonomy_core_runtime.MAX_LESSONS:]


def _prepare_teams(state: Dict[str, Any]) -> Dict[str, Any]:
    core = autonomy_core_runtime._core(state)
    accounts = _accounts(state)
    opportunities = _canonical_opportunities(state)
    existing = {
        str(x.get("opportunity_id") or ""): x
        for x in state.get("mission_teams", []) or []
        if isinstance(x, dict) and x.get("opportunity_id")
    }
    load: Dict[str, int] = {}
    for team in existing.values():
        if team.get("status") in {"active", "blocked_budget", "ready", "close_path"}:
            for member in team.get("members", []) or []:
                aid = str(member.get("agent_id") or "")
                if aid:
                    load[aid] = load.get(aid, 0) + 1

    active_ids = {str(x.get("id") or "") for x in opportunities[:MAX_ACTIVE_TEAMS]}
    cycle = _int(state.get("ticks"))
    teams: List[Dict[str, Any]] = []
    for rank, opp in enumerate(opportunities, start=1):
        oid = str(opp.get("id") or "")
        if not oid:
            continue
        team = existing.get(oid) or {
            "id": f"TEAM-{_fingerprint(oid)}", "opportunity_id": oid, "created_at": _now(),
            "stage": "REQUIREMENT", "stagnant_cycles": 0, "members": [], "handoffs": [],
        }
        buyer = accounts.get(str(opp.get("buyer_account_id") or ""), {})
        supplier = accounts.get(str(opp.get("supplier_account_id") or ""), {})
        category = _clean(opp.get("category") or opp.get("product") or opp.get("title") or buyer.get("category") or supplier.get("category") or "suministro industrial")[:180]
        buyer_name = _clean(buyer.get("company") or buyer.get("name") or buyer.get("name_hint") or buyer.get("title") or buyer.get("domain") or "comprador")[:180]
        stage = _opportunity_stage(state, opp)
        previous = str(team.get("stage") or stage)
        objective, metric = _team_objective(stage, category, buyer_name)
        if previous != stage:
            _record_stage_event(state, team, previous, stage)
            _compile_team_playbook(state, team, previous, stage)
            team["previous_stage"] = previous
            team["stage_changed_at"] = _now()
            team["stagnant_cycles"] = 0
        elif _int(team.get("last_evaluated_cycle"), -1) != cycle:
            team["stagnant_cycles"] = _int(team.get("stagnant_cycles")) + 1
        team.update({
            "version": VERSION, "updated_at": _now(), "last_evaluated_cycle": cycle,
            "rank": rank, "priority": max(70, 101 - rank * 4), "stage": stage,
            "status": "completed" if stage == "COMPLETED" else ("active" if oid in active_ids else "reserve"),
            "category": category, "buyer_name": buyer_name,
            "buyer_account_id": opp.get("buyer_account_id"), "supplier_account_id": opp.get("supplier_account_id"),
            "objective": objective, "current_task": _stage_task(stage, category, buyer_name),
            "success_metric": metric, "baseline_metric": _team_metric_value(state, metric),
            "goal_id": f"GOAL-TEAM-{oid}",
            "authority": "nonbinding_preparation_and_research_only",
        })
        if team["status"] == "active":
            team["members"] = _assign_members(state, team, stage, load)
            team["lead_agent_id"] = next((x.get("agent_id") for x in team["members"] if x.get("role") == "revops"), None)
            _ensure_team_peer_help(state, team)
            _ensure_team_research_mission(state, team)
        teams.append(team)

    # Preserve historical teams whose opportunity is no longer canonical, but remove them from active work.
    known = {str(x.get("opportunity_id") or "") for x in teams}
    for oid, team in existing.items():
        if oid in known:
            continue
        team["status"] = "archived_noncanonical"
        team["updated_at"] = _now()
        teams.append(team)

    state["mission_teams"] = teams[-30:]
    active = [x for x in teams if x.get("status") == "active"]
    state["mission_team_control"] = {
        "version": VERSION, "status": "active", "updated_at": _now(),
        "active_teams": len(active), "reserve_teams": sum(1 for x in teams if x.get("status") == "reserve"),
        "completed_teams": sum(1 for x in teams if x.get("status") == "completed"),
        "max_active_teams": MAX_ACTIVE_TEAMS,
        "operating_model": "temporary_cross_functional_teams_per_canonical_objective",
        "team_chain": ["research_analyst", "supplier_hunter", "negotiator", "revops", "risk_quality", "finance"],
        "production_code_self_modify": False, "binding_authority_changed": False,
    }
    core["mission_teams"] = [
        {
            "id": x.get("id"), "opportunity_id": x.get("opportunity_id"), "stage": x.get("stage"),
            "objective": x.get("objective"), "current_task": x.get("current_task"),
            "priority": x.get("priority"), "members": x.get("members"), "stagnant_cycles": x.get("stagnant_cycles"),
        }
        for x in active
    ]
    return state["mission_team_control"]


def _link_professional_cases(state: Dict[str, Any]) -> List[str]:
    active_teams = [x for x in state.get("mission_teams", []) or [] if x.get("status") == "active"]
    cases = list(state.get("professional_cases", []) or [])
    for case in cases:
        case["mission_team_ids"] = []
        case["mission_team_priority"] = 0
    scored: List[Tuple[int, str, Dict[str, Any], Dict[str, Any]]] = []
    for team in active_teams:
        source_ids = {str(team.get("buyer_account_id") or ""), str(team.get("supplier_account_id") or "")}
        source_ids.discard("")
        tt = _tokens(team.get("category"))
        for case in cases:
            score = 0
            source_id = str(case.get("source_id") or "")
            if source_id and source_id in source_ids:
                score = 100
            else:
                overlap = len(tt & _tokens(case.get("category")))
                if overlap:
                    score = min(88, 68 + overlap * 5)
            if score:
                scored.append((score, str(case.get("id") or ""), case, team))
    scored.sort(key=lambda row: (-row[0], row[1]))
    focus_ids: List[str] = []
    for score, _, case, team in scored:
        cid = str(case.get("id") or "")
        if cid not in focus_ids and len(focus_ids) >= MAX_FOCUS_CASES:
            continue
        if cid not in focus_ids:
            focus_ids.append(cid)
        ids = case.setdefault("mission_team_ids", [])
        if team.get("id") not in ids:
            ids.append(team.get("id"))
        case["mission_team_priority"] = max(_int(case.get("mission_team_priority")), score + max(0, 5 - _int(team.get("rank"))))
        case["mission_team_stage"] = team.get("stage")
        case["mission_team_task"] = team.get("current_task")
    state["mission_team_focus_case_ids"] = focus_ids
    for team in active_teams:
        team["focus_case_ids"] = [cid for cid in focus_ids if any(str(c.get("id")) == cid and team.get("id") in (c.get("mission_team_ids") or []) for c in cases)]
    return focus_ids


def _handoff_packets(state: Dict[str, Any]) -> int:
    cases = {str(x.get("id") or ""): x for x in state.get("professional_cases", []) or [] if isinstance(x, dict)}
    created = 0
    for team in state.get("mission_teams", []) or []:
        if team.get("status") != "active":
            continue
        packets = list(team.get("handoffs", []) or [])
        existing = {str(x.get("case_id") or "") + "|" + str(x.get("stage") or "") for x in packets}
        for cid in team.get("focus_case_ids", []) or []:
            case = cases.get(str(cid))
            if not case:
                continue
            key = f"{cid}|{case.get('stage')}"
            if key in existing:
                continue
            if case.get("status") not in {"ready_for_handoff", "active", "waiting_budget"}:
                continue
            facts = _safe_dict(case.get("facts"))
            packet = {
                "id": f"HANDOFF-{_fingerprint(team.get('id'), cid, case.get('stage'))}",
                "created_at": _now(), "case_id": cid, "stage": case.get("stage"),
                "from_role": case.get("owner_role"), "to_roles": _ROLE_BY_STAGE.get(str(team.get("stage")), ["revops"]),
                "summary": _clean(_safe_dict(facts.get("commercial_thesis")).get("statement") or case.get("next_action"))[:500],
                "evidence_count": len(case.get("evidence", []) or []),
                "next_action": case.get("next_action"), "binding": False,
            }
            packets.append(packet)
            existing.add(key)
            created += 1
        team["handoffs"] = packets[-20:]
    return created


def _team_blackboard_and_briefings(state: Dict[str, Any], core: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    _ORIGINAL_BLACKBOARD(state, core, issues)
    active = [x for x in state.get("mission_teams", []) or [] if x.get("status") == "active"]
    cards = list(core.get("blackboard", []) or [])
    for team in active:
        cards.append({
            "kind": "mission_team", "priority": team.get("priority", 90), "id": team.get("id"),
            "text": team.get("current_task"), "stage": team.get("stage"),
            "roles": [x.get("role") for x in team.get("members", []) or []],
        })
    cards.sort(key=lambda x: -_int(x.get("priority")))
    core["blackboard"] = cards[:autonomy_core_runtime.MAX_BLACKBOARD]
    briefings = _safe_dict(core.get("role_briefings"))
    for role, briefing in briefings.items():
        relevant = []
        for team in active:
            member = next((m for m in team.get("members", []) or [] if m.get("role") == role), None)
            if not member:
                continue
            relevant.append({
                "team_id": team.get("id"), "opportunity_id": team.get("opportunity_id"),
                "stage": team.get("stage"), "objective": team.get("objective"),
                "current_task": team.get("current_task"), "lead_agent_id": team.get("lead_agent_id"),
            })
        if isinstance(briefing, dict):
            briefing["mission_teams"] = relevant[:MAX_ACTIVE_TEAMS]
    workforce = state.setdefault("agent_workforce", {})
    workforce["autonomy_briefing"] = briefings
    workforce["shared_blackboard"] = core["blackboard"][:30]


def _team_aware_professional_casework_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    try:
        _prepare_teams(state)
        created = professional_casework._sync_cases(state)
        focus_ids = _link_professional_cases(state)
        cases = state.setdefault("professional_cases", [])
        active = [x for x in cases if x.get("status") in {"active", "waiting_budget"}]
        active.sort(key=lambda x: (
            -_int(x.get("mission_team_priority")),
            str(x.get("last_worked_at") or ""),
            -_int(x.get("cycles_worked")),
            str(x.get("id") or ""),
        ))
        queue = active[:professional_casework.MAX_CASES_PER_CYCLE]
        cycle_searches = {"used": 0}
        outcomes = {"advanced": 0, "waiting": 0, "ready": 0, "reopened": 0, "parked": 0}
        worked_cases: List[Dict[str, Any]] = []
        for case in queue:
            result = professional_casework._work_case(state, case, cycle_searches)
            outcomes[result] = outcomes.get(result, 0) + 1
            worked_cases.append({
                "case_id": case.get("id"), "owner": case.get("owner_agent_id"), "subject": case.get("title"),
                "kind": case.get("subject_kind"), "stage": case.get("stage"), "status": case.get("status"),
                "progress_pct": case.get("progress_pct"), "next_action": case.get("next_action"),
                "evidence_count": len(case.get("evidence", []) or []),
                "mission_team_priority": case.get("mission_team_priority"),
                "mission_team_ids": case.get("mission_team_ids"),
            })
        status_counts: Dict[str, int] = {}
        stage_counts: Dict[str, int] = {}
        for case in cases:
            status = str(case.get("status") or "unknown")
            stage = str(case.get("stage") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        budget = professional_casework._deep_budget(state)
        global_budget = professional_casework.agent_fleet._budget(state)
        report = {
            "version": "1.1-professional-deep-work-mission-teams", "updated_at": professional_casework.utcnow(),
            "cases_total": len(cases), "cases_created": created, "cases_worked": len(worked_cases),
            "searches_used": cycle_searches["used"],
            "deep_search_budget_used_today": _int(budget.get("searches_used")),
            "deep_search_budget_remaining": _int(budget.get("searches_remaining")),
            "global_general_search_remaining": _int(global_budget.get("general_queries_remaining")),
            "status_counts": status_counts, "stage_counts": stage_counts, "outcomes": outcomes,
            "ready_for_handoff": status_counts.get("ready_for_handoff", 0),
            "waiting_budget": status_counts.get("waiting_budget", 0), "worked_cases": worked_cases,
            "operating_model": "persistent_owned_cases_with_cross_functional_mission_team_priority",
            "authority": "research_and_nonbinding_commercial_preparation_only",
            "mission_team_focus": {
                "active_teams": _int(_safe_dict(state.get("mission_team_control")).get("active_teams")),
                "focus_case_ids": focus_ids,
                "focused_cases_worked": sum(1 for x in worked_cases if x.get("mission_team_priority")),
            },
        }
        state["professional_casework"] = report
        history = list(state.get("professional_casework_history", []) or [])
        history.append({k: report[k] for k in ("updated_at", "cases_total", "cases_worked", "searches_used", "ready_for_handoff", "waiting_budget")})
        state["professional_casework_history"] = history[-48:]
        state.setdefault("activity", []).insert(0, {
            "ts": professional_casework.utcnow(),
            "msg": (
                f"Deep Work + Mission Teams: {len(worked_cases)} expedientes, {cycle_searches['used']} búsquedas, "
                f"{outcomes.get('advanced', 0)} avances y {report['mission_team_focus']['focused_cases_worked']} casos foco trabajados."
            ),
        })
        state["activity"] = state["activity"][:100]
        mission_team_tick(state)
        return report
    except Exception as exc:
        report = dict(_ORIGINAL_PROFESSIONAL_TICK(state) or {})
        report["mission_team_fail_open"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        return report


def mission_team_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    control = _prepare_teams(state)
    focus_ids = _link_professional_cases(state)
    handoffs_created = _handoff_packets(state)
    active = [x for x in state.get("mission_teams", []) or [] if x.get("status") == "active"]
    stalled = [x for x in active if _int(x.get("stagnant_cycles")) >= STAGNATION_ESCALATION_CYCLES]
    for team in stalled:
        _ensure_team_peer_help(state, team)
        _ensure_team_research_mission(state, team)
        team["escalation"] = {
            "status": "auto_escalated_nonbinding", "at": _now(),
            "reason": f"stage unchanged for {team.get('stagnant_cycles')} evaluated cycles",
            "action": "increase peer-help/research priority and preserve evidence-first gates",
        }
        team["priority"] = min(100, _int(team.get("priority")) + 4)
    control.update({
        "focus_cases": len(focus_ids), "handoffs_created_this_tick": handoffs_created,
        "stalled_teams": len(stalled),
        "team_summary": [
            {
                "id": x.get("id"), "opportunity_id": x.get("opportunity_id"), "stage": x.get("stage"),
                "priority": x.get("priority"), "stagnant_cycles": x.get("stagnant_cycles"),
                "members": [m.get("agent_id") for m in x.get("members", []) or []],
                "focus_cases": len(x.get("focus_case_ids", []) or []), "current_task": x.get("current_task"),
            }
            for x in active
        ],
        "authority": {
            "binding_contracts": "human_required", "payments_orders_financial_commitments": "human_required",
            "material_legal_liability": "human_required", "new_external_connectors_accounts": "human_required",
            "paid_media_spend": "human_required", "production_code_changes_deploys": "human_required",
            "binding_authority_changed": False,
        },
    })
    state["mission_team_control"] = control
    return control


def _continuous_learning_with_mission_teams(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_CONTINUOUS_LEARNING(state) or {})
    try:
        team_report = mission_team_tick(state)
        report["mission_teams"] = {
            "active_teams": team_report.get("active_teams"),
            "focus_cases": team_report.get("focus_cases"),
            "handoffs_created_this_tick": team_report.get("handoffs_created_this_tick"),
            "stalled_teams": team_report.get("stalled_teams"),
        }
        print({"mission_teams": team_report}, flush=True)
    except Exception as exc:
        report["mission_teams"] = {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}
        print({"mission_teams": report["mission_teams"]}, flush=True)
    state["continuous_learning"] = report
    return report


professional_casework.professional_casework_tick = _team_aware_professional_casework_tick
autonomy_core_runtime._blackboard_and_briefings = _team_blackboard_and_briefings
continuous_learning_runtime.continuous_learning_tick = _continuous_learning_with_mission_teams

print({
    "mission_team_runtime": {
        "version": VERSION, "status": "active", "max_active_teams": MAX_ACTIVE_TEAMS,
        "professional_casework_priority": True, "shared_handoffs": True,
        "skill_aware_staffing": True, "auto_peer_help": True, "auto_research_missions": True,
        "playbook_learning": True, "cross_role_briefings": True,
        "production_code_self_modify": False, "binding_authority_changed": False,
    }
}, flush=True)
