from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

MAX_VENTURES = 24
MAX_HISTORY = 160
MIN_OBSERVATIONS_FOR_KILL = 12
MIN_CONFIDENCE_FOR_PILOT = 0.55


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


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _ensure(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("venture_builder_memory", {})
    memory.setdefault("cycle", 0)
    memory.setdefault("ventures", {})
    memory.setdefault("history", [])
    memory.setdefault("killed", [])
    return memory


def _category_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    learning = state.get("profit_learning", {}) or {}
    rows = learning.get("category_rankings", []) or learning.get("rankings", []) or []
    if rows:
        return [dict(x) for x in rows if isinstance(x, dict)]
    memory = (state.get("profit_learning_memory", {}) or {}).get("category_scores", {}) or {}
    out = []
    for raw in memory.values():
        if isinstance(raw, dict):
            out.append(dict(raw))
    return out


def _network_by_category(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    profiles = state.get("supplier_network_profiles", []) or []
    for profile in profiles:
        category = str(profile.get("category") or "").strip()
        if not category:
            continue
        key = _norm(category)
        rec = rows.setdefault(key, {"category": category, "profiles": 0, "strong": 0, "contactable": 0, "score_sum": 0.0})
        rec["profiles"] += 1
        score = _f(profile.get("network_score"), _f(profile.get("score")))
        rec["score_sum"] += score
        if score >= 68:
            rec["strong"] += 1
        if profile.get("contact_verified") or profile.get("commercial_channel_verified"):
            rec["contactable"] += 1
    for rec in rows.values():
        rec["avg_score"] = round(rec["score_sum"] / max(1, rec["profiles"]), 1)
    return rows


def _buyer_demand_by_category(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for account in state.get("candidate_accounts", []) or []:
        if account.get("type") != "buyer" or not account.get("verified_company"):
            continue
        category = str(account.get("category") or "").strip()
        if not category:
            continue
        key = _norm(category)
        rec = rows.setdefault(key, {"category": category, "verified_buyers": 0, "demand_buyers": 0, "contactable": 0})
        rec["verified_buyers"] += 1
        if account.get("demand_signal"):
            rec["demand_buyers"] += 1
        if account.get("verified_contact") or account.get("commercial_channel_verified"):
            rec["contactable"] += 1
    return rows


def _economics_by_category(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    cfo_rankings = (state.get("cfo", {}) or {}).get("deal_financial_rankings", []) or []
    deals = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}
    for row in cfo_rankings:
        deal = deals.get(str(row.get("deal_id") or ""), {})
        category = str(row.get("category") or deal.get("category") or deal.get("need") or "").strip()
        if not category:
            continue
        key = _norm(category)
        rec = rows.setdefault(key, {"category": category, "deals": 0, "money_score_sum": 0.0, "risk_profit": 0.0, "safe_sum": 0.0})
        rec["deals"] += 1
        rec["money_score_sum"] += _f(row.get("money_score"))
        rec["risk_profit"] += max(0.0, _f(row.get("risk_adjusted_expected_profit_usd")))
        rec["safe_sum"] += _f(row.get("safe_close_score"), 75.0)
    for rec in rows.values():
        rec["avg_money_score"] = round(rec["money_score_sum"] / max(1, rec["deals"]), 1)
        rec["avg_safe_close"] = round(rec["safe_sum"] / max(1, rec["deals"]), 1)
    return rows


def _real_venture_transactions(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    real_statuses = {"closed", "settled", "paid", "completed", "delivered", "invoiced"}
    deals = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}
    rows: Dict[str, Dict[str, Any]] = {}
    for txn in state.get("transactions", []) or []:
        if str(txn.get("status") or "") not in real_statuses:
            continue
        deal = deals.get(str(txn.get("deal_id") or ""), {})
        venture_id = str(deal.get("venture_id") or txn.get("venture_id") or "")
        if not venture_id:
            continue
        rec = rows.setdefault(venture_id, {"transactions": 0, "profit_usd": 0.0})
        rec["transactions"] += 1
        rec["profit_usd"] += max(0.0, _f(txn.get("company_profit")))
    return rows


def _growth_hypotheses(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    growth = state.get("growth_expansion", {}) or {}
    out: List[Dict[str, Any]] = []
    for raw in growth.get("expansion_candidates", []) or []:
        category = str(raw.get("category") or "").strip()
        market = str(raw.get("market") or "").strip()
        kind = str(raw.get("kind") or "")
        score = _f(raw.get("score"))
        if not category or not market or score < 55:
            continue
        if kind not in {"market_entry_buyer", "international_supplier", "lookalike_buyer"}:
            continue
        out.append({
            "key": f"market_cell|{_norm(category)}|{_norm(market)}",
            "type": "market_cell",
            "category": category,
            "market": market,
            "source": "growth_expansion",
            "source_score": score,
            "thesis": f"Construir una línea B2B de {category} en {market} si demanda, oferta y economía quedan validadas.",
        })
    return out


def _core_hypotheses(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    categories = _category_rows(state)
    network = _network_by_category(state)
    demand = _buyer_demand_by_category(state)
    economics = _economics_by_category(state)
    out: List[Dict[str, Any]] = []
    seen = set()

    for row in categories:
        category = str(row.get("category") or "").strip()
        if not category:
            continue
        key = _norm(category)
        learned = _f(row.get("learned_score"), _f(row.get("score"), _f(row.get("ema"), 50.0)))
        confidence = _f(row.get("confidence"))
        observations = _i(row.get("observations"))
        d = demand.get(key, {})
        n = network.get(key, {})
        e = economics.get(key, {})

        demand_count = _i(d.get("demand_buyers"))
        supply_depth = _i(n.get("profiles"))
        strong_supply = _i(n.get("strong"))
        money = _f(e.get("avg_money_score"))

        if demand_count >= 1 and supply_depth < 3:
            venture_key = f"supply_gap|{key}"
            if venture_key not in seen:
                out.append({
                    "key": venture_key,
                    "type": "supply_gap_vertical",
                    "category": category,
                    "market": "home",
                    "source": "demand_plus_network_gap",
                    "source_score": min(100.0, 45 + demand_count * 12 + learned * 0.25),
                    "thesis": f"Existe demanda verificada en {category} pero falta profundidad de oferta; construir una vertical especializada puede capturar margen y velocidad.",
                    "observations_hint": observations,
                    "learning_confidence": confidence,
                })
                seen.add(venture_key)

        if strong_supply >= 2 and learned >= 58 and confidence >= 0.35:
            venture_key = f"distribution|{key}"
            if venture_key not in seen:
                out.append({
                    "key": venture_key,
                    "type": "distribution_vertical",
                    "category": category,
                    "market": "home",
                    "source": "supplier_strength",
                    "source_score": min(100.0, learned * 0.65 + _f(n.get("avg_score")) * 0.35),
                    "thesis": f"LUMEN ya tiene fortaleza de abastecimiento en {category}; validar si puede convertirse en una línea recurrente de distribución B2B.",
                    "observations_hint": observations,
                    "learning_confidence": confidence,
                })
                seen.add(venture_key)

        if money >= 60 and learned >= 55 and observations >= 8:
            venture_key = f"repeatable_model|{key}"
            if venture_key not in seen:
                out.append({
                    "key": venture_key,
                    "type": "repeatable_model",
                    "category": category,
                    "market": "home",
                    "source": "economics_plus_learning",
                    "source_score": min(100.0, money * 0.55 + learned * 0.45),
                    "thesis": f"Los economics y el aprendizaje de {category} justifican validar un modelo comercial repetible, no solo deals aislados.",
                    "observations_hint": observations,
                    "learning_confidence": confidence,
                })
                seen.add(venture_key)

    return out


def _evidence_for(state: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    category = _norm(raw.get("category"))
    market = _norm(raw.get("market"))
    buyers = [x for x in state.get("candidate_accounts", []) if x.get("type") == "buyer" and x.get("verified_company") and _norm(x.get("category")) == category]
    suppliers = [x for x in state.get("candidate_accounts", []) if x.get("type") == "supplier" and x.get("verified_company") and _norm(x.get("category")) == category]
    demand = [x for x in buyers if x.get("demand_signal")]
    contact_buyers = [x for x in buyers if x.get("verified_contact") or x.get("commercial_channel_verified")]
    contact_suppliers = [x for x in suppliers if x.get("verified_contact") or x.get("commercial_channel_verified")]
    leads = [x for x in state.get("research_leads", []) if _norm(x.get("category")) == category]
    venture_leads = [x for x in leads if str(x.get("venture_id") or "") == str(raw.get("id") or "")]
    offers = []
    deal_ids = set()
    for deal in state.get("deals", []) or []:
        if _norm(deal.get("category") or deal.get("need")) == category:
            deal_ids.add(str(deal.get("id") or ""))
    offers = [x for x in state.get("offers", []) if str(x.get("deal_id") or "") in deal_ids and x.get("source") != "demo/simulación"]
    market_accounts = [x for x in buyers + suppliers if market in {"", "home"} or _norm(x.get("market") or x.get("growth_market")) == market]
    return {
        "research_leads": len(leads),
        "venture_research_leads": len(venture_leads),
        "verified_buyers": len(buyers),
        "buyers_with_demand": len(demand),
        "contactable_buyers": len(contact_buyers),
        "verified_suppliers": len(suppliers),
        "contactable_suppliers": len(contact_suppliers),
        "real_offers": len(offers),
        "market_accounts": len(market_accounts),
    }


def _score_venture(state: Dict[str, Any], raw: Dict[str, Any], old: Dict[str, Any] | None) -> Dict[str, Any]:
    venture = dict(old or {})
    venture.update({k: v for k, v in raw.items() if v is not None})
    venture_id = str(venture.get("id") or f"VENT-{abs(hash(raw['key'])) % 100000:05d}")
    venture["id"] = venture_id
    evidence = _evidence_for(state, venture)

    category_key = _norm(venture.get("category"))
    network = _network_by_category(state).get(category_key, {})
    economics = _economics_by_category(state).get(category_key, {})
    safeguard_cases = [x for x in state.get("deal_safeguard_cases", []) if _norm(next((d.get("category") or d.get("need") for d in state.get("deals", []) if str(d.get("id")) == str(x.get("deal_id"))), "")) == category_key]

    demand_signal = min(100.0, evidence["buyers_with_demand"] * 28.0 + evidence["contactable_buyers"] * 8.0 + evidence["venture_research_leads"] * 4.0)
    supply_signal = min(100.0, evidence["verified_suppliers"] * 18.0 + evidence["contactable_suppliers"] * 10.0 + _f(network.get("avg_score")) * 0.35)
    economics_signal = min(100.0, _f(economics.get("avg_money_score")) * 0.75 + min(25.0, _f(economics.get("risk_profit")) / 100.0))
    evidence_signal = min(100.0, evidence["research_leads"] * 3.0 + evidence["real_offers"] * 14.0 + evidence["market_accounts"] * 5.0)
    risk_penalty = 0.0
    if safeguard_cases:
        avg_safe = sum(_f(x.get("safe_close_score"), 70.0) for x in safeguard_cases) / len(safeguard_cases)
        risk_penalty += max(0.0, 70.0 - avg_safe) * 0.35
    risk_penalty += sum(18.0 for x in state.get("commercial_incidents", []) if x.get("status") not in {"resolved", "closed"} and str(x.get("deal_id") or "") in {str(d.get("id")) for d in state.get("deals", []) if _norm(d.get("category") or d.get("need")) == category_key})

    source_signal = min(100.0, _f(venture.get("source_score"), 50.0))
    score = demand_signal * 0.30 + supply_signal * 0.20 + economics_signal * 0.22 + evidence_signal * 0.13 + source_signal * 0.15 - min(35.0, risk_penalty)
    observations = evidence["research_leads"] + evidence["verified_buyers"] * 2 + evidence["verified_suppliers"] * 2 + evidence["real_offers"] * 3
    confidence = min(0.98, 0.20 + observations / 40.0)

    transactions = (_real_venture_transactions(state).get(venture_id) or {})
    blockers: List[str] = []
    if evidence["buyers_with_demand"] == 0:
        blockers.append("no_verified_demand")
    if evidence["verified_suppliers"] == 0:
        blockers.append("no_verified_supplier")
    if evidence["contactable_buyers"] == 0:
        blockers.append("no_verified_buyer_channel")
    if evidence["contactable_suppliers"] == 0:
        blockers.append("no_verified_supplier_channel")
    if venture.get("type") == "market_cell" and evidence["market_accounts"] < 2:
        blockers.append("target_market_evidence_thin")

    previous_stage = str(venture.get("stage") or "idea")
    if _i(transactions.get("transactions")) >= 2 and _f(transactions.get("profit_usd")) > 0:
        stage = "scale_candidate"
    elif score >= 75 and confidence >= MIN_CONFIDENCE_FOR_PILOT and not blockers:
        stage = "pilot_candidate"
    elif score >= 63:
        stage = "evidence_build"
    elif score >= 48:
        stage = "validate"
    else:
        stage = "idea"

    if observations >= MIN_OBSERVATIONS_FOR_KILL and confidence >= 0.60 and score < 32:
        stage = "kill_candidate"
    elif observations >= MIN_OBSERVATIONS_FOR_KILL and confidence >= 0.55 and score < 42:
        stage = "pause_candidate"

    venture.update({
        "key": raw["key"],
        "score": round(max(0.0, min(100.0, score)), 2),
        "confidence": round(confidence, 2),
        "observations": observations,
        "stage": stage,
        "previous_stage": previous_stage,
        "evidence": evidence,
        "signals": {
            "demand": round(demand_signal, 1),
            "supply": round(supply_signal, 1),
            "economics": round(economics_signal, 1),
            "evidence": round(evidence_signal, 1),
            "source": round(source_signal, 1),
            "risk_penalty": round(min(35.0, risk_penalty), 1),
        },
        "blockers": blockers,
        "real_transactions": _i(transactions.get("transactions")),
        "realized_profit_usd": round(_f(transactions.get("profit_usd")), 2),
        "updated_at": utcnow(),
    })
    return venture


def _next_action(venture: Dict[str, Any]) -> Dict[str, Any]:
    stage = str(venture.get("stage") or "idea")
    blockers = list(venture.get("blockers") or [])
    if stage == "kill_candidate":
        return {"code": "kill_venture", "title": "Cerrar hipótesis y liberar atención", "autonomous": True}
    if stage == "pause_candidate":
        return {"code": "pause_venture", "title": "Pausar hasta nueva evidencia", "autonomous": True}
    if "no_verified_demand" in blockers:
        return {"code": "validate_demand", "title": "Buscar demanda pública verificable", "autonomous": True}
    if "no_verified_supplier" in blockers:
        return {"code": "build_supply", "title": "Construir oferta/proveedores verificables", "autonomous": True}
    if "no_verified_buyer_channel" in blockers:
        return {"code": "find_buyer_channel", "title": "Encontrar canal corporativo del comprador", "autonomous": True}
    if "no_verified_supplier_channel" in blockers:
        return {"code": "find_supplier_channel", "title": "Encontrar canal corporativo del proveedor", "autonomous": True}
    if stage == "pilot_candidate":
        return {"code": "prepare_nonbinding_pilot", "title": "Preparar piloto comercial reversible", "autonomous": True}
    if stage == "scale_candidate":
        return {"code": "propose_scale", "title": "Escalar la venture con disciplina de capital", "autonomous": True}
    return {"code": "gather_evidence", "title": "Aumentar evidencia de mercado y economía", "autonomous": True}


def _materialize_task(state: Dict[str, Any], venture: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    task = {
        "key": f"venture_builder|{venture.get('id')}|{action.get('code')}",
        "kind": "venture_builder",
        "title": f"Venture Builder: {action.get('title')} — {venture.get('category')}",
        "reason": f"Venture {venture.get('type')} score {venture.get('score')}/100; confianza {venture.get('confidence')}; etapa {venture.get('stage')}.",
        "impact": min(100.0, 62.0 + _f(venture.get("score")) * 0.32),
        "urgency": min(95.0, 55.0 + _f(venture.get("score")) * 0.28),
        "confidence": max(0.35, min(0.98, _f(venture.get("confidence")))),
        "effort": 1.0,
        "risk": "low",
        "autonomous": bool(action.get("autonomous", True)),
        "object_type": "venture",
        "object_id": str(venture.get("id")),
        "payload": {"category": venture.get("category"), "market": venture.get("market"), "stage": venture.get("stage"), "action": action.get("code")},
        "priority_score": round(min(94.0, 55.0 + _f(venture.get("score")) * 0.38), 2),
        "created_at": utcnow(),
    }
    queue = list(state.get("operating_action_queue", []) or [])
    by_key = {str(x.get("key")): x for x in queue if x.get("key")}
    by_key[task["key"]] = task
    state["operating_action_queue"] = sorted(by_key.values(), key=lambda x: _f(x.get("priority_score")), reverse=True)[:80]
    return task


def venture_builder_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = _ensure(state)
    memory["cycle"] = _i(memory.get("cycle")) + 1

    governance = state.get("master_governance", {}) or {}
    switches = governance.get("kill_switches", {}) or {}
    mode = str(governance.get("company_mode") or "")
    venture_paused = bool(switches.get("global_pause")) or mode in {"RECOVERY", "PROTECT_CASH"}

    raw_hypotheses = _core_hypotheses(state) + _growth_hypotheses(state)
    unique: Dict[str, Dict[str, Any]] = {}
    for raw in raw_hypotheses:
        current = unique.get(str(raw.get("key")))
        if current is None or _f(raw.get("source_score")) > _f(current.get("source_score")):
            unique[str(raw.get("key"))] = raw

    ventures: Dict[str, Dict[str, Any]] = memory.setdefault("ventures", {})
    scored: List[Dict[str, Any]] = []
    for key, raw in unique.items():
        old = ventures.get(key)
        venture = _score_venture(state, raw, old)
        ventures[key] = venture
        scored.append(venture)

    scored.sort(key=lambda x: (_f(x.get("score")), _f(x.get("confidence")), _i(x.get("observations"))), reverse=True)
    scored = scored[:MAX_VENTURES]
    keep = {str(x.get("key")) for x in scored}
    memory["ventures"] = {k: v for k, v in ventures.items() if k in keep}

    primary = next((x for x in scored if x.get("stage") not in {"kill_candidate", "pause_candidate"}), scored[0] if scored else None)
    action = _next_action(primary) if primary else {}
    task = None
    if primary and not venture_paused:
        task = _materialize_task(state, primary, action)

    directive = {
        "venture_id": primary.get("id") if primary else None,
        "category": primary.get("category") if primary else None,
        "market": primary.get("market") if primary else None,
        "type": primary.get("type") if primary else None,
        "stage": primary.get("stage") if primary else None,
        "score": primary.get("score") if primary else None,
        "confidence": primary.get("confidence") if primary else None,
        "next_action": action.get("code") if action else None,
        "next_action_title": action.get("title") if action else None,
        "research_validation_allowed": bool(primary and not venture_paused and primary.get("stage") in {"idea", "validate", "evidence_build", "pilot_candidate"}),
        "paused_by_constitution": venture_paused,
    }
    state["venture_builder_directive"] = directive

    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_venture_builder",
        "cycle": memory["cycle"],
        "ventures": scored,
        "venture_count": len(scored),
        "stage_counts": {stage: sum(1 for x in scored if x.get("stage") == stage) for stage in {"idea", "validate", "evidence_build", "pilot_candidate", "scale_candidate", "pause_candidate", "kill_candidate"}},
        "primary_venture": primary,
        "directive": directive,
        "operating_task": task,
        "governance": {
            "idea_is_not_business": True,
            "pilot_rule": "requires verified demand, verified suppliers, verified corporate channels and adequate evidence confidence",
            "scale_rule": "requires real attributable transactions and positive realized profit; pipeline alone is insufficient",
            "capital_rule": "research and nonbinding validation may be autonomous; spending, orders, contracts, payments and binding commitments remain human-gated",
            "legal_rule": "Deal Safeguards and Operating Constitution remain superior to venture growth",
            "self_modification_rule": "Venture Builder creates business hypotheses and tasks, never production code changes",
        },
    }
    state["venture_builder"] = report

    memory.setdefault("history", []).append({
        "ts": report["updated_at"],
        "primary_venture_id": directive.get("venture_id"),
        "stage": directive.get("stage"),
        "score": directive.get("score"),
        "action": directive.get("next_action"),
        "paused": venture_paused,
    })
    memory["history"] = memory["history"][-MAX_HISTORY:]

    if primary:
        record_decision(
            state,
            engine="Autonomous Venture Builder",
            object_type="venture",
            object_id=str(primary.get("id")),
            decision=f"venture_stage:{primary.get('stage')}",
            reason=f"{primary.get('thesis')} Score {primary.get('score')}/100, confianza {primary.get('confidence')}; próxima acción: {action.get('title')}.",
            action="prepare_draft" if action.get("code") == "prepare_nonbinding_pilot" else "score_opportunity",
            confidence=max(0.35, min(0.98, _f(primary.get("confidence")))),
            evidence_refs=[],
            allowed=not venture_paused,
            requires_approval=False,
        )
    return report
