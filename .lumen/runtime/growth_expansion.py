from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from autonomy_governor import record_decision
from scout_connector import API_KEY, PROVIDER, DAILY_QUERY_BUDGET, MARKET, _budget, _store_results, search, utcnow


MAX_CANDIDATES = 12
MAX_HISTORY = 160
EMA_ALPHA = 0.30
QUERY_CADENCE_CYCLES = max(4, min(96, int(os.getenv("LUMEN_EXPANSION_QUERY_CADENCE", "16"))))
MIN_BUDGET_RESERVE = max(2, min(20, int(os.getenv("LUMEN_EXPANSION_BUDGET_RESERVE", "4"))))
RAW_MARKETS = os.getenv("LUMEN_EXPANSION_MARKETS", "Chile,Uruguay,Paraguay,Brasil")
EXPANSION_MARKETS = [x.strip() for x in RAW_MARKETS.split(",") if x.strip()][:10]


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _ensure(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("growth_expansion_memory", {})
    memory.setdefault("cycles", 0)
    memory.setdefault("candidate_scores", {})
    memory.setdefault("research_history", [])
    memory.setdefault("market_history", [])
    memory.setdefault("last_query_cycle", 0)
    memory.setdefault("last_query_key", None)
    return memory


def _account_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) if x.get("id")}


