from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import demand_hunter
import demand_intelligence
import lead_intelligence
import scout_connector

VERSION = "1.0-demand-first-runtime"
DAILY_CAP = max(1, min(12, int(os.getenv("LUMEN_DEMAND_HUNTER_DAILY_CAP", "6"))))
MIN_HINT_SCORE = max(55, min(95, int(os.getenv("LUMEN_DEMAND_HUNTER_MIN_HINT_SCORE", "65"))))

# Broaden only explicit public buying-intent language. This does not bypass company/contact verification.
demand_hunter.DEMAND_TERMS = tuple(dict.fromkeys(demand_hunter.DEMAND_TERMS + (
    "solicitud de oferta", "registro de proveedores", "portal de proveedores", "alta de proveedores",
    "presentar oferta", "recepción de ofertas", "recepcion de ofertas", "request for quotation",
    "tender", "procurement", "sourcing",
)))
demand_hunter.NEGATIVE_VENDOR_TERMS = tuple(dict.fromkeys(demand_hunter.NEGATIVE_VENDOR_TERMS + (
    "empleo", "trabajo", "vacante", "curriculum", "currículum", "curso", "capacitacion", "capacitación",
)))


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _supplier_categories(state: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for account in state.get("candidate_accounts", []) or []:
        if account.get("type") != "supplier" or not account.get("verified_company"):
            continue
        category = " ".join(str(account.get("category") or "").split())
        if category and _norm(category) not in {_norm(x) for x in out}:
            out.append(category)
    return out


def _verified_demand_categories(state: Dict[str, Any]) -> set[str]:
    return {
        _norm(x.get("category"))
        for x in state.get("candidate_accounts", []) or []
        if x.get("type") == "buyer" and x.get("verified_company") and x.get("demand_signal") and x.get("category")
    }


def _gap_categories(state: Dict[str, Any]) -> List[str]:
    demand = _verified_demand_categories(state)
    return [x for x in _supplier_categories(state) if _norm(x) not in demand]


def _needs_hunt(state: Dict[str, Any]) -> bool:
    gaps = _gap_categories(state)
    if not gaps:
        return False
    if demand_hunter.COLLECTION_FOCUS == "mercadopago_ars":
        suppliers = [
            x for x in state.get("candidate_accounts", []) or []
            if x.get("type") == "supplier" and x.get("verified_company") and demand_hunter._is_argentina(x)
        ]
        if not suppliers:
            return False
    return True


def _categories(state: Dict[str, Any]) -> List[str]:
    return _gap_categories(state)


def _query(category: str) -> str:
    aliases = demand_hunter._aliases(category)[:5]
    alias_expr = " OR ".join(f'"{x}"' for x in aliases)
    return (
        f'({alias_expr}) '
        '("solicitud de cotización" OR "solicitud de cotizacion" OR "solicitud de oferta" '
        'OR "concurso de precios" OR "licitación" OR "licitacion" OR "registro de proveedores" '
        'OR "portal de proveedores" OR RFQ OR procurement) '
        f'{demand_hunter.MARKET} -venta -proveedor -distribuidor -fabricante -empleo -trabajo'
    )


demand_hunter._needs_hunt = _needs_hunt
demand_hunter._categories = _categories
demand_hunter._query = _query


def _daily_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    budget = state.setdefault("demand_hunter_budget", {"date": today, "queries_used": 0, "daily_cap": DAILY_CAP})
    if budget.get("date") != today:
        budget.clear()
        budget.update({"date": today, "queries_used": 0, "daily_cap": DAILY_CAP})
    budget["daily_cap"] = DAILY_CAP
    budget["queries_used"] = int(budget.get("queries_used") or 0)
    budget["queries_remaining"] = max(0, DAILY_CAP - budget["queries_used"])
    return budget


_ORIGINAL_SCOUT_TICK = scout_connector.scout_tick


def demand_first_scout_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    budget = _daily_budget(state)
    if budget["queries_remaining"] > 0:
        hunter = dict(demand_hunter.demand_hunter_tick(state) or {})
        used = max(0, int(hunter.get("queries") or 0))
        budget["queries_used"] += used
        budget["queries_remaining"] = max(0, DAILY_CAP - budget["queries_used"])
    else:
        hunter = {
            "active": False,
            "mode": "demand_first",
            "queries": 0,
            "signals_found": 0,
            "buyer_leads_created": 0,
            "reason": "demand_hunter_daily_cap_reached",
            "budget_remaining": 0,
        }
    base = dict(_ORIGINAL_SCOUT_TICK(state) or {})
    base["demand_hunter"] = hunter
    base["demand_hunter_daily_budget"] = dict(budget)
    state["demand_hunter_runtime"] = {
        "version": VERSION,
        "daily_cap": DAILY_CAP,
        "queries_used": budget["queries_used"],
        "queries_remaining": budget["queries_remaining"],
        "gap_categories": _gap_categories(state),
        "updated_at": scout_connector.utcnow(),
    }
    return base


scout_connector.scout_tick = demand_first_scout_tick


_ORIGINAL_SCORE_LEAD = lead_intelligence.score_lead


def score_lead_with_demand_hint(lead: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(_ORIGINAL_SCORE_LEAD(lead) or {})
    if not lead.get("public_demand_hint"):
        return result
    hint = int(lead.get("demand_score") or 0)
    if hint < MIN_HINT_SCORE:
        return result
    bonus = min(14, max(4, round((hint - 50) * 0.28)))
    score = min(100, int(result.get("lead_score") or 0) + bonus)
    reasons = list(result.get("qualification_reasons") or [])
    reasons.append(f"Señal pública de compra detectada por Demand Hunter (score {hint}); requiere validación corporativa")
    if score >= 75:
        tier, status, next_action = "A", "qualified_candidate", "Validar empresa, demanda y contacto antes de cualquier outreach"
    elif score >= 55:
        tier, status, next_action = "B", "research_required", "Profundizar empresa y confirmar que la señal de compra pertenece al comprador"
    elif score >= 38:
        tier, status, next_action = "C", "low_priority", "Mantener en observación; no usar para outreach"
    else:
        tier, status, next_action = "D", "rejected_noise", "Descartar salvo nueva evidencia"
    result.update({
        "lead_score": score,
        "tier": tier,
        "qualification_status": status,
        "qualification_reasons": reasons[:8],
        "next_research_action": next_action,
        "confidence": round(min(0.95, max(float(result.get("confidence") or 0), 0.50 + score / 220.0)), 2),
    })
    return result


lead_intelligence.score_lead = score_lead_with_demand_hint


_ORIGINAL_QUALIFY_TICK = lead_intelligence.qualify_tick


def qualify_tick_with_demand_provenance(state: Dict[str, Any]) -> Dict[str, int]:
    stats = dict(_ORIGINAL_QUALIFY_TICK(state) or {})
    leads = {str(x.get("id") or ""): x for x in state.get("research_leads", []) or []}
    linked = 0
    for account in state.get("candidate_accounts", []) or []:
        lead = leads.get(str(account.get("source_lead_id") or ""))
        if not lead or not lead.get("public_demand_hint"):
            continue
        account["public_demand_hint"] = True
        account["demand_discovery_score"] = int(lead.get("demand_score") or 0)
        account["demand_discovery_url"] = lead.get("url")
        account["demand_source_kind"] = lead.get("demand_source_kind") or "demand_first_public_search"
        account["demand_discovery_requires_confirmation"] = True
        linked += 1
    stats["demand_hint_accounts_linked"] = linked
    state.setdefault("lead_intelligence_stats", {}).update(stats)
    return stats


lead_intelligence.qualify_tick = qualify_tick_with_demand_provenance


_ORIGINAL_DEMAND_CANDIDATES = demand_intelligence._candidates


def demand_candidates_prioritized(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = list(_ORIGINAL_DEMAND_CANDIDATES(state) or [])
    rows.sort(
        key=lambda x: (
            1 if x.get("public_demand_hint") else 0,
            int(x.get("demand_discovery_score") or 0),
            1 if x.get("verified_contact") else 0,
            float(x.get("verification_score") or 0),
            float(x.get("lead_score") or 0),
        ),
        reverse=True,
    )
    return rows


demand_intelligence._candidates = demand_candidates_prioritized


_ORIGINAL_DEMAND_TICK = demand_intelligence.demand_intelligence_tick


def demand_tick_with_intent_level(state: Dict[str, Any]) -> Dict[str, Any]:
    stats = dict(_ORIGINAL_DEMAND_TICK(state) or {})
    signals = state.get("demand_signals", []) or []
    by_account: Dict[str, List[Dict[str, Any]]] = {}
    for signal in signals:
        aid = str(signal.get("account_id") or "")
        if aid:
            by_account.setdefault(aid, []).append(signal)
    high = 0
    medium = 0
    for account in state.get("candidate_accounts", []) or []:
        if account.get("type") != "buyer" or not account.get("verified_company"):
            continue
        rows = by_account.get(str(account.get("id") or ""), [])
        if not rows:
            continue
        best = max(rows, key=lambda x: int(x.get("score") or 0))
        score = int(best.get("score") or 0)
        strong = int(best.get("strong_demand_hits") or 0)
        official = str(best.get("source") or "") == "official_site"
        if account.get("demand_signal") and score >= 85 and strong >= 2 and official:
            account["demand_intent_level"] = "high"
            account["high_intent_public_demand"] = True
            account["demand_priority_reason"] = "Señal fuerte de compra en fuente oficial; aún requiere confirmación humana/comercial de vigencia"
            high += 1
        elif account.get("demand_signal"):
            account["demand_intent_level"] = "medium"
            account["high_intent_public_demand"] = False
            medium += 1
    stats["high_intent_public_demand"] = high
    stats["medium_intent_public_demand"] = medium
    stats["demand_hunter_runtime_version"] = VERSION
    state["demand_hunter_intent_summary"] = {
        "version": VERSION,
        "high": high,
        "medium": medium,
        "policy": "public_signal_is_not_a_confirmed_order",
        "updated_at": scout_connector.utcnow(),
    }
    return stats


demand_intelligence.demand_intelligence_tick = demand_tick_with_intent_level
