from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

MAX_CANDIDATES = 80
MAX_SELECTED = 12
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


def _safe(value: Any, default: float = 72.0) -> float:
    if value in (None, ""):
        return default
    return max(0.0, min(100.0, _f(value)))


def _capital_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return dict(state.get("capital_priority_index", {}) or {})


def _collection_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for case in state.get("commission_settlement_cases", []) or []:
        status = str(case.get("status") or "")
        if status not in {"OVERDUE", "PARTIAL_RECEIVED", "AWAITING_PAYMENT"}:
            continue
        value = max(0.0, _f(case.get("outstanding_amount_usd")))
        if value <= 0:
            continue
        rows.append({
            "id": f"collection|{case.get('transaction_id')}",
            "kind": "COLLECT_CASH",
            "object_type": "transaction",
            "object_id": str(case.get("transaction_id") or ""),
            "deal_id": str(case.get("deal_id") or ""),
            "title": "Cobrar comisión pendiente",
            "economic_value_usd": value,
            "value_type": "documented_receivable",
            "evidence_confidence": 0.99,
            "safe_close_score": 95.0 if not case.get("incident_hold") else 20.0,
            "urgency": 100.0 if status == "OVERDUE" else 92.0 if status == "PARTIAL_RECEIVED" else 72.0,
            "attention_units": 1.0,
            "autonomous": True,
            "blocking": bool(case.get("incident_hold")),
            "reason": f"Saldo de comisión documentado USD {value:,.2f}; estado {status}.",
            "recommended_action": case.get("next_action") or "Gestionar cobro profesionalmente",
        })
    return rows


def _closing_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    capital = _capital_index(state)
    rows: List[Dict[str, Any]] = []
    for pack in state.get("closing_packs", []) or []:
        deal_id = str(pack.get("deal_id") or "")
        cap = capital.get(deal_id, {})
        profit = max(0.0, _f(cap.get("risk_adjusted_expected_profit_usd")))
        if profit <= 0:
            profit = max(0.0, _f((pack.get("economics") or {}).get("company_profit")))
        if profit <= 0:
            continue
        status = str(pack.get("status") or "")
        if status == "BLOCKED_RISK":
            kind = "REPAIR_CLOSE_RISK"
            autonomous = True
            urgency = 94.0
            blocking = True
        elif status == "READY_FOR_HUMAN_APPROVAL":
            kind = "REQUEST_CLOSE_APPROVAL"
            autonomous = False
            urgency = 100.0
            blocking = False
        else:
            kind = "COMPLETE_CLOSE_PACK"
            autonomous = True
            urgency = 90.0
            blocking = False
        rows.append({
            "id": f"close|{deal_id}",
            "kind": kind,
            "object_type": "deal",
            "object_id": deal_id,
            "deal_id": deal_id,
            "title": "Convertir valor maduro en cierre",
            "economic_value_usd": profit,
            "value_type": "risk_adjusted_expected_profit" if _f(cap.get("risk_adjusted_expected_profit_usd")) > 0 else "known_company_profit",
            "evidence_confidence": max(0.45, min(0.98, _f(cap.get("close_probability"), 0.72))),
            "safe_close_score": _safe(pack.get("safe_close_score")),
            "capital_priority_score": _f(cap.get("capital_priority_score"), 60.0),
            "urgency": urgency,
            "attention_units": 1.4 if status == "READY_FOR_HUMAN_APPROVAL" else 2.0,
            "autonomous": autonomous,
            "blocking": blocking,
            "reason": f"Paquete de cierre {status}; beneficio priorizable USD {profit:,.2f}.",
            "recommended_action": "Pedir decisión humana final" if not autonomous else "Resolver faltantes del paquete de cierre",
        })
    return rows


