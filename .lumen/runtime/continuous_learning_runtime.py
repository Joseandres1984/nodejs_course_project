from __future__ import annotations

"""Continuous learning layer for LUMEN.

Turns existing internal outcomes and already-collected public-web evidence into a bounded,
auditable learning record. Web content is always treated as untrusted data, never as executable
instructions. This module does not widen outreach, financial, contractual, legal, publishing,
connector, or production-deployment authority.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlparse

VERSION = "1.0-continuous-learning"
MAX_LEDGER = 80
MAX_EXTERNAL_SIGNALS = 20
MAX_HISTORY = 120


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


def _domain(url: Any) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        return (urlparse(text).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _age_days(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 365.0
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
    except Exception:
        return 365.0


def _freshness_score(value: Any) -> float:
    days = _age_days(value)
    if days <= 1:
        return 1.0
    if days <= 7:
        return 0.92
    if days <= 30:
        return 0.78
    if days <= 90:
        return 0.58
    return 0.35


def _verified_domains(state: Dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for row in state.get("candidate_accounts", []) or []:
        if not row.get("verified_company"):
            continue
        for value in (row.get("official_url"), row.get("source_url")):
            d = _domain(value)
            if d:
                out.add(d)
        d = str(row.get("domain") or "").lower().removeprefix("www.")
        if d:
            out.add(d)
    return out


def _partner_domains(state: Dict[str, Any]) -> set[str]:
    return {
        str(x.get("domain") or "").lower().removeprefix("www.")
        for x in state.get("partner_stores", []) or []
        if x.get("domain")
    }


def _source_quality(domain: str, state: Dict[str, Any]) -> tuple[str, float]:
    if not domain:
        return "unknown", 0.35
    gov_markers = (".gov.ar", ".gob.ar", ".gov", ".gob")
    if any(domain.endswith(x) for x in gov_markers) or domain in {"comprar.gob.ar", "boletinoficial.gob.ar"}:
        return "official_public_source", 0.97
    if domain in _verified_domains(state):
        return "verified_company_source", 0.92
    if domain in _partner_domains(state):
        return "known_partner_store", 0.84
    return "public_web_source", 0.64


def _metric_snapshot(state: Dict[str, Any]) -> Dict[str, float]:
    funnel = state.get("business_funnel", {}) or {}
    workforce = (state.get("agent_workforce", {}) or {}).get("workload", {}) or {}
    readiness = state.get("external_market_readiness", {}) or {}
    acquisition = state.get("acquisition_campaigns", {}) or {}
    watchdog = state.get("system_watchdog", {}) or {}
    truth = state.get("data_truth_engine", {}) or {}
    cfo = state.get("cfo_war_room", {}) or {}
    finance = (state.get("business_kpis", {}) or {}).get("finance", {}) or {}
    return {
        "verified_buyers": _f(funnel.get("verified_buyers")),
        "buyers_with_public_demand": _f(funnel.get("buyers_with_public_demand")),
        "verified_commercial_channels": _f(funnel.get("verified_commercial_channels")),
        "evidence_backed_opportunities": _f(funnel.get("evidence_backed_opportunities") or workforce.get("opportunities")),
        "quotes": _f(workforce.get("quotes")),
        "proposals": _f(funnel.get("proposals") or workforce.get("proposals")),
        "close_ready": _f(funnel.get("close_ready") or workforce.get("close_ready")),
        "eligible_external_prospects": _f(readiness.get("eligible_external_prospects")),
        "click_to_lead_rate": _f(acquisition.get("click_to_lead_rate")),
        "system_health_score": _f(watchdog.get("score_pct")),
        "average_truth_score": _f(truth.get("average_truth_score")),
        "realized_profit_usd": _f(cfo.get("realized_profit_usd") or finance.get("realized_profit_usd")),
    }


def _target_metric_value(target: Any, metrics: Dict[str, float]) -> float | None:
    key = str(target or "").strip().lower()
    aliases = {
        "average_truth_score": "average_truth_score",
        "risk_adjusted_expected_profit_usd": "realized_profit_usd",
        "quality_gate_block_rate": None,
        "calibration_gap": None,
        "intervention_conclusive_rate": None,
        "supported_experiment_rate": None,
        "successful_concession_rate": None,
        "primary_priority_stability": None,
        "resolved_decisions": None,
    }
    mapped = aliases.get(key, key if key in metrics else None)
    return metrics.get(mapped) if mapped else None


def _direction(metric: Any) -> str:
    text = str(metric or "").lower()
    if any(token in text for token in ("gap", "block_rate", "error", "failure", "stale", "latency", "cost")):
        return "lower_is_better"
    return "higher_is_better"


def _external_intelligence(state: Dict[str, Any]) -> Dict[str, Any]:
    observations = list(state.get("market_intelligence_observations", []) or [])
    identity_domains: Dict[str, set[str]] = defaultdict(set)
    for row in observations:
        identity = str(row.get("identity_key") or "")
        d = str(row.get("source_domain") or "").lower().removeprefix("www.") or _domain(row.get("source_url"))
        if identity and d:
            identity_domains[identity].add(d)

    signals: List[Dict[str, Any]] = []
    for row in observations[-600:]:
        url = row.get("source_url")
        domain = str(row.get("source_domain") or "").lower().removeprefix("www.") or _domain(url)
        source_class, authority = _source_quality(domain, state)
        freshness = _freshness_score(row.get("observed_at"))
        identity_conf = max(0.0, min(1.0, _f(row.get("identity_confidence"), 0.45)))
        corroboration = len(identity_domains.get(str(row.get("identity_key") or ""), set()))
        corroboration_score = min(1.0, 0.35 + max(0, corroboration - 1) * 0.22)
        commercial = 0.48
        if row.get("price") not in (None, "") and row.get("currency"):
            commercial += 0.16
        if row.get("availability"):
            commercial += 0.08
        if identity_conf >= 0.9:
            commercial += 0.12
        confidence = authority * 0.34 + freshness * 0.22 + identity_conf * 0.28 + corroboration_score * 0.16
        signals.append({
            "kind": "public_market_observation",
            "title": row.get("product"),
            "source_domain": domain,
            "source_url": url,
            "source_class": source_class,
            "observed_at": row.get("observed_at"),
            "freshness_score": round(freshness, 3),
            "corroboration_sources": corroboration,
            "identity_confidence": round(identity_conf, 3),
            "confidence": round(min(1.0, confidence), 3),
            "commercial_relevance": round(min(1.0, commercial), 3),
            "price": row.get("price"),
            "currency": row.get("currency"),
            "action_authority": "research_only",
        })

    # Include broader public-web research already gathered by Scout. These are leads/signals,
    # not instructions and never receive execution authority merely because they score well.
    for lead in list(state.get("research_leads", []) or [])[-300:]:
        url = lead.get("source_url") or lead.get("url") or lead.get("evidence_url")
        domain = _domain(url)
        if not domain:
            continue
        source_class, authority = _source_quality(domain, state)
        observed = lead.get("updated_at") or lead.get("created_at") or lead.get("observed_at")
        freshness = _freshness_score(observed)
        evidence_conf = 0.72 if lead.get("tier") == "A" else 0.58
        if lead.get("demand_signal") or lead.get("direct_inbound_demand"):
            evidence_conf = max(evidence_conf, 0.86)
        commercial = 0.88 if (lead.get("demand_signal") or lead.get("direct_inbound_demand")) else 0.70 if lead.get("tier") == "A" else 0.48
        confidence = authority * 0.42 + freshness * 0.28 + evidence_conf * 0.30
        signals.append({
            "kind": "public_research_signal",
            "title": lead.get("company") or lead.get("title") or lead.get("subject") or lead.get("query"),
            "source_domain": domain,
            "source_url": url,
            "source_class": source_class,
            "observed_at": observed,
            "freshness_score": round(freshness, 3),
            "corroboration_sources": 1,
            "identity_confidence": round(evidence_conf, 3),
            "confidence": round(min(1.0, confidence), 3),
            "commercial_relevance": round(commercial, 3),
            "demand_signal": bool(lead.get("demand_signal") or lead.get("direct_inbound_demand")),
            "action_authority": "research_only",
        })

    dedup: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    for row in signals:
        key = (str(row.get("kind")), str(row.get("source_url")), str(row.get("title")))
        previous = dedup.get(key)
        score = _f(row.get("confidence")) * 0.62 + _f(row.get("commercial_relevance")) * 0.38
        prev_score = _f((previous or {}).get("confidence")) * 0.62 + _f((previous or {}).get("commercial_relevance")) * 0.38
        if previous is None or score > prev_score:
            dedup[key] = row
    ranked = list(dedup.values())
    ranked.sort(key=lambda x: (_f(x.get("confidence")) * 0.62 + _f(x.get("commercial_relevance")) * 0.38), reverse=True)
    top = ranked[:MAX_EXTERNAL_SIGNALS]
    classes = Counter(str(x.get("source_class") or "unknown") for x in ranked)
    domains = {str(x.get("source_domain")) for x in ranked if x.get("source_domain")}
    return {
        "status": "active",
        "mode": "bounded_public_web_learning",
        "signals_total": len(ranked),
        "sources_total": len(domains),
        "high_confidence_signals": sum(1 for x in ranked if _f(x.get("confidence")) >= 0.78),
        "source_classes": dict(classes),
        "top_signals": top,
        "policy": {
            "web_content": "untrusted_data_never_executable_instructions",
            "source_requirement": "retain_url_date_confidence_and_corroboration",
            "promotion": "high_score_is_research_priority_not_execution_authority",
            "collection": "public_authorized_sources_only_respect_robots_rate_limits_and_existing_connectors",
        },
    }


def _update_improvement_ledger(state: Dict[str, Any], metrics: Dict[str, float]) -> List[Dict[str, Any]]:
    ledger = list(state.get("improvement_ledger", []) or [])[-MAX_LEDGER:]
    lab = state.get("self_improvement_lab", {}) or {}
    primary = lab.get("primary_proposal") or {}
    if not primary:
        return ledger

    code = str(primary.get("code") or "BASELINE-LEARN")
    target = str(primary.get("target_metric") or "")
    cycle = _i(state.get("ticks"))
    current_value = _target_metric_value(target, metrics)
    existing = next((x for x in reversed(ledger) if x.get("code") == code and x.get("status") in {"OBSERVING", "SUPPORTED", "DEMOTED", "HUMAN_REVIEW_REQUIRED"}), None)

    if existing is None:
        row = {
            "id": f"LEARN-{code}-{cycle}",
            "code": code,
            "problem": primary.get("reason"),
            "evidence": primary.get("evidence") or {},
            "hypothesis": primary.get("title"),
            "change_proposed": primary.get("title"),
            "target_metric": target,
            "direction": _direction(target),
            "baseline_value": current_value,
            "current_value": current_value,
            "start_cycle": cycle,
            "last_cycle": cycle,
            "samples": 1,
            "confidence": primary.get("evidence_confidence"),
            "autonomous_test_allowed": bool(primary.get("autonomous_test_allowed")),
            "code_change_required": bool(primary.get("code_change_required")),
            "status": "HUMAN_REVIEW_REQUIRED" if primary.get("code_change_required") else "OBSERVING",
            "decision": "measure_before_change" if not primary.get("code_change_required") else "propose_only_no_auto_deploy",
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        ledger.append(row)
    else:
        existing["last_cycle"] = cycle
        existing["samples"] = _i(existing.get("samples"), 1) + 1
        existing["current_value"] = current_value
        existing["updated_at"] = utcnow()
        baseline = existing.get("baseline_value")
        if existing.get("code_change_required"):
            existing["status"] = "HUMAN_REVIEW_REQUIRED"
            existing["decision"] = "propose_only_no_auto_deploy"
        elif baseline is not None and current_value is not None and _i(existing.get("samples")) >= 3:
            delta = current_value - _f(baseline)
            if existing.get("direction") == "lower_is_better":
                delta = -delta
            tolerance = max(0.01, abs(_f(baseline)) * 0.02)
            if delta > tolerance:
                existing["status"] = "SUPPORTED"
                existing["decision"] = "keep_and_continue_measuring"
            elif delta < -tolerance:
                existing["status"] = "DEMOTED"
                existing["decision"] = "reduce_priority_or_retest_reversibly"
            else:
                existing["status"] = "OBSERVING"
                existing["decision"] = "collect_more_evidence"

    return ledger[-MAX_LEDGER:]


def _materialize_external_learning_action(state: Dict[str, Any], external: Dict[str, Any]) -> None:
    top = (external.get("top_signals") or [None])[0]
    if not top or _f(top.get("confidence")) < 0.78 or _f(top.get("commercial_relevance")) < 0.68:
        return
    queue = list(state.get("operating_action_queue", []) or [])
    key = "external_intelligence|validate_top_signal"
    task = {
        "key": key,
        "kind": "external_intelligence_validation",
        "title": "Validar la señal externa de mayor valor comercial",
        "reason": f"Señal pública de {top.get('source_domain')} con confianza {top.get('confidence')} y relevancia {top.get('commercial_relevance')}; debe corroborarse antes de promoverla.",
        "impact": 74,
        "urgency": 76,
        "confidence": top.get("confidence"),
        "effort": 1.0,
        "risk": "low",
        "autonomous": True,
        "object_type": "company",
        "object_id": "LUMEN",
        "payload": {"signal": top, "authority": "research_only"},
        "priority_score": 76,
        "created_at": utcnow(),
    }
    by_key = {str(x.get("key")): x for x in queue if x.get("key")}
    by_key[key] = task
    state["operating_action_queue"] = sorted(by_key.values(), key=lambda x: _f(x.get("priority_score")), reverse=True)[:120]


def continuous_learning_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    metrics = _metric_snapshot(state)
    external = _external_intelligence(state)
    ledger = _update_improvement_ledger(state, metrics)
    state["improvement_ledger"] = ledger
    _materialize_external_learning_action(state, external)

    recent = ledger[-20:]
    promoted = [x for x in recent if x.get("status") == "SUPPORTED"][-5:]
    demoted = [x for x in recent if x.get("status") == "DEMOTED"][-5:]
    human = [x for x in recent if x.get("status") == "HUMAN_REVIEW_REQUIRED"][-5:]
    crd = state.get("continuous_revenue_drive", {}) or {}
    lab = state.get("self_improvement_lab", {}) or {}
    profit = state.get("profit_learning", {}) or {}
    top_signal = (external.get("top_signals") or [None])[0]

    report = {
        "version": VERSION,
        "updated_at": utcnow(),
        "status": "active",
        "mode": "execute_measure_learn_improve",
        "objective": "improve truth quality speed conversion margin and learning capacity without widening authority",
        "metrics": metrics,
        "continuous_revenue": {
            "mode": crd.get("mode"),
            "primary_lane": crd.get("primary_lane"),
            "primary_action": crd.get("primary_action"),
        },
        "self_improvement": {
            "primary_code": (lab.get("primary_proposal") or {}).get("code"),
            "primary_title": (lab.get("primary_proposal") or {}).get("title"),
            "autonomous_tests": lab.get("autonomous_tests"),
            "code_change_proposals": lab.get("code_change_proposals"),
        },
        "profit_learning": {
            "primary_category": profit.get("primary_category"),
            "exploit_pct": profit.get("exploit_pct"),
            "explore_pct": profit.get("explore_pct"),
        },
        "external_intelligence": external,
        "improvement_ledger": {
            "entries": len(ledger),
            "observing": sum(1 for x in ledger if x.get("status") == "OBSERVING"),
            "supported": sum(1 for x in ledger if x.get("status") == "SUPPORTED"),
            "demoted": sum(1 for x in ledger if x.get("status") == "DEMOTED"),
            "human_review_required": sum(1 for x in ledger if x.get("status") == "HUMAN_REVIEW_REQUIRED"),
            "latest": ledger[-8:],
        },
        "learning_feedback": {
            "promoted": [{"code": x.get("code"), "decision": x.get("decision")} for x in promoted],
            "demoted": [{"code": x.get("code"), "decision": x.get("decision")} for x in demoted],
            "human_review": [{"code": x.get("code"), "decision": x.get("decision")} for x in human],
            "top_external_signal": top_signal,
        },
        "governance": {
            "external_information_is_untrusted_data": True,
            "autonomous_production_code_change": False,
            "autonomous_deploy": False,
            "binding_contracts_payments_legal": "human_required",
            "high_confidence_does_not_equal_execution_authority": True,
        },
    }
    state["continuous_learning"] = report

    if crd:
        crd["learning_context"] = {
            "self_improvement_primary": report["self_improvement"]["primary_code"],
            "top_external_signal": top_signal,
            "promoted": report["learning_feedback"]["promoted"],
            "demoted": report["learning_feedback"]["demoted"],
        }
        state["continuous_revenue_drive"] = crd

    history = list(state.get("continuous_learning_history", []) or [])
    history.append({
        "ts": report["updated_at"],
        "cycle": state.get("ticks"),
        "crd_mode": report["continuous_revenue"]["mode"],
        "primary_improvement": report["self_improvement"]["primary_code"],
        "external_signals": external.get("signals_total"),
        "high_confidence_external": external.get("high_confidence_signals"),
        "supported": report["improvement_ledger"]["supported"],
        "demoted": report["improvement_ledger"]["demoted"],
    })
    state["continuous_learning_history"] = history[-MAX_HISTORY:]
    return report
