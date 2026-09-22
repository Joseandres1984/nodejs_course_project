from __future__ import annotations

"""Suppress legacy non-canonical deal priorities without deleting audit history.

This layer runs immediately before the Executive Secretary. It removes active queue items
that would present a quarantined legacy deal as a close/data-refresh priority, while storing
bounded audit copies explaining why they were suppressed. Raw deals and diagnostic history
remain intact.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from canonical_revenue_truth_runtime import canonical_revenue_truth_tick

VERSION = "1.0-canonical-priority-cleanup"
MAX_AUDIT = 80
_DEAL_RE = re.compile(r"\bDEAL-[A-Za-z0-9_-]+\b", re.I)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _deal_id(row: Dict[str, Any]) -> str:
    object_id = str(row.get("object_id") or "")
    if object_id.upper().startswith("DEAL-"):
        return object_id
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    for value in (row.get("deal_id"), payload.get("deal_id"), row.get("key"), row.get("title"), row.get("reason")):
        match = _DEAL_RE.search(str(value or ""))
        if match:
            return match.group(0)
    return ""


def _is_priority_action(row: Dict[str, Any]) -> bool:
    key = str(row.get("key") or "").lower()
    kind = str(row.get("kind") or "").lower()
    title = str(row.get("title") or "").lower()
    reason = str(row.get("reason") or "").lower()
    return bool(
        key.startswith("deal_safeguards|")
        or key.startswith("data_truth|")
        or key.startswith("first_cash|")
        or "safe close" in title
        or "close" in kind
        or "cierre" in title
        or "pre-cierre" in title
        or "close-ready" in title
        or "safe-close" in reason
    )


def canonical_priority_cleanup_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    truth = canonical_revenue_truth_tick(state)
    canonical = {str(x) for x in truth.get("canonical_deal_ids", []) or []}
    raw_deals = {str(x.get("id")) for x in state.get("deals", []) or [] if isinstance(x, dict) and x.get("id")}
    quarantined = raw_deals - canonical

    queue = list(state.get("operating_action_queue", []) or [])
    kept: List[Dict[str, Any]] = []
    suppressed: List[Dict[str, Any]] = []
    for row in queue:
        if not isinstance(row, dict):
            kept.append(row)
            continue
        did = _deal_id(row)
        if did and did in quarantined and _is_priority_action(row):
            suppressed.append({
                "ts": utcnow(),
                "key": row.get("key"),
                "title": row.get("title"),
                "deal_id": did,
                "reason": "noncanonical_deal_audit_only",
                "canonical_lane": truth.get("recommended_lane"),
            })
            continue
        kept.append(row)
    state["operating_action_queue"] = kept

    audit = list(state.get("canonical_priority_suppressed_actions", []) or [])
    known = {(str(x.get("key")), str(x.get("deal_id"))) for x in audit if isinstance(x, dict)}
    for row in suppressed:
        sig = (str(row.get("key")), str(row.get("deal_id")))
        if sig not in known:
            audit.append(row)
            known.add(sig)
    state["canonical_priority_suppressed_actions"] = audit[-MAX_AUDIT:]

    # Mark legacy Professional OS snapshots as overridden when they still point to a quarantined deal.
    legacy_overrides = 0
    for key in ("professional_operating_system", "professional_os", "professional_operating_system_snapshot"):
        obj = state.get(key)
        if not isinstance(obj, dict):
            continue
        text = " ".join(str(obj.get(k) or "") for k in ("top_action", "primary_action", "primary", "recommendation"))
        match = _DEAL_RE.search(text)
        if match and match.group(0) in quarantined:
            obj["canonical_priority_suppressed"] = True
            obj["canonical_override_lane"] = truth.get("recommended_lane")
            obj["canonical_override_reason"] = "Legacy diagnostic references a quarantined deal and cannot drive active revenue priority."
            obj["updated_at"] = utcnow()
            legacy_overrides += 1

    report = {
        "version": VERSION,
        "status": "active",
        "updated_at": utcnow(),
        "canonical_lane": truth.get("recommended_lane"),
        "canonical_deals": len(canonical),
        "quarantined_deals": len(quarantined),
        "actions_suppressed_this_tick": len(suppressed),
        "suppressed_deal_ids": sorted({x.get("deal_id") for x in suppressed if x.get("deal_id")}),
        "legacy_snapshots_overridden": legacy_overrides,
        "audit_entries": len(state.get("canonical_priority_suppressed_actions", []) or []),
        "policy": "preserve_raw_history_but_never_rank_noncanonical_deals_for_close_or_first_cash",
    }
    state["canonical_priority_cleanup"] = report
    return report


def _install() -> None:
    try:
        import executive_secretary
    except Exception as exc:
        print({"canonical_priority_cleanup_install": {"status": "error", "error": str(exc)[:200]}}, flush=True)
        return
    original = getattr(executive_secretary, "secretary_tick", None)
    if not callable(original) or getattr(original, "_canonical_priority_cleanup_wrapped", False):
        return

    def wrapped(state: Dict[str, Any]):
        report = canonical_priority_cleanup_tick(state)
        print({"canonical_priority_cleanup": report}, flush=True)
        return original(state)

    wrapped._canonical_priority_cleanup_wrapped = True
    wrapped._canonical_priority_cleanup_original = original
    executive_secretary.secretary_tick = wrapped
    print({"canonical_priority_cleanup_install": {"status": "active", "version": VERSION}}, flush=True)


_install()

# Install the guarded Microservice Factory during the deterministic pre-cycle extension phase.
# It only patches acquisition learning with a product-build lane; it cannot publish/charge/deploy.
import microservice_factory_runtime  # noqa: F401,E402
