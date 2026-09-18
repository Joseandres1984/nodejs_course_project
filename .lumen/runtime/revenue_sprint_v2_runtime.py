from __future__ import annotations

"""LUMEN Revenue Sprint 2.0.

Conversion-first overlay for the path to first realized cash. It does four things without
increasing spend or widening authority:
1) broadens direct official-document enrichment while preserving exact-evidence RFQ gates;
2) safely repairs procurement lineage only on strong buyer/category/source evidence;
3) forces early-stage Mission Teams onto the highest First Cash opportunities;
4) records one compact sprint scoreboard after each worker cycle.

No missing quantity, technical scope, delivery location, quote, reply, delivery or revenue is
fabricated. Contracts, payments, orders and binding acceptance remain human-gated.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlparse
import re

import commercial_truth_repair_runtime as truth
import mission_team_runtime
import procurement_document_enrichment_runtime as documents

VERSION = "2.0-revenue-sprint"
MAX_FIRST_CASH_TEAMS = 3
MAX_DOCUMENT_CANDIDATES = 8
MAX_STRONG_LINKS_PER_CASE = 2

_ORIGINAL_LINKED_CURRENT_URLS = documents._linked_current_urls
_ORIGINAL_CANDIDATE_URLS = truth._candidate_urls
_ORIGINAL_CANONICAL_OPPORTUNITIES = mission_team_runtime._canonical_opportunities
_ORIGINAL_PREPARE_TEAMS = mission_team_runtime._prepare_teams

_STOP = {
    "para", "por", "del", "las", "los", "con", "sin", "una", "uno", "unos", "unas",
    "empresa", "servicios", "servicio", "industrial", "industriales", "argentina", "compras",
    "compra", "adquisicion", "adquisición", "licitacion", "licitación", "publica", "pública",
    "portal", "oficial", "materiales", "srl", "sa", "sociedad",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _norm(value: Any) -> str:
    return _clean(value).lower()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _tokens(value: Any) -> set[str]:
    return {
        x.lower() for x in re.findall(r"[A-Za-zÁÉÍÓÚÜáéíóúüÑñ0-9]+", str(value or ""))
        if len(x) >= 4 and x.lower() not in _STOP
    }


def _host(value: Any) -> str:
    try:
        return (urlparse(str(value or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _focus_opportunity_ids(state: Dict[str, Any]) -> List[str]:
    market_ids = {
        str(x.get("id") or "") for x in state.get("market_opportunities", []) or []
        if isinstance(x, dict) and x.get("id")
    }
    explicit = [str(x) for x in state.get("first_cash_focus_opportunity_ids", []) or [] if str(x) in market_ids]
    if explicit:
        return explicit[:MAX_FIRST_CASH_TEAMS]

    focus: List[str] = []
    for case in (state.get("first_cash_mode", {}) or {}).get("top_cash_cases", []) or []:
        if not isinstance(case, dict):
            continue
        sid = str(case.get("source_id") or "")
        if sid in market_ids and sid not in focus:
            focus.append(sid)
        if len(focus) >= MAX_FIRST_CASH_TEAMS:
            break
    return focus


def _focus_categories(state: Dict[str, Any]) -> set[str]:
    ids = set(_focus_opportunity_ids(state))
    cats = {
        _norm(x.get("category"))
        for x in state.get("market_opportunities", []) or []
        if isinstance(x, dict) and str(x.get("id") or "") in ids and _norm(x.get("category"))
    }
    return cats


def _signal_priority(signal: Dict[str, Any], focus_categories: set[str]) -> tuple[float, int, str]:
    score = _float(signal.get("score") or signal.get("priority_score"), 0.0)
    category = _norm(signal.get("category"))
    focused = 1 if category and any(_tokens(category) & _tokens(x) for x in focus_categories) else 0
    return (score, focused, str(signal.get("url") or signal.get("source_url") or ""))


def _linked_current_urls_first_cash(state: Dict[str, Any]) -> List[str]:
    base = list(_ORIGINAL_LINKED_CURRENT_URLS(state) or [])
    signals = list((truth._signal_map(state) or {}).values())
    focus_categories = _focus_categories(state)
    signals.sort(key=lambda x: _signal_priority(x, focus_categories), reverse=True)
    for signal in signals[:MAX_DOCUMENT_CANDIDATES]:
        url = str(signal.get("url") or signal.get("source_url") or "")
        if url and url not in base:
            base.append(url)
    return base


def _source_ids(row: Dict[str, Any]) -> set[str]:
    values = set()
    for key in (
        "source_lead_id", "research_lead_id", "demand_source_lead_id", "lead_id",
        "source_signal_id", "demand_signal_id", "public_procurement_signal_id",
    ):
        value = str(row.get(key) or "").strip()
        if value:
            values.add(value)
    return values


def _candidate_urls_first_cash(state: Dict[str, Any], case: Dict[str, Any], opportunity: Dict[str, Any]) -> List[str]:
    base = list(_ORIGINAL_CANDIDATE_URLS(state, case, opportunity) or [])
    signals = truth._signal_map(state) or {}
    if any(url in signals for url in base):
        return base

    accounts = {
        str(x.get("id") or ""): x
        for x in state.get("candidate_accounts", []) or []
        if isinstance(x, dict) and x.get("id")
    }
    buyer_id = str(case.get("buyer_account_id") or opportunity.get("buyer_account_id") or "")
    buyer = accounts.get(buyer_id, {})
    buyer_name = _clean(
        buyer.get("company_name") or buyer.get("name_hint") or buyer.get("site_title") or buyer.get("title")
    )
    buyer_tokens = _tokens(buyer_name)
    category_tokens = _tokens(case.get("category") or opportunity.get("category") or buyer.get("category"))
    buyer_host = _host(buyer.get("official_url") or buyer.get("source_url") or buyer.get("url")) or _norm(buyer.get("domain"))
    source_ids = _source_ids(case) | _source_ids(opportunity) | _source_ids(buyer)

    candidates: List[tuple[int, float, str]] = []
    for url, signal in signals.items():
        signal_text = truth._signal_text(signal)
        signal_tokens = _tokens(signal_text)
        signal_category_tokens = _tokens(signal.get("category") or signal.get("title"))
        signal_ids = _source_ids(signal)
        exact_source = bool(source_ids and signal_ids and source_ids & signal_ids)
        same_buyer_id = buyer_id and str(signal.get("buyer_account_id") or signal.get("account_id") or "") == buyer_id
        name_overlap = len(buyer_tokens & signal_tokens)
        category_overlap = len(category_tokens & signal_category_tokens) or len(category_tokens & signal_tokens)
        signal_host = _host(url)
        same_host = bool(buyer_host and signal_host and (buyer_host == signal_host or buyer_host.endswith("." + signal_host) or signal_host.endswith("." + buyer_host)))

        confidence = 0
        if exact_source or same_buyer_id:
            confidence += 6
        if name_overlap >= 2:
            confidence += 4
        elif name_overlap == 1:
            confidence += 2
        if category_overlap:
            confidence += 2
        if same_host:
            confidence += 2

        strong = exact_source or same_buyer_id or (name_overlap >= 1 and category_overlap) or (same_host and category_overlap)
        if not strong or confidence < 4:
            continue
        candidates.append((confidence, _float(signal.get("score"), 0.0), url))

    candidates.sort(reverse=True)
    for _, _, url in candidates[:MAX_STRONG_LINKS_PER_CASE]:
        if url not in base:
            base.append(url)
    return base


def _canonical_opportunities_first_cash(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = list(_ORIGINAL_CANONICAL_OPPORTUNITIES(state) or [])
    focus = _focus_opportunity_ids(state)
    order = {oid: idx for idx, oid in enumerate(focus)}
    rows.sort(key=lambda x: (
        0 if str(x.get("id") or "") in order else 1,
        order.get(str(x.get("id") or ""), 999),
        -_float(x.get("score") or x.get("portfolio_priority_score"), 0.0),
        str(x.get("id") or ""),
    ))
    return rows


def _prepare_teams_first_cash(state: Dict[str, Any]) -> Dict[str, Any]:
    focus = set(_focus_opportunity_ids(state))
    reallocated = 0
    first_cash_active = str((state.get("first_cash_mode", {}) or {}).get("status") or "").upper() == "ACTIVE"
    if first_cash_active and focus:
        for team in state.get("mission_teams", []) or []:
            if not isinstance(team, dict) or team.get("status") != "active":
                continue
            if str(team.get("opportunity_id") or "") in focus:
                continue
            if str(team.get("stage") or "") not in {"REQUIREMENT", "RFQ_READY"}:
                continue
            team["status"] = "reserve"
            team["sprint_reallocated_at"] = _now()
            team["sprint_reallocation_reason"] = "first_cash_focus"
            reallocated += 1
    report = dict(_ORIGINAL_PREPARE_TEAMS(state) or {})
    report["revenue_sprint_v2"] = True
    report["first_cash_focus_opportunity_ids"] = list(focus)
    report["teams_reallocated"] = reallocated
    return report


def _install() -> None:
    if getattr(documents, "_lumen_revenue_sprint_v2_installed", False):
        return
    documents._linked_current_urls = _linked_current_urls_first_cash
    truth._candidate_urls = _candidate_urls_first_cash
    mission_team_runtime._canonical_opportunities = _canonical_opportunities_first_cash
    mission_team_runtime._prepare_teams = _prepare_teams_first_cash
    documents._lumen_revenue_sprint_v2_installed = True


def revenue_sprint_v2_tick(state: Dict[str, Any], first_cash: Dict[str, Any] | None = None) -> Dict[str, Any]:
    first_cash = first_cash or (state.get("first_cash_mode", {}) or {})
    market_ids = {
        str(x.get("id") or "") for x in state.get("market_opportunities", []) or []
        if isinstance(x, dict) and x.get("id")
    }
    focus: List[str] = []
    for case in first_cash.get("top_cash_cases", []) or []:
        if not isinstance(case, dict):
            continue
        sid = str(case.get("source_id") or "")
        if sid in market_ids and sid not in focus:
            focus.append(sid)
        if len(focus) >= MAX_FIRST_CASH_TEAMS:
            break
    if not focus:
        focus = _focus_opportunity_ids(state)
    state["first_cash_focus_opportunity_ids"] = focus[:MAX_FIRST_CASH_TEAMS]

    before_ready = sum(1 for x in state.get("interlocution_cases", []) or [] if isinstance(x, dict) and x.get("supplier_rfq_ready"))
    bridge = truth._apply_procurement_requirement_evidence(state)
    after_ready = sum(1 for x in state.get("interlocution_cases", []) or [] if isinstance(x, dict) and x.get("supplier_rfq_ready"))

    active_teams = [x for x in state.get("mission_teams", []) or [] if isinstance(x, dict) and x.get("status") == "active"]
    focus_teams = [x for x in active_teams if str(x.get("opportunity_id") or "") in set(focus)]
    cache = [x for x in state.get("public_procurement_document_cache", []) or [] if isinstance(x, dict)]
    docs_ok = sum(1 for x in cache if x.get("status") == "ok" and x.get("text_excerpt"))
    outbound = state.get("outbound_engine", {}) or {}
    brevo = state.get("brevo_delivery_truth", {}) or {}

    previous = state.get("revenue_sprint_v2", {}) or {}
    report = {
        "version": VERSION,
        "status": "ACTIVE" if str(first_cash.get("status") or "").upper() == "ACTIVE" else "MONITORING",
        "objective": "break_first_zero_requirement_to_rfq_to_quote_to_offer_to_cash",
        "updated_at": _now(),
        "first_cash_focus_opportunity_ids": focus,
        "first_cash_team_target": MAX_FIRST_CASH_TEAMS,
        "active_mission_teams": len(active_teams),
        "active_focus_teams": len(focus_teams),
        "requirement_completion": {
            "ready_before": before_ready,
            "ready_after": after_ready,
            "ready_delta_this_tick": after_ready - before_ready,
            "official_evidence_matched": int(bridge.get("matched") or 0),
            "exact_fields_added": int(bridge.get("fields_added") or 0),
            "rfq_ready_from_exact_official_evidence": int(bridge.get("rfq_ready_from_official_evidence") or 0),
            "document_cache_total": len(cache),
            "document_text_available": docs_ok,
            "truth_rule": "technical_scope_quantity_delivery_location_must_be_observed_not_inferred",
        },
        "delivery_truth": {
            "provider_accepted": int(outbound.get("provider_accepted_total") or outbound.get("sent_total") or 0),
            "delivered_verified": int(outbound.get("delivered_verified") or brevo.get("delivered_verified_total") or 0),
            "replies_detected": int(outbound.get("replies_detected") or 0),
            "brevo_checks": int(brevo.get("checked") or 0),
        },
        "movement": {
            "requirements_ready_prev_cycle": int(((previous.get("requirement_completion") or {}).get("ready_after")) or 0),
            "requirements_ready_now": after_ready,
        },
        "search_spend_increased": False,
        "outbound_caps_increased": False,
        "binding_authority_changed": False,
    }
    state["revenue_sprint_v2"] = report
    return report


_install()

print({
    "revenue_sprint_v2_runtime": {
        "version": VERSION,
        "status": "installed",
        "official_document_broadening": True,
        "exact_evidence_requirement_gate": True,
        "first_cash_mission_focus": True,
        "search_spend_increased": False,
        "outbound_caps_increased": False,
        "binding_authority_changed": False,
    }
}, flush=True)