def _top_categories(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    strategic = state.get("strategic_directive", {}) or {}
    learning = state.get("profit_learning", {}) or {}
    war = state.get("war_room", {}) or {}
    deprioritized = {_norm(x) for x in strategic.get("deprioritized_categories", []) or []}
    rows: Dict[str, Dict[str, Any]] = {}

    for item in learning.get("category_rankings", []) or []:
        category = str(item.get("category") or "").strip()
        key = _norm(category)
        if not category or key in deprioritized:
            continue
        rows[key] = {
            "category": category,
            "learned_score": _f(item.get("learned_score"), 50.0),
            "confidence": _f(item.get("confidence")),
            "observations": int(item.get("observations") or 0),
            "strategic_focus": False,
            "money_score": 0.0,
        }

    for category in strategic.get("focus_categories", []) or []:
        key = _norm(category)
        if not key or key in deprioritized:
            continue
        row = rows.setdefault(key, {
            "category": str(category), "learned_score": 50.0, "confidence": 0.25,
            "observations": 0, "strategic_focus": False, "money_score": 0.0,
        })
        row["strategic_focus"] = True

    for item in war.get("top_money_opportunities", []) or []:
        category = str(item.get("category") or "").strip()
        key = _norm(category)
        if not category or key in deprioritized:
            continue
        row = rows.setdefault(key, {
            "category": category, "learned_score": 50.0, "confidence": 0.25,
            "observations": 0, "strategic_focus": False, "money_score": 0.0,
        })
        row["money_score"] = max(_f(row.get("money_score")), _f(item.get("money_score")))

    values = list(rows.values())
    for row in values:
        row["category_strength"] = round(
            _f(row["learned_score"]) * 0.45
            + _f(row["confidence"]) * 100.0 * 0.20
            + _f(row["money_score"], 50.0) * 0.25
            + (10.0 if row.get("strategic_focus") else 0.0),
            2,
        )
    values.sort(key=lambda x: (x["category_strength"], x["observations"]), reverse=True)
    return values[:5]


def _readiness(state: Dict[str, Any], categories: List[Dict[str, Any]]) -> Dict[str, Any]:
    accounts = state.get("candidate_accounts", [])
    verified_buyers = sum(1 for x in accounts if x.get("type") == "buyer" and x.get("verified_company"))
    verified_suppliers = sum(1 for x in accounts if x.get("type") == "supplier" and x.get("verified_company"))
    demand_buyers = sum(1 for x in accounts if x.get("type") == "buyer" and x.get("verified_company") and x.get("demand_signal"))
    opportunities = len(state.get("market_opportunities", []))
    strategy = str((state.get("strategic_directive", {}) or {}).get("mode") or "")
    cfo = state.get("cfo", {}) or {}
    snapshot = cfo.get("financial_snapshot", {}) or {}
    risk_profit = _f(snapshot.get("risk_adjusted_expected_profit_usd"))
    top = categories[0] if categories else {}
    category_ready = bool(top) and _f(top.get("confidence")) >= 0.35 and _f(top.get("learned_score"), 50.0) >= 50

    blockers: List[str] = []
    if strategy in {"build_foundation", "protect_cash_quality"}:
        blockers.append(f"strategy_{strategy}")
    if verified_buyers < 1:
        blockers.append("home_market_buyer_base_too_thin")
    if verified_suppliers < 1:
        blockers.append("home_market_supplier_base_too_thin")
    if opportunities < 1 and demand_buyers < 1:
        blockers.append("insufficient_home_market_evidence")
    if not category_ready:
        blockers.append("no_category_with_sufficient_learning")

    score = min(100.0, (
        min(30.0, verified_buyers * 7.5)
        + min(25.0, verified_suppliers * 6.25)
        + min(20.0, opportunities * 5.0)
        + min(10.0, demand_buyers * 5.0)
        + min(15.0, max(0.0, _f(top.get("category_strength")) - 45.0) * 0.6)
    ))
    if risk_profit > 0:
        score = min(100.0, score + 5.0)

    return {
        "score": round(score, 2),
        "ready": not blockers and score >= 55.0,
        "blockers": blockers,
        "verified_buyers": verified_buyers,
        "verified_suppliers": verified_suppliers,
        "buyers_with_demand": demand_buyers,
        "opportunities": opportunities,
        "risk_adjusted_expected_profit_usd": round(risk_profit, 2),
        "corporate_strategy": strategy,
    }


def _observed_expansion_stats(state: Dict[str, Any]) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    leads = [x for x in state.get("research_leads", []) if x.get("growth_hypothesis_key")]
    accounts = state.get("candidate_accounts", [])
    by_source = {str(x.get("source_lead_id")): x for x in accounts if x.get("source_lead_id")}
    groups: Dict[Tuple[str, str, str], Dict[str, Any]] = defaultdict(lambda: {
        "leads": 0, "verified": 0, "demand": 0, "contactable": 0,
    })
    for lead in leads:
        key = (
            str(lead.get("growth_kind") or ""),
            str(lead.get("growth_market") or lead.get("market") or ""),
            str(lead.get("category") or ""),
        )
        g = groups[key]
        g["leads"] += 1
        account = by_source.get(str(lead.get("id") or ""), {})
        if account.get("verified_company"):
            g["verified"] += 1
        if account.get("demand_signal"):
            g["demand"] += 1
        if account.get("commercial_channel_verified"):
            g["contactable"] += 1
    return groups


def _candidate_score(kind: str, category: Dict[str, Any], market: str, observed: Dict[str, Any], prior_ema: float | None) -> Tuple[float, float]:
    strength = _f(category.get("category_strength"), 50.0)
    leads = int(observed.get("leads") or 0)
    verified = int(observed.get("verified") or 0)
    demand = int(observed.get("demand") or 0)
    contactable = int(observed.get("contactable") or 0)
    confidence = min(1.0, (leads + verified * 2 + demand * 3 + contactable * 2) / 18.0)
    observed_score = 50.0
    if leads:
        verification_rate = verified / leads * 100.0
        demand_rate = demand / max(1, verified) * 100.0
        contact_rate = contactable / max(1, verified) * 100.0
        observed_score = verification_rate * 0.45 + demand_rate * 0.35 + contact_rate * 0.20

    kind_bonus = {
        "lookalike_buyer": 10.0,
        "market_entry_buyer": 2.0,
        "international_supplier": 5.0,
    }.get(kind, 0.0)
    cross_border_penalty = 0.0 if market == MARKET else 8.0
    base = strength * 0.72 + 50.0 * 0.28 + kind_bonus - cross_border_penalty
    evidence_adjusted = base * (1.0 - confidence) + observed_score * confidence
    previous = evidence_adjusted if prior_ema is None else prior_ema
    ema = previous * (1.0 - EMA_ALPHA) + evidence_adjusted * EMA_ALPHA
    return round(max(0.0, min(100.0, ema)), 2), round(confidence, 2)


def _build_candidates(state: Dict[str, Any], memory: Dict[str, Any], categories: List[Dict[str, Any]], readiness: Dict[str, Any]) -> List[Dict[str, Any]]:
    observed = _observed_expansion_stats(state)
    scores = memory["candidate_scores"]
    candidates: List[Dict[str, Any]] = []

    for category in categories[:3]:
        cat = str(category.get("category") or "").strip()
        if not cat:
            continue

        specs = [("lookalike_buyer", MARKET)]
        if readiness.get("ready"):
            for market in EXPANSION_MARKETS:
                specs.append(("market_entry_buyer", market))
                specs.append(("international_supplier", market))

        for kind, market in specs:
            key = f"{kind}|{_norm(market)}|{_norm(cat)}"
            obs = observed.get((kind, market, cat), {})
            prev = scores.get(key, {})
            score, confidence = _candidate_score(kind, category, market, obs, _f(prev.get("ema")) if prev else None)
            scores[key] = {
                "ema": score,
                "confidence": confidence,
                "samples": int(obs.get("leads") or 0),
                "updated_at": utcnow(),
            }
            candidates.append({
                "key": key,
                "kind": kind,
                "market": market,
                "category": cat,
                "score": score,
                "confidence": confidence,
                "observed": obs,
                "category_strength": category.get("category_strength"),
                "strategic_focus": bool(category.get("strategic_focus")),
                "status": "explore" if readiness.get("ready") or kind == "lookalike_buyer" else "blocked",
            })

    candidates.sort(key=lambda x: (x["status"] == "explore", x["score"], x["confidence"]), reverse=True)
    return candidates[:MAX_CANDIDATES]


def _query_for(candidate: Dict[str, Any]) -> Tuple[str, str]:
    category = str(candidate.get("category") or "")
    market = str(candidate.get("market") or MARKET)
    kind = str(candidate.get("kind") or "")
    if kind == "international_supplier":
        if _norm(market) == "brasil":
            return f'"{category}" fabricante distribuidor fornecedor Brasil industrial', "supplier"
        return f'"{category}" fabricante distribuidor proveedor {market} industrial', "supplier"
    if kind == "market_entry_buyer":
        if _norm(market) == "brasil":
            return f'empresa indústria planta manutenção compras "{category}" Brasil -fornecedor -distribuidor', "buyer"
        return f'empresa industria planta mantenimiento compras "{category}" {market} -proveedor -distribuidor', "buyer"
    return f'empresa industria planta mantenimiento compras "{category}" {MARKET} -proveedor -distribuidor', "buyer"


def _select_candidate(candidates: List[Dict[str, Any]], memory: Dict[str, Any]) -> Dict[str, Any] | None:
    explore = [x for x in candidates if x.get("status") == "explore"]
    if not explore:
        return None
    last = str(memory.get("last_query_key") or "")
    alternatives = [x for x in explore if str(x.get("key")) != last]
    return (alternatives or explore)[0]


def _run_research(state: Dict[str, Any], memory: Dict[str, Any], candidate: Dict[str, Any] | None) -> Dict[str, Any]:
    stats = {"executed": False, "query": None, "kind": None, "market": None, "category": None, "new_leads": 0, "errors": 0, "reason": None}
    if not candidate:
        stats["reason"] = "no_eligible_expansion_candidate"
        return stats
    if not (PROVIDER and API_KEY):
        stats["reason"] = "scout_not_configured"
        return stats

    cycle = int(memory.get("cycles") or 0)
    if cycle - int(memory.get("last_query_cycle") or 0) < QUERY_CADENCE_CYCLES:
        stats["reason"] = "expansion_query_cadence"
        return stats

    budget = _budget(state)
    remaining = int(budget.get("queries_remaining") or 0)
    if remaining <= MIN_BUDGET_RESERVE:
        stats["reason"] = "reserved_scout_budget"
        return stats

    query, lead_type = _query_for(candidate)
    stats.update({"query": query, "kind": candidate.get("kind"), "market": candidate.get("market"), "category": candidate.get("category")})
    try:
        before = len(state.setdefault("research_leads", []))
        budget["queries_used"] = int(budget.get("queries_used") or 0) + 1
        results = search(query)
        created = _store_results(state, query, lead_type, str(candidate.get("category") or ""), results)
        new_items = state["research_leads"][before:]
        for lead in new_items:
            lead["market"] = candidate.get("market") or MARKET
            lead["growth_market"] = candidate.get("market") or MARKET
            lead["growth_kind"] = candidate.get("kind")
            lead["growth_hypothesis_key"] = candidate.get("key")
            lead["growth_research_only"] = True
        budget["queries_remaining"] = max(0, DAILY_QUERY_BUDGET - int(budget.get("queries_used") or 0))
        budget["updated_at"] = utcnow()
        memory["last_query_cycle"] = cycle
        memory["last_query_key"] = candidate.get("key")
        entry = {
            "ts": utcnow(), "cycle": cycle, "key": candidate.get("key"), "query": query,
            "market": candidate.get("market"), "category": candidate.get("category"),
            "kind": candidate.get("kind"), "new_leads": created,
        }
        memory["research_history"].append(entry)
        if len(memory["research_history"]) > MAX_HISTORY:
            del memory["research_history"][:-MAX_HISTORY]
        stats["executed"] = True
        stats["new_leads"] = created
        stats["reason"] = "evidence_first_expansion_research"
    except Exception as exc:
        stats["errors"] = 1
        stats["reason"] = f"research_error:{str(exc)[:140]}"
    return stats


def _cross_sell_investigations(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    deals = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}
    account_by_name = {
        _norm(x.get("company_name") or x.get("name_hint")): x
        for x in state.get("candidate_accounts", [])
        if x.get("type") == "buyer" and x.get("verified_company")
    }
    plans: List[Dict[str, Any]] = []
    real_statuses = {"closed", "settled", "paid", "completed", "delivered", "invoiced"}
    for txn in state.get("transactions", []):
        if str(txn.get("status") or "") not in real_statuses:
            continue
        deal = deals.get(str(txn.get("deal_id") or ""), {})
        buyer_name = str(deal.get("buyer") or "")
        account = account_by_name.get(_norm(buyer_name), {})
        domain = str(account.get("domain") or "").strip()
        if not domain:
            continue
        plans.append({
            "deal_id": deal.get("id"),
            "buyer": buyer_name,
            "domain": domain,
            "base_category": deal.get("need") or deal.get("category"),
            "query": f'site:{domain} (compras OR abastecimiento OR procurement OR proveedores OR licitación OR licitacion OR cotización OR cotizacion)',
            "rule": "buscar demanda adyacente en fuente oficial; no asumir categoría ni necesidad hasta clasificar evidencia",
            "status": "research_candidate",
        })
    return plans[:6]


def _sourcing_spreads(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_deal: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for offer in state.get("offers", []):
        if offer.get("source") == "demo/simulación":
            continue
        if not offer.get("deal_id") or _f(offer.get("amount")) <= 0:
            continue
        by_deal[str(offer["deal_id"])].append(offer)

    spreads: List[Dict[str, Any]] = []
    for deal_id, offers in by_deal.items():
        currencies = {_norm(x.get("currency")) for x in offers if x.get("currency")}
        if len(offers) < 2 or len(currencies) != 1:
            continue
        ordered = sorted(offers, key=lambda x: _f(x.get("amount")))
        low = _f(ordered[0].get("amount")); high = _f(ordered[-1].get("amount"))
        if high <= 0:
            continue
        spread_pct = (high - low) / high * 100.0
        spreads.append({
            "deal_id": deal_id,
            "currency": ordered[0].get("currency"),
            "best_offer_id": ordered[0].get("id"),
            "high_offer_id": ordered[-1].get("id"),
            "best_amount": round(low, 2),
            "high_amount": round(high, 2),
            "spread_pct": round(spread_pct, 2),
            "action": "investigate_sourcing_advantage" if spread_pct >= 5.0 else "normal_competition",
            "rule": "comparar solo ofertas reales en la misma moneda; no llamar arbitraje a una diferencia sin validar flete, impuestos, plazo, términos y equivalencia técnica",
        })
    spreads.sort(key=lambda x: x["spread_pct"], reverse=True)
    return spreads[:10]


def growth_expansion_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = _ensure(state)
    memory["cycles"] = int(memory.get("cycles") or 0) + 1
    categories = _top_categories(state)
    readiness = _readiness(state, categories)
    candidates = _build_candidates(state, memory, categories, readiness)
    selected = _select_candidate(candidates, memory)
    research = _run_research(state, memory, selected)
    cross_sell = _cross_sell_investigations(state)
    sourcing_spreads = _sourcing_spreads(state)

    primary = selected or (candidates[0] if candidates else None)
    directive = {
        "updated_at": utcnow(),
        "ready": readiness.get("ready"),
        "readiness_score": readiness.get("score"),
        "blockers": readiness.get("blockers", []),
        "primary_kind": primary.get("kind") if primary else None,
        "primary_market": primary.get("market") if primary else None,
        "primary_category": primary.get("category") if primary else None,
        "primary_score": primary.get("score") if primary else None,
        "recommended_action": (
            "expand_with_public_evidence" if readiness.get("ready") and primary
            else "strengthen_home_market_before_cross_border_expansion"
        ),
    }
    state["growth_directive"] = directive

    report = {
        "updated_at": utcnow(),
        "mode": "evidence_gated_growth_and_expansion_brain",
        "cycle": memory["cycles"],
        "home_market": MARKET,
        "configured_expansion_markets": EXPANSION_MARKETS,
        "readiness": readiness,
        "top_categories": categories,
        "expansion_candidates": candidates,
        "primary_expansion": primary,
        "research": research,
        "cross_sell_investigations": cross_sell,
        "sourcing_spread_candidates": sourcing_spreads,
        "governance": {
            "query_cadence_cycles": QUERY_CADENCE_CYCLES,
            "budget_reserve_queries": MIN_BUDGET_RESERVE,
            "first_step": "public_research_only",
            "new_market_rule": "un lead internacional debe pasar por la misma verificación de empresa, demanda y contacto antes de outreach",
            "cross_sell_rule": "una relación previa habilita investigación, no permite inventar necesidad adyacente",
            "arbitrage_rule": "no afirmar ventaja económica internacional sin normalizar moneda, flete, impuestos, plazo, términos y equivalencia técnica",
            "binding_rule": "la expansión puede reasignar investigación y preparar acciones; contratos, pagos y compromisos siguen requiriendo aprobación humana",
        },
    }
    state["growth_expansion"] = report

    if primary:
        record_decision(
            state,
            engine="Growth & Expansion Brain",
            object_type="market_expansion",
            object_id=str(primary.get("key") or "growth"),
            decision=str(primary.get("kind") or "explore_growth"),
            reason=(
                f"Mercado {primary.get('market')}, categoría {primary.get('category')}, score de expansión {primary.get('score')}; "
                f"readiness {readiness.get('score')}."
            ),
            action="research_public",
            confidence=max(0.45, min(0.95, _f(primary.get("confidence"), 0.55))),
            evidence_refs=[],
        )
    return report
