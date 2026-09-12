from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

EMA_ALPHA = 0.35
MAX_CATEGORY_MEMORY = 100
MAX_QUERY_MEMORY = 80


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(num: float, den: float) -> float:
    return 0.0 if den <= 0 else min(100.0, max(0.0, num / den * 100.0))


def _ensure(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("profit_learning_memory", {})
    memory.setdefault("category_scores", {})
    memory.setdefault("query_scores", {})
    memory.setdefault("cycles", 0)
    memory.setdefault("last_focus_category", None)
    memory.setdefault("focus_streak", 0)
    return memory


def _category_buckets(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}

    def bucket(category: Any) -> Dict[str, Any]:
        key = _norm(category) or "sin categoría"
        if key not in buckets:
            buckets[key] = {
                "category": str(category or "Sin categoría").strip() or "Sin categoría",
                "leads": 0,
                "tier_a": 0,
                "tier_d": 0,
                "accounts": 0,
                "verified_accounts": 0,
                "verified_buyers": 0,
                "verified_suppliers": 0,
                "buyers_with_demand": 0,
                "commercial_channels": 0,
                "market_opportunities": 0,
                "opportunity_score_sum": 0.0,
                "requirements_ready": 0,
                "legacy_deals": 0,
                "viable_deals": 0,
                "close_ready": 0,
                "expected_value_usd": 0.0,
                "company_profit_usd": 0.0,
                "transactions": 0,
                "transaction_profit_usd": 0.0,
            }
        return buckets[key]

    for lead in state.get("research_leads", []):
        b = bucket(lead.get("category"))
        b["leads"] += 1
        tier = str(lead.get("tier") or "")
        if tier == "A": b["tier_a"] += 1
        if tier == "D": b["tier_d"] += 1

    for account in state.get("candidate_accounts", []):
        b = bucket(account.get("category"))
        b["accounts"] += 1
        if account.get("verified_company"):
            b["verified_accounts"] += 1
            if account.get("type") == "buyer":
                b["verified_buyers"] += 1
                if account.get("demand_signal"):
                    b["buyers_with_demand"] += 1
            elif account.get("type") == "supplier":
                b["verified_suppliers"] += 1
        if account.get("commercial_channel_verified"):
            b["commercial_channels"] += 1

    for opp in state.get("market_opportunities", []):
        b = bucket(opp.get("category"))
        b["market_opportunities"] += 1
        b["opportunity_score_sum"] += _f(opp.get("score"))

    for case in state.get("interlocution_cases", []):
        b = bucket(case.get("category"))
        if case.get("supplier_rfq_ready"):
            b["requirements_ready"] += 1

    deal_by_id: Dict[str, Dict[str, Any]] = {}
    for deal in state.get("deals", []):
        category = deal.get("need") or deal.get("category")
        b = bucket(category)
        b["legacy_deals"] += 1
        b["expected_value_usd"] += _f(deal.get("expected_value"))
        b["company_profit_usd"] += max(0.0, _f(deal.get("company_profit")))
        if deal.get("economics", {}).get("viable"):
            b["viable_deals"] += 1
        if deal.get("stage") in {"listo para cerrar", "autorizado para cierre", "cerrado", "cerrado (simulación)"}:
            b["close_ready"] += 1
        if deal.get("id"):
            deal_by_id[str(deal["id"])] = deal

    for txn in state.get("transactions", []):
        deal = deal_by_id.get(str(txn.get("deal_id") or ""), {})
        category = deal.get("need") or deal.get("category") or "sin categoría"
        b = bucket(category)
        b["transactions"] += 1
        b["transaction_profit_usd"] += max(0.0, _f(txn.get("company_profit")))

    return buckets


def _score_category(raw: Dict[str, Any]) -> Dict[str, Any]:
    leads = int(raw["leads"])
    accounts = int(raw["accounts"])
    verified = int(raw["verified_accounts"])
    buyers = int(raw["verified_buyers"])
    opps = int(raw["market_opportunities"])
    deals = int(raw["legacy_deals"])

    evidence_yield = _pct(raw["tier_a"], leads)
    verification_yield = _pct(verified, accounts)
    demand_yield = _pct(raw["buyers_with_demand"], buyers)
    contact_yield = _pct(raw["commercial_channels"], verified)
    opp_quality = _pct(raw["opportunity_score_sum"], max(1, opps) * 100.0)
    requirement_yield = _pct(raw["requirements_ready"], opps)
    viable_yield = _pct(raw["viable_deals"], deals)
    close_yield = _pct(raw["close_ready"], deals)

    # Economics are deliberately capped so a single large simulated deal cannot dominate learning.
    economics_signal = min(100.0, raw["company_profit_usd"] / 50.0)
    transaction_signal = min(100.0, raw["transaction_profit_usd"] / 50.0)

    raw_score = (
        evidence_yield * 0.16
        + verification_yield * 0.14
        + demand_yield * 0.16
        + contact_yield * 0.08
        + opp_quality * 0.12
        + requirement_yield * 0.10
        + viable_yield * 0.08
        + close_yield * 0.08
        + economics_signal * 0.05
        + transaction_signal * 0.03
    )

    observations = leads + accounts * 2 + opps * 3 + deals * 4 + int(raw["transactions"]) * 6
    confidence = min(1.0, observations / 35.0)
    # Shrink sparse categories toward neutral rather than overfitting early noise.
    score = 50.0 * (1.0 - confidence) + raw_score * confidence

    return {
        **raw,
        "score_raw": round(raw_score, 2),
        "score": round(score, 2),
        "confidence": round(confidence, 2),
        "observations": observations,
        "evidence_yield_pct": round(evidence_yield, 1),
        "verification_yield_pct": round(verification_yield, 1),
        "demand_yield_pct": round(demand_yield, 1),
        "contact_yield_pct": round(contact_yield, 1),
        "opportunity_quality_pct": round(opp_quality, 1),
        "requirement_ready_pct": round(requirement_yield, 1),
        "viable_deal_pct": round(viable_yield, 1),
        "close_ready_pct": round(close_yield, 1),
    }


def _query_rankings(state: Dict[str, Any], memory: Dict[str, Any]) -> List[Dict[str, Any]]:
    leads = state.get("research_leads", [])
    accounts = state.get("candidate_accounts", [])
    verified_source_leads = {
        str(x.get("source_lead_id")) for x in accounts
        if x.get("verified_company") and x.get("source_lead_id")
    }
    groups: Dict[str, Dict[str, Any]] = {}
    for lead in leads:
        query = str(lead.get("query") or "").strip()
        if not query:
            continue
        g = groups.setdefault(query, {"query": query, "leads": 0, "tier_a": 0, "verified_companies": 0})
        g["leads"] += 1
        if lead.get("tier") == "A":
            g["tier_a"] += 1
        if str(lead.get("id") or "") in verified_source_leads:
            g["verified_companies"] += 1

    old = memory["query_scores"]
    rankings: List[Dict[str, Any]] = []
    for query, g in groups.items():
        tier_a_rate = _pct(g["tier_a"], g["leads"])
        verified_rate = _pct(g["verified_companies"], g["leads"])
        confidence = min(1.0, g["leads"] / 10.0)
        score = (tier_a_rate * 0.55 + verified_rate * 0.45) * confidence + 45.0 * (1.0 - confidence)
        previous = _f(old.get(query, {}).get("ema"), score)
        ema = previous * (1.0 - EMA_ALPHA) + score * EMA_ALPHA
        old[query] = {"ema": round(ema, 2), "samples": g["leads"], "updated_at": utcnow()}
        rankings.append({
            **g,
            "tier_a_rate_pct": round(tier_a_rate, 1),
            "verified_company_rate_pct": round(verified_rate, 1),
            "confidence": round(confidence, 2),
            "score": round(score, 2),
            "learned_score": round(ema, 2),
        })

    rankings.sort(key=lambda x: (x["learned_score"], x["confidence"]), reverse=True)
    if len(old) > MAX_QUERY_MEMORY:
        keep = {x["query"] for x in rankings[:MAX_QUERY_MEMORY]}
        memory["query_scores"] = {k: v for k, v in old.items() if k in keep}
    return rankings


def learning_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = _ensure(state)
    memory["cycles"] = int(memory.get("cycles") or 0) + 1
    raw_buckets = _category_buckets(state)
    previous = memory["category_scores"]
    rankings: List[Dict[str, Any]] = []

    for key, raw in raw_buckets.items():
        scored = _score_category(raw)
        prev = _f(previous.get(key, {}).get("ema"), scored["score"])
        ema = prev * (1.0 - EMA_ALPHA) + scored["score"] * EMA_ALPHA
        scored["learned_score"] = round(ema, 2)
        previous[key] = {
            "category": scored["category"],
            "ema": round(ema, 2),
            "observations": scored["observations"],
            "confidence": scored["confidence"],
            "updated_at": utcnow(),
        }
        rankings.append(scored)

    rankings.sort(key=lambda x: (x["learned_score"], x["confidence"], x["observations"]), reverse=True)
    query_rankings = _query_rankings(state, memory)

    if len(previous) > MAX_CATEGORY_MEMORY:
        keep = {_norm(x["category"]) for x in rankings[:MAX_CATEGORY_MEMORY]}
        memory["category_scores"] = {k: v for k, v in previous.items() if k in keep}

    strong = [x for x in rankings if x["confidence"] >= 0.35 and x["observations"] >= 8]
    focus = (strong or rankings)[:3]
    deprioritized = [
        x for x in rankings
        if x["confidence"] >= 0.55 and x["observations"] >= 15 and x["learned_score"] < 35
    ][-5:]

    if focus and focus[0]["confidence"] >= 0.70:
        second = focus[1]["learned_score"] if len(focus) > 1 else 50.0
        spread = focus[0]["learned_score"] - second
        exploit_pct = 80 if spread >= 8 else 75
    elif focus and focus[0]["confidence"] >= 0.40:
        exploit_pct = 70
    else:
        exploit_pct = 60
    explore_pct = 100 - exploit_pct

    primary_category = focus[0]["category"] if focus else None
    if memory.get("last_focus_category") == primary_category:
        memory["focus_streak"] = int(memory.get("focus_streak") or 0) + 1
    else:
        memory["last_focus_category"] = primary_category
        memory["focus_streak"] = 1

    report = {
        "updated_at": utcnow(),
        "mode": "self_learning_profit_engine",
        "cycles": memory["cycles"],
        "primary_category": primary_category,
        "focus_streak_cycles": memory["focus_streak"],
        "exploit_pct": exploit_pct,
        "explore_pct": explore_pct,
        "focus_categories": focus,
        "deprioritized_categories": deprioritized,
        "category_rankings": rankings[:20],
        "query_rankings": query_rankings[:20],
        "best_queries": [x for x in query_rankings if x["confidence"] >= 0.30][:5],
        "learning_rule": "aumentar atención donde evidencia, verificación, demanda, avance comercial y economía mejoran de forma repetida; conservar exploración para evitar encierro prematuro",
    }
    state["profit_learning"] = report

    record_decision(
        state,
        engine="Self-Learning Profit Engine",
        object_type="company",
        object_id="LUMEN",
        decision="focus_category" if primary_category else "explore_market",
        reason=(
            f"Categoría líder aprendida: {primary_category}; explotación {exploit_pct}% / exploración {explore_pct}%."
            if primary_category else "Todavía no hay evidencia suficiente para concentrar el mercado."
        ),
        action="score_opportunity",
        confidence=float(focus[0]["confidence"] if focus else 0.35),
        evidence_refs=[],
    )
    return report
