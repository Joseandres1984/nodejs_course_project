from __future__ import annotations

"""LUMEN Zero Experiment Engine v1.

Turns the existing acquisition A/B surfaces into a deterministic 80/20 experiment loop:
4 decisions exploit the strongest currently observed variant and every 5th decision explores an
under-exposed alternative. The engine never creates paid spend, never accepts binding terms and
never bypasses the existing outbound/contact/publication gates.

Execution is deliberately conservative: the selected variant may enqueue one governed distribution
canary through the already-existing acquisition/distribution pipeline. Email canaries keep their
verified-business-contact, opt-out, risk and daily/cycle caps. Social publication and paid media
permissions are not expanded by this module.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import acquisition_campaigns as acquisition
import autonomous_director_runtime as director

VERSION = "1.0-zero-experiment-engine"
POLICY = "80_20_exploit_explore"
WINDOW_SIZE = 5
MAX_HISTORY = 100
MAX_DIRECTOR_PRIORITY = 99
DISPATCH_CHANNEL = "email_b2b"

_ORIGINAL_DIRECTOR_TICK = director.director_tick
_ORIGINAL_ACQUISITION_TICK = acquisition.acquisition_campaign_tick


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _d(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _l(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean(value: Any, limit: int = 160) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _mode_for_sequence(sequence: int) -> str:
    return "explore" if max(1, int(sequence)) % WINDOW_SIZE == 0 else "exploit"


def _audience_fit(bottleneck: str, audience: str) -> int:
    b = str(bottleneck or "").lower()
    audience = str(audience or "").lower()
    if any(token in b for token in ("demand", "buyer", "inbound")):
        return 3 if audience == "buyer" else 1
    if any(token in b for token in ("supplier", "supply", "quote", "offer")):
        return 3 if audience == "supplier" else 1
    if "partner" in b or "catalog" in b:
        return 3 if audience == "partner" else 1
    return 1


def _candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for campaign in _l(state.get("acquisition_campaigns")):
        if not isinstance(campaign, dict) or campaign.get("status") != "active":
            continue
        cid = _clean(campaign.get("id"), 80)
        champion = _clean(campaign.get("champion_variant_id"), 100)
        for variant in _l(campaign.get("variants")):
            if not isinstance(variant, dict) or not variant.get("id"):
                continue
            perf = _d(variant.get("performance"))
            rows.append({
                "campaign": campaign,
                "variant": variant,
                "campaign_id": cid,
                "variant_id": _clean(variant.get("id"), 100),
                "audience": _clean(campaign.get("audience"), 40),
                "is_champion": _clean(variant.get("id"), 100) == champion,
                "status": _clean(variant.get("status"), 40) or "testing",
                "clicks": max(0, _i(perf.get("clicks"))),
                "landing_views": max(0, _i(perf.get("landing_views"))),
                "leads": max(0, _i(perf.get("submissions"))),
                "verified_companies": max(0, _i(perf.get("verified_companies"))),
                "conversion_rate": max(0.0, min(1.0, _f(perf.get("click_to_lead_rate")))),
                "score": _f(perf.get("score")),
                "angle": _clean(variant.get("angle"), 80),
                "headline": _clean(variant.get("headline"), 220),
                "tracking_path": _clean(variant.get("tracking_path"), 180),
            })
    return rows


def _select_candidate(state: Dict[str, Any], mode: str, bottleneck: str = "") -> Optional[Dict[str, Any]]:
    rows = _candidates(state)
    if not rows:
        return None

    if mode == "explore":
        pool = [x for x in rows if not x["is_champion"] and x["status"] != "needs_rotation"]
        if not pool:
            pool = [x for x in rows if not x["is_champion"]]
        if not pool:
            pool = rows
        return sorted(
            pool,
            key=lambda x: (
                x["clicks"],
                x["landing_views"],
                -_audience_fit(bottleneck, x["audience"]),
                x["campaign_id"],
                x["variant_id"],
            ),
        )[0]

    champions = [x for x in rows if x["is_champion"] and x["status"] != "needs_rotation"]
    pool = champions or [x for x in rows if x["status"] != "needs_rotation"] or rows
    return sorted(
        pool,
        key=lambda x: (
            x["verified_companies"],
            x["leads"],
            x["conversion_rate"],
            x["score"],
            _audience_fit(bottleneck, x["audience"]),
            -x["clicks"],
            x["campaign_id"],
            x["variant_id"],
        ),
        reverse=True,
    )[0]


def _cognitive_truth(state: Dict[str, Any]) -> Dict[str, Any]:
    learning = _d(state.get("cognitive_director_learning"))
    product = _d(learning.get("top_product"))
    channel = _d(learning.get("top_channel"))
    return {
        "product_slug": _clean(product.get("product_slug"), 80) or None,
        "product_evidence_class": product.get("evidence_class"),
        "channel": _clean(channel.get("source"), 80) or None,
        "channel_campaign": _clean(channel.get("campaign"), 120) or None,
        "settled_count": max(0, _i(product.get("settled_count"))),
        "realized_revenue_usd": round(max(0.0, _f(product.get("realized_revenue_usd"))), 4),
        "outcome_samples": max(0, _i(product.get("samples"))),
    }


def _experiment_id(cycle: int, sequence: int, candidate: Dict[str, Any]) -> str:
    marker = cycle if cycle > 0 else sequence
    return f"EXP-{marker:06d}-{sequence:05d}-{candidate['variant_id']}"[:190]


def _payload_for(candidate: Dict[str, Any], channel: str) -> Optional[Dict[str, Any]]:
    campaign = candidate.get("campaign")
    variant = candidate.get("variant")
    if not isinstance(campaign, dict) or not isinstance(variant, dict):
        return None
    for payload in acquisition._channel_payloads(campaign, variant):
        if str(payload.get("channel") or "") == channel:
            return dict(payload)
    return None


def _queue_governed_canary(state: Dict[str, Any], experiment: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    channel = DISPATCH_CHANNEL
    payload = _payload_for(candidate, channel)
    if not payload:
        return {"queued": False, "channel": channel, "reason": "payload_unavailable"}
    if payload.get("requires_human_budget_approval") or channel == "paid_ads":
        return {"queued": False, "channel": channel, "reason": "paid_or_budget_gated"}

    queue = state.setdefault("acquisition_distribution_queue", [])
    key = f"EXPERIMENT|{experiment['id']}|{channel}"
    if any(str(row.get("key") or "") == key for row in queue if isinstance(row, dict)):
        return {"queued": False, "channel": channel, "reason": "already_queued", "key": key}

    queue.append({
        "key": key,
        "campaign_id": candidate["campaign_id"],
        "variant_id": candidate["variant_id"],
        "audience": candidate["audience"],
        "channel": channel,
        "payload": payload,
        "status": "ready_owned_or_existing_channel",
        "experiment_id": experiment["id"],
        "experiment_mode": experiment["mode"],
        "created_at": _now(),
        "updated_at": _now(),
    })
    state["acquisition_distribution_queue"] = queue[-300:]
    return {"queued": True, "channel": channel, "reason": "governed_canary_scheduled", "key": key}


def _roles(candidate: Dict[str, Any]) -> List[str]:
    audience = candidate.get("audience")
    if audience == "buyer":
        return ["market_manager", "buyer_hunter", "revops"]
    if audience == "supplier":
        return ["market_manager", "supplier_hunter", "revops"]
    return ["market_manager", "revops", "research_analyst"]


def _merge_boosts(base: Dict[str, Any], candidate: Dict[str, Any], mode: str) -> Dict[str, float]:
    out = {str(k): min(director.ROLE_BOOST_CAP, max(0.0, _f(v))) for k, v in _d(base).items()}
    amount = 0.09 if mode == "exploit" else 0.06
    for role in _roles(candidate):
        out[role] = round(min(director.ROLE_BOOST_CAP, max(_f(out.get(role)), amount)), 4)
    return out


def _refresh_history(state: Dict[str, Any], history: List[Dict[str, Any]]) -> None:
    current = {(x["campaign_id"], x["variant_id"]): x for x in _candidates(state)}
    for row in history[-25:]:
        key = (str(row.get("campaign_id") or ""), str(row.get("variant_id") or ""))
        now = current.get(key)
        if not now:
            continue
        row["observed_clicks"] = now["clicks"]
        row["observed_leads"] = now["leads"]
        row["observed_verified_companies"] = now["verified_companies"]
        row["observed_conversion_rate"] = round(now["conversion_rate"], 4)
        row["lead_delta"] = max(0, now["leads"] - _i(row.get("baseline_leads")))
        row["verified_delta"] = max(0, now["verified_companies"] - _i(row.get("baseline_verified_companies")))
        if row["lead_delta"] > 0 or row["verified_delta"] > 0:
            row["result"] = "commercial_progress_observed"
        elif _i(state.get("ticks")) > _i(row.get("cycle")):
            row.setdefault("result", "observing")
        row["observed_at"] = _now()


def _build_experiment(state: Dict[str, Any], candidate: Dict[str, Any], mode: str, sequence: int, bottleneck: str, target_metric: str) -> Dict[str, Any]:
    cycle = max(0, _i(state.get("ticks")))
    cognitive = _cognitive_truth(state)
    evidence = (
        f"clicks={candidate['clicks']}, leads={candidate['leads']}, verified={candidate['verified_companies']}, "
        f"conversion={candidate['conversion_rate']:.1%}"
    )
    if mode == "exploit":
        decision = f"Explotar {candidate['variant_id']} y medir lead verificado/cobro sin ampliar gasto."
        hypothesis = f"La variante con mejor señal comercial actual debería convertir mejor que una alternativa menos probada ({evidence})."
    else:
        decision = f"Explorar {candidate['variant_id']} con capacidad acotada para buscar una alternativa superior."
        hypothesis = f"Una variante menos expuesta puede superar al champion sin abandonar la vía principal ({evidence})."

    return {
        "id": _experiment_id(cycle, sequence, candidate),
        "version": VERSION,
        "created_at": _now(),
        "cycle": cycle,
        "sequence": sequence,
        "mode": mode,
        "policy": POLICY,
        "campaign_id": candidate["campaign_id"],
        "variant_id": candidate["variant_id"],
        "audience": candidate["audience"],
        "angle": candidate["angle"],
        "headline": candidate["headline"],
        "tracking_path": candidate["tracking_path"],
        "hypothesis": hypothesis,
        "next_decision": decision,
        "bottleneck": bottleneck,
        "target_metric": target_metric,
        "baseline_clicks": candidate["clicks"],
        "baseline_leads": candidate["leads"],
        "baseline_verified_companies": candidate["verified_companies"],
        "baseline_conversion_rate": round(candidate["conversion_rate"], 4),
        "product_winner": cognitive["product_slug"],
        "channel_winner": cognitive["channel"],
        "channel_winner_campaign": cognitive["channel_campaign"],
        "verified_settlements": cognitive["settled_count"],
        "verified_revenue_usd": cognitive["realized_revenue_usd"],
        "outcome_samples": cognitive["outcome_samples"],
        "status": "scheduled",
        "spend_usd": 0,
        "binding": False,
        "paid_media": False,
        "hard_bottleneck_override": False,
    }


def experiment_engine_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    previous = _d(state.get("experiment_engine"))
    history = [dict(x) for x in _l(previous.get("history")) if isinstance(x, dict)]
    _refresh_history(state, history)
    sequence = max(0, _i(previous.get("decision_sequence"))) + 1
    mode = _mode_for_sequence(sequence)
    director_state = _d(state.get("autonomous_director"))
    bottleneck = str(director_state.get("bottleneck") or "")
    target_metric = str(director_state.get("target_metric") or "")
    candidate = _select_candidate(state, mode, bottleneck)

    if not candidate:
        report = {
            "version": VERSION,
            "status": "waiting_for_acquisition_variants",
            "updated_at": _now(),
            "policy": POLICY,
            "exploit_share": 0.80,
            "explore_share": 0.20,
            "decision_sequence": sequence,
            "current_experiment": None,
            "history": history[-MAX_HISTORY:],
            "winner_product": None,
            "winner_channel": None,
            "verified_settlements": 0,
            "verified_revenue_usd": 0,
            "bottleneck": bottleneck or None,
            "next_decision": "Esperar variantes atribuibles antes de asignar capacidad experimental.",
            "guardrails": {"monetary_budget_usd": 0, "paid_media_authority_changed": False, "binding_authority_changed": False, "search_budget_increased": False, "hard_bottleneck_override": False},
        }
        state["experiment_engine"] = report
        return report

    experiment = _build_experiment(state, candidate, mode, sequence, bottleneck, target_metric)
    experiment["dispatch"] = _queue_governed_canary(state, experiment, candidate)
    history.append(dict(experiment))
    cognitive = _cognitive_truth(state)
    report = {
        "version": VERSION,
        "status": "active",
        "updated_at": _now(),
        "policy": POLICY,
        "exploit_share": 0.80,
        "explore_share": 0.20,
        "decision_sequence": sequence,
        "exploit_decisions": max(0, _i(previous.get("exploit_decisions"))) + (1 if mode == "exploit" else 0),
        "explore_decisions": max(0, _i(previous.get("explore_decisions"))) + (1 if mode == "explore" else 0),
        "current_experiment": experiment,
        "history": history[-MAX_HISTORY:],
        "winner_product": cognitive["product_slug"],
        "winner_channel": cognitive["channel"],
        "verified_settlements": cognitive["settled_count"],
        "verified_revenue_usd": cognitive["realized_revenue_usd"],
        "outcome_samples": cognitive["outcome_samples"],
        "bottleneck": bottleneck or None,
        "next_decision": experiment["next_decision"],
        "guardrails": {"monetary_budget_usd": 0, "paid_media_authority_changed": False, "binding_authority_changed": False, "search_budget_increased": False, "hard_bottleneck_override": False, "governed_outbound_caps_preserved": True},
    }
    state["experiment_engine"] = report
    return report


def _experiment_task(engine: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    experiment = _d(engine.get("current_experiment"))
    if not experiment:
        return None
    candidate_stub = {"audience": str(experiment.get("audience") or "")}
    strong = _i(experiment.get("baseline_leads")) > 0 or _f(experiment.get("verified_revenue_usd")) > 0
    mode = str(experiment.get("mode") or "exploit")
    priority = 97 if mode == "exploit" and strong else (92 if mode == "exploit" else 86)
    return {
        "id": "DIR-EXPERIMENT-ENGINE",
        "title": f"{mode.upper()} {experiment.get('campaign_id')} / {experiment.get('variant_id')}",
        "priority": min(MAX_DIRECTOR_PRIORITY, priority),
        "roles": _roles(candidate_stub),
        "action": experiment.get("next_decision"),
        "success_metric": "qualified_lead_or_verified_settlement",
        "mode": f"experiment_{mode}",
        "autonomous": True,
        "spend_usd": 0,
        "binding": False,
        "experiment_id": experiment.get("id"),
        "campaign_id": experiment.get("campaign_id"),
        "variant_id": experiment.get("variant_id"),
        "hard_bottleneck_override": False,
    }


def director_tick_with_experiments(state: Dict[str, Any], adaptive_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    report = dict(_ORIGINAL_DIRECTOR_TICK(state, adaptive_report) or {})
    engine = _d(state.get("experiment_engine"))
    task = _experiment_task(engine)
    if not task:
        report["experiment_engine"] = {"version": VERSION, "status": engine.get("status") or "not_initialized", "policy": POLICY, "hard_bottleneck_preserved": True, "monetary_budget_usd": 0}
        return report

    plan = [dict(x) for x in _l(report.get("plan")) if isinstance(x, dict) and x.get("id") != "DIR-EXPERIMENT-ENGINE"]
    plan.append(task)
    plan.sort(key=lambda row: _i(row.get("priority")), reverse=True)
    report["plan"] = plan[: int(getattr(director, "MAX_PLAN", 6))]
    experiment = _d(engine.get("current_experiment"))
    report["role_boosts"] = _merge_boosts(_d(report.get("role_boosts")), {"audience": experiment.get("audience")}, str(experiment.get("mode") or "exploit"))
    report["experiment_engine"] = {
        "version": VERSION,
        "status": engine.get("status") or "active",
        "policy": POLICY,
        "mode": experiment.get("mode"),
        "experiment_id": experiment.get("id"),
        "campaign_id": experiment.get("campaign_id"),
        "variant_id": experiment.get("variant_id"),
        "dispatch": experiment.get("dispatch"),
        "next_decision": experiment.get("next_decision"),
        "hard_bottleneck_preserved": True,
        "monetary_budget_usd": 0,
    }
    authority = dict(_d(report.get("authority")))
    authority.update({"experiment_engine_authority": "reversible_zero_cost_testing_only", "experiment_engine_monetary_budget_usd": 0, "experiment_engine_paid_media_authority_changed": False, "experiment_engine_binding_authority_changed": False, "experiment_engine_search_budget_increased": False, "experiment_engine_hard_bottleneck_override": False})
    report["authority"] = authority
    state["autonomous_director"] = report
    return report


def acquisition_tick_with_experiments(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_ACQUISITION_TICK(state) or {})
    engine = experiment_engine_tick(state)
    current = _d(engine.get("current_experiment"))
    report["experiment_engine"] = {"version": VERSION, "status": engine.get("status"), "policy": POLICY, "mode": current.get("mode"), "experiment_id": current.get("id"), "variant_id": current.get("variant_id"), "dispatch": current.get("dispatch"), "monetary_budget_usd": 0}
    return report


# Acquisition is wrapped so the experiment is selected after canonical campaign performance refresh
# and before distribution runs. Director is wrapped after Cognitive learning in worker_entry.
director.director_tick = director_tick_with_experiments
acquisition.acquisition_campaign_tick = acquisition_tick_with_experiments

print({"experiment_engine_runtime": {"version": VERSION, "status": "installed", "policy": POLICY, "exploit_share": 0.80, "explore_share": 0.20, "dispatch_channel": DISPATCH_CHANNEL, "monetary_budget_usd": 0, "paid_media_authority_changed": False, "binding_authority_changed": False, "search_budget_increased": False, "hard_bottleneck_override": False}}, flush=True)
