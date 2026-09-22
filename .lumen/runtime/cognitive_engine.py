from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from autonomy_governor import (
    HIGH_RISK_ACTIONS,
    LOW_RISK_ACTIONS,
    MEDIUM_RISK_ACTIONS,
    authorize,
    record_decision,
    register_incident,
)


ENGINE_VERSION = "1.0.0"
HARD_AI_MONETARY_BUDGET_USD = 0.0
MAX_HISTORY = 240
KNOWN_ACTIONS = set(LOW_RISK_ACTIONS) | set(MEDIUM_RISK_ACTIONS) | set(HIGH_RISK_ACTIONS)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp_confidence(value: Any, default: float = 0.5) -> float:
    return max(0.0, min(1.0, _float(value, default)))


def _specialist_for(event: Dict[str, Any]) -> str:
    kind = str(event.get("kind") or event.get("type") or "").lower()
    action = str(event.get("action") or "").lower()
    text = f"{kind} {action}"

    if any(x in text for x in ("payment", "financial", "cash", "invoice", "margin")):
        return "cfo"
    if any(x in text for x in ("contract", "negot", "close", "deal")):
        return "closer"
    if any(x in text for x in ("email", "outreach", "message", "reply")):
        return "communication"
    if any(x in text for x in ("market", "lead", "opportunity", "research", "supplier", "buyer")):
        return "market_intelligence"
    if any(x in text for x in ("strategy", "objective", "portfolio", "growth")):
        return "corporate_brain"
    return "master_orchestrator"


def _normalize_evidence(refs: Iterable[Any] | None) -> list[str]:
    return [str(x)[:500] for x in (refs or [])][:8]


def _valid_proposal(proposal: Any) -> bool:
    if not isinstance(proposal, dict):
        return False
    if str(proposal.get("action") or "") not in KNOWN_ACTIONS:
        return False
    if not str(proposal.get("decision") or "").strip():
        return False
    if not str(proposal.get("reason") or "").strip():
        return False
    confidence = proposal.get("confidence")
    if confidence is not None and not 0.0 <= _float(confidence, -1.0) <= 1.0:
        return False
    refs = proposal.get("evidence_refs", [])
    if refs is not None and not isinstance(refs, (list, tuple, set)):
        return False
    return True


def _local_proposal(event: Dict[str, Any], specialist: str) -> Dict[str, Any]:
    requested = str(event.get("action") or "").strip()
    action = requested if requested in KNOWN_ACTIONS else "score_opportunity"
    object_type = str(event.get("object_type") or event.get("kind") or "event")[:80]
    object_id = str(event.get("object_id") or event.get("id") or "unknown")[:160]
    decision = str(event.get("decision") or f"route_to:{specialist}")[:240]
    reason = str(event.get("reason") or f"Deterministic routing to {specialist}; no external AI required.")[:600]
    return {
        "action": action,
        "decision": decision,
        "reason": reason,
        "confidence": _clamp_confidence(event.get("confidence"), 0.72),
        "evidence_refs": _normalize_evidence(event.get("evidence_refs")),
        "object_type": object_type,
        "object_id": object_id,
        "specialist": specialist,
    }


def _advisor_cost_usd(advisor: Any) -> Optional[float]:
    raw = getattr(advisor, "monetary_cost_usd", None)
    if raw is None:
        return None
    cost = _float(raw, -1.0)
    return cost if cost >= 0 else None


def _advisor_allowed(advisor: Any) -> bool:
    cost = _advisor_cost_usd(advisor)
    return cost is not None and cost <= HARD_AI_MONETARY_BUDGET_USD


