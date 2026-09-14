from __future__ import annotations

import hashlib
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List

import market_pipeline

VERSION = "1.0-opportunity-factory"
MAX_CASES = 80
MAX_ACTIONS = 8


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any, limit: int = 400) -> str:
    return " ".join(str(value or "").split())[:limit]


def _norm(value: Any) -> str:
    return _clean(value, 240).lower()


def _host(value: Any) -> str:
    try:
        return (urllib.parse.urlparse(str(value or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _stable(*parts: Any) -> str:
    raw = "|".join(str(x or "") for x in parts)
    return "OF-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _signal_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("unlinked_demand_signals", "public_procurement_signals"):
        for row in state.get(key, []) or []:
            if not isinstance(row, dict):
                continue
            ident = str(row.get("id") or row.get("url") or row.get("source_url") or _stable(row.get("title"), row.get("category")))
            if ident in seen:
                continue
            seen.add(ident)
            rows.append(row)
    return rows


def _match_buyer(signal: Dict[str, Any], accounts: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    explicit = str(signal.get("buyer_account_id") or "")
    if explicit:
        exact = next((x for x in accounts if str(x.get("id") or "") == explicit and x.get("type") == "buyer"), None)
        if exact:
            return exact

    source_host = _host(signal.get("url") or signal.get("source_url"))
    if source_host:
        exact = next((x for x in accounts if x.get("type") == "buyer" and source_host in {
            _host(x.get("official_url")), _norm(x.get("domain")).removeprefix("www.")
        }), None)
        if exact:
            return exact
    return None


def _supplier_matches(signal: Dict[str, Any], accounts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    category = _norm(signal.get("category"))
    if not category:
        return []
    exact = [x for x in accounts if x.get("type") == "supplier" and x.get("verified_company") and _norm(x.get("category")) == category]
    return exact[:3]


def _case(signal: Dict[str, Any], accounts: List[Dict[str, Any]]) -> Dict[str, Any]:
    buyer = _match_buyer(signal, accounts)
    suppliers = _supplier_matches(signal, accounts)
    buyer_verified = bool(buyer and buyer.get("verified_company"))
    demand_verified = bool(buyer and buyer.get("demand_signal"))
    buyer_contact = bool(buyer and (buyer.get("commercial_channel_verified") or buyer.get("verified_contact")))
    requirement_evidence = len(_clean(signal.get("summary") or signal.get("description"))) >= 70
    supplier_ready = bool(suppliers)

    missing: List[str] = []
    if not buyer:
        missing.append("buyer_identity")
    elif not buyer_verified:
        missing.append("buyer_verification")
    if not demand_verified:
        missing.append("demand_confirmation")
    if not requirement_evidence:
        missing.append("requirement_details")
    if buyer_verified and not buyer_contact:
        missing.append("buyer_contact")
    if buyer_verified and demand_verified and not supplier_ready:
        missing.append("verified_supplier_match")

    if not missing:
        next_action = "Reevaluar Market Pipeline para materializar una oportunidad evidence-backed."
        stage = "READY_FOR_PIPELINE"
    else:
        next_map = {
            "buyer_identity": "Resolver la identidad legal/corporativa del comprador sin asumirla por el portal fuente.",
            "buyer_verification": "Verificar la empresa compradora con evidencia corporativa independiente.",
            "demand_confirmation": "Confirmar que la demanda pertenece al comprador y sigue vigente.",
            "requirement_details": "Extraer alcance, cantidades, especificaciones, fechas y condiciones del requerimiento.",
            "buyer_contact": "Encontrar y verificar un canal comercial corporativo del comprador.",
            "verified_supplier_match": "Encontrar hasta 3 proveedores verificados de la misma categoría.",
        }
        next_action = next_map[missing[0]]
        stage = "ENRICHMENT"

    raw_score = max(_f(signal.get("score"), 50.0), 50.0)
    completeness = sum([buyer_verified, demand_verified, buyer_contact, requirement_evidence, supplier_ready]) / 5.0
    priority = round(min(100.0, raw_score * 0.72 + completeness * 28.0), 1)
    return {
        "id": _stable(signal.get("id"), signal.get("url"), signal.get("title")),
        "signal_id": signal.get("id"),
        "title": _clean(signal.get("title") or signal.get("summary") or "Señal de demanda", 220),
        "category": _clean(signal.get("category"), 160),
        "source": signal.get("source"),
        "url": signal.get("url") or signal.get("source_url"),
        "signal_score": round(raw_score, 1),
        "priority": priority,
        "stage": stage,
        "buyer_account_id": buyer.get("id") if buyer else None,
        "buyer_verified": buyer_verified,
        "demand_verified": demand_verified,
        "buyer_contact_verified": buyer_contact,
        "requirement_evidence": requirement_evidence,
        "supplier_matches": [x.get("id") for x in suppliers],
        "missing": missing,
        "next_action": next_action,
        "ready_for_pipeline": not bool(missing),
        "truth_rule": "signal_is_not_opportunity_until_buyer_demand_supplier_evidence_passes_existing_pipeline_gates",
        "updated_at": utcnow(),
    }


def _inject_actions(state: Dict[str, Any], cases: List[Dict[str, Any]]) -> int:
    existing = [x for x in state.get("operating_action_queue", []) or [] if not str(x.get("key") or "").startswith("opportunity_factory|")]
    actions: List[Dict[str, Any]] = []
    for case in cases[:MAX_ACTIONS]:
        if case.get("ready_for_pipeline"):
            continue
        actions.append({
            "key": f"opportunity_factory|{case['id']}",
            "kind": "opportunity_enrichment",
            "title": f"Opportunity Factory: {case['title']}",
            "reason": case["next_action"],
            "impact": case["priority"],
            "urgency": case["priority"],
            "confidence": min(0.95, max(0.55, case["signal_score"] / 100.0)),
            "effort": 1.0,
            "risk": "low",
            "autonomous": True,
            "object_type": "opportunity_factory_case",
            "object_id": case["id"],
            "priority_score": case["priority"],
            "payload": {
                "signal_id": case.get("signal_id"),
                "category": case.get("category"),
                "missing": list(case.get("missing") or []),
                "next_action": case.get("next_action"),
            },
            "created_at": utcnow(),
        })
    merged = existing + actions
    merged.sort(key=lambda x: _f(x.get("priority_score")), reverse=True)
    state["operating_action_queue"] = merged[:120]
    return len(actions)


def opportunity_factory_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    accounts = list(state.get("candidate_accounts", []) or [])
    signals = _signal_rows(state)
    cases = [_case(x, accounts) for x in signals]
    cases.sort(key=lambda x: (x["ready_for_pipeline"], x["priority"]), reverse=True)
    cases = cases[:MAX_CASES]

    before = len(state.get("market_opportunities", []) or [])
    pipeline = dict(market_pipeline.build_market_pipeline(state) or {})
    after = len(state.get("market_opportunities", []) or [])
    actions = _inject_actions(state, cases)

    report = {
        "version": VERSION,
        "status": "active",
        "updated_at": utcnow(),
        "signals_reviewed": len(signals),
        "cases_total": len(cases),
        "ready_for_pipeline": sum(1 for x in cases if x.get("ready_for_pipeline")),
        "enrichment_required": sum(1 for x in cases if not x.get("ready_for_pipeline")),
        "actions_injected": actions,
        "opportunities_before": before,
        "opportunities_after": after,
        "opportunities_materialized": max(0, after - before),
        "pipeline_stats": pipeline,
        "top_cases": cases[:8],
        "authority": "research_enrichment_and_existing_evidence_gated_pipeline_only",
        "guardrails": {
            "fabricate_buyer_identity": False,
            "fabricate_demand": False,
            "lower_market_pipeline_threshold": False,
            "binding_outreach_or_order": False,
        },
    }
    state["opportunity_factory"] = report
    state["opportunity_factory_cases"] = cases
    return report
