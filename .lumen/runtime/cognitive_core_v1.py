from __future__ import annotations

"""LUMEN Cognitive Core v1.

A supervisory reasoning layer that turns the current LUMEN state into bounded,
constitutionally validated priorities. It is deliberately fail-open with respect
to the existing runtime and fail-closed with respect to binding/financial actions.

The core never stores or exposes chain-of-thought. It persists only compact
decision summaries, evidence references and execution outcomes.
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
import json
import os
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional
from urllib import request as urllib_request

import operating_constitution

VERSION = "1.0-cognitive-core"
MODES = {"shadow", "advisory", "active"}
MAX_CONTEXT_CHARS = 12000
MAX_HISTORY = 40
DEFAULT_TIMEOUT_SECONDS = 4.0

SUPPORTED_ACTIONS = {
    "public_research",
    "company_verification",
    "opportunity_scoring",
    "document_parsing",
    "prepare_public_listing",
    "publish_owned_catalog",
    "publish_external_marketplace",
    "prepare_outreach",
    "send_verified_corporate_outreach",
    "request_quote",
    "nonbinding_negotiation",
    "prepare_proposal",
    "contract",
    "accept_binding_terms",
    "place_order",
    "payment",
    "financial_commitment",
}

OUTBOUND_ACTIONS = {
    "publish_owned_catalog",
    "publish_external_marketplace",
    "send_verified_corporate_outreach",
    "request_quote",
    "nonbinding_negotiation",
}

SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "private_key",
    "seed",
    "credential",
    "authorization",
    "cookie",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _safe_mode(value: Optional[str]) -> str:
    mode = _clean(value or os.getenv("LUMEN_COGNITIVE_CORE_V1_MODE", "shadow"), 20).lower()
    return mode if mode in MODES else "shadow"


def _redacted_key(key: Any) -> bool:
    normalized = str(key or "").strip().lower()
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[depth_limited]"
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, item in list(value.items())[:80]:
            if _redacted_key(key):
                result[str(key)] = "[redacted]"
            else:
                result[str(key)] = _sanitize(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, depth=depth + 1) for item in list(value)[:80]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            return value[:1200]
        return value
    return _clean(value, 300)


def _extract_metrics(state: Mapping[str, Any]) -> Dict[str, Any]:
    expansion = state.get("expansion_revenue_metrics", {}) or {}
    service = state.get("service_revenue_runtime", {}) or {}
    revenue = state.get("canonical_revenue_truth", {}) or {}
    autonomy = state.get("autonomy_core", {}) or {}
    director = state.get("autonomous_director", {}) or state.get("director_runtime", {}) or {}
    return {
        "verified_revenue_usd": round(
            max(
                _float(revenue.get("verified_revenue_usd")),
                _float(expansion.get("revenue_generated_usd")),
                _float(service.get("realized_service_revenue_usd")),
            ),
            4,
        ),
        "sales_closed": max(_int(expansion.get("sales_closed")), _int(service.get("won"))),
        "opportunities_active": _int(expansion.get("opportunities_active")),
        "buyers_contacted": _int(expansion.get("buyers_contacted")),
        "replies": _int(expansion.get("replies")),
        "negotiations": _int(expansion.get("negotiations")),
        "proposals": _int(expansion.get("proposals")),
        "learning_cycle": _int(autonomy.get("learning_cycle")),
        "director_bottleneck": _clean(
            director.get("bottleneck") or director.get("hard_bottleneck") or "", 120
        ),
    }


def build_observation(state: Mapping[str, Any]) -> Dict[str, Any]:
    """Build a compact, secret-redacted view of the current operating state."""
    constitution = operating_constitution.ensure_constitution(dict(state))
    selected_keys = (
        "continuous_revenue_drive",
        "service_revenue_runtime",
        "expansion_revenue_metrics",
        "market_intelligence",
        "market_hunter",
        "adaptive_market_hunter",
        "autonomy_core",
        "autonomous_director",
        "director_runtime",
        "experiment_engine",
        "cognitive_director_learning",
        "commercial_learning_v2",
        "agent_network_runtime",
        "intelligence_revenue_runtime",
        "master_governance",
    )
    context = {key: _sanitize(state.get(key)) for key in selected_keys if key in state}
    observation = {
        "objective": constitution.get("supreme_objective"),
        "business_model": _sanitize(constitution.get("business_model", {})),
        "authority_matrix": _sanitize(constitution.get("authority_matrix", {})),
        "metrics": _extract_metrics(state),
        "context": context,
    }

    encoded = json.dumps(observation, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(encoded) <= MAX_CONTEXT_CHARS:
        return observation

    return {
        "objective": observation["objective"],
        "business_model": observation["business_model"],
        "authority_matrix": observation["authority_matrix"],
        "metrics": observation["metrics"],
        "context_truncated": True,
        "context_excerpt": encoded[: MAX_CONTEXT_CHARS - 1000],
    }


@dataclass
class ProposedAction:
    action_type: str
    title: str
    reason: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    expected_value: float = 0.0


class CognitiveWorkerClient:
    """HTTP adapter for the existing lumen-zero-cognitive /decide endpoint."""

    def __init__(self, base_url: Optional[str] = None, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
        self.base_url = _clean(base_url or os.getenv("LUMEN_COGNITIVE_WORKER_URL", ""), 500).rstrip("/")
        self.timeout_seconds = max(0.5, min(15.0, _float(timeout_seconds, DEFAULT_TIMEOUT_SECONDS)))

    def decide(self, observation: Mapping[str, Any]) -> Dict[str, Any]:
        if not self.base_url:
            raise RuntimeError("cognitive_worker_url_not_configured")
        payload = json.dumps(
            {
                "task": "director",
                "subject": {
                    "current_product": None,
                    "objective": _clean(observation.get("objective"), 500),
                },
                "context": observation,
            },
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        req = urllib_request.Request(
            f"{self.base_url}/decide",
            data=payload,
            method="POST",
            headers={"content-type": "application/json", "user-agent": "lumen-cognitive-core-v1"},
        )
        with urllib_request.urlopen(req, timeout=self.timeout_seconds) as response:
            raw = response.read(64000)
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise RuntimeError("cognitive_worker_invalid_response")
        return parsed


def _fallback_action(observation: Mapping[str, Any]) -> ProposedAction:
    metrics = observation.get("metrics", {}) or {}
    replies = _int(metrics.get("replies"))
    negotiations = _int(metrics.get("negotiations"))
    proposals = _int(metrics.get("proposals"))
    active = _int(metrics.get("opportunities_active"))
    contacted = _int(metrics.get("buyers_contacted"))

    if negotiations > 0:
        return ProposedAction(
            "nonbinding_negotiation",
            "Advance existing non-binding negotiations",
            "Active negotiations are closer to revenue than expanding discovery.",
            confidence=0.72,
            expected_value=0.78,
        )
    if replies > 0:
        return ProposedAction(
            "prepare_proposal",
            "Convert qualified replies into proposals",
            "Observed replies indicate a live commercial path that should be advanced first.",
            confidence=0.70,
            expected_value=0.74,
        )
    if proposals > contacted and proposals > 0:
        return ProposedAction(
            "prepare_outreach",
            "Prepare governed outreach for ready proposals",
            "Existing proposal inventory should be converted before adding search volume.",
            confidence=0.66,
            expected_value=0.68,
        )
    if active > 0:
        return ProposedAction(
            "opportunity_scoring",
            "Rank active opportunities by risk-adjusted value",
            "There is active opportunity inventory but insufficient downstream conversion evidence.",
            confidence=0.64,
            expected_value=0.62,
        )
    return ProposedAction(
        "public_research",
        "Discover evidence-backed commercial opportunities",
        "No stronger verified downstream signal is visible in the current snapshot.",
        confidence=0.55,
        expected_value=0.50,
    )


def _map_model_decision(model_result: Mapping[str, Any], observation: Mapping[str, Any]) -> ProposedAction:
    explicit = _clean(model_result.get("action_type"), 80)
    if explicit in SUPPORTED_ACTIONS:
        return ProposedAction(
            explicit,
            _clean(model_result.get("next_action") or explicit.replace("_", " ").title(), 220),
            _clean(" ".join(str(x) for x in (model_result.get("reasons") or [])[:3]), 600),
            parameters=_sanitize(model_result.get("parameters") or {}),
            confidence=max(0.0, min(1.0, _float(model_result.get("confidence")))),
            expected_value=max(0.0, min(1.0, _float(model_result.get("expected_value"), 0.5))),
        )

    decision = _clean(model_result.get("decision"), 40).lower()
    fallback = _fallback_action(observation)
    reasons = model_result.get("reasons") or []
    reason = _clean(" ".join(str(item) for item in reasons[:3]), 600) or fallback.reason
    confidence = max(0.0, min(1.0, _float(model_result.get("confidence"), fallback.confidence)))

    if decision == "research":
        action = "public_research"
    elif decision in {"contact", "prioritize"}:
        action = fallback.action_type
    elif decision in {"hold", "qa_pass", "qa_revise"}:
        action = "opportunity_scoring"
    else:
        action = fallback.action_type

    return ProposedAction(
        action_type=action,
        title=_clean(model_result.get("next_action") or fallback.title, 220),
        reason=reason,
        confidence=confidence,
        expected_value=fallback.expected_value,
    )


def _policy_check(state: MutableMapping[str, Any], proposal: ProposedAction) -> Dict[str, Any]:
    action = proposal.action_type if proposal.action_type in SUPPORTED_ACTIONS else "financial_commitment"
    check = operating_constitution.constitutional_check(
        state,
        action,
        outbound=action in OUTBOUND_ACTIONS,
    )
    return {
        "action_type": action,
        "allowed": bool(check.get("allowed")),
        "requires_approval": bool(check.get("requires_approval")),
        "authority": check.get("authority"),
        "reasons": list(check.get("reasons") or []),
        "constitution_version": check.get("constitution_version"),
    }


def _execute_if_allowed(
    proposal: ProposedAction,
    policy: Mapping[str, Any],
    *,
    mode: str,
    tool_registry: Optional[Mapping[str, Callable[[Mapping[str, Any]], Any]]],
) -> Dict[str, Any]:
    result = {
        "attempted": False,
        "executed": False,
        "status": "not_executed",
        "detail": None,
    }
    if mode != "active":
        result["status"] = f"{mode}_mode"
        return result
    if not policy.get("allowed") or policy.get("requires_approval"):
        result["status"] = "blocked_by_constitution"
        return result
    if not tool_registry or proposal.action_type not in tool_registry:
        result["status"] = "no_registered_tool"
        return result

    result["attempted"] = True
    try:
        value = tool_registry[proposal.action_type](dict(proposal.parameters))
        result.update(
            {
                "executed": True,
                "status": "executed",
                "detail": _sanitize(value),
            }
        )
    except Exception as exc:
        result["status"] = "tool_failed"
        result["detail"] = f"{type(exc).__name__}: {_clean(exc, 240)}"
    return result


def run_cognitive_core(
    state: MutableMapping[str, Any],
    *,
    mode: Optional[str] = None,
    model_client: Optional[Any] = None,
    tool_registry: Optional[Mapping[str, Callable[[Mapping[str, Any]], Any]]] = None,
) -> Dict[str, Any]:
    """Run one bounded cognitive cycle and persist its compact decision summary into state."""
    resolved_mode = _safe_mode(mode)
    observation = build_observation(state)
    provider = "deterministic"
    model_result: Dict[str, Any] = {}
    model_error: Optional[str] = None

    client = model_client if model_client is not None else CognitiveWorkerClient()
    try:
        model_result = dict(client.decide(observation) or {})
        proposal = _map_model_decision(model_result, observation)
        provider = _clean(model_result.get("provider") or "cognitive_worker", 80)
    except Exception as exc:
        model_error = f"{type(exc).__name__}: {_clean(exc, 220)}"
        proposal = _fallback_action(observation)

    policy = _policy_check(state, proposal)
    execution = _execute_if_allowed(
        proposal,
        policy,
        mode=resolved_mode,
        tool_registry=tool_registry,
    )

    blocked = bool(policy.get("requires_approval")) or not bool(policy.get("allowed"))
    cycle_id = f"CC-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    result = {
        "version": VERSION,
        "cycle_id": cycle_id,
        "created_at": _now_iso(),
        "status": "blocked" if blocked else "ready",
        "mode": resolved_mode,
        "provider": provider,
        "objective": observation.get("objective"),
        "metrics": observation.get("metrics"),
        "proposal": asdict(proposal),
        "policy": policy,
        "execution": execution,
        "model_error": model_error,
        "rationale_summary": proposal.reason,
        "chain_of_thought_stored": False,
        "guardrails": {
            "constitution_enforced": True,
            "human_required_actions_auto_executed": False,
            "outgoing_spend_authority_changed": False,
            "binding_authority_changed": False,
            "secrets_redacted_from_model_context": True,
        },
    }

    state["cognitive_core_v1"] = result
    history = state.get("cognitive_core_history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "cycle_id": cycle_id,
            "created_at": result["created_at"],
            "mode": resolved_mode,
            "provider": provider,
            "action_type": proposal.action_type,
            "status": result["status"],
            "authority": policy.get("authority"),
            "executed": execution.get("executed", False),
            "confidence": proposal.confidence,
            "expected_value": proposal.expected_value,
            "rationale_summary": proposal.reason,
        }
    )
    state["cognitive_core_history"] = history[-MAX_HISTORY:]
    return result


def cognitive_core_enabled() -> bool:
    # Default-on in shadow mode: observes and learns, but cannot execute external actions.
    return _bool_env("LUMEN_COGNITIVE_CORE_V1_ENABLED", True)
