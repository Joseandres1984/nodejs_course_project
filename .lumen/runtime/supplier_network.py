from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, List

from autonomy_governor import record_decision

MAX_PROFILES = 200
MAX_SQUAD = 4
MAX_SQUADS = 80
REAL_TX_STATUSES = {"closed", "settled", "paid", "completed", "delivered", "invoiced"}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _supplier_name(account: Dict[str, Any]) -> str:
    return str(account.get("company_name") or account.get("name_hint") or account.get("site_title") or account.get("domain") or "Proveedor")


def _relations(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("account_id")): x for x in state.get("commercial_relationships", []) if x.get("account_id")}


def _deal_category_map(state: Dict[str, Any]) -> Dict[str, str]:
    return {str(x.get("id")): str(x.get("need") or x.get("category") or "") for x in state.get("deals", []) if x.get("id")}


def _supplier_account_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(x.get("id")): x for x in state.get("candidate_accounts", [])
        if x.get("id") and x.get("type") == "supplier" and x.get("verified_company")
    }


def _offer_stats(state: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, Any]:
    aid = str(account.get("id") or "")
    name = _norm(_supplier_name(account))
    offers = [
        x for x in state.get("offers", [])
        if x.get("source") != "demo/simulación"
        and (str(x.get("supplier_account_id") or "") == aid or _norm(x.get("supplier")) == name)
    ]
    comparable = [x for x in offers if x.get("comparable")]
    completeness = [_f(x.get("quote_completeness")) for x in offers if x.get("quote_completeness") is not None]
    leads = [_f(x.get("lead_days")) for x in comparable if x.get("lead_days") not in (None, "")]
    tech_known = [x for x in offers if x.get("technical_compliance") not in (None, "", "unknown", "por validar")]
    tech_positive = [x for x in tech_known if _norm(x.get("technical_compliance")) not in {"no", "false", "does not comply", "no cumple", "non-compliant"}]

    deal_categories = _deal_category_map(state)
    categories: Dict[str, int] = defaultdict(int)
    for offer in offers:
        cat = deal_categories.get(str(offer.get("deal_id") or ""), "")
        if cat:
            categories[cat] += 1

    competition_scores: List[float] = []
    offer_ids = {str(x.get("id")) for x in offers if x.get("id")}
    for comparison in state.get("quote_comparisons", []) or []:
        ranking = comparison.get("ranking", []) or []
        if comparison.get("status") != "comparable" or not ranking:
            continue
        for row in ranking:
            if str(row.get("offer_id") or "") in offer_ids:
                competition_scores.append(_f(row.get("score")))

    return {
        "quotes": len(offers),
        "comparable_quotes": len(comparable),
        "comparable_rate": round(len(comparable) / len(offers), 3) if offers else None,
        "avg_quote_completeness": round(sum(completeness) / len(completeness), 1) if completeness else None,
        "median_lead_days": round(median(leads), 1) if leads else None,
        "technical_observations": len(tech_known),
        "technical_positive_rate": round(len(tech_positive) / len(tech_known), 3) if tech_known else None,
        "avg_competition_score": round(sum(competition_scores) / len(competition_scores), 1) if competition_scores else None,
        "competition_observations": len(competition_scores),
        "category_history": dict(sorted(categories.items(), key=lambda kv: kv[1], reverse=True)[:12]),
    }


def _trade_stats(state: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, Any]:
    aid = str(account.get("id") or "")
    cases = [x for x in state.get("trade_cases", []) if str(x.get("supplier_account_id") or "") == aid]
    ready = [x for x in cases if x.get("decision_ready")]
    return {
        "trade_cases": len(cases),
        "trade_ready_cases": len(ready),
        "trade_ready_rate": round(len(ready) / len(cases), 3) if cases else None,
        "cross_border_observed": any(x.get("cross_border") is True for x in cases),
    }


def _transaction_stats(state: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, Any]:
    aid = str(account.get("id") or "")
    deals = {
        str(x.get("id")): x for x in state.get("deals", [])
        if str(x.get("supplier_account_id") or "") == aid and x.get("id")
    }
    real = [
        x for x in state.get("transactions", [])
        if str(x.get("deal_id") or "") in deals and str(x.get("status") or "") in REAL_TX_STATUSES
        and str(x.get("status") or "") not in {"closed_simulated", "simulated"}
    ]
    realized = [x for x in real if str(x.get("status") or "") in {"settled", "paid", "completed"}]
    return {"real_transactions": len(real), "realized_transactions": len(realized)}


