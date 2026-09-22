from __future__ import annotations

"""Outcome-learning bridge from LUMEN Cognitive Engine into the Autonomous Director.

The Cognitive Shadow loop owns outcome reconciliation in Cloudflare D1. This module reads only
aggregate, non-canary outcome truth and lets the Director reallocate reversible attention toward
commercial lanes that have accumulated enough evidence. It never changes the hard funnel
bottleneck, creates search budget, authorizes spend, changes products/decisions in the Cognitive
Engine, or widens binding/execution authority.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import autonomous_director_runtime as director

try:
    import d1_persistence_runtime as d1
except Exception:  # Tests / non-Zero runtime may not install the D1 adapter.
    d1 = None

VERSION = "1.0-cognitive-director-learning"
MIN_LEARNING_SAMPLE = 5
MIN_ALLOCATION_SAMPLE = 8
MIN_FINALIZED_FOR_PROMISING = 5
MAX_SIGNALS = 24
MAX_LEARNING_TASKS = 2
MAX_LEARNING_PRIORITY = 99

_ORIGINAL_DIRECTOR_TICK = director.director_tick
_REFRESH_ATTEMPTED = False

PRODUCT_ROLE_BOOSTS: Dict[str, Dict[str, float]] = {
    "supplier-snapshot": {"risk_quality": 0.10, "supplier_hunter": 0.08, "research_analyst": 0.06},
    "quote-sanity": {"negotiator": 0.10, "revops": 0.08, "research_analyst": 0.05},
    "tender-scan": {"buyer_hunter": 0.10, "research_analyst": 0.10, "revops": 0.06},
    "sourcing-5": {"supplier_hunter": 0.10, "research_analyst": 0.08, "revops": 0.06},
    "buyer-signals": {"buyer_hunter": 0.10, "market_manager": 0.08, "research_analyst": 0.06},
    "export-pulse": {"market_manager": 0.10, "buyer_hunter": 0.08, "research_analyst": 0.08},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _clean(value: Any, limit: int = 120) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _rows(statement: Any) -> List[Dict[str, Any]]:
    if d1 is None:
        return []
    statements = d1._result_statements(statement)
    if not statements:
        return []
    return d1._statement_rows(statements[0])


def _normalized_signal(row: Dict[str, Any], *, kind: str) -> Dict[str, Any]:
    signal = {
        "kind": kind,
        "samples": max(0, _i(row.get("samples"))),
        "finalized_samples": max(0, _i(row.get("finalized_samples"))),
        "checkout_rate": round(max(0.0, min(1.0, _f(row.get("checkout_rate")))), 4),
        "settlement_rate": round(max(0.0, min(1.0, _f(row.get("settlement_rate")))), 4),
        "observed_success_rate": round(max(0.0, min(1.0, _f(row.get("observed_success_rate")))), 4),
        "realized_revenue_usd": round(max(0.0, _f(row.get("realized_revenue_usd"))), 4),
    }
    if kind == "product":
        signal["product_slug"] = _clean(row.get("product_slug"), 80) or "unknown"
    else:
        signal["source"] = _clean(row.get("source"), 80) or "unknown"
        signal["campaign"] = _clean(row.get("campaign"), 120)
    signal["evidence_score"] = _evidence_score(signal)
    signal["evidence_class"] = _evidence_class(signal)
    return signal


def _evidence_score(signal: Dict[str, Any]) -> float:
    samples = max(0, _i(signal.get("samples")))
    sample_strength = min(1.0, samples / 16.0)
    score = (
        max(0.0, min(1.0, _f(signal.get("settlement_rate")))) * 0.50
        + max(0.0, min(1.0, _f(signal.get("observed_success_rate")))) * 0.28
        + max(0.0, min(1.0, _f(signal.get("checkout_rate")))) * 0.17
        + sample_strength * 0.05
    )
    if _f(signal.get("realized_revenue_usd")) > 0:
        score += 0.10
    return round(min(1.0, score), 4)


def _evidence_class(signal: Dict[str, Any]) -> str:
    samples = _i(signal.get("samples"))
    finalized = _i(signal.get("finalized_samples"))
    settlement = _f(signal.get("settlement_rate"))
    revenue = _f(signal.get("realized_revenue_usd"))
    checkout = _f(signal.get("checkout_rate"))
    success = _f(signal.get("observed_success_rate"))
    if samples < MIN_LEARNING_SAMPLE:
        return "insufficient_sample"
    if samples >= MIN_ALLOCATION_SAMPLE and settlement > 0 and revenue > 0:
        return "revenue_proven"
    if samples >= MIN_ALLOCATION_SAMPLE and finalized >= MIN_FINALIZED_FOR_PROMISING and checkout >= 0.35 and success >= 0.55:
        return "conversion_promising"
    return "observe_only"


def _build_snapshot(product_rows: List[Dict[str, Any]], channel_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    products = [_normalized_signal(row, kind="product") for row in product_rows]
    products = [row for row in products if row["samples"] >= MIN_LEARNING_SAMPLE and row.get("product_slug") != "unknown"]
    products.sort(key=lambda row: (row["evidence_score"], row["realized_revenue_usd"], row["samples"]), reverse=True)

    channels = [_normalized_signal(row, kind="channel") for row in channel_rows]
    channels = [row for row in channels if row["samples"] >= MIN_LEARNING_SAMPLE and row.get("source") != "unknown"]
    channels.sort(key=lambda row: (row["evidence_score"], row["realized_revenue_usd"], row["samples"]), reverse=True)

    eligible_products = [row for row in products if row["evidence_class"] in {"revenue_proven", "conversion_promising"}]
    eligible_channels = [row for row in channels if row["evidence_class"] in {"revenue_proven", "conversion_promising"}]
    return {
        "version": VERSION,
        "status": "active" if products or channels else "insufficient_data",
        "updated_at": _now_iso(),
        "mode": "read_only_outcome_allocation",
        "product_signals": products[:MAX_SIGNALS],
        "channel_signals": channels[:MAX_SIGNALS],
        "eligible_product_signals": len(eligible_products),
        "eligible_channel_signals": len(eligible_channels),
        "top_product": eligible_products[0] if eligible_products else None,
        "top_channel": eligible_channels[0] if eligible_channels else None,
        "guardrails": {
            "read_only_d1": True,
            "minimum_learning_sample": MIN_LEARNING_SAMPLE,
            "minimum_allocation_sample": MIN_ALLOCATION_SAMPLE,
            "hard_bottleneck_override": False,
            "search_budget_increased": False,
            "monetary_budget_usd": 0,
            "binding_authority_changed": False,
            "execution_authority_changed": False,
        },
    }


def _read_d1_snapshot() -> Optional[Dict[str, Any]]:
    if d1 is None or not bool(getattr(d1, "_CONFIGURED", False)):
        return None
    result = d1._request({
        "batch": [
            {
                "sql": """
                    SELECT
                      COALESCE(NULLIF(TRIM(s.current_product_slug),''),'unknown') AS product_slug,
                      COUNT(*) AS samples,
                      SUM(CASE WHEN o.finalized=1 THEN 1 ELSE 0 END) AS finalized_samples,
                      AVG(CASE WHEN o.checkout_started=1 OR o.settled_verified=1 THEN 1.0 ELSE 0.0 END) AS checkout_rate,
                      AVG(CASE WHEN o.settled_verified=1 THEN 1.0 ELSE 0.0 END) AS settlement_rate,
                      AVG(o.outcome_score) AS observed_success_rate,
                      SUM(CASE WHEN o.settled_verified=1 THEN o.settled_amount_usd ELSE 0 END) AS realized_revenue_usd
                    FROM lumen_cognitive_outcomes o
                    JOIN lumen_cognitive_shadow_links s ON s.lead_id=o.lead_id
                    WHERE o.technical_canary=0 AND s.technical_canary=0
                    GROUP BY COALESCE(NULLIF(TRIM(s.current_product_slug),''),'unknown')
                    HAVING COUNT(*) >= ?
                    ORDER BY realized_revenue_usd DESC, settlement_rate DESC, observed_success_rate DESC, samples DESC
                    LIMIT ?
                """,
                "params": [MIN_LEARNING_SAMPLE, MAX_SIGNALS],
            },
            {
                "sql": """
                    SELECT
                      COALESCE(NULLIF(TRIM(l.source),''),'unknown') AS source,
                      COALESCE(NULLIF(TRIM(l.campaign),''),'') AS campaign,
                      COUNT(*) AS samples,
                      SUM(CASE WHEN o.finalized=1 THEN 1 ELSE 0 END) AS finalized_samples,
                      AVG(CASE WHEN o.checkout_started=1 OR o.settled_verified=1 THEN 1.0 ELSE 0.0 END) AS checkout_rate,
                      AVG(CASE WHEN o.settled_verified=1 THEN 1.0 ELSE 0.0 END) AS settlement_rate,
                      AVG(o.outcome_score) AS observed_success_rate,
                      SUM(CASE WHEN o.settled_verified=1 THEN o.settled_amount_usd ELSE 0 END) AS realized_revenue_usd
                    FROM lumen_cognitive_outcomes o
                    JOIN lumen_conversion_leads l ON l.id=o.lead_id
                    WHERE o.technical_canary=0 AND l.technical_canary=0
                    GROUP BY COALESCE(NULLIF(TRIM(l.source),''),'unknown'), COALESCE(NULLIF(TRIM(l.campaign),''),'')
                    HAVING COUNT(*) >= ?
                    ORDER BY realized_revenue_usd DESC, settlement_rate DESC, observed_success_rate DESC, samples DESC
                    LIMIT ?
                """,
                "params": [MIN_LEARNING_SAMPLE, MAX_SIGNALS],
            },
        ]
    })
    statements = d1._result_statements(result)
    product_rows = d1._statement_rows(statements[0]) if len(statements) > 0 else []
    channel_rows = d1._statement_rows(statements[1]) if len(statements) > 1 else []
    return _build_snapshot(product_rows, channel_rows)


def _refresh_learning_once(state: Dict[str, Any]) -> Dict[str, Any]:
    global _REFRESH_ATTEMPTED
    existing = _safe_dict(state.get("cognitive_director_learning"))
    if _REFRESH_ATTEMPTED:
        return existing
    _REFRESH_ATTEMPTED = True

    # In tests or non-Zero deployments, preserve an explicitly supplied snapshot and do no I/O.
    if d1 is None or not bool(getattr(d1, "_CONFIGURED", False)):
        return existing
    try:
        snapshot = _read_d1_snapshot()
        if snapshot is not None:
            state["cognitive_director_learning"] = snapshot
            return snapshot
    except Exception as exc:
        state["cognitive_director_learning"] = {
            "version": VERSION,
            "status": "degraded_fail_open",
            "updated_at": _now_iso(),
            "mode": "read_only_outcome_allocation",
            "product_signals": [],
            "channel_signals": [],
            "error_type": type(exc).__name__,
            "guardrails": {
                "hard_bottleneck_override": False,
                "search_budget_increased": False,
                "monetary_budget_usd": 0,
                "binding_authority_changed": False,
                "execution_authority_changed": False,
            },
        }
        return state["cognitive_director_learning"]
    return existing


def _winner(snapshot: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    if snapshot.get("status") != "active":
        return None
    direct = snapshot.get(key)
    if isinstance(direct, dict) and direct.get("evidence_class") in {"revenue_proven", "conversion_promising"}:
        return direct
    rows_key = "product_signals" if key == "top_product" else "channel_signals"
    candidates = [row for row in _safe_list(snapshot.get(rows_key)) if isinstance(row, dict) and row.get("evidence_class") in {"revenue_proven", "conversion_promising"}]
    return candidates[0] if candidates else None


def _merge_role_boosts(base: Dict[str, Any], additions: Dict[str, float]) -> Dict[str, float]:
    merged = {str(role): min(director.ROLE_BOOST_CAP, max(0.0, _f(value))) for role, value in base.items()}
    for role, value in additions.items():
        merged[role] = min(director.ROLE_BOOST_CAP, max(_f(merged.get(role)), max(0.0, _f(value))))
    return merged


def _product_task(signal: Dict[str, Any]) -> Dict[str, Any]:
    product = _clean(signal.get("product_slug"), 80)
    revenue_proven = signal.get("evidence_class") == "revenue_proven"
    priority = 98 if revenue_proven else 91
    return {
        "id": "DIR-COGNITIVE-PRODUCT-FOCUS",
        "title": f"Concentrar atención reversible en la vía {product}",
        "owner": max(PRODUCT_ROLE_BOOSTS.get(product, {"revops": 0.08}), key=PRODUCT_ROLE_BOOSTS.get(product, {"revops": 0.08}).get),
        "priority": min(MAX_LEARNING_PRIORITY, priority),
        "autonomous": True,
        "spend_usd": 0,
        "binding": False,
        "product_slug": product,
        "why": (
            f"Aprendizaje real: n={_i(signal.get('samples'))}, checkout={_f(signal.get('checkout_rate')):.0%}, "
            f"settlement={_f(signal.get('settlement_rate')):.0%}, revenue_usd={_f(signal.get('realized_revenue_usd')):.2f}."
        ),
        "success_metric": "settled_verified_revenue_or_verified_conversion_progress",
        "learning_evidence_class": signal.get("evidence_class"),
        "hard_bottleneck_override": False,
    }


def _channel_task(signal: Dict[str, Any]) -> Dict[str, Any]:
    source = _clean(signal.get("source"), 80)
    campaign = _clean(signal.get("campaign"), 120)
    label = f"{source}/{campaign}" if campaign else source
    revenue_proven = signal.get("evidence_class") == "revenue_proven"
    priority = 94 if revenue_proven else 88
    return {
        "id": "DIR-COGNITIVE-CHANNEL-FOCUS",
        "title": f"Priorizar orgánicamente el canal/campaña {label}",
        "owner": "market_manager",
        "priority": min(MAX_LEARNING_PRIORITY, priority),
        "autonomous": True,
        "spend_usd": 0,
        "binding": False,
        "source": source,
        "campaign": campaign,
        "why": (
            f"Aprendizaje real: n={_i(signal.get('samples'))}, checkout={_f(signal.get('checkout_rate')):.0%}, "
            f"settlement={_f(signal.get('settlement_rate')):.0%}, revenue_usd={_f(signal.get('realized_revenue_usd')):.2f}."
        ),
        "success_metric": "settled_verified_revenue_or_verified_conversion_progress",
        "learning_evidence_class": signal.get("evidence_class"),
        "hard_bottleneck_override": False,
    }


def _augment_report(state: Dict[str, Any], report: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(report or {})
    plan = [dict(row) for row in _safe_list(out.get("plan")) if isinstance(row, dict)]
    role_boosts = dict(_safe_dict(out.get("role_boosts")))
    product = _winner(snapshot, "top_product")
    channel = _winner(snapshot, "top_channel")
    added: List[str] = []

    if product:
        plan.append(_product_task(product))
        role_boosts = _merge_role_boosts(role_boosts, PRODUCT_ROLE_BOOSTS.get(str(product.get("product_slug")), {"revops": 0.08}))
        added.append("product_focus")
    if channel and len(added) < MAX_LEARNING_TASKS:
        plan.append(_channel_task(channel))
        role_boosts = _merge_role_boosts(role_boosts, {"market_manager": 0.08, "revops": 0.05})
        added.append("channel_focus")

    # The original hard-bottleneck task remains priority 100. Learned tasks are capped below it.
    plan.sort(key=lambda row: _i(row.get("priority")), reverse=True)
    out["plan"] = plan[: int(getattr(director, "MAX_PLAN", 6))]
    out["role_boosts"] = role_boosts
    out["cognitive_learning"] = {
        "version": VERSION,
        "status": snapshot.get("status") or "unavailable",
        "mode": "bounded_director_allocation",
        "allocation_tasks_added": added,
        "top_product": product,
        "top_channel": channel,
        "hard_bottleneck_preserved": True,
        "search_budget_increased": False,
        "monetary_budget_usd": 0,
        "binding_authority_changed": False,
        "execution_authority_changed": False,
    }
    authority = dict(_safe_dict(out.get("authority")))
    authority.update({
        "cognitive_learning_authority": "reversible_attention_only",
        "cognitive_learning_hard_bottleneck_override": False,
        "cognitive_learning_search_budget_increased": False,
        "cognitive_learning_monetary_budget_usd": 0,
    })
    out["authority"] = authority
    state["autonomous_director"] = out
    return out


def director_tick_with_cognitive_learning(state: Dict[str, Any], adaptive_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    snapshot = _refresh_learning_once(state)
    report = _ORIGINAL_DIRECTOR_TICK(state, adaptive_report)
    return _augment_report(state, report, snapshot)


# Patch only the Director decision surface. Adaptive Operator's installed wrapper resolves
# autonomous_director_runtime.director_tick dynamically, so the normal runtime automatically receives
# the bounded learning allocation without changing its execution or Governor path.
director.director_tick = director_tick_with_cognitive_learning

print(
    {
        "cognitive_director_learning_runtime": {
            "version": VERSION,
            "status": "installed",
            "minimum_learning_sample": MIN_LEARNING_SAMPLE,
            "minimum_allocation_sample": MIN_ALLOCATION_SAMPLE,
            "max_learning_tasks": MAX_LEARNING_TASKS,
            "hard_bottleneck_override": False,
            "search_budget_increased": False,
            "monetary_budget_usd": 0,
            "binding_authority_changed": False,
        }
    },
    flush=True,
)