def _capital_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for cap in (state.get("capital_margin_intelligence", {}) or {}).get("deal_capital_rankings", []) or []:
        deal_id = str(cap.get("deal_id") or "")
        action = str(cap.get("capital_action") or "")
        value = max(0.0, _f(cap.get("risk_adjusted_expected_profit_usd")))
        if not deal_id or value <= 0:
            continue
        kind_map = {
            "ACCELERATE": "ACCELERATE_DEAL",
            "IMPROVE_MARGIN": "IMPROVE_MARGIN",
            "IMPROVE_CONVERSION": "IMPROVE_CONVERSION",
            "REPAIR_TERMS": "REPAIR_TERMS",
            "COMPLETE_ECONOMICS": "COMPLETE_ECONOMICS",
            "HOLD_RISK": "REPAIR_OR_PARK_RISK",
            "DEPRIORITIZE": "PARK_DEAL",
        }
        kind = kind_map.get(action, "IMPROVE_DEAL")
        rows.append({
            "id": f"capital|{deal_id}|{action}",
            "kind": kind,
            "object_type": "deal",
            "object_id": deal_id,
            "deal_id": deal_id,
            "title": cap.get("category") or cap.get("buyer") or "Optimizar deal",
            "economic_value_usd": value,
            "value_type": "risk_adjusted_expected_profit",
            "evidence_confidence": max(0.40, min(0.98, _f(cap.get("close_probability"), 0.5))),
            "safe_close_score": _safe(cap.get("safe_close_score")),
            "capital_priority_score": _f(cap.get("capital_priority_score")),
            "urgency": 94.0 if action in {"ACCELERATE", "IMPROVE_MARGIN"} else 88.0 if action in {"REPAIR_TERMS", "COMPLETE_ECONOMICS"} else 72.0,
            "attention_units": 2.0 if action in {"ACCELERATE", "IMPROVE_MARGIN", "IMPROVE_CONVERSION"} else 2.5,
            "autonomous": action not in {"HOLD_RISK"},
            "blocking": action == "HOLD_RISK",
            "reason": str(cap.get("capital_reason") or "Decisión de capital y margen"),
            "recommended_action": action,
        })
    return rows


def _pipeline_candidate(state: Dict[str, Any], goal: Dict[str, Any]) -> List[Dict[str, Any]]:
    active = goal.get("active_goal", {}) or {}
    code = str(active.get("code") or "")
    if code not in {"BUILD_REVENUE_ENGINE", "BUILD_EVIDENCE_AND_PIPELINE"}:
        return []
    factory = state.get("revenue_factory", {}) or {}
    directive = factory.get("directive", {}) or {}
    gap = _f((factory.get("reverse_plan", {}) or {}).get("profit_gap_usd"))
    return [{
        "id": f"pipeline|{directive.get('code') or code}",
        "kind": "BUILD_PIPELINE",
        "object_type": "company",
        "object_id": "LUMEN",
        "title": str(directive.get("title") or "Construir pipeline verificable"),
        "economic_value_usd": max(0.0, gap),
        "value_type": "profit_gap_context_not_expected_value",
        "evidence_confidence": 0.60 if (factory.get("reverse_plan", {}) or {}).get("status") == "reverse_plan_ready" else 0.45,
        "safe_close_score": 80.0,
        "capital_priority_score": 55.0,
        "urgency": _f(directive.get("priority"), 78.0),
        "attention_units": 3.0,
        "autonomous": bool(directive.get("autonomous", True)),
        "blocking": False,
        "reason": str(active.get("reason") or directive.get("title") or "Cerrar brecha del funnel"),
        "recommended_action": directive.get("code") or "build_pipeline",
    }]


def _venture_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    ventures = (state.get("venture_builder", {}) or {}).get("ventures", []) or []
    for venture in ventures[:8]:
        stage = str(venture.get("stage") or "")
        if stage in {"KILL", "PAUSE", "KILL_CANDIDATE", "PAUSE_CANDIDATE"}:
            continue
        score = _f(venture.get("score") or venture.get("venture_score"), 50.0)
        confidence = _f(venture.get("confidence"), 0.35)
        realized = _f(venture.get("realized_profit_usd"))
        if realized > 0:
            value = realized
            value_type = "venture_realized_profit_history"
        else:
            value = 0.0
            value_type = "unknown_not_invented"
        rows.append({
            "id": f"venture|{venture.get('id')}",
            "kind": "VALIDATE_VENTURE",
            "object_type": "venture",
            "object_id": str(venture.get("id") or ""),
            "title": venture.get("title") or venture.get("hypothesis") or "Validar nueva línea",
            "economic_value_usd": value,
            "value_type": value_type,
            "evidence_confidence": max(0.20, min(0.9, confidence)),
            "safe_close_score": 75.0,
            "capital_priority_score": score,
            "urgency": min(78.0, 55.0 + score * 0.25),
            "attention_units": 3.5,
            "autonomous": True,
            "blocking": False,
            "reason": "Exploración de nueva línea; no se le atribuye valor económico futuro sin evidencia.",
            "recommended_action": "validate_venture",
        })
    return rows