def ensure_cognitive_state(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("cognitive_engine", {})
    memory.setdefault("version", ENGINE_VERSION)
    memory.setdefault("decisions", 0)
    memory.setdefault("advisor_uses", 0)
    memory.setdefault("advisor_fallbacks", 0)
    memory.setdefault("paid_ai_blocked", 0)
    memory.setdefault("history", [])
    memory["hard_ai_monetary_budget_usd"] = HARD_AI_MONETARY_BUDGET_USD
    return memory


class CognitiveEngine:
    """Provider-agnostic decision layer.

    External AI may propose a structured decision only when its declared monetary
    cost is exactly zero. The Governor remains authoritative and this engine never
    executes side effects directly.
    """

    def __init__(self, advisor: Any | None = None) -> None:
        self.advisor = advisor

    def decide(
        self,
        state: Dict[str, Any],
        event: Dict[str, Any],
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        memory = ensure_cognitive_state(state)
        specialist = _specialist_for(event)
        proposal = _local_proposal(event, specialist)
        source = "deterministic"
        advisor_status = "not_configured"

        if self.advisor is not None:
            if not _advisor_allowed(self.advisor):
                memory["paid_ai_blocked"] += 1
                advisor_status = "blocked_by_zero_cost_policy"
                register_incident(
                    state,
                    "Cognitive Engine",
                    "advisor_cost_blocked",
                    "External advisor was not called because zero monetary cost was not explicitly declared.",
                )
            else:
                try:
                    candidate = self.advisor.propose(
                        event=dict(event),
                        context=dict(context or {}),
                        local_proposal=dict(proposal),
                        specialist=specialist,
                    )
                    if _valid_proposal(candidate):
                        proposal = {
                            **proposal,
                            **candidate,
                            "confidence": _clamp_confidence(candidate.get("confidence"), proposal["confidence"]),
                            "evidence_refs": _normalize_evidence(candidate.get("evidence_refs")),
                            "specialist": specialist,
                        }
                        source = "zero_cost_advisor"
                        advisor_status = "accepted"
                        memory["advisor_uses"] += 1
                    else:
                        advisor_status = "invalid_proposal_fallback"
                        memory["advisor_fallbacks"] += 1
                        register_incident(
                            state,
                            "Cognitive Engine",
                            "invalid_advisor_proposal",
                            "Advisor output failed structured proposal validation; deterministic fallback used.",
                        )
                except Exception as exc:
                    advisor_status = "advisor_error_fallback"
                    memory["advisor_fallbacks"] += 1
                    register_incident(
                        state,
                        "Cognitive Engine",
                        "advisor_error",
                        f"{type(exc).__name__}: {exc}",
                    )

        governance_context = {**dict(context or {}), **dict(event.get("governance_context") or {})}
        governance = authorize(state, str(proposal["action"]), governance_context)
        allowed = bool(governance.get("allowed"))
        requires_approval = bool(governance.get("requires_approval"))
        status = "approved" if allowed else ("approval_required" if requires_approval else "blocked")

        ledger = record_decision(
            state,
            engine="Cognitive Engine",
            object_type=str(proposal.get("object_type") or "event"),
            object_id=str(proposal.get("object_id") or "unknown"),
            decision=str(proposal["decision"]),
            reason=str(proposal["reason"]),
            action=str(proposal["action"]),
            confidence=_clamp_confidence(proposal.get("confidence"), 0.5),
            evidence_refs=proposal.get("evidence_refs") or [],
            allowed=allowed,
            requires_approval=requires_approval,
        )

        result = {
            "ts": utcnow(),
            "version": ENGINE_VERSION,
            "status": status,
            "source": source,
            "advisor_status": advisor_status,
            "specialist": specialist,
            "proposal": proposal,
            "governance": governance,
            "ledger_id": ledger.get("id"),
            "side_effect_executed": False,
            "hard_ai_monetary_budget_usd": HARD_AI_MONETARY_BUDGET_USD,
        }

        memory["decisions"] += 1
        memory["last_decision"] = result
        memory["history"].append({
            "ts": result["ts"],
            "status": status,
            "source": source,
            "advisor_status": advisor_status,
            "specialist": specialist,
            "action": proposal["action"],
            "decision": proposal["decision"],
            "ledger_id": result["ledger_id"],
        })
        memory["history"] = memory["history"][-MAX_HISTORY:]
        return result
