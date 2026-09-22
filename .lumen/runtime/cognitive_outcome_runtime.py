from __future__ import annotations

from typing import Any, Dict, List


MAX_OUTCOME_HISTORY = 240
_REAL_TRANSACTION_STATUSES = {"closed", "settled", "paid", "completed", "delivered", "invoiced"}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def outcome_snapshot(state: Dict[str, Any]) -> Dict[str, float]:
    cfo = state.get("cfo", {}) or {}
    finance = cfo.get("financial_snapshot", {}) or state.get("financial_snapshot", {}) or {}
    transactions = [
        x for x in state.get("transactions", []) or []
        if isinstance(x, dict)
        and str(x.get("status") or "") in _REAL_TRANSACTION_STATUSES
        and str(x.get("status") or "") not in {"closed_simulated", "simulated"}
    ]
    verified_companies = sum(
        1 for x in state.get("candidate_accounts", []) or []
        if isinstance(x, dict) and x.get("verified_company")
    )
    sent = sum(
        1 for x in state.get("outbox", []) or []
        if isinstance(x, dict) and x.get("status") == "sent"
    )
    inbound = len(state.get("inbox", []) or [])
    return {
        "realized_profit_usd": round(_f(finance.get("realized_profit_usd")), 2),
        "risk_adjusted_expected_profit_usd": round(_f(finance.get("risk_adjusted_expected_profit_usd")), 2),
        "gross_unsettled_receivable_usd": round(_f(finance.get("gross_unsettled_receivable_usd")), 2),
        "real_transactions": float(len(transactions)),
        "verified_companies": float(verified_companies),
        "evidence_backed_opportunities": float(len(state.get("market_opportunities", []) or [])),
        "outbound_sent": float(sent),
        "inbound_received": float(inbound),
    }


def _delta(before: Dict[str, float], after: Dict[str, float]) -> Dict[str, float]:
    keys = sorted(set(before) | set(after))
    return {key: round(_f(after.get(key)) - _f(before.get(key)), 2) for key in keys}


def _result_index(delta: Dict[str, float]) -> float:
    """Directional observational index only; it is not causal attribution."""
    score = 0.0
    score += max(-40.0, min(40.0, delta.get("real_transactions", 0.0) * 20.0))
    score += max(-25.0, min(25.0, delta.get("realized_profit_usd", 0.0) / 100.0))
    score += max(-15.0, min(15.0, delta.get("risk_adjusted_expected_profit_usd", 0.0) / 250.0))
    score += max(-10.0, min(10.0, delta.get("evidence_backed_opportunities", 0.0) * 2.0))
    score += max(-5.0, min(5.0, delta.get("verified_companies", 0.0)))
    score += max(-5.0, min(5.0, delta.get("inbound_received", 0.0) * 2.0))
    score += max(-10.0, min(10.0, -delta.get("gross_unsettled_receivable_usd", 0.0) / 250.0))
    return round(score, 2)


def _direction(index: float) -> str:
    if index >= 5.0:
        return "improved"
    if index <= -5.0:
        return "worsened"
    return "flat_or_mixed"


def settle_and_stage_outcome(
    state: Dict[str, Any],
    memory: Dict[str, Any],
    *,
    cycle: int,
    cognitive_mode: str,
    master_mode: str,
    agreed: bool,
) -> Dict[str, Any]:
    current = outcome_snapshot(state)
    memory.setdefault("outcome_history", [])
    settled = None
    pending = memory.get("pending_outcome")
    if isinstance(pending, dict) and isinstance(pending.get("snapshot_before"), dict):
        delta = _delta(pending["snapshot_before"], current)
        index = _result_index(delta)
        settled = {
            "decision_cycle": pending.get("cycle"),
            "observed_at_cycle": cycle,
            "cognitive_mode": pending.get("cognitive_mode"),
            "master_mode": pending.get("master_mode"),
            "agreed": bool(pending.get("agreed")),
            "delta": delta,
            "observed_result_index": index,
            "direction": _direction(index),
            "causal_attribution": False,
            "interpretation": "Observed business-state change after the prior cycle; not proof that either engine caused the change.",
        }
        memory["outcome_history"].append(settled)
        memory["outcome_history"] = memory["outcome_history"][-MAX_OUTCOME_HISTORY:]
        memory["last_outcome"] = settled

    memory["pending_outcome"] = {
        "cycle": cycle,
        "cognitive_mode": cognitive_mode,
        "master_mode": master_mode,
        "agreed": bool(agreed),
        "snapshot_before": current,
    }
    return {
        "settled_previous": settled,
        "current_snapshot": current,
        "causal_attribution": False,
    }
