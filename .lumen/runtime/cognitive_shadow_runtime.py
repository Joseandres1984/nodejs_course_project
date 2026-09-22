from __future__ import annotations

from typing import Any, Dict

import master_orchestrator as _master
from cognitive_engine import CognitiveEngine


_ORIGINAL_MASTER_TICK = _master.master_orchestrator_tick
_ENGINE = CognitiveEngine()


def _shadow_event(master_report: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(master_report.get("company_mode") or "BALANCED")
    winning_engine = str(master_report.get("winning_engine") or "Master Orchestrator")
    reason = str(master_report.get("reason") or "Master orchestration completed")
    signals = master_report.get("signals") or {}
    evidence = [
        f"company_mode:{mode}",
        f"winning_engine:{winning_engine}",
    ]
    revenue_directive = signals.get("revenue_directive")
    if revenue_directive:
        evidence.append(f"revenue_directive:{revenue_directive}")
    strategy_mode = signals.get("strategy_mode")
    if strategy_mode:
        evidence.append(f"strategy_mode:{strategy_mode}")
    return {
        "kind": "strategy",
        "object_type": "company",
        "object_id": "LUMEN",
        "action": "score_opportunity",
        "decision": f"shadow_validate_company_mode:{mode.lower()}",
        "reason": f"Shadow validation of Master Orchestrator: {reason}",
        "confidence": 0.90,
        "evidence_refs": evidence,
    }


def master_orchestrator_with_cognitive_shadow(
    state: Dict[str, Any],
    db_status: Dict[str, Any],
    preflight: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    report = dict(_ORIGINAL_MASTER_TICK(state, db_status, preflight=preflight) or {})
    try:
        cognitive = _ENGINE.decide(
            state,
            _shadow_event(report),
            context={
                "live_outbound": False,
                "shadow_mode": True,
                "master_company_mode": report.get("company_mode"),
            },
        )
        shadow = {
            "status": cognitive.get("status"),
            "source": cognitive.get("source"),
            "advisor_status": cognitive.get("advisor_status"),
            "specialist": cognitive.get("specialist"),
            "ledger_id": cognitive.get("ledger_id"),
            "side_effect_executed": cognitive.get("side_effect_executed"),
            "hard_ai_monetary_budget_usd": cognitive.get("hard_ai_monetary_budget_usd"),
            "master_company_mode": report.get("company_mode"),
            "authoritative": False,
        }
        state["cognitive_shadow"] = shadow
        report["cognitive_shadow"] = shadow
    except Exception as exc:
        shadow = {
            "status": "degraded_fail_open",
            "error": f"{type(exc).__name__}: {str(exc)[:260]}",
            "master_company_mode": report.get("company_mode"),
            "authoritative": False,
            "side_effect_executed": False,
        }
        state["cognitive_shadow"] = shadow
        report["cognitive_shadow"] = shadow
    return report


_master.master_orchestrator_tick = master_orchestrator_with_cognitive_shadow

print({
    "cognitive_shadow_runtime": {
        "status": "active",
        "authoritative": False,
        "fail_open_to_master": True,
        "hard_ai_monetary_budget_usd": 0.0,
    }
}, flush=True)
