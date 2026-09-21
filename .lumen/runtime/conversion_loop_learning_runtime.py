from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

VERSION = "1.1-conversion-loop-learning"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _i(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def tick(state: Dict[str, Any]) -> Dict[str, Any]:
    events = state.get("acquisition_events", []) or []
    leads_rows = state.get("acquisition_leads", []) or []
    distribution = state.get("distribution_operator", {}) or {}
    payments = state.get("canonical_revenue_truth", {}) or state.get("operational_truth", {}) or {}
    funnel = distribution.get("funnel", {}) if isinstance(distribution, dict) else {}
    funnel = funnel or {}
    clicks = sum(1 for x in events if isinstance(x, dict) and x.get("event") == "click") + _i(funnel.get("clicks"))
    leads = len([x for x in leads_rows if isinstance(x, dict)]) + _i(funnel.get("leads"))
    payment_block = payments.get("payments", {}) if isinstance(payments, dict) else {}
    revenue_block = payments.get("revenue", {}) if isinstance(payments, dict) else {}
    settled = _i((payment_block or {}).get("settled_orders"))
    revenue = float((revenue_block or {}).get("realized_revenue_evidence_usd") or 0.0)
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
