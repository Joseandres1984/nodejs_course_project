from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

MAX_PROFILES = 160
MAX_PLANS = 60
MAX_NEGOTIATION_ROUNDS = 2
MIN_EVENTS_FOR_PERSONALIZATION = 3
MAX_PROACTIVE_MESSAGES_PER_CYCLE = 1


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


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _account_maps(state: Dict[str, Any]) -> tuple[Dict[str, Dict[str, Any]], Dict[str, str], Dict[str, str]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    by_email: Dict[str, str] = {}
    by_name: Dict[str, str] = {}
    for account in state.get("candidate_accounts", []) or []:
        account_id = str(account.get("id") or "")
        if not account_id:
            continue
        by_id[account_id] = account
        email = str(account.get("commercial_email") or "").strip().lower()
        if email:
            by_email[email] = account_id
        for name in (account.get("company_name"), account.get("name_hint"), account.get("site_title"), account.get("domain")):
            key = _norm(name)
            if key:
                by_name[key] = account_id
    return by_id, by_email, by_name


def _account_for_name(name: Any, by_name: Dict[str, str]) -> str:
    target = _norm(name)
    if not target:
        return ""
    if target in by_name:
        return by_name[target]
    for candidate, account_id in by_name.items():
        if candidate and (candidate in target or target in candidate):
            return account_id
    return ""


def _offer_account_id(offer: Dict[str, Any], by_name: Dict[str, str]) -> str:
    return str(offer.get("supplier_account_id") or "") or _account_for_name(offer.get("supplier"), by_name)


def _message_account_id(message: Dict[str, Any], by_email: Dict[str, str], by_name: Dict[str, str]) -> str:
    explicit = str(message.get("counterparty_account_id") or "")
    if explicit:
        return explicit
    contact = str(message.get("contact") or message.get("from") or "").strip().lower()
    if contact and contact in by_email:
        return by_email[contact]
    return _account_for_name(message.get("counterparty"), by_name)


def _offer_time(offer: Dict[str, Any]) -> datetime:
    for field in ("received_at", "source_received_at", "created_at", "normalized_at"):
        parsed = _parse_ts(offer.get(field))
        if parsed:
            return parsed
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _profile_shell(account: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "account_id": account.get("id"), "name": account.get("company_name") or account.get("name_hint") or account.get("site_title") or account.get("domain"),
        "type": account.get("type"), "domain": account.get("domain"), "observed_events": 0, "outbound_sent": 0, "responses": 0,
        "negotiation_requests": 0, "negotiation_responses": 0, "offer_revisions": 0, "price_improvements": 0,
        "price_improvement_total_pct": 0.0, "lead_time_improvements": 0, "payment_term_changes": 0,
        "buyer_price_objections": 0, "buyer_delivery_questions": 0, "buyer_interest_signals": 0,
        "closed_transactions": 0, "realized_profit_usd": 0.0,
    }


def _build_profiles(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_id, by_email, by_name = _account_maps(state)
    profiles: Dict[str, Dict[str, Any]] = {aid: _profile_shell(account) for aid, account in by_id.items()}

    for message in state.get("outbox", []) or []:
        if message.get("status") != "sent":
            continue
        account_id = _message_account_id(message, by_email, by_name)
        if account_id not in profiles:
            continue
        p = profiles[account_id]
        p["outbound_sent"] += 1
        if message.get("kind") == "supplier_negotiation":
            p["negotiation_requests"] += 1

    outbox_by_id = {str(x.get("id") or ""): x for x in state.get("outbox", []) if x.get("id")}
    for incoming in state.get("inbox", []) or []:
        sender = str(incoming.get("from") or "").strip().lower()
        account_id = by_email.get(sender, "")
        if account_id not in profiles:
            continue
        p = profiles[account_id]
        p["responses"] += 1
        kind = str((incoming.get("classification") or {}).get("kind") or "")
        if kind == "price_objection": p["buyer_price_objections"] += 1
        elif kind == "delivery_question": p["buyer_delivery_questions"] += 1
        elif kind == "buyer_interest": p["buyer_interest_signals"] += 1
        source = outbox_by_id.get(str(incoming.get("revops_source_message_id") or ""), {})
        if source.get("kind") == "supplier_negotiation":
            p["negotiation_responses"] += 1

    grouped: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for offer in state.get("offers", []) or []:
        if offer.get("source") == "demo/simulación":
            continue
        account_id = _offer_account_id(offer, by_name)
        deal_id = str(offer.get("deal_id") or "")
        if account_id and deal_id and account_id in profiles:
            grouped[(account_id, deal_id)].append(offer)

    for (account_id, _deal_id), offers in grouped.items():
        offers.sort(key=_offer_time)
        p = profiles[account_id]
        for prev, cur in zip(offers, offers[1:]):
            p["offer_revisions"] += 1
            if str(prev.get("currency") or "") == str(cur.get("currency") or ""):
                old_amount, new_amount = _f(prev.get("amount")), _f(cur.get("amount"))
                if old_amount > 0 and 0 < new_amount < old_amount:
                    p["price_improvements"] += 1
                    p["price_improvement_total_pct"] += (old_amount - new_amount) / old_amount * 100.0
            old_lead, new_lead = _f(prev.get("lead_days")), _f(cur.get("lead_days"))
            if old_lead > 0 and 0 < new_lead < old_lead:
                p["lead_time_improvements"] += 1
            old_terms, new_terms = _norm(prev.get("payment_terms")), _norm(cur.get("payment_terms"))
            if old_terms and new_terms and old_terms != new_terms:
                p["payment_term_changes"] += 1

    deals = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}
    real_status = {"closed", "settled", "paid", "completed", "delivered", "invoiced"}
    for txn in state.get("transactions", []) or []:
        if str(txn.get("status") or "") not in real_status:
            continue
        deal = deals.get(str(txn.get("deal_id") or ""), {})
        for account_id in (str(deal.get("buyer_account_id") or ""), str(deal.get("supplier_account_id") or "")):
            if account_id in profiles:
                profiles[account_id]["closed_transactions"] += 1
                profiles[account_id]["realized_profit_usd"] += max(0.0, _f(txn.get("company_profit")))

    rows: List[Dict[str, Any]] = []
    for account_id, p in profiles.items():
        outbound, responses = _i(p.get("outbound_sent")), _i(p.get("responses"))
        req, neg_resp = _i(p.get("negotiation_requests")), _i(p.get("negotiation_responses"))
        price_improvements, revisions = _i(p.get("price_improvements")), _i(p.get("offer_revisions"))
        events = outbound + responses + revisions + _i(p.get("closed_transactions")) * 3
        p["observed_events"] = events
        p["response_rate"] = round(responses / max(1, outbound), 3) if outbound else None
        p["negotiation_response_rate"] = round(neg_resp / max(1, req), 3) if req else None
        p["price_concession_rate"] = round(price_improvements / max(1, revisions), 3) if revisions else None
        p["avg_observed_price_improvement_pct"] = round(_f(p.get("price_improvement_total_pct")) / max(1, price_improvements), 2) if price_improvements else None
        p["confidence"] = round(min(0.96, events / 12.0), 2)
        if p.get("type") == "supplier":
            signals = {"price_flexibility": price_improvements, "lead_time_flexibility": _i(p.get("lead_time_improvements")), "payment_term_flexibility": _i(p.get("payment_term_changes"))}
            p["observed_supplier_flexibility"] = max(signals, key=signals.get) if max(signals.values(), default=0) > 0 else "unknown"
        else:
            priorities = {"price": _i(p.get("buyer_price_objections")), "delivery": _i(p.get("buyer_delivery_questions")), "interest": _i(p.get("buyer_interest_signals"))}
            p["observed_buyer_priority"] = max(priorities, key=priorities.get) if max(priorities.values(), default=0) > 0 else "unknown"
        p["personalization_ready"] = bool(events >= MIN_EVENTS_FOR_PERSONALIZATION and _f(p.get("confidence")) >= 0.35)
        p["evidence_rule"] = "Behavioral conclusions use only persisted interactions, offers and real outcomes; sparse history stays neutral."
        p["updated_at"] = utcnow()
        account = by_id.get(account_id, {})
        account["negotiation_behavior"] = {
            "confidence": p["confidence"], "personalization_ready": p["personalization_ready"], "response_rate": p.get("response_rate"),
            "observed_supplier_flexibility": p.get("observed_supplier_flexibility"), "observed_buyer_priority": p.get("observed_buyer_priority"), "updated_at": p["updated_at"],
        }
        rows.append(p)
    rows.sort(key=lambda x: (_f(x.get("confidence")), _i(x.get("observed_events"))), reverse=True)
    return rows[:MAX_PROFILES]


def _negotiation_rounds(state: Dict[str, Any], deal_id: str, supplier_id: str) -> int:
    return sum(1 for x in state.get("outbox", []) or [] if x.get("kind") == "supplier_negotiation" and str(x.get("deal_id") or "") == deal_id and str(x.get("counterparty_account_id") or "") == supplier_id and x.get("status") in {"ready", "sent"})


def _plan_for_deal(state: Dict[str, Any], deal: Dict[str, Any], profiles: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    deal_id = str(deal.get("id") or ""); buyer_id = str(deal.get("buyer_account_id") or ""); supplier_id = str(deal.get("supplier_account_id") or "")
    buyer, supplier = profiles.get(buyer_id, {}), profiles.get(supplier_id, {})
    capital = (state.get("capital_priority_index", {}) or {}).get(deal_id, {})
    safeguards = (state.get("deal_safeguard_index", {}) or {}).get(deal_id, {}) or deal.get("deal_safeguards", {}) or {}
    action = str(capital.get("capital_action") or deal.get("capital_action") or "IMPROVE_CONVERSION")
    rounds = _negotiation_rounds(state, deal_id, supplier_id); safe_score = _f(safeguards.get("safe_close_score"), 100.0)
    buyer_priority = str(buyer.get("observed_buyer_priority") or "unknown"); supplier_flex = str(supplier.get("observed_supplier_flexibility") or "unknown"); supplier_conf = _f(supplier.get("confidence"))

    if deal.get("incident_hold") or deal.get("legal_review_required") or safe_score < 55:
        strategy, objective, reason = "HOLD", "repair_risk", "Deal Safeguards domina cualquier negociación económica."
    elif rounds >= MAX_NEGOTIATION_ROUNDS:
        strategy, objective, reason = "WALK_AWAY_FROM_FURTHER_PRESSURE", "preserve_relationship", "Se alcanzó el límite de rondas autónomas; no erosionar relación ni crear presión repetitiva."
    elif action == "IMPROVE_MARGIN":
        if supplier_conf >= 0.35 and supplier_flex == "price_flexibility": strategy, objective, reason = "TARGET_PRICE", "supplier_price", "Hay evidencia observada de flexibilidad de precio y el deal necesita mejorar margen."
        elif supplier_conf >= 0.35 and supplier_flex == "payment_term_flexibility": strategy, objective, reason = "TARGET_TERMS", "payment_terms", "La contraparte mostró más flexibilidad en términos que en precio."
        elif supplier_conf >= 0.35 and supplier_flex == "lead_time_flexibility": strategy, objective, reason = "TARGET_DELIVERY", "lead_time", "La flexibilidad histórica observada está en plazo; mejorar valor sin sacrificar margen comprador."
        else: strategy, objective, reason = "NEUTRAL_BEST_TERMS", "best_real_condition", "Historia insuficiente: pedir mejor condición real sin inventar palancas."
    elif action == "REPAIR_TERMS":
        strategy, objective, reason = "TARGET_TERMS", "risk_alignment", "La prioridad económica es reparar términos/Safe Close antes de acelerar."
    elif action == "ACCELERATE":
        if buyer_priority == "delivery" and supplier_flex == "lead_time_flexibility" and supplier_conf >= 0.35:
            strategy, objective, reason = "TARGET_DELIVERY", "lead_time", "Comprador muestra interés en entrega y proveedor evidencia flexibilidad de plazo."
        else:
            strategy, objective, reason = "PRESERVE_MARGIN", "close_without_unnecessary_concession", "El deal ya es atractivo; evitar descuentos no solicitados."
    else:
        strategy, objective, reason = "NEUTRAL_BEST_TERMS", "best_real_condition", "Mejorar conversión con una solicitud prudente y no vinculante."

    expected_leverage = "unknown"
    if supplier.get("personalization_ready"):
        if strategy == "TARGET_PRICE" and supplier.get("avg_observed_price_improvement_pct") is not None: expected_leverage = f"observed_price_improvement_avg:{supplier.get('avg_observed_price_improvement_pct')}%"
        elif strategy == "TARGET_DELIVERY": expected_leverage = "observed_lead_time_flexibility"
        elif strategy == "TARGET_TERMS": expected_leverage = "observed_payment_term_flexibility"

    return {
        "deal_id": deal_id, "buyer_account_id": buyer_id, "supplier_account_id": supplier_id, "capital_action": action,
        "strategy": strategy, "objective": objective, "reason": reason, "autonomous": strategy not in {"HOLD", "WALK_AWAY_FROM_FURTHER_PRESSURE"},
        "negotiation_rounds": rounds, "max_autonomous_rounds": MAX_NEGOTIATION_ROUNDS, "buyer_observed_priority": buyer_priority,
        "buyer_confidence": buyer.get("confidence"), "supplier_observed_flexibility": supplier_flex, "supplier_confidence": supplier.get("confidence"),
        "expected_leverage": expected_leverage, "defended_target_margin_pct": capital.get("defended_target_margin_pct") or deal.get("defended_target_margin_pct"),
        "current_margin_pct": capital.get("margin_pct") or (deal.get("economics", {}) or {}).get("company_share_pct") or deal.get("company_share_pct"),
        "safe_close_score": safe_score, "updated_at": utcnow(),
        "governance": {"nonbinding_only": True, "no_fake_competition": True, "no_fake_urgency": True, "no_unverified_concession_claims": True, "binding_acceptance_requires_human": True},
    }


def _relationship_blocked(state: Dict[str, Any], supplier_id: str) -> bool:
    relation = next((x for x in state.get("commercial_relationships", []) if str(x.get("account_id") or "") == supplier_id), {})
    return bool(relation.get("opted_out") or relation.get("relationship_state") in {"cooldown", "do_not_contact"})


def _negotiation_body(plan: Dict[str, Any], deal: Dict[str, Any]) -> str:
    strategy = str(plan.get("strategy") or "NEUTRAL_BEST_TERMS")
    if strategy == "TARGET_PRICE":
        ask = "¿Existe posibilidad de revisar el precio total y confirmarnos su mejor condición real para esta oportunidad?"
    elif strategy == "TARGET_TERMS":
        ask = "¿Existe posibilidad de mejorar la forma de pago o alguna condición comercial que reduzca la exposición sin modificar el alcance técnico?"
    elif strategy == "TARGET_DELIVERY":
        ask = "¿Existe posibilidad real de mejorar el plazo de entrega manteniendo la especificación y las demás condiciones?"
    else:
        ask = "¿Existe alguna mejora real posible en precio, plazo o forma de pago que permita fortalecer la propuesta?"
    return (
        "Estamos revisando esta oportunidad sobre una base estrictamente comercial y no vinculante. "
        + ask + " Nos sirve conocer únicamente condiciones que puedan confirmar realmente; no necesitamos supuestos ni compromisos anticipados. "
        "Cualquier decisión posterior queda sujeta a validación final."
    )


def _prepare_proactive_message(state: Dict[str, Any], plans: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_id, _, _ = _account_maps(state)
    deals = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}
    created = 0; selected = None
    for plan in plans:
        if created >= MAX_PROACTIVE_MESSAGES_PER_CYCLE:
            break
        # Proactive negotiation is intentionally narrow: only improve-margin cases, first autonomous round.
        if plan.get("capital_action") != "IMPROVE_MARGIN" or not plan.get("autonomous") or _i(plan.get("negotiation_rounds")) != 0:
            continue
        if plan.get("strategy") not in {"TARGET_PRICE", "TARGET_TERMS", "TARGET_DELIVERY", "NEUTRAL_BEST_TERMS"}:
            continue
        deal_id = str(plan.get("deal_id") or ""); supplier_id = str(plan.get("supplier_account_id") or "")
        deal = deals.get(deal_id, {}); supplier = by_id.get(supplier_id, {})
        if not deal or not supplier or _relationship_blocked(state, supplier_id):
            continue
        email = str(supplier.get("commercial_email") or "").strip().lower()
        if not email or not supplier.get("verified_contact"):
            continue
        key = f"negotiation_intel|{deal_id}|{supplier_id}|v1"
        if any(str(x.get("execution_key") or "") == key for x in state.get("outbox", []) or []):
            continue
        revops = next((x for x in (state.get("commercial_execution_memory", {}) or {}).get("cases", []) if str(x.get("deal_id") or "") == deal_id), {})
        state.setdefault("outbox", []).append({
            "id": f"MSG-{len(state.get('outbox', []))+1:04d}", "deal_id": deal_id, "revops_case_id": revops.get("id"),
            "opportunity_id": deal.get("opportunity_id"), "counterparty_account_id": supplier_id,
            "kind": "supplier_negotiation", "purpose": "behavioral_nonbinding_margin_negotiation",
            "counterparty": supplier.get("company_name") or supplier.get("name_hint") or supplier.get("domain"),
            "channel": "email", "contact": email, "contact_verified": True,
            "subject": "Revisión de condiciones comerciales", "body": _negotiation_body(plan, deal),
            "status": "ready", "execution_key": key, "created_at": utcnow(),
            "negotiation_strategy": plan.get("strategy"), "negotiation_objective": plan.get("objective"),
            "negotiation_evidence_confidence": plan.get("supplier_confidence"), "nonbinding": True,
        })
        plan["proactive_message_prepared"] = True
        selected = {"deal_id": deal_id, "supplier_account_id": supplier_id, "strategy": plan.get("strategy"), "message_execution_key": key}
        created += 1
    return {"created": created, "selected": selected, "max_per_cycle": MAX_PROACTIVE_MESSAGES_PER_CYCLE}


def negotiation_intelligence_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    profiles = _build_profiles(state); profile_map = {str(x.get("account_id")): x for x in profiles if x.get("account_id")}
    plans: List[Dict[str, Any]] = []
    for deal in state.get("deals", []) or []:
        if deal.get("source") == "demo" or str(deal.get("stage") or "") in {"cerrado (simulación)", "closed_simulated"}:
            continue
        plan = _plan_for_deal(state, deal, profile_map)
        if plan.get("deal_id"):
            plans.append(plan); deal["negotiation_strategy"] = plan.get("strategy"); deal["negotiation_objective"] = plan.get("objective"); deal["negotiation_reviewed_at"] = plan.get("updated_at")
    priority = {"TARGET_PRICE": 7, "TARGET_TERMS": 6, "TARGET_DELIVERY": 5, "PRESERVE_MARGIN": 4, "NEUTRAL_BEST_TERMS": 3, "HOLD": 2, "WALK_AWAY_FROM_FURTHER_PRESSURE": 1}
    plans.sort(key=lambda x: (priority.get(str(x.get("strategy")), 0), _f(x.get("supplier_confidence"))), reverse=True); plans = plans[:MAX_PLANS]
    state["counterparty_behavior_profiles"] = profiles; state["negotiation_plan_index"] = {str(x.get("deal_id")): x for x in plans if x.get("deal_id")}
    proactive = _prepare_proactive_message(state, plans)
    primary = plans[0] if plans else None
    report = {
        "updated_at": utcnow(), "mode": "negotiation_intelligence_2", "profiles": profiles, "plans": plans,
        "profiles_total": len(profiles), "personalized_profiles": sum(1 for x in profiles if x.get("personalization_ready")), "plans_total": len(plans),
        "primary_plan": primary, "proactive_execution": proactive,
        "governance": {
            "personalization_rule": f"At least {MIN_EVENTS_FOR_PERSONALIZATION} observed events; sparse counterparties remain neutral.",
            "round_limit": MAX_NEGOTIATION_ROUNDS, "proactive_limit_per_cycle": MAX_PROACTIVE_MESSAGES_PER_CYCLE,
            "truth_rule": "Never invent competitor quotes, urgency, volume, concessions, deadlines or counterpart behavior.",
            "authority_rule": "May prepare/request nonbinding improvements only; accepting terms, discounts, orders, contracts or payments remains human-gated.",
            "relationship_rule": "Do not continue pressure after autonomous round limit, opt-out, cooldown or risk hold.",
        },
    }
    state["negotiation_intelligence"] = report
    if primary:
        record_decision(state, engine="Negotiation Intelligence 2.0", object_type="deal", object_id=str(primary.get("deal_id")), decision=f"strategy:{str(primary.get('strategy') or '').lower()}", reason=str(primary.get("reason") or "Behavioral strategy selected from observed evidence."), action="negotiate_nonbinding" if primary.get("autonomous") else "score_opportunity", confidence=max(0.45, min(0.96, _f(primary.get("supplier_confidence"), 0.5))), evidence_refs=[], allowed=bool(primary.get("autonomous")), requires_approval=False)
    return report


def plan_for_deal(state: Dict[str, Any], deal_id: Any) -> Dict[str, Any]:
    return dict((state.get("negotiation_plan_index", {}) or {}).get(str(deal_id or ""), {}) or {})
