from __future__ import annotations

"""LUMEN Zero Commercial Experiment Engine v1.

Runs bounded, deterministic commercial experiments over the existing acquisition variants.
The engine deliberately allocates most cycles to the current champion while reserving a small
exploration lane for a challenger. It never creates paid spend, binding authority, new search
budget or production self-modification.

The engine also exposes the already-learned Cognitive Director product/channel signals so the
Autonomous Director can combine experimentation with real downstream outcome evidence.
"""

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import autonomous_director_runtime as director

VERSION = "1.0-commercial-experiment-engine"
EXPLOIT_SHARE = 0.80
EXPLORE_SHARE = 0.20
ALLOCATION_BUCKETS = 5
MIN_EVALUATION_CLICKS = 8
MIN_WIN_LEADS = 1
MAX_HISTORY = 120
MAX_EXPERIMENTS = 24
MAX_PLAN = int(getattr(director, "MAX_PLAN", 6))
ROLE_BOOST_CAP = float(getattr(director, "ROLE_BOOST_CAP", 0.12))

_ORIGINAL_DIRECTOR_TICK = director.director_tick


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
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


def _cycle(state: Dict[str, Any]) -> int:
    workforce = _safe_dict(_safe_dict(state.get("agent_workforce")).get("last_cycle"))
    return max(1, _i(workforce.get("company_cycle"), _i(state.get("ticks"), 1)))


def _perf(variant: Dict[str, Any]) -> Dict[str, Any]:
    p = _safe_dict(variant.get("performance"))
    clicks = max(0, _i(p.get("clicks")))
    leads = max(0, _i(p.get("submissions")))
    verified = max(0, _i(p.get("verified_companies")))
    rate = leads / max(1, clicks)
    score = verified * 100.0 + leads * 35.0 + rate * 20.0 + min(clicks, 20) * 0.05
    return {
        "clicks": clicks,
        "leads": leads,
        "verified_companies": verified,
        "lead_rate": round(rate, 4),
        "score": round(score, 4),
    }


def _rank_key(variant: Dict[str, Any]) -> tuple[float, int, int, str]:
    p = _perf(variant)
    return (p["score"], p["verified_companies"], p["leads"], str(variant.get("id") or ""))


