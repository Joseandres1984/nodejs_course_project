from __future__ import annotations

"""Persistent adaptive learning for LUMEN Instagram editorial content.

This layer learns from signals LUMEN can verify itself: publication receipts plus
post-creation changes in the related acquisition campaign's clicks and leads.
Those deltas are explicitly treated as shared downstream campaign signals, not as
Instagram-only attribution. Future headline and visual-style choices use a bounded
explore/exploit policy. Publication remains explicitly human-approved.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import instagram_pro_editorial_runtime as pro


VERSION = "1.0-instagram-persistent-learning"
MIN_SAMPLES_FOR_WINNER = 2
MIN_CLICKS_FOR_WINNER = 8
MAX_OUTCOME_DAYS = 14

_ORIGINAL_EDITORIAL_TICK = pro.instagram_editorial_tick
_ORIGINAL_CHOOSE_HEADLINE = pro._choose_headline
_ORIGINAL_WEEKDAY_BRIEF = pro._weekday_brief
_ORIGINAL_STRATEGY_FOR = pro._strategy_for
_STATE_CONTEXT: Optional[Dict[str, Any]] = None

STYLE_CANDIDATES = {
    "buyer_value": ["procurement_radar", "evidence_grid"],
    "authority": ["evidence_grid", "procurement_radar"],
    "supplier_value": ["matching_network", "evidence_grid"],
    "education": ["education_steps", "evidence_grid"],
    "partner_growth": ["partner_channel", "matching_network"],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_dt(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [text, text.replace(" UTC", "+00:00"), text.replace("Z", "+00:00")]
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def _receipt_for(state: Dict[str, Any], job_id: str) -> Dict[str, Any]:
    rows = [
        row for row in state.get("distribution_receipts", []) or []
        if isinstance(row, dict)
        and str(row.get("distribution_job_id") or "") == str(job_id)
        and (row.get("external_post_id") or row.get("external_url"))
    ]
    rows.sort(key=lambda row: str(row.get("published_at") or row.get("received_at") or ""), reverse=True)
    return rows[0] if rows else {}


def _signal(state: Dict[str, Any], audience: str) -> Dict[str, int]:
    # Reuse the same campaign truth already used by the Pro editorial engine.
    return dict(pro._campaign_signal(state, audience) or {"clicks": 0, "leads": 0})


def _ensure_baselines(state: Dict[str, Any]) -> int:
    created = 0
    for job in state.get("distribution_operator_jobs", []) or []:
        if not isinstance(job, dict) or not job.get("editorial_pro_v1"):
            continue
        if isinstance(job.get("learning_baseline"), dict):
            continue
        audience = str(job.get("audience") or "b2b")
        signal = _signal(state, audience)
        job["learning_baseline"] = {
            "captured_at": _now_iso(),
            "clicks": int(signal.get("clicks") or 0),
            "leads": int(signal.get("leads") or 0),
            "source": "shared_acquisition_campaign_signal",
            "attribution": "not_instagram_only",
        }
        created += 1
    return created


def _update_outcomes(state: Dict[str, Any]) -> int:
    updated = 0
    for job in state.get("distribution_operator_jobs", []) or []:
        if not isinstance(job, dict) or not job.get("editorial_pro_v1"):
            continue
        receipt = _receipt_for(state, str(job.get("id") or ""))
        baseline = job.get("learning_baseline") if isinstance(job.get("learning_baseline"), dict) else None
        if not receipt or not baseline:
            continue
        published_at = _parse_dt(receipt.get("published_at") or receipt.get("received_at"))
        if not published_at:
            continue
        age_hours = max(0.0, (_now() - published_at).total_seconds() / 3600.0)
        if age_hours > MAX_OUTCOME_DAYS * 24:
            age_hours = float(MAX_OUTCOME_DAYS * 24)
        current = _signal(state, str(job.get("audience") or "b2b"))
        clicks_delta = max(0, int(current.get("clicks") or 0) - int(baseline.get("clicks") or 0))
        leads_delta = max(0, int(current.get("leads") or 0) - int(baseline.get("leads") or 0))
        prior = job.get("learning_outcome") if isinstance(job.get("learning_outcome"), dict) else {}
        snapshot = {
            "updated_at": _now_iso(),
            "published_at": receipt.get("published_at") or receipt.get("received_at"),
            "age_hours": round(age_hours, 2),
            "clicks_delta": clicks_delta,
            "leads_delta": leads_delta,
            "score": round(leads_delta * 100.0 + clicks_delta * 3.0, 2),
            "source": "shared_acquisition_campaign_signal",
            "attribution": "directional_not_instagram_only",
            "confidence": "medium" if leads_delta > 0 else "low" if clicks_delta < 8 else "medium",
            "mature_24h": age_hours >= 24,
            "mature_72h": age_hours >= 72,
        }
        if snapshot != prior:
            job["learning_outcome"] = snapshot
            updated += 1
    return updated


def _aggregate(state: Dict[str, Any], field: str) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for job in state.get("distribution_operator_jobs", []) or []:
        if not isinstance(job, dict) or not job.get("editorial_pro_v1"):
            continue
        outcome = job.get("learning_outcome") if isinstance(job.get("learning_outcome"), dict) else {}
        if not outcome.get("mature_24h"):
            continue
        name = str(job.get(field) or "").strip()
        if not name:
            continue
        grouped.setdefault(name, []).append(outcome)
    result: Dict[str, Dict[str, Any]] = {}
    for name, rows in grouped.items():
        samples = len(rows)
        clicks = sum(int(row.get("clicks_delta") or 0) for row in rows)
        leads = sum(int(row.get("leads_delta") or 0) for row in rows)
        avg = sum(float(row.get("score") or 0) for row in rows) / max(1, samples)
        result[name] = {
            "samples": samples,
            "clicks_delta": clicks,
            "leads_delta": leads,
            "avg_score": round(avg, 2),
            "winner_eligible": samples >= MIN_SAMPLES_FOR_WINNER and (clicks >= MIN_CLICKS_FOR_WINNER or leads > 0),
            "attribution": "directional_shared_campaign_signal",
        }
    return result


def _learning_report(state: Dict[str, Any], baselines: int, outcomes: int) -> Dict[str, Any]:
    headline_stats = _aggregate(state, "headline")
    style_stats = _aggregate(state, "creative_style")
    pillar_stats = _aggregate(state, "content_pillar")
    mature = sum(int(row.get("samples") or 0) for row in pillar_stats.values())
    report = {
        "version": VERSION,
        "status": "learning" if mature else "cold_start_collecting_evidence",
        "baselines_created_this_tick": baselines,
        "outcomes_updated_this_tick": outcomes,
        "mature_observations": mature,
        "headline_stats": headline_stats,
        "style_stats": style_stats,
        "pillar_stats": pillar_stats,
        "policy": {
            "mode": "bounded_explore_exploit",
            "winner_min_samples": MIN_SAMPLES_FOR_WINNER,
            "winner_min_clicks_or_lead": MIN_CLICKS_FOR_WINNER,
            "exploration_floor": "one_week_in_four_or_under_sampled_variant",
            "truth_rule": "campaign deltas are directional and never presented as Instagram-only attribution",
            "no_fabricated_metrics": True,
            "publication_authority": "explicit_human_approval_unchanged",
        },
        "updated_at": _now_iso(),
    }
    state["instagram_editorial_learning"] = report
    return report


def _strategy_with_context(state: Dict[str, Any], audience: str) -> str:
    global _STATE_CONTEXT
    _STATE_CONTEXT = state
    return _ORIGINAL_STRATEGY_FOR(state, audience)


def _pick(candidates: List[str], stats: Dict[str, Dict[str, Any]]) -> str:
    if not candidates:
        return ""
    eligible = [name for name in candidates if bool((stats.get(name) or {}).get("winner_eligible"))]
    week = _now().isocalendar().week
    if eligible and week % 4 != 0:
        return max(
            eligible,
            key=lambda name: (
                float((stats.get(name) or {}).get("avg_score") or 0),
                int((stats.get(name) or {}).get("leads_delta") or 0),
                int((stats.get(name) or {}).get("clicks_delta") or 0),
            ),
        )
    minimum = min(int((stats.get(name) or {}).get("samples") or 0) for name in candidates)
    pool = [name for name in candidates if int((stats.get(name) or {}).get("samples") or 0) == minimum]
    return pool[week % len(pool)] if pool else candidates[0]


def _weekday_brief_learning(weekday: int, strategy: str) -> Dict[str, Any]:
    brief = dict(_ORIGINAL_WEEKDAY_BRIEF(weekday, strategy) or {})
    state = _STATE_CONTEXT or {}
    learning = state.get("instagram_editorial_learning", {}) or {}
    candidates = list(STYLE_CANDIDATES.get(str(brief.get("pillar") or ""), []))
    if candidates:
        chosen = _pick(candidates, learning.get("style_stats", {}) or {})
        if chosen:
            brief["style"] = chosen
            brief["style_selection"] = "adaptive_learning"
    return brief


def _choose_headline_learning(state: Dict[str, Any], slot: str, brief: Dict[str, Any], strategy: str) -> str:
    options = [str(x) for x in brief.get("headlines", []) or [] if str(x).strip()]
    if not options:
        return _ORIGINAL_CHOOSE_HEADLINE(state, slot, brief, strategy)
    recent = {
        str(row.get("headline") or "").strip().lower()
        for row in pro._history(state)[-10:]
        if isinstance(row, dict)
    }
    candidates = [text for text in options if text.strip().lower() not in recent] or options
    learning = state.get("instagram_editorial_learning", {}) or {}
    chosen = _pick(candidates, learning.get("headline_stats", {}) or {})
    return chosen or _ORIGINAL_CHOOSE_HEADLINE(state, slot, brief, strategy)


pro._strategy_for = _strategy_with_context
pro._weekday_brief = _weekday_brief_learning
pro._choose_headline = _choose_headline_learning


def _editorial_tick_with_learning(state: Dict[str, Any]) -> Dict[str, Any]:
    # Learn from prior published pieces before choosing today's headline/style.
    baselines_before = _ensure_baselines(state)
    outcomes_before = _update_outcomes(state)
    learning_before = _learning_report(state, baselines_before, outcomes_before)
    report = dict(_ORIGINAL_EDITORIAL_TICK(state) or {})
    # Today's freshly prepared piece also gets a baseline immediately.
    baselines_after = _ensure_baselines(state)
    outcomes_after = _update_outcomes(state)
    report["adaptive_learning"] = _learning_report(state, baselines_after, outcomes_after)
    report["learning_status_before_generation"] = learning_before.get("status")
    state["instagram_editorial_system"] = report
    return report


pro.instagram_editorial_tick = _editorial_tick_with_learning

print({
    "instagram_editorial_learning": {
        "version": VERSION,
        "status": "active",
        "persistent_baselines": True,
        "outcome_windows": ["24h", "72h", "14d_max"],
        "headline_learning": True,
        "style_learning": True,
        "bounded_explore_exploit": True,
        "campaign_signal_attribution": "directional_not_instagram_only",
        "human_approval_unchanged": True,
        "fabricated_metrics": False,
    }
}, flush=True)