def _response_score(relation: Dict[str, Any]) -> Dict[str, Any]:
    outbound = int(relation.get("outbound_count") or 0)
    responses = int(relation.get("response_count") or 0)
    # Bayesian shrinkage toward 50% prevents one lucky reply from looking perfect.
    rate = (responses + 1.5) / (outbound + 3.0) if outbound or responses else 0.5
    return {"outbound": outbound, "responses": responses, "shrunk_response_rate": round(rate, 3)}


def _profile_score(account: Dict[str, Any], relation: Dict[str, Any], offer: Dict[str, Any], trade: Dict[str, Any], tx: Dict[str, Any]) -> Dict[str, Any]:
    response = _response_score(relation)
    verification = min(15.0, _f(account.get("verification_score")) * 0.15)
    contactability = 10.0 if account.get("verified_contact") and account.get("commercial_email") else 6.0 if account.get("commercial_channel_verified") else 0.0
    relationship = response["shrunk_response_rate"] * 15.0

    quote_quality = 6.0
    if offer.get("quotes"):
        completeness = _f(offer.get("avg_quote_completeness"), 50.0) / 100.0
        comparable_rate = _f(offer.get("comparable_rate"), 0.0)
        quote_quality = min(20.0, completeness * 10.0 + comparable_rate * 10.0)

    competition = 7.5
    if offer.get("competition_observations"):
        competition = min(15.0, _f(offer.get("avg_competition_score")) * 0.15)

    technical = 5.0
    if offer.get("technical_observations"):
        technical = min(10.0, _f(offer.get("technical_positive_rate")) * 10.0)

    trade_score = 5.0
    if trade.get("trade_cases"):
        trade_score = min(10.0, _f(trade.get("trade_ready_rate")) * 10.0)

    outcome = min(5.0, int(tx.get("realized_transactions") or 0) * 2.0 + int(tx.get("real_transactions") or 0) * 0.75)
    risk_penalty = 0.0
    flags: List[str] = []
    if relation.get("opted_out"):
        flags.append("do_not_contact"); risk_penalty += 100
    if relation.get("relationship_state") == "cooldown":
        flags.append("relationship_cooldown"); risk_penalty += 18
    if not account.get("commercial_channel_verified"):
        flags.append("commercial_channel_missing"); risk_penalty += 8

    raw = verification + contactability + relationship + quote_quality + competition + technical + trade_score + outcome
    score = max(0.0, min(100.0, raw - risk_penalty))
    observations = int(offer.get("quotes") or 0) + int(response.get("outbound") or 0) + int(tx.get("real_transactions") or 0) + int(trade.get("trade_cases") or 0)
    confidence = min(0.96, 0.42 + min(20, observations) * 0.025 + (0.08 if account.get("verified_company") else 0.0))
    tier = "blocked" if "do_not_contact" in flags else "A" if score >= 78 and confidence >= 0.60 else "B" if score >= 58 else "developing"
    return {
        "score": round(score, 1), "tier": tier, "confidence": round(confidence, 2),
        "components": {
            "verification": round(verification, 1), "contactability": round(contactability, 1),
            "relationship": round(relationship, 1), "quote_quality": round(quote_quality, 1),
            "competition": round(competition, 1), "technical": round(technical, 1),
            "trade_readiness": round(trade_score, 1), "real_outcomes": round(outcome, 1),
        },
        "risk_flags": flags, "observations": observations, "response": response,
    }


