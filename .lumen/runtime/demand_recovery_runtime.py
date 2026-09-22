from __future__ import annotations

"""Bounded anti-stall recovery for the verified-buyer demand bottleneck.

This layer does not discover new buyers, search the web, relax evidence thresholds,
bypass cooldowns, infer demand, or authorize outbound. It only reorders the buyer
candidates that Demand Intelligence already considers eligible, using evidence that
is already persisted in LUMEN. If anything fails, the original candidate ordering is
returned unchanged.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

import app
import demand_intelligence

VERSION = "1.0-bounded-demand-recovery"
MAX_QUEUE = 24
MAX_HISTORY = 40

_ORIGINAL_CANDIDATES = demand_intelligence._candidates


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _linked_account_id(row: Dict[str, Any]) -> str:
    for key in ("account_id", "buyer_account_id", "candidate_account_id", "linked_account_id"):
        value = _text(row.get(key))
        if value:
            return value
    return ""


def _url(row: Dict[str, Any]) -> str:
    for key in ("url", "source_url", "demand_evidence_url", "official_url"):
        value = _text(row.get(key))
        if value.startswith("http://") or value.startswith("https://"):
            return value
    return ""


def _strong_term_present(row: Dict[str, Any]) -> bool:
    blob = " ".join(
        _text(row.get(key)).lower()
        for key in ("title", "snippet", "summary", "need", "category", "query")
        if _text(row.get(key))
    )
    return any(term in blob for term in demand_intelligence.STRONG_DEMAND_TERMS)


def _evidence_rows(state: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for key in ("demand_signals", "public_procurement_signals", "unlinked_demand_signals", "research_leads"):
        for row in state.get(key, []) or []:
            if isinstance(row, dict):
                yield row


def _evidence_index(state: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    index: Dict[str, Dict[str, int]] = {}
    for row in _evidence_rows(state):
        account_id = _linked_account_id(row)
        if not account_id:
            continue
        bucket = index.setdefault(account_id, {"rows": 0, "url_rows": 0, "strong_rows": 0, "qualified_hint_rows": 0})
        bucket["rows"] += 1
        if _url(row):
            bucket["url_rows"] += 1
        if _strong_term_present(row):
            bucket["strong_rows"] += 1
        if _url(row) and _strong_term_present(row) and _i(row.get("score") or row.get("demand_score")) >= 60:
            # This is only a prioritization hint. Demand verification still requires
            # the unchanged Demand Intelligence / inventory-reuse score threshold of 75.
            bucket["qualified_hint_rows"] += 1
    return index


def _recent_account_ids(state: Dict[str, Any]) -> List[str]:
    recovery = state.get("demand_recovery") if isinstance(state.get("demand_recovery"), dict) else {}
    history = recovery.get("history") if isinstance(recovery, dict) else []
    out: List[str] = []
    for event in list(history or [])[-4:]:
        if not isinstance(event, dict):
            continue
        for account_id in event.get("selected_account_ids", []) or []:
            value = _text(account_id)
            if value and value not in out:
                out.append(value)
    return out


def _mode(stall_cycles: int) -> str:
    if stall_cycles >= 12:
        return "challenge_plan"
    if stall_cycles >= 6:
        return "portfolio_rotation"
    if stall_cycles >= 3:
        return "evidence_reuse"
    return "observe"


def _priority(account: Dict[str, Any], evidence: Dict[str, int], recent_ids: List[str], mode: str) -> float:
    account_id = _text(account.get("id"))
    score = 0.0
    score += min(35.0, _f(account.get("verification_score")) * 0.35)
    score += min(20.0, _f(account.get("lead_score")) * 0.20)
    score += min(16.0, _f(account.get("demand_score")) * 0.16)
    score += min(8.0, evidence.get("rows", 0) * 1.5)
    score += min(10.0, evidence.get("url_rows", 0) * 2.0)
    score += min(18.0, evidence.get("strong_rows", 0) * 6.0)
    score += min(18.0, evidence.get("qualified_hint_rows", 0) * 9.0)

    # Once stalled, prefer buyers with useful stored evidence and rotate away from
    # the same repeatedly-selected accounts. This changes attention only, not truth.
    if mode in {"evidence_reuse", "portfolio_rotation", "challenge_plan"}:
        score += min(12.0, evidence.get("strong_rows", 0) * 4.0)
    if mode in {"portfolio_rotation", "challenge_plan"} and account_id in recent_ids:
        score -= 18.0
    if mode == "challenge_plan" and evidence.get("strong_rows", 0) == 0:
        score -= 6.0
    return round(score, 3)


def build_queue(state: Dict[str, Any], eligible: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    director = state.get("autonomous_director") if isinstance(state.get("autonomous_director"), dict) else {}
    stall_cycles = _i((director or {}).get("stall_cycles"))
    mode = _mode(stall_cycles)
    evidence_index = _evidence_index(state)
    recent_ids = _recent_account_ids(state)

    ranked: List[Dict[str, Any]] = []
    for account in eligible:
        if not isinstance(account, dict):
            continue
        account_id = _text(account.get("id"))
        evidence = evidence_index.get(account_id, {})
        ranked.append({
            "account": account,
            "account_id": account_id,
            "priority": _priority(account, evidence, recent_ids, mode),
            "evidence_rows": _i(evidence.get("rows")),
            "strong_evidence_rows": _i(evidence.get("strong_rows")),
            "qualified_hint_rows": _i(evidence.get("qualified_hint_rows")),
        })

    ranked.sort(key=lambda row: (-_f(row.get("priority")), str(row.get("account_id") or "")))
    return ranked[:MAX_QUEUE]


def _prioritized_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        eligible = list(_ORIGINAL_CANDIDATES(state) or [])
        if len(eligible) <= 1:
            return eligible
        queue = build_queue(state, eligible)
        ordered = [row["account"] for row in queue if isinstance(row.get("account"), dict)]
        seen = {_text(row.get("id")) for row in ordered}
        ordered.extend(row for row in eligible if _text(row.get("id")) not in seen)
        return ordered
    except Exception:
        # Fail open to the exact production behavior that existed before this module.
        return list(_ORIGINAL_CANDIDATES(state) or [])


def run_once(state: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if state is None:
        if not app.load_state():
            report = {"version": VERSION, "status": "state_unavailable", "searches_used": 0}
            print({"demand_recovery": report}, flush=True)
            return report
        state = app.STATE

    director = state.get("autonomous_director") if isinstance(state.get("autonomous_director"), dict) else {}
    stall_cycles = _i((director or {}).get("stall_cycles"))
    eligible = list(_ORIGINAL_CANDIDATES(state) or [])
    queue = build_queue(state, eligible)
    mode = _mode(stall_cycles)
    previous = state.get("demand_recovery") if isinstance(state.get("demand_recovery"), dict) else {}
    history = list((previous or {}).get("history", []) or [])
    selected_ids = [str(row.get("account_id") or "") for row in queue[: min(6, len(queue))]]
    history.append({
        "at": _now(),
        "cycle": _i(state.get("ticks")),
        "stall_cycles": stall_cycles,
        "mode": mode,
        "selected_account_ids": selected_ids,
    })

    report = {
        "version": VERSION,
        "status": "active",
        "mode": mode,
        "stall_cycles": stall_cycles,
        "eligible_buyers": len(eligible),
        "queue_size": len(queue),
        "selected_account_ids": selected_ids,
        "top_queue": [
            {
                "account_id": row.get("account_id"),
                "priority": row.get("priority"),
                "evidence_rows": row.get("evidence_rows"),
                "strong_evidence_rows": row.get("strong_evidence_rows"),
                "qualified_hint_rows": row.get("qualified_hint_rows"),
            }
            for row in queue[:6]
        ],
        "searches_used": 0,
        "search_cap_changed": False,
        "minimum_demand_score_unchanged": 75,
        "cooldowns_bypassed": False,
        "requirements_inferred": False,
        "outbound_gate_relaxed": False,
        "binding_authority_changed": False,
        "monetary_budget_usd": 0,
        "fallback": "original_demand_intelligence_candidate_order",
        "history": history[-MAX_HISTORY:],
        "updated_at": _now(),
    }
    state["demand_recovery"] = report
    app.save_state()
    print({"demand_recovery": {k: v for k, v in report.items() if k != "history"}}, flush=True)
    return report


# Patch only candidate ordering. The original function remains the sole authority for
# buyer verification, collection eligibility, demand status and demand_next_check cooldown.
demand_intelligence._candidates = _prioritized_candidates

print({
    "demand_recovery_runtime": {
        "version": VERSION,
        "status": "installed",
        "scope": "eligible_verified_buyer_priority_only",
        "search_cap_changed": False,
        "minimum_demand_score_unchanged": 75,
        "cooldowns_bypassed": False,
        "requirements_inferred": False,
        "outbound_gate_relaxed": False,
        "binding_authority_changed": False,
        "monetary_budget_usd": 0,
        "fail_safe": "original_candidate_order",
    }
}, flush=True)