def _champion(campaign: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    variants = [v for v in _safe_list(campaign.get("variants")) if isinstance(v, dict) and v.get("id")]
    if not variants:
        return None
    current_id = str(campaign.get("champion_variant_id") or "")
    current = next((v for v in variants if str(v.get("id") or "") == current_id), None)
    converting = [v for v in variants if _perf(v)["leads"] > 0 or _perf(v)["verified_companies"] > 0]
    if converting:
        best = max(converting, key=_rank_key)
        if current and _perf(current)["leads"] > 0 and _perf(best)["score"] <= _perf(current)["score"]:
            return current
        return best
    return current or variants[0]


def _challenger(campaign: Dict[str, Any], champion: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    variants = [
        v for v in _safe_list(campaign.get("variants"))
        if isinstance(v, dict) and v.get("id") and str(v.get("id")) != str(champion.get("id"))
    ]
    if not variants:
        return None
    return min(
        variants,
        key=lambda v: (
            _perf(v)["clicks"],
            -_perf(v)["leads"],
            -_perf(v)["verified_companies"],
            str(v.get("id") or ""),
        ),
    )


def _allocation_phase(campaign_id: str, cycle: int) -> str:
    offset = int(hashlib.sha1(campaign_id.encode("utf-8")).hexdigest()[:4], 16) % ALLOCATION_BUCKETS
    return "explore" if ((cycle + offset) % ALLOCATION_BUCKETS) == 0 else "exploit"


def _evaluation(champion: Dict[str, Any], challenger: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not challenger:
        return {"status": "single_arm", "winner": str(champion.get("id") or ""), "reason": "no_challenger"}
    cp = _perf(champion)
    xp = _perf(challenger)
    if cp["clicks"] < MIN_EVALUATION_CLICKS or xp["clicks"] < MIN_EVALUATION_CLICKS:
        return {"status": "testing", "winner": None, "reason": "minimum_exposure_not_reached"}
    if xp["verified_companies"] > cp["verified_companies"]:
        return {"status": "supported", "winner": str(challenger.get("id") or ""), "reason": "more_verified_companies"}
    if xp["leads"] >= MIN_WIN_LEADS and xp["lead_rate"] >= cp["lead_rate"] + 0.05:
        return {"status": "supported", "winner": str(challenger.get("id") or ""), "reason": "material_lead_rate_lift"}
    if xp["leads"] == 0 and cp["leads"] > 0:
        return {"status": "demoted", "winner": str(champion.get("id") or ""), "reason": "challenger_zero_leads_after_minimum_exposure"}
    return {"status": "testing", "winner": None, "reason": "no_material_difference_yet"}


def _payloads(campaign: Dict[str, Any], variant: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        import acquisition_campaigns

        return [dict(x) for x in acquisition_campaigns._channel_payloads(campaign, variant)]
    except Exception:
        return []


def _activate_variant_queue(
    state: Dict[str, Any],
    campaign: Dict[str, Any],
    variant: Dict[str, Any],
    experiment_id: str,
    phase: str,
) -> int:
    cid = str(campaign.get("id") or "")
    vid = str(variant.get("id") or "")
    queue = [x for x in _safe_list(state.get("acquisition_distribution_queue")) if isinstance(x, dict)]
    queue = [x for x in queue if str(x.get("campaign_id") or "") != cid]
    added = 0
    for payload in _payloads(campaign, variant):
        channel = str(payload.get("channel") or "")
        key = f"{cid}|{vid}|{channel}"
        queue.append({
            "key": key,
            "campaign_id": cid,
            "variant_id": vid,
            "audience": campaign.get("audience"),
            "channel": channel,
            "payload": payload,
            "status": "ready_for_authorized_connector" if payload.get("requires_authorized_connector") else "ready_owned_or_existing_channel",
            "experiment_id": experiment_id,
            "experiment_phase": phase,
            "experiment_active": True,
            "experiment_allocation": EXPLORE_SHARE if phase == "explore" else EXPLOIT_SHARE,
            "updated_at": _now(),
        })
        added += 1
    state["acquisition_distribution_queue"] = queue[-300:]

    active_keys = {str(x.get("key") or "") for x in queue}
    kept_jobs = []
    for job in _safe_list(state.get("distribution_operator_jobs")):
        if not isinstance(job, dict):
            continue
        key = str(job.get("queue_key") or "")
        if key in active_keys or str(job.get("campaign_id") or "") != cid:
            kept_jobs.append(job)
            continue
        terminal = str(job.get("status") or "") in {"verified_published", "email_sent_verified", "live_first_party"}
        irreversible = bool(job.get("outbox_id"))
        if terminal or irreversible:
            job["experiment_active"] = False
            job["experiment_status"] = "historical_inactive_arm"
            kept_jobs.append(job)
    state["distribution_operator_jobs"] = kept_jobs[-500:]
    return added


def _cognitive_focus(state: Dict[str, Any]) -> Dict[str, Any]:
    snap = _safe_dict(state.get("cognitive_director_learning"))
    top_product = _safe_dict(snap.get("top_product")) or None
    top_channel = _safe_dict(snap.get("top_channel")) or None
    return {
        "status": snap.get("status") or "unavailable",
        "top_product": top_product,
        "top_channel": top_channel,
        "eligible_product_signals": _i(snap.get("eligible_product_signals")),
        "eligible_channel_signals": _i(snap.get("eligible_channel_signals")),
    }


def experiment_engine_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    cycle = _cycle(state)
    experiments: List[Dict[str, Any]] = []
    distribution_entries = 0
    campaigns = [x for x in _safe_list(state.get("acquisition_campaigns")) if isinstance(x, dict) and x.get("status") == "active"]

    for campaign in campaigns:
        champion = _champion(campaign)
        if not champion:
            continue
        challenger = _challenger(campaign, champion)
        evaluation = _evaluation(champion, challenger)
        if evaluation.get("status") == "supported" and challenger and evaluation.get("winner") == str(challenger.get("id") or ""):
            campaign["champion_variant_id"] = str(challenger.get("id") or "")
            champion = challenger
            challenger = _challenger(campaign, champion)
            evaluation = {"status": "promoted", "winner": str(champion.get("id") or ""), "reason": "challenger_became_champion"}
        else:
            campaign["champion_variant_id"] = str(champion.get("id") or "")

        phase = _allocation_phase(str(campaign.get("id") or ""), cycle)
        selected = challenger if phase == "explore" and challenger else champion
        exp_id = f"EXP-{str(campaign.get('id') or 'ACQ')}-{str(champion.get('id') or 'A')}-{str((challenger or {}).get('id') or 'NONE')}"
        experiment = {
            "id": exp_id,
            "campaign_id": campaign.get("id"),
            "audience": campaign.get("audience"),
            "hypothesis": f"La variante {str((challenger or {}).get('id') or 'sin_challenger')} puede superar a {str(champion.get('id') or '')} en leads/empresas verificadas sin ampliar autoridad.",
            "phase": phase,
            "allocation": EXPLORE_SHARE if phase == "explore" else EXPLOIT_SHARE,
            "champion_variant_id": champion.get("id"),
            "challenger_variant_id": (challenger or {}).get("id"),
            "selected_variant_id": selected.get("id"),
            "champion_performance": _perf(champion),
            "challenger_performance": _perf(challenger) if challenger else None,
            "evaluation": evaluation,
            "status": "testing" if evaluation.get("status") in {"testing", "single_arm"} else evaluation.get("status"),
            "updated_at": _now(),
        }
        campaign["experiment_engine"] = {
            "experiment_id": exp_id,
            "phase": phase,
            "selected_variant_id": selected.get("id"),
            "allocation_policy": "80_exploit_20_explore",
            "updated_at": experiment["updated_at"],
        }
        distribution_entries += _activate_variant_queue(state, campaign, selected, exp_id, phase)
        experiments.append(experiment)

    cognitive = _cognitive_focus(state)
    active = [x for x in experiments if x.get("status") in {"testing", "promoted"}]
    hard_bottleneck = _safe_dict(state.get("autonomous_director")).get("bottleneck")
    report = {
        "version": VERSION,
        "status": "active" if experiments else "waiting_for_campaigns",
        "updated_at": _now(),
        "cycle": cycle,
        "allocation_policy": {
            "exploit_share": EXPLOIT_SHARE,
            "explore_share": EXPLORE_SHARE,
            "deterministic_buckets": ALLOCATION_BUCKETS,
        },
        "experiments_active": len(active),
        "experiments_total": len(experiments),
        "experiments": experiments[:MAX_EXPERIMENTS],
        "distribution_entries_active": distribution_entries,
        "cognitive_focus": cognitive,
        "hard_bottleneck": hard_bottleneck,
        "next_decision": (
            f"Mantener {int(EXPLOIT_SHARE*100)}% en ganadores y reservar {int(EXPLORE_SHARE*100)}% para challengers hasta reunir evidencia suficiente."
            if experiments else "Crear tráfico real y resultados atribuibles antes de optimizar."
        ),
        "guardrails": {
            "monetary_budget_usd": 0,
            "paid_media_autonomous": False,
            "search_budget_increased": False,
            "binding_authority_changed": False,
            "new_connector_authority": False,
            "production_self_modify": False,
            "hard_bottleneck_override": False,
        },
    }
    state["experiment_engine"] = report
    history = [x for x in _safe_list(state.get("experiment_engine_history")) if isinstance(x, dict)]
    history.append({
        "updated_at": report["updated_at"],
        "cycle": cycle,
        "experiments_active": report["experiments_active"],
        "phase_counts": {
            "exploit": sum(1 for x in experiments if x.get("phase") == "exploit"),
            "explore": sum(1 for x in experiments if x.get("phase") == "explore"),
        },
        "top_product": _safe_dict(cognitive.get("top_product")).get("product_slug"),
        "top_channel": _safe_dict(cognitive.get("top_channel")).get("source"),
        "hard_bottleneck": hard_bottleneck,
    })
    state["experiment_engine_history"] = history[-MAX_HISTORY:]
    return report


def _merge_boosts(base: Dict[str, Any], additions: Dict[str, float]) -> Dict[str, float]:
    merged = {str(k): min(ROLE_BOOST_CAP, max(0.0, _f(v))) for k, v in base.items()}
    for role, value in additions.items():
        merged[role] = min(ROLE_BOOST_CAP, max(_f(merged.get(role)), value))
    return merged


def director_tick_with_experiment_engine(state: Dict[str, Any], adaptive_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    report = dict(_ORIGINAL_DIRECTOR_TICK(state, adaptive_report) or {})
    engine = _safe_dict(state.get("experiment_engine"))
    experiments = [x for x in _safe_list(engine.get("experiments")) if isinstance(x, dict)]
    active = [x for x in experiments if x.get("status") in {"testing", "promoted"}]
    phases = [str(x.get("phase") or "") for x in active]
    phase = "explore" if "explore" in phases else "exploit" if active else "waiting"

    boosts = dict(_safe_dict(report.get("role_boosts")))
    if phase == "explore":
        boosts = _merge_boosts(boosts, {"research_analyst": 0.04, "market_manager": 0.04})
    elif phase == "exploit":
        boosts = _merge_boosts(boosts, {"revops": 0.04, "buyer_hunter": 0.03})
    report["role_boosts"] = boosts

    plan = [dict(x) for x in _safe_list(report.get("plan")) if isinstance(x, dict)]
    if active and not any(str(x.get("id") or "") == "DIR-EXPERIMENT-ENGINE" for x in plan):
        plan.append({
            "id": "DIR-EXPERIMENT-ENGINE",
            "priority": 86,
            "roles": ["research_analyst", "market_manager", "revops"],
            "action": "Ejecutar la asignación 80/20 del Experiment Engine usando únicamente canales orgánicos/propios o conectores ya autorizados; medir leads y resultados verificables.",
            "success_metric": "experiment_verified_conversion_progress",
            "mode": phase,
            "reason": "Aprender qué variante/canal genera mejor avance comercial sin desplazar el cuello de botella canónico.",
            "binding": False,
            "spend_usd": 0,
        })
        plan.sort(key=lambda x: _i(x.get("priority")), reverse=True)
        report["plan"] = plan[:MAX_PLAN]

    report["experiment_engine"] = {
        "version": VERSION,
        "status": engine.get("status") or "not_initialized",
        "phase": phase,
        "experiments_active": len(active),
        "exploit_share": EXPLOIT_SHARE,
        "explore_share": EXPLORE_SHARE,
        "hard_bottleneck_preserved": True,
        "monetary_budget_usd": 0,
        "search_budget_increased": False,
        "binding_authority_changed": False,
    }
    authority = dict(_safe_dict(report.get("authority")))
    authority.update({
        "experiment_engine_authority": "reversible_attention_and_variant_allocation_only",
        "experiment_engine_monetary_budget_usd": 0,
        "experiment_engine_search_budget_increased": False,
        "experiment_engine_hard_bottleneck_override": False,
    })
    report["authority"] = authority
    state["autonomous_director"] = report
    return report


# The Cognitive Director bridge is installed first in worker_entry. Wrap that final decision surface
# so Experiment Engine adds only bounded reversible allocation on top of it.
director.director_tick = director_tick_with_experiment_engine

# Acquisition Campaigns already refreshes performance and canonical tracking on every Meta-LUMEN
# cycle. Wrap that tick rather than adding another scheduler: experimentation runs immediately after
# fresh campaign metrics and before Creative Distribution / Distribution Operator consume the queue.
try:
    import acquisition_campaigns as _acquisition_campaigns

    _ORIGINAL_ACQUISITION_TICK = _acquisition_campaigns.acquisition_campaign_tick

    def _acquisition_tick_with_experiments(state: Dict[str, Any]) -> Dict[str, Any]:
        acquisition = dict(_ORIGINAL_ACQUISITION_TICK(state) or {})
        experiment = dict(experiment_engine_tick(state) or {})
        acquisition["experiment_engine"] = {
            "version": experiment.get("version"),
            "status": experiment.get("status"),
            "experiments_active": experiment.get("experiments_active"),
            "experiments_total": experiment.get("experiments_total"),
            "distribution_entries_active": experiment.get("distribution_entries_active"),
            "allocation_policy": experiment.get("allocation_policy"),
        }
        return acquisition

    _acquisition_campaigns.acquisition_campaign_tick = _acquisition_tick_with_experiments
except Exception as exc:
    print({"experiment_engine_acquisition_bridge": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:220]}"}}, flush=True)

print({
    "experiment_engine_runtime": {
        "version": VERSION,
        "status": "installed",
        "allocation": "80_exploit_20_explore",
        "minimum_evaluation_clicks_per_arm": MIN_EVALUATION_CLICKS,
        "monetary_budget_usd": 0,
        "search_budget_increased": False,
        "binding_authority_changed": False,
        "hard_bottleneck_override": False,
    }
}, flush=True)