def _score(candidates: List[Dict[str, Any]], company_mode: str) -> None:
    known_values = [max(0.0, _f(x.get("economic_value_usd"))) for x in candidates if _f(x.get("economic_value_usd")) > 0 and x.get("value_type") != "profit_gap_context_not_expected_value"]
    max_value = max(known_values) if known_values else 1.0
    for row in candidates:
        value = max(0.0, _f(row.get("economic_value_usd")))
        if row.get("value_type") in {"unknown_not_invented", "profit_gap_context_not_expected_value"}:
            value_signal = 18.0 if row.get("value_type") == "unknown_not_invented" else 32.0
        else:
            value_signal = min(100.0, value / max_value * 100.0)
        safe = _safe(row.get("safe_close_score"))
        evidence = max(0.0, min(100.0, _f(row.get("evidence_confidence")) * 100.0))
        capital = max(0.0, min(100.0, _f(row.get("capital_priority_score"), 55.0)))
        urgency = max(0.0, min(100.0, _f(row.get("urgency"), 70.0)))
        attention = max(1.0, min(5.0, _f(row.get("attention_units"), 2.0)))
        raw = value_signal * 0.38 + safe * 0.18 + evidence * 0.14 + capital * 0.16 + urgency * 0.14
        score = raw - (attention - 1.0) * 5.0
        if row.get("blocking"):
            score *= 0.45
        if company_mode == "PROTECT_CASH" and row.get("kind") == "COLLECT_CASH":
            score += 12.0
        if company_mode == "RECOVERY":
            score = 0.0
        if row.get("kind") == "PARK_DEAL":
            score *= 0.35
        row["value_signal"] = round(value_signal, 2)
        row["portfolio_priority_score"] = round(max(0.0, min(100.0, score)), 2)
        row["ranking_note"] = "Heuristic opportunity-cost rank; not a forecast probability or guaranteed return."