def _build_profiles(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    relations = _relations(state)
    profiles: List[Dict[str, Any]] = []
    for account in _supplier_account_map(state).values():
        aid = str(account.get("id") or "")
        relation = relations.get(aid, {})
        offer = _offer_stats(state, account)
        trade = _trade_stats(state, account)
        tx = _transaction_stats(state, account)
        scoring = _profile_score(account, relation, offer, trade, tx)
        profile = {
            "account_id": aid,
            "supplier": _supplier_name(account),
            "market": account.get("growth_market") or account.get("market") or account.get("country"),
            "category": account.get("category"),
            "category_matches": list(account.get("category_matches") or [])[:12],
            "verified_contact": bool(account.get("verified_contact") and account.get("commercial_email")),
            "commercial_channel_verified": bool(account.get("commercial_channel_verified")),
            "network_score": scoring["score"], "tier": scoring["tier"], "confidence": scoring["confidence"],
            "components": scoring["components"], "risk_flags": scoring["risk_flags"], "observations": scoring["observations"],
            "response_metrics": scoring["response"], "quote_metrics": offer, "trade_metrics": trade, "outcome_metrics": tx,
            "updated_at": utcnow(),
            "method": "observable_supplier_evidence_with_sparse_data_shrinkage",
        }
        account["supplier_network_profile"] = {
            "network_score": profile["network_score"], "tier": profile["tier"], "confidence": profile["confidence"],
            "risk_flags": profile["risk_flags"], "updated_at": profile["updated_at"],
        }
        profiles.append(profile)
    profiles.sort(key=lambda x: (x["tier"] != "blocked", _f(x.get("network_score")), _f(x.get("confidence"))), reverse=True)
    return profiles[:MAX_PROFILES]


def _category_fit(profile: Dict[str, Any], category: str) -> float:
    target = _norm(category)
    if not target:
        return 0.45
    labels = [profile.get("category"), *(profile.get("category_matches") or [])]
    history = list((profile.get("quote_metrics", {}) or {}).get("category_history", {}).keys())
    labels.extend(history)
    norms = [_norm(x) for x in labels if x]
    if target in norms:
        return 1.0
    if any(target in x or x in target for x in norms if x):
        return 0.82
    return 0.25


def _candidate_ids(state: Dict[str, Any], deal: Dict[str, Any], profiles: Dict[str, Dict[str, Any]]) -> List[str]:
    ids: List[str] = []
    primary = str(deal.get("supplier_account_id") or "")
    if primary in profiles:
        ids.append(primary)
    opp_id = str(deal.get("opportunity_id") or "")
    for deep in state.get("deep_dive_cases", []) or []:
        if str(deep.get("opportunity_id") or "") != opp_id:
            continue
        for row in deep.get("supplier_alternatives", []) or []:
            sid = str(row.get("id") or row.get("account_id") or "")
            if sid in profiles and sid not in ids:
                ids.append(sid)
    category = str(deal.get("need") or deal.get("category") or "")
    for sid, profile in profiles.items():
        if sid not in ids and _category_fit(profile, category) >= 0.82:
            ids.append(sid)
    return ids


def _squad_for_deal(state: Dict[str, Any], deal: Dict[str, Any], profiles: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    deal_id = str(deal.get("id") or "")
    category = str(deal.get("need") or deal.get("category") or "")
    candidates: List[Dict[str, Any]] = []
    for sid in _candidate_ids(state, deal, profiles):
        profile = profiles[sid]
        if profile.get("tier") == "blocked" or "relationship_cooldown" in (profile.get("risk_flags") or []):
            continue
        fit = _category_fit(profile, category)
        contact = 1.0 if profile.get("verified_contact") else 0.6 if profile.get("commercial_channel_verified") else 0.0
        confidence = _f(profile.get("confidence"))
        score = _f(profile.get("network_score")) * 0.62 + fit * 100.0 * 0.22 + contact * 100.0 * 0.08 + confidence * 100.0 * 0.08
        candidates.append({
            "account_id": sid, "supplier": profile.get("supplier"), "market": profile.get("market"),
            "network_score": profile.get("network_score"), "network_confidence": profile.get("confidence"),
            "category_fit": round(fit, 2), "squad_score": round(score, 1),
            "verified_contact": profile.get("verified_contact"), "quote_metrics": profile.get("quote_metrics"),
            "risk_flags": profile.get("risk_flags"),
        })
    candidates.sort(key=lambda x: (_f(x.get("squad_score")), bool(x.get("verified_contact"))), reverse=True)

    squad: List[Dict[str, Any]] = []
    if candidates:
        anchor = dict(candidates[0]); anchor["role"] = "anchor"; squad.append(anchor)
    if len(candidates) > 1:
        challenger = dict(candidates[1]); challenger["role"] = "challenger"; squad.append(challenger)
    anchor_market = _norm((squad[0] if squad else {}).get("market"))
    diversifier = next((x for x in candidates[2:] if _norm(x.get("market")) and _norm(x.get("market")) != anchor_market), None)
    if diversifier and len(squad) < MAX_SQUAD:
        row = dict(diversifier); row["role"] = "route_diversifier"; squad.append(row)
    for candidate in candidates:
        if len(squad) >= MAX_SQUAD:
            break
        if any(x.get("account_id") == candidate.get("account_id") for x in squad):
            continue
        row = dict(candidate); row["role"] = "alternative"; squad.append(row)

    min_target = 3
    verified_contact_count = sum(1 for x in squad if x.get("verified_contact"))
    status = "ready" if len(squad) >= min_target and verified_contact_count >= 2 else "network_gap"
    return {
        "deal_id": deal_id, "category": category, "status": status,
        "supplier_count": len(squad), "verified_contact_count": verified_contact_count,
        "squad": squad, "candidate_pool": len(candidates),
        "gap": None if status == "ready" else "need_more_verified_category_fit_suppliers",
        "updated_at": utcnow(),
        "rule": "supplier squad prioritizes observable performance + category fit + contactability + diversity; historical prices are never treated as current quotes",
    }


def supplier_network_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    profiles_list = _build_profiles(state)
    profiles = {str(x.get("account_id")): x for x in profiles_list if x.get("account_id")}
    deals = [
        x for x in state.get("deals", []) or []
        if x.get("id") and x.get("source") != "demo" and str(x.get("stage") or "") not in {"closed_simulated", "cerrado (simulación)"}
    ]
    squads = [_squad_for_deal(state, deal, profiles) for deal in deals][:MAX_SQUADS]
    state["supplier_network_profiles"] = profiles_list
    state["supplier_squads"] = squads
    state["supplier_squad_index"] = {str(x.get("deal_id")): x for x in squads}

    gaps = [x for x in squads if x.get("status") != "ready"]
    ready = [x for x in squads if x.get("status") == "ready"]
    primary_gap = gaps[0] if gaps else None
    directive = {
        "mode": "close_supplier_network_gap" if primary_gap else "deploy_best_supplier_squads" if ready else "build_supplier_network",
        "deal_id": (primary_gap or (ready[0] if ready else {})).get("deal_id"),
        "category": (primary_gap or (ready[0] if ready else {})).get("category"),
        "priority": 86 if primary_gap else 72 if ready else 80,
        "next_action": "discover_and_verify_more_suppliers" if primary_gap else "use_ranked_supplier_squad_for_rfq" if ready else "discover_verified_suppliers",
        "reason": "Supplier competition is only strong when category-fit providers are verified, contactable and independently evidenced.",
    }
    report = {
        "updated_at": utcnow(), "mode": "autonomous_procurement_supplier_network",
        "supplier_profiles": len(profiles_list), "tier_a": sum(1 for x in profiles_list if x.get("tier") == "A"),
        "tier_b": sum(1 for x in profiles_list if x.get("tier") == "B"),
        "blocked": sum(1 for x in profiles_list if x.get("tier") == "blocked"),
        "deal_squads": len(squads), "squads_ready": len(ready), "network_gaps": len(gaps),
        "primary_directive": directive,
        "governance": {
            "evidence_rule": "scores use verified companies and observable interactions, quotes, technical evidence, trade readiness and real outcomes",
            "sparse_data_rule": "response rates are shrunk and confidence is observation-sensitive; one quote or reply cannot create an elite supplier",
            "price_rule": "historical competitiveness ranks sourcing attention only; every new deal still requires a fresh traceable quote",
            "diversification_rule": "squads seek route diversity when evidence exists; diversity never overrides technical/category fit",
            "binding_rule": "supplier selection for research/RFQ is autonomous; purchase orders, contracts, payments and binding acceptance require human approval",
        },
    }
    state["supplier_network"] = report

    if directive.get("deal_id"):
        record_decision(
            state,
            engine="Autonomous Procurement & Supplier Network Brain",
            object_type="deal",
            object_id=str(directive.get("deal_id")),
            decision=str(directive.get("mode")),
            reason=str(directive.get("reason")),
            action="request_quote" if directive.get("mode") == "deploy_best_supplier_squads" else "research_public",
            confidence=0.88 if directive.get("mode") == "deploy_best_supplier_squads" else 0.72,
            evidence_refs=[],
            allowed=True,
            requires_approval=False,
        )
    return report
