from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

VERSION = "1.0-conversion-loop-learning"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _i(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def tick(state: Dict[str, Any]) -> Dict[str, Any]:
    campaigns = state.get("acquisition_campaigns", {}) or {}
    distribution = state.get("distribution_operator", {}) or {}
    payments = state.get("canonical_revenue_truth", {}) or state.get("operational_truth", {}) or {}
    funnel = distribution.get("funnel", {}) or {}
    clicks = _i(campaigns.get("clicks")) + _i(funnel.get("clicks"))
    leads = _i(campaigns.get("leads")) + _i(funnel.get("leads"))
    settled = _i((payments.get("payments", {}) or {}).get("settled_orders"))
    revenue = float((payments.get("revenue", {}) or {}).get("realized_revenue_evidence_usd") or 0.0)
    status = "learning" if clicks or leads or settled else "cold_start_collecting_evidence"
    out = {
        "version": VERSION,
        "status": status,
        "updated_at": utcnow(),
        "signals": {"clicks": clicks, "leads": leads, "settled_orders": settled, "realized_revenue_usd": revenue},
        "optimization_priority": "settled_revenue" if settled else ("lead_conversion" if leads else "qualified_intent"),
        "rules": {
            "no_fabricated_attribution": True,
            "do_not_optimize_for_likes_alone": True,
            "promote_winner_only_with_observed_conversion_evidence": True,
            "paid_media_spend_requires_human": True,
        },
    }
    state["conversion_loop_learning"] = out
    return out