def _dedupe(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_key: Dict[str, Dict[str, Any]] = {}
    for row in candidates:
        object_key = f"{row.get('object_type')}|{row.get('object_id')}"
        current = by_key.get(object_key)
        if current is None or _f(row.get("portfolio_priority_score")) > _f(current.get("portfolio_priority_score")):
            by_key[object_key] = row
    return list(by_key.values())


def _apply_overlay(state: Dict[str, Any], primary: Dict[str, Any] | None) -> Dict[str, Any]:
    governance = state.get("master_governance", {}) or {}
    mode = str(governance.get("company_mode") or "")
    switches = governance.get("kill_switches", {}) or {}
    base = dict(governance.get("resource_plan", {}) or state.get("master_resource_plan", {}) or {})
    result = {"applied": False, "reason": "no_primary_candidate", "base_resource_plan": base}
    if not primary or not base:
        state["portfolio_optimizer_overlay"] = result
        return result
    if mode == "RECOVERY" or switches.get("global_pause"):
        result["reason"] = "constitutional_recovery_blocks_portfolio_overlay"
        state["portfolio_optimizer_overlay"] = result
        return result

    kind = str(primary.get("kind") or "")
    adjustments = {
        "COLLECT_CASH": {"deep_dive_pct": 12, "core_research_pct": -6, "exploration_pct": -6},
        "REQUEST_CLOSE_APPROVAL": {"deep_dive_pct": 12, "core_research_pct": -6, "exploration_pct": -6},
        "COMPLETE_CLOSE_PACK": {"deep_dive_pct": 10, "core_research_pct": -5, "exploration_pct": -5},
        "ACCELERATE_DEAL": {"deep_dive_pct": 10, "core_research_pct": -5, "exploration_pct": -5},
        "IMPROVE_MARGIN": {"deep_dive_pct": 10, "expansion_pct": -5, "exploration_pct": -5},
        "REPAIR_CLOSE_RISK": {"deep_dive_pct": 10, "expansion_pct": -5, "exploration_pct": -5},
        "BUILD_PIPELINE": {"core_research_pct": 8, "deep_dive_pct": -4, "exploration_pct": -4},
        "VALIDATE_VENTURE": {"exploration_pct": 6, "core_research_pct": -3, "expansion_pct": -3},
    }.get(kind, {})
    if not adjustments:
        result["reason"] = f"no_overlay_for:{kind}"
        state["portfolio_optimizer_overlay"] = result
        return result

    adjusted = dict(base)
    for key in RESOURCE_KEYS:
        adjusted[key] = max(0.0, min(100.0, _f(base.get(key)) + _f(adjustments.get(key))))
    if switches.get("expansion_pause"):
        adjusted["expansion_pct"] = 0.0
    total = sum(_f(adjusted.get(k)) for k in RESOURCE_KEYS)
    if total > 0:
        for key in RESOURCE_KEYS:
            adjusted[key] = round(_f(adjusted.get(key)) / total * 100.0, 1)
    for key in ("outbound_cap", "mission_queries_cap", "expansion_queries_cap", "daily_queries_remaining", "resource_type", "authorizes_spending"):
        if key in base:
            adjusted[key] = base[key]
    governance["resource_plan"] = adjusted
    state["master_governance"] = governance
    state["master_resource_plan"] = adjusted
    result.update({"applied": True, "reason": f"focus_on:{kind}", "adjustments": adjustments, "adjusted_resource_plan": adjusted})
    state["portfolio_optimizer_overlay"] = result
    return result


def _materialize_tasks(state: Dict[str, Any], selected: List[Dict[str, Any]]) -> None:
    queue = list(state.get("operating_action_queue", []) or [])
    by_key = {str(x.get("key")): x for x in queue if x.get("key")}
    for rank, row in enumerate(selected[:8], start=1):
        task = {
            "key": f"portfolio_optimizer|{row.get('kind')}|{row.get('object_type')}|{row.get('object_id')}",
            "kind": "portfolio_optimizer",
            "title": f"Prioridad de cartera #{rank}: {row.get('title')}",
            "reason": str(row.get("reason") or row.get("recommended_action") or "Prioridad económica"),
            "impact": min(100.0, 65.0 + _f(row.get("portfolio_priority_score")) * 0.35),
            "urgency": _f(row.get("urgency"), 80.0),
            "confidence": _f(row.get("evidence_confidence"), 0.7),
            "effort": _f(row.get("attention_units"), 2.0),
            "risk": "high" if row.get("blocking") else "medium" if not row.get("autonomous") else "low",
            "autonomous": bool(row.get("autonomous")) and not bool(row.get("blocking")),
            "object_type": row.get("object_type"),
            "object_id": row.get("object_id"),
            "payload": dict(row),
            "priority_score": _f(row.get("portfolio_priority_score")),
            "created_at": utcnow(),
        }
        by_key[task["key"]] = task
    state["operating_action_queue"] = sorted(by_key.values(), key=lambda x: _f(x.get("priority_score")), reverse=True)[:120]


def _annotate_deals(state: Dict[str, Any], selected: List[Dict[str, Any]]) -> None:
    best: Dict[str, Dict[str, Any]] = {}
    for row in selected:
        deal_id = str(row.get("deal_id") or "")
        if not deal_id:
            continue
        if deal_id not in best or _f(row.get("portfolio_priority_score")) > _f(best[deal_id].get("portfolio_priority_score")):
            best[deal_id] = row
    for deal in state.get("deals", []) or []:
        row = best.get(str(deal.get("id") or ""))
        if not row:
            continue
        deal["portfolio_priority_score"] = row.get("portfolio_priority_score")
        deal["portfolio_action"] = row.get("kind")
        deal["portfolio_ranked_at"] = utcnow()


def portfolio_optimizer_tick(state: Dict[str, Any], goal_plan: Dict[str, Any] | None = None) -> Dict[str, Any]:
    goal = goal_plan or state.get("autonomous_goal_planner", {}) or {}
    mode = str((state.get("master_governance", {}) or {}).get("company_mode") or "BALANCED")
    candidates = [
        *_collection_candidates(state),
        *_closing_candidates(state),
        *_capital_candidates(state),
        *_pipeline_candidate(state, goal),
        *_venture_candidates(state),
    ]
    _score(candidates, mode)
    candidates = _dedupe(candidates)
    candidates.sort(key=lambda x: (_f(x.get("portfolio_priority_score")), _f(x.get("economic_value_usd"))), reverse=True)
    candidates = candidates[:MAX_CANDIDATES]

    selected: List[Dict[str, Any]] = []
    for rank, row in enumerate(candidates[:MAX_SELECTED], start=1):
        item = dict(row)
        item["rank"] = rank
        if rank <= 3 and item.get("portfolio_priority_score", 0) >= 55:
            item["portfolio_decision"] = "PURSUE_NOW"
        elif item.get("portfolio_priority_score", 0) >= 40:
            item["portfolio_decision"] = "NEXT"
        elif item.get("blocking"):
            item["portfolio_decision"] = "HOLD"
        else:
            item["portfolio_decision"] = "PARK"
        selected.append(item)

    primary = selected[0] if selected else None
    overlay = _apply_overlay(state, primary)
    _materialize_tasks(state, selected)
    _annotate_deals(state, selected)

    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_opportunity_cost_portfolio_optimization",
        "company_mode": mode,
        "goal": (goal.get("active_goal") or {}).get("code"),
        "primary_action": primary,
        "selected_actions": selected,
        "candidate_count": len(candidates),
        "pursue_now": sum(1 for x in selected if x.get("portfolio_decision") == "PURSUE_NOW"),
        "next": sum(1 for x in selected if x.get("portfolio_decision") == "NEXT"),
        "hold": sum(1 for x in selected if x.get("portfolio_decision") == "HOLD"),
        "park": sum(1 for x in selected if x.get("portfolio_decision") == "PARK"),
        "resource_overlay": overlay,
        "governance": {
            "objective": "Asignar atención a la combinación de acciones con mejor valor económico sostenible ajustado por riesgo y evidencia.",
            "score_rule": "Portfolio Priority Score is a heuristic ranking, not a forecast probability or guaranteed ROI.",
            "unknown_value_rule": "Ventures/pipeline without observed economics do not receive invented future dollar value.",
            "constitutional_rule": "Portfolio allocation cannot widen outbound/search/spending caps or override recovery, legal, risk, payment or human-approval controls.",
            "authority_rule": "May prioritize and execute reversible work; binding close, payments and capital commitments remain human-controlled.",
        },
    }
    state["portfolio_optimizer"] = report
    state["portfolio_action_plan"] = selected
    state.setdefault("portfolio_optimizer_history", []).append({
        "ts": report["updated_at"],
        "goal": report.get("goal"),
        "primary_kind": (primary or {}).get("kind"),
        "primary_object_id": (primary or {}).get("object_id"),
        "primary_score": (primary or {}).get("portfolio_priority_score"),
    })
    state["portfolio_optimizer_history"] = state["portfolio_optimizer_history"][-192:]

    if primary:
        record_decision(
            state,
            engine="Autonomous Portfolio Optimizer",
            object_type=str(primary.get("object_type") or "company"),
            object_id=str(primary.get("object_id") or "LUMEN"),
            decision=f"portfolio:{str(primary.get('kind') or '').lower()}",
            reason=f"Portfolio score {primary.get('portfolio_priority_score')}; valor conocido USD {_f(primary.get('economic_value_usd')):,.2f}. {primary.get('reason')}",
            action="score_opportunity" if primary.get("autonomous") else "request_human_close_approval",
            confidence=max(0.45, min(0.99, _f(primary.get("evidence_confidence"), 0.7))),
            evidence_refs=[],
            allowed=not bool(primary.get("blocking")),
            requires_approval=not bool(primary.get("autonomous")) or bool(primary.get("blocking")),
        )
    return report
