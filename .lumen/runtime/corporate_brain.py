from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from autonomy_governor import record_decision


STRATEGY_MIN_HOLD_CYCLES = 32
STRATEGY_REVIEW_CYCLES = 96
MAX_STRATEGY_HISTORY = 120
MAX_REVIEW_HISTORY = 120
MAX_EXPERIMENT_HISTORY = 160
MAX_ACTIVE_EXPERIMENTS = 4


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return utcnow_dt().strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _pct(num: float, den: float) -> float:
    return 0.0 if den <= 0 else max(0.0, min(100.0, num / den * 100.0))


def _ensure_memory(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("corporate_brain_memory", {})
    memory.setdefault("cycles", 0)
    memory.setdefault("strategy_epoch", 0)
    memory.setdefault("current_strategy", None)
    memory.setdefault("strategy_streak", 0)
    memory.setdefault("strategy_history", [])
    memory.setdefault("review_history", [])
    memory.setdefault("experiment_history", [])
    memory.setdefault("active_experiments", [])
    memory.setdefault("period_baselines", {})
    memory.setdefault("objective_sets", {})
    memory.setdefault("last_review_cycle", 0)
    return memory


def _period_keys(now: datetime) -> Tuple[str, str]:
    month = now.strftime("%Y-%m")
    quarter = f"{now.year}-Q{((now.month - 1) // 3) + 1}"
    return month, quarter


def _real_transactions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    real_statuses = {"closed", "settled", "paid", "completed", "delivered", "invoiced"}
    return [
        x for x in state.get("transactions", [])
        if str(x.get("status") or "") in real_statuses
        and str(x.get("status") or "") not in {"closed_simulated", "simulated"}
    ]


def _metrics(state: Dict[str, Any]) -> Dict[str, Any]:
    accounts = state.get("candidate_accounts", [])
    verified = [x for x in accounts if x.get("verified_company")]
    buyers = [x for x in verified if x.get("type") == "buyer"]
    suppliers = [x for x in verified if x.get("type") == "supplier"]
    demand_buyers = [x for x in buyers if x.get("demand_signal")]
    opps = state.get("market_opportunities", [])
    cases = state.get("interlocution_cases", [])
    sent = [x for x in state.get("outbox", []) if x.get("status") == "sent"]
    inbox = state.get("inbox", [])
    real_offers = [x for x in state.get("offers", []) if x.get("source") != "demo/simulación"]
    comparable = [x for x in state.get("quote_comparisons", []) if x.get("status") == "comparable"]
    deals = [x for x in state.get("deals", []) if x.get("source") != "demo"]
    viable = [x for x in deals if x.get("economics", {}).get("viable")]
    close_ready = [
        x for x in deals
        if x.get("stage") in {"listo para cerrar", "autorizado para cierre", "listo para cierre aprobado"}
    ]
    transactions = _real_transactions(state)
    realized = [x for x in transactions if str(x.get("status") or "") in {"settled", "paid", "completed"}]
    cfo = state.get("cfo", {}) or state.get("cfo_report", {}) or {}
    snapshot = cfo.get("financial_snapshot", {}) or state.get("financial_snapshot", {}) or {}
    learning = state.get("profit_learning", {}) or {}
    primary_learning = (learning.get("focus_categories") or [{}])[0] if learning.get("focus_categories") else {}
    war = state.get("war_room", {}) or {}
    primary_money = war.get("primary_money_move") or {}
    attack_cases = [x for x in state.get("deep_dive_cases", []) if x.get("status") == "attack"]
    supplier_competitions = state.get("supplier_competitions", []) or []
    supplier_depth_ready = sum(1 for x in supplier_competitions if int(x.get("ready_supplier_count") or 0) >= 2)

    realized_profit = _f(snapshot.get("realized_profit_usd"))
    if realized_profit <= 0:
        realized_profit = sum(max(0.0, _f(x.get("company_profit"))) for x in realized)

    return {
        "research_leads": len(state.get("research_leads", [])),
        "verified_companies": len(verified),
        "verified_buyers": len(buyers),
        "verified_suppliers": len(suppliers),
        "buyers_with_verified_demand": len(demand_buyers),
        "evidence_backed_opportunities": len(opps),
        "requirements_ready": sum(1 for x in cases if x.get("supplier_rfq_ready")),
        "outbound_sent": len(sent),
        "inbound_received": len(inbox),
        "response_rate_pct": round(_pct(len(inbox), len(sent)), 2),
        "real_offers": len(real_offers),
        "comparable_quote_sets": len(comparable),
        "proposals": len(state.get("proposals", [])),
        "viable_deals": len(viable),
        "close_ready_deals": len(close_ready),
        "real_transactions": len(transactions),
        "realized_transactions": len(realized),
        "realized_profit_usd": round(realized_profit, 2),
        "risk_adjusted_expected_profit_usd": round(_f(snapshot.get("risk_adjusted_expected_profit_usd")), 2),
        "gross_unsettled_receivable_usd": round(_f(snapshot.get("gross_unsettled_receivable_usd")), 2),
        "potential_supplier_commitment_usd": round(_f(snapshot.get("potential_supplier_commitment_usd")), 2),
        "attack_cases": len(attack_cases),
        "supplier_competitions_ready": supplier_depth_ready,
        "primary_category": primary_learning.get("category") or learning.get("primary_category"),
        "primary_category_score": round(_f(primary_learning.get("learned_score"), 50.0), 2),
        "primary_category_confidence": round(_f(primary_learning.get("confidence")), 2),
        "primary_money_score": round(_f(primary_money.get("money_score")), 2),
        "primary_money_deal_id": primary_money.get("deal_id") or primary_money.get("deep_dive_case_id"),
    }


def _objective_value(metrics: Dict[str, Any], metric: str) -> float:
    return _f(metrics.get(metric))


def _objective_progress(baseline: float, target: float, current: float) -> float:
    if target <= baseline:
        return 100.0 if current >= target else 0.0
    return round(max(0.0, min(100.0, (current - baseline) / (target - baseline) * 100.0)), 1)


def _adaptive_objectives(memory: Dict[str, Any], metrics: Dict[str, Any], month: str, quarter: str) -> Dict[str, Any]:
    period_baselines = memory["period_baselines"]
    objective_sets = memory["objective_sets"]

    def baseline_for(period: str) -> Dict[str, Any]:
        if period not in period_baselines:
            period_baselines[period] = {**metrics, "captured_at": utcnow()}
        return period_baselines[period]

    month_base = baseline_for(month)
    quarter_base = baseline_for(quarter)

    if month not in objective_sets:
        demand_base = int(month_base.get("buyers_with_verified_demand") or 0)
        opp_base = int(month_base.get("evidence_backed_opportunities") or 0)
        comparable_base = int(month_base.get("comparable_quote_sets") or 0)
        tx_base = int(month_base.get("real_transactions") or 0)
        risk_profit_base = _f(month_base.get("risk_adjusted_expected_profit_usd"))
        month_targets: List[Dict[str, Any]] = [
            {
                "id": f"{month}|demand",
                "metric": "buyers_with_verified_demand",
                "objective": "Aumentar compradores con demanda pública verificada",
                "baseline": demand_base,
                "target": demand_base + max(1, math.ceil(max(1, demand_base) * 0.25)),
            },
            {
                "id": f"{month}|opportunities",
                "metric": "evidence_backed_opportunities",
                "objective": "Aumentar oportunidades respaldadas por evidencia",
                "baseline": opp_base,
                "target": opp_base + max(2, math.ceil(max(1, opp_base) * 0.25)),
            },
            {
                "id": f"{month}|quotes",
                "metric": "comparable_quote_sets",
                "objective": "Generar competencia de precios con cotizaciones comparables",
                "baseline": comparable_base,
                "target": comparable_base + max(1, math.ceil(max(1, comparable_base) * 0.30)),
            },
            {
                "id": f"{month}|transactions",
                "metric": "real_transactions",
                "objective": "Convertir pipeline en operaciones reales",
                "baseline": tx_base,
                "target": tx_base + max(1, math.ceil(max(1, tx_base) * 0.20)),
            },
        ]
        if risk_profit_base > 0:
            month_targets.append({
                "id": f"{month}|risk_profit",
                "metric": "risk_adjusted_expected_profit_usd",
                "objective": "Elevar beneficio esperado ajustado por riesgo",
                "baseline": round(risk_profit_base, 2),
                "target": round(risk_profit_base * 1.20, 2),
            })
        objective_sets[month] = month_targets

    if quarter not in objective_sets:
        tx_base = int(quarter_base.get("real_transactions") or 0)
        realized_base = _f(quarter_base.get("realized_profit_usd"))
        verified_base = int(quarter_base.get("verified_companies") or 0)
        quarter_targets: List[Dict[str, Any]] = [
            {
                "id": f"{quarter}|transactions",
                "metric": "real_transactions",
                "objective": "Construir repetibilidad comercial trimestral",
                "baseline": tx_base,
                "target": tx_base + max(3, math.ceil(max(1, tx_base) * 0.35)),
            },
            {
                "id": f"{quarter}|verified_network",
                "metric": "verified_companies",
                "objective": "Ampliar red de compradores y proveedores verificados",
                "baseline": verified_base,
                "target": verified_base + max(6, math.ceil(max(1, verified_base) * 0.30)),
            },
            {
                "id": f"{quarter}|supplier_competition",
                "metric": "supplier_competitions_ready",
                "objective": "Crear profundidad de oferta para negociar con alternativas reales",
                "baseline": int(quarter_base.get("supplier_competitions_ready") or 0),
                "target": int(quarter_base.get("supplier_competitions_ready") or 0) + 3,
            },
        ]
        if realized_base > 0:
            quarter_targets.append({
                "id": f"{quarter}|realized_profit",
                "metric": "realized_profit_usd",
                "objective": "Aumentar beneficio realizado, no solo pipeline",
                "baseline": round(realized_base, 2),
                "target": round(realized_base * 1.25, 2),
            })
        objective_sets[quarter] = quarter_targets

    def hydrate(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for raw in items:
            current = _objective_value(metrics, str(raw["metric"]))
            item = dict(raw)
            item["current"] = round(current, 2)
            item["progress_pct"] = _objective_progress(_f(raw["baseline"]), _f(raw["target"]), current)
            item["status"] = "achieved" if current >= _f(raw["target"]) else "active"
            out.append(item)
        return out

    return {
        "month": month,
        "quarter": quarter,
        "monthly": hydrate(objective_sets[month]),
        "quarterly": hydrate(objective_sets[quarter]),
    }


def _bottlenecks(metrics: Dict[str, Any]) -> List[str]:
    gaps: List[str] = []
    if metrics["verified_suppliers"] == 0:
        gaps.append("supplier_gap")
    if metrics["verified_buyers"] == 0:
        gaps.append("buyer_gap")
    elif metrics["buyers_with_verified_demand"] == 0:
        gaps.append("demand_gap")
    if metrics["evidence_backed_opportunities"] > 0 and metrics["requirements_ready"] == 0:
        gaps.append("requirement_gap")
    if metrics["real_offers"] > 0 and metrics["comparable_quote_sets"] == 0:
        gaps.append("quote_comparison_gap")
    if metrics["proposals"] > 0 and metrics["real_transactions"] == 0:
        gaps.append("conversion_gap")
    return gaps


def _strategy_candidate(state: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
    learning = state.get("profit_learning", {}) or {}
    focus = [str(x.get("category")) for x in learning.get("focus_categories", []) if x.get("category")][:3]
    deprioritized = [str(x.get("category")) for x in learning.get("deprioritized_categories", []) if x.get("category")][:5]
    bottlenecks = _bottlenecks(metrics)
    warnings = list((state.get("cfo", {}) or {}).get("warnings", []) or [])
    collection = metrics["gross_unsettled_receivable_usd"]
    risk_profit = metrics["risk_adjusted_expected_profit_usd"]
    score = metrics["primary_category_score"]
    confidence = metrics["primary_category_confidence"]
    money_score = metrics["primary_money_score"]

    if metrics["verified_suppliers"] == 0 or metrics["verified_buyers"] == 0 or metrics["evidence_backed_opportunities"] == 0:
        return {
            "mode": "build_foundation",
            "priority": 99,
            "research_side": "supplier" if metrics["verified_suppliers"] == 0 else "buyer",
            "exploit_pct": 55,
            "thesis": "Construir ambos lados del mercado con evidencia antes de intentar escalar volumen comercial.",
            "focus_categories": focus,
            "deprioritized_categories": deprioritized,
            "reason": ", ".join(bottlenecks) or "pipeline comercial todavía insuficiente",
        }

    if (collection > 0 and collection > max(1000.0, risk_profit * 1.5)) or any("collection" in _norm(x) or "receivable" in _norm(x) for x in warnings):
        return {
            "mode": "protect_cash_quality",
            "priority": 99,
            "research_side": "balanced",
            "exploit_pct": 75,
            "thesis": "Priorizar conversión y calidad de cobro; reducir exposición incremental hasta mejorar recuperación y certeza.",
            "focus_categories": focus,
            "deprioritized_categories": deprioritized,
            "reason": "La exposición de cobranza exige proteger caja y calidad antes de expandir riesgo.",
        }

    if bottlenecks and bottlenecks[0] in {"demand_gap", "requirement_gap", "quote_comparison_gap", "conversion_gap"}:
        return {
            "mode": "repair_funnel",
            "priority": 96,
            "research_side": "buyer" if bottlenecks[0] in {"demand_gap", "requirement_gap"} else "balanced",
            "exploit_pct": 65,
            "thesis": "Reparar el cuello de botella más cercano al dinero antes de aumentar indiscriminadamente el volumen de leads.",
            "focus_categories": focus,
            "deprioritized_categories": deprioritized,
            "reason": f"Cuello de botella dominante: {bottlenecks[0]}.",
        }

    if focus and confidence >= 0.60 and score >= 60 and money_score >= 65:
        return {
            "mode": "scale_winner",
            "priority": 94,
            "research_side": "balanced",
            "exploit_pct": 82,
            "thesis": f"Concentrar capital intelectual y comercial en {focus[0]} mientras conserve superioridad económica y evidencia.",
            "focus_categories": focus,
            "deprioritized_categories": deprioritized,
            "reason": f"Categoría líder con score {score:.1f}, confianza {confidence:.0%} y money score {money_score:.1f}.",
        }

    if risk_profit > 0 and (metrics["viable_deals"] > 0 or metrics["proposals"] > 0):
        return {
            "mode": "convert_pipeline",
            "priority": 92,
            "research_side": "balanced",
            "exploit_pct": 76,
            "thesis": "Convertir beneficio esperado en operaciones reales antes de dispersar esfuerzo en expansión adicional.",
            "focus_categories": focus,
            "deprioritized_categories": deprioritized,
            "reason": f"Existe beneficio esperado ajustado por riesgo de USD {risk_profit:,.2f} pendiente de conversión.",
        }

    return {
        "mode": "balanced_growth",
        "priority": 86,
        "research_side": "balanced",
        "exploit_pct": 68,
        "thesis": "Combinar explotación disciplinada de señales prometedoras con exploración suficiente para descubrir mercados mejores.",
        "focus_categories": focus,
        "deprioritized_categories": deprioritized,
        "reason": "No existe todavía evidencia suficiente para un pivot agresivo ni un cuello de botella crítico.",
    }


def _choose_strategy(memory: Dict[str, Any], candidate: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    current = memory.get("current_strategy")
    streak = int(memory.get("strategy_streak") or 0)
    emergency = candidate["mode"] in {"build_foundation", "protect_cash_quality"}

    if not current:
        chosen = dict(candidate)
        changed = True
    elif str(current.get("mode")) == str(candidate.get("mode")):
        chosen = {**current, **candidate}
        changed = False
    elif emergency or streak >= STRATEGY_MIN_HOLD_CYCLES:
        chosen = dict(candidate)
        changed = True
    else:
        chosen = dict(current)
        chosen["candidate_mode"] = candidate.get("mode")
        chosen["candidate_reason"] = candidate.get("reason")
        chosen["hold_reason"] = f"Evitar oscilación estratégica hasta completar {STRATEGY_MIN_HOLD_CYCLES} ciclos salvo riesgo crítico."
        changed = False

    if changed:
        memory["strategy_epoch"] = int(memory.get("strategy_epoch") or 0) + 1
        memory["strategy_streak"] = 1
        chosen["epoch"] = memory["strategy_epoch"]
        chosen["started_at"] = utcnow()
        memory["strategy_history"].append({
            "ts": utcnow(),
            "epoch": memory["strategy_epoch"],
            "mode": chosen.get("mode"),
            "thesis": chosen.get("thesis"),
            "reason": chosen.get("reason"),
        })
        if len(memory["strategy_history"]) > MAX_STRATEGY_HISTORY:
            del memory["strategy_history"][:-MAX_STRATEGY_HISTORY]
    else:
        memory["strategy_streak"] = streak + 1
        chosen["epoch"] = current.get("epoch") if current else memory["strategy_epoch"]
        chosen["started_at"] = current.get("started_at") if current else utcnow()

    chosen["streak_cycles"] = memory["strategy_streak"]
    memory["current_strategy"] = chosen
    return chosen, changed


def _category_metric(state: Dict[str, Any], category: str) -> Tuple[float, int]:
    target = _norm(category)
    for item in (state.get("profit_learning", {}) or {}).get("category_rankings", []) or []:
        if _norm(item.get("category")) == target:
            return _f(item.get("learned_score"), 50.0), int(item.get("observations") or 0)
    return 50.0, 0


def _best_query_metric(state: Dict[str, Any]) -> Tuple[str | None, float, int]:
    best = ((state.get("profit_learning", {}) or {}).get("best_queries") or [None])[0]
    if not best:
        return None, 45.0, 0
    return str(best.get("query") or "") or None, _f(best.get("learned_score"), 45.0), int(best.get("leads") or 0)


def _experiment_candidates(state: Dict[str, Any], metrics: Dict[str, Any], strategy: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    focus = strategy.get("focus_categories") or []
    if focus:
        value, observations = _category_metric(state, str(focus[0]))
        candidates.append({
            "key": f"category_focus|{_norm(focus[0])}",
            "kind": "category_focus",
            "hypothesis": f"Concentrar investigación y avance comercial en {focus[0]} elevará su score aprendido sin deteriorar evidencia.",
            "metric": "learned_category_score",
            "scope": str(focus[0]),
            "baseline": round(value, 2),
            "target": round(min(100.0, value + 5.0), 2),
            "observations": observations,
            "min_observations": max(10, observations + 5),
            "min_cycles": 32,
            "max_cycles": 672,
            "reversible": True,
        })

    best_query, query_score, query_obs = _best_query_metric(state)
    if best_query:
        candidates.append({
            "key": f"query_quality|{best_query[:80]}",
            "kind": "query_quality",
            "hypothesis": "Reutilizar búsquedas con mejor evidencia histórica generará más empresas verificables por consulta que búsquedas genéricas.",
            "metric": "best_query_score",
            "scope": best_query,
            "baseline": round(query_score, 2),
            "target": round(min(100.0, query_score + 4.0), 2),
            "observations": query_obs,
            "min_observations": max(8, query_obs + 4),
            "min_cycles": 32,
            "max_cycles": 672,
            "reversible": True,
        })

    primary_case = next((x for x in state.get("deep_dive_cases", []) if x.get("status") == "attack"), None)
    if primary_case:
        suppliers = int(primary_case.get("supplier_alternative_count") or 0)
        candidates.append({
            "key": f"supplier_depth|{primary_case.get('id')}",
            "kind": "supplier_depth",
            "hypothesis": "Aumentar proveedores verificables para una oportunidad fuerte mejorará poder de negociación y comparabilidad de cotizaciones.",
            "metric": "supplier_alternative_count",
            "scope": str(primary_case.get("id") or ""),
            "baseline": suppliers,
            "target": max(4, suppliers + 1),
            "observations": int(primary_case.get("cycles") or 0),
            "min_observations": int(primary_case.get("cycles") or 0) + 3,
            "min_cycles": 16,
            "max_cycles": 384,
            "reversible": True,
        })

    if metrics["outbound_sent"] >= 2:
        candidates.append({
            "key": "relationship_followup|global",
            "kind": "relationship_followup",
            "hypothesis": "Seguimientos profesionales y limitados aumentarán la tasa de respuesta sin aumentar opt-outs ni hostigamiento.",
            "metric": "response_rate_pct",
            "scope": "global",
            "baseline": metrics["response_rate_pct"],
            "target": round(min(100.0, metrics["response_rate_pct"] + 8.0), 2),
            "observations": metrics["outbound_sent"],
            "min_observations": metrics["outbound_sent"] + 5,
            "min_cycles": 192,
            "max_cycles": 960,
            "reversible": True,
        })

    return candidates[:MAX_ACTIVE_EXPERIMENTS]


def _experiment_value(state: Dict[str, Any], metrics: Dict[str, Any], experiment: Dict[str, Any]) -> Tuple[float, int]:
    kind = experiment.get("kind")
    if kind == "category_focus":
        return _category_metric(state, str(experiment.get("scope") or ""))
    if kind == "query_quality":
        _, score, observations = _best_query_metric(state)
        return score, observations
    if kind == "supplier_depth":
        case = next((x for x in state.get("deep_dive_cases", []) if str(x.get("id")) == str(experiment.get("scope"))), {})
        return _f(case.get("supplier_alternative_count")), int(case.get("cycles") or 0)
    if kind == "relationship_followup":
        return metrics["response_rate_pct"], metrics["outbound_sent"]
    return 0.0, 0


def _experiments(memory: Dict[str, Any], state: Dict[str, Any], metrics: Dict[str, Any], strategy: Dict[str, Any]) -> List[Dict[str, Any]]:
    active = {str(x.get("key")): x for x in memory.get("active_experiments", []) if x.get("key")}
    cycle = int(memory.get("cycles") or 0)

    for candidate in _experiment_candidates(state, metrics, strategy):
        key = str(candidate["key"])
        if key not in active:
            active[key] = {
                **candidate,
                "id": f"EXP-{len(memory.get('experiment_history', [])) + len(active) + 1:05d}",
                "status": "running",
                "started_at": utcnow(),
                "started_cycle": cycle,
                "last_value": candidate["baseline"],
                "last_observations": candidate["observations"],
            }

    completed: List[str] = []
    for key, exp in active.items():
        value, observations = _experiment_value(state, metrics, exp)
        age = max(0, cycle - int(exp.get("started_cycle") or cycle))
        exp["last_value"] = round(value, 2)
        exp["last_observations"] = observations
        exp["age_cycles"] = age
        exp["updated_at"] = utcnow()

        enough = age >= int(exp.get("min_cycles") or 0) and observations >= int(exp.get("min_observations") or 0)
        if enough and value >= _f(exp.get("target")):
            exp["status"] = "validated"
            exp["result"] = "hypothesis_supported"
            completed.append(key)
        elif age >= int(exp.get("max_cycles") or 672) and observations >= int(exp.get("min_observations") or 0):
            exp["status"] = "closed"
            exp["result"] = "not_supported" if value <= _f(exp.get("baseline")) else "inconclusive"
            completed.append(key)
        else:
            exp["status"] = "running"
            exp["result"] = "collecting_evidence"

    for key in completed:
        exp = active.pop(key)
        memory["experiment_history"].append(exp)
    if len(memory["experiment_history"]) > MAX_EXPERIMENT_HISTORY:
        del memory["experiment_history"][:-MAX_EXPERIMENT_HISTORY]

    memory["active_experiments"] = list(active.values())[:MAX_ACTIVE_EXPERIMENTS]
    return memory["active_experiments"]


def _review_if_due(memory: Dict[str, Any], strategy: Dict[str, Any], metrics: Dict[str, Any], objectives: Dict[str, Any], changed: bool) -> Dict[str, Any] | None:
    cycle = int(memory.get("cycles") or 0)
    last = int(memory.get("last_review_cycle") or 0)
    if not changed and cycle - last < STRATEGY_REVIEW_CYCLES:
        return None

    monthly_progress = [x.get("progress_pct", 0) for x in objectives.get("monthly", [])]
    quarterly_progress = [x.get("progress_pct", 0) for x in objectives.get("quarterly", [])]
    review = {
        "ts": utcnow(),
        "cycle": cycle,
        "strategy_epoch": strategy.get("epoch"),
        "mode": strategy.get("mode"),
        "reason": strategy.get("reason"),
        "monthly_progress_avg_pct": round(sum(monthly_progress) / len(monthly_progress), 1) if monthly_progress else 0.0,
        "quarterly_progress_avg_pct": round(sum(quarterly_progress) / len(quarterly_progress), 1) if quarterly_progress else 0.0,
        "risk_adjusted_expected_profit_usd": metrics.get("risk_adjusted_expected_profit_usd"),
        "realized_profit_usd": metrics.get("realized_profit_usd"),
        "real_transactions": metrics.get("real_transactions"),
        "primary_category": metrics.get("primary_category"),
        "primary_category_score": metrics.get("primary_category_score"),
    }
    memory["review_history"].append(review)
    if len(memory["review_history"]) > MAX_REVIEW_HISTORY:
        del memory["review_history"][:-MAX_REVIEW_HISTORY]
    memory["last_review_cycle"] = cycle
    return review


def corporate_brain_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = _ensure_memory(state)
    memory["cycles"] = int(memory.get("cycles") or 0) + 1
    now = utcnow_dt()
    month, quarter = _period_keys(now)
    metrics = _metrics(state)
    objectives = _adaptive_objectives(memory, metrics, month, quarter)
    candidate = _strategy_candidate(state, metrics)
    strategy, changed = _choose_strategy(memory, candidate)
    experiments = _experiments(memory, state, metrics, strategy)
    review = _review_if_due(memory, strategy, metrics, objectives, changed)

    exploit_pct = max(50, min(88, int(strategy.get("exploit_pct") or 68)))
    directive = {
        "updated_at": utcnow(),
        "strategy_epoch": strategy.get("epoch"),
        "mode": strategy.get("mode"),
        "priority": strategy.get("priority"),
        "thesis": strategy.get("thesis"),
        "reason": strategy.get("reason"),
        "focus_categories": list(strategy.get("focus_categories") or [])[:3],
        "deprioritized_categories": list(strategy.get("deprioritized_categories") or [])[:5],
        "research_side": strategy.get("research_side") or "balanced",
        "exploit_pct": exploit_pct,
        "explore_pct": 100 - exploit_pct,
        "top_money_object_id": metrics.get("primary_money_deal_id"),
        "operating_priorities": [
            "cumplir objetivos mensuales y trimestrales con evidencia observable",
            "convertir beneficio esperado en beneficio realizado",
            "escalar solo categorías con evidencia y confianza suficientes",
            "mantener experimentación reversible para descubrir estrategias mejores",
            "no sacrificar controles contractuales, financieros, reputacionales ni de evidencia",
        ],
    }
    state["strategic_directive"] = directive

    report = {
        "updated_at": utcnow(),
        "mode": "long_horizon_corporate_brain",
        "cycle": memory["cycles"],
        "strategy": strategy,
        "strategy_changed": changed,
        "strategic_directive": directive,
        "objectives": objectives,
        "active_experiments": experiments,
        "latest_review": review or (memory.get("review_history") or [None])[-1],
        "metrics": metrics,
        "governance": {
            "min_strategy_hold_cycles": STRATEGY_MIN_HOLD_CYCLES,
            "review_every_cycles": STRATEGY_REVIEW_CYCLES,
            "experiment_rule": "no validar hipótesis por intuición: exigir observaciones mínimas, horizonte mínimo y métricas persistidas",
            "binding_rule": "la estrategia puede reasignar investigación y esfuerzo, nunca autorizar contratos, pagos o compromisos financieros",
        },
    }
    state["corporate_brain"] = report

    record_decision(
        state,
        engine="Corporate Brain",
        object_type="company",
        object_id="LUMEN",
        decision=str(strategy.get("mode") or "balanced_growth"),
        reason=str(strategy.get("reason") or strategy.get("thesis") or "Revisión estratégica"),
        action="score_opportunity",
        confidence=max(0.55, min(0.98, metrics.get("primary_category_confidence") or 0.60)),
        evidence_refs=[],
    )
    return report
