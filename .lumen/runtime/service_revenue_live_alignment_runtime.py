from __future__ import annotations

"""Late-bound paid-service alignment for LUMEN Zero.

Revenue OS v3.1 aligns service attention during bootstrap, but the normal worker can verify or
re-activate accounts later in the same cycle. This patch re-runs the existing strict eligibility
alignment at the exact moment outbound asks for eligible prospects and also upgrades already-queued,
unsent generic outbound messages immediately before Commercial Execution sends them.

It never widens targeting, changes caps, bypasses opt-out/risk/contact-policy controls, recontacts an
already-sent message, creates spend, or authorizes a binding action.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

import outbound_engine
import revenue_os_v31_alignment_runtime as alignment_runtime
import service_revenue_outbound_runtime as service_bridge
import service_revenue_runtime


VERSION = "1.1-late-bound-service-outbound-alignment"
_ORIGINAL_COMMERCIAL_EXECUTION = outbound_engine._ORIGINAL_COMMERCIAL_EXECUTION


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _eligible_with_live_service_alignment(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Always start from the original strict outbound gate captured before service prioritization.
    # This preserves company/contact verification, corporate-domain matching, suppression, risk,
    # recency/cooldown and minimum-score requirements exactly as the production sender defines them.
    strict = list(service_bridge._ORIGINAL_ELIGIBLE(state) or [])
    queueable = alignment_runtime._queueable_new_prospects(
        state,
        strict,
        outbound_engine._sequence_id,
    )

    alignment = alignment_runtime.align_strict_service_attention(
        state,
        queueable,
        service_revenue_runtime,
    )

    # The existing service bridge now sees the freshly activated rows and decorates only those
    # strict prospects with service context. Its existing queue/message hooks remain authoritative.
    prospects = list(service_bridge._eligible_service_first(state) or [])

    state["service_revenue_live_alignment"] = {
        "version": VERSION,
        "status": "active",
        "strict_outbound_eligible_now": len(strict),
        "strict_new_sequence_queueable_now": len(queueable),
        "selected_service_candidates_now": int(alignment.get("selected_service_candidates") or 0),
        "seeded_service_matches_now": int(alignment.get("seeded_service_matches") or 0),
        "existing_service_matches_now": int(alignment.get("existing_service_matches") or 0),
        "service_ready_in_returned_set": sum(1 for x in prospects if x.get("service_revenue_ready")),
        "same_outbound_daily_cap": int(outbound_engine.MAX_NEW_PER_DAY),
        "same_outbound_cycle_cap": int(outbound_engine.MAX_NEW_PER_CYCLE),
        "eligibility_gate_relaxed": False,
        "cooldown_bypassed": False,
        "paid_spend": False,
        "binding_authority_changed": False,
        "updated_at": _utcnow(),
        "alignment": alignment,
    }
    return prospects


def _current_nonrecency_safety_allows(state: Dict[str, Any], account: Dict[str, Any], email: str) -> bool:
    """Re-check every mutable safety gate except recency for an already-queued unsent message.

    Recency cannot be reused here because the ready queue row itself intentionally makes the account
    look recently contacted. We instead require that the row has never been sent and leave the normal
    Commercial Execution send/quality gates intact.
    """
    if not account.get("verified_company") or not account.get("verified_contact"):
        return False
    if str(account.get("commercial_email") or "").strip().lower() != email:
        return False
    domain = outbound_engine._email_domain(email)
    official = str(account.get("domain") or "").strip().lower().removeprefix("www.")
    if not domain or domain in outbound_engine.FREE_DOMAINS:
        return False
    if official and domain != official and not domain.endswith("." + official):
        return False
    if str(account.get("contact_policy") or "public_corporate_channels_only") != "public_corporate_channels_only":
        return False
    if outbound_engine._suppressed(state, email) or not outbound_engine._risk_allows(state, account):
        return False
    relation = outbound_engine._relationship(state, account, email)
    if relation.get("opted_out") or relation.get("relationship_state") in {"do_not_contact", "cooldown"}:
        return False
    return True


def _retrofit_ready_generic_messages(state: Dict[str, Any]) -> Dict[str, Any]:
    """Convert only already-governed, unsent generic OUT messages into a paid-service offer."""
    accounts = {
        str(x.get("id") or ""): x
        for x in state.get("candidate_accounts", []) or []
        if isinstance(x, dict) and x.get("id")
    }
    sequences = {
        str(x.get("id") or ""): x
        for x in state.get("outbound_sequences", []) or []
        if isinstance(x, dict)
    }
    converted = 0
    reviewed = 0
    skipped_safety = 0
    skipped_no_service = 0
    converted_preview: List[Dict[str, Any]] = []

    for msg in state.get("outbox", []) or []:
        if not isinstance(msg, dict):
            continue
        if msg.get("source") != "outbound_engine" or str(msg.get("status") or "").lower() != "ready":
            continue
        if msg.get("sent_at") or msg.get("service_revenue"):
            continue
        reviewed += 1
        aid = str(msg.get("counterparty_account_id") or "").strip()
        email = str(msg.get("contact") or "").strip().lower()
        account = accounts.get(aid)
        if not account or not _current_nonrecency_safety_allows(state, account, email):
            skipped_safety += 1
            continue

        service = service_revenue_runtime._service_for(account)
        if not service:
            skipped_no_service += 1
            continue

        prospect = {
            "account": account,
            "email": email,
            "score": float(msg.get("target_score") or 0.0),
            "reasons": list(msg.get("target_reasons") or []),
        }
        pipeline, _seeded = alignment_runtime._ensure_seeded_rows(
            state,
            service_revenue_runtime,
            prospect,
        )
        if not isinstance(pipeline, dict):
            skipped_no_service += 1
            continue

        service_id = str(pipeline.get("service_id") or service.get("id") or "")
        intelligence = bool(pipeline.get("intelligence_revenue")) or service_id in {
            "SRV-QUOTECHECK", "SRV-SUPPLIERCHECK", "SRV-EXPORT-SCOUT", "SRV-TENDER-HUNTER"
        }
        ctx = {
            "pipeline_id": pipeline.get("id"),
            "service_opportunity_id": pipeline.get("service_opportunity_id"),
            "service_id": service_id,
            "service_name": pipeline.get("service_name") or service.get("name"),
            "company_name": pipeline.get("company_name"),
            "email": email,
            "qualification_score": pipeline.get("qualification_score"),
            "intelligence_revenue": intelligence,
        }

        account["_lumen_service_revenue_context"] = ctx
        try:
            kind, subject, body = service_bridge._service_message_text(account, {}, service_bridge.SERVICE_URL)
        finally:
            account.pop("_lumen_service_revenue_context", None)

        target_url = service_bridge.INTELLIGENCE_URL if intelligence else service_bridge.SERVICE_URL
        msg.update({
            "kind": kind,
            "subject": subject,
            "body": body,
            "service_revenue": True,
            "intelligence_revenue": intelligence,
            "service_id": service_id,
            "service_name": ctx.get("service_name"),
            "service_pipeline_id": pipeline.get("id"),
            "service_opportunity_id": pipeline.get("service_opportunity_id"),
            "purpose": "paid_intelligence_revenue_acquisition" if intelligence else "paid_service_revenue_acquisition",
            "tracking_url": target_url,
            "service_retrofitted_before_send_at": _utcnow(),
        })

        seq = sequences.get(str(msg.get("outbound_sequence_id") or ""))
        if isinstance(seq, dict):
            seq.update({
                "service_revenue": True,
                "intelligence_revenue": intelligence,
                "service_id": service_id,
                "service_pipeline_id": pipeline.get("id"),
                "service_opportunity_id": pipeline.get("service_opportunity_id"),
                "tracking_url": target_url,
            })

        pipeline["proactive_attention_active"] = True
        pipeline["strict_outbound_eligible"] = True
        pipeline["outbound_queue_truth"] = "queued_not_sent"
        pipeline["outbound_message_id"] = msg.get("id")
        pipeline["next_action"] = "Esperar aceptación real del proveedor de email; no contar contacto antes de envío aceptado."
        if str(pipeline.get("stage") or "") not in alignment_runtime.TERMINAL_OR_POST_CONTACT:
            service_revenue_runtime._advance(pipeline, "outreach_prepared", "retrofit_existing_governed_ready_message")

        converted += 1
        if len(converted_preview) < 5:
            converted_preview.append({
                "outbox_id": msg.get("id"),
                "account_id": aid,
                "service_id": service_id,
                "kind": kind,
            })

    report = {
        "version": VERSION,
        "status": "active",
        "ready_generic_reviewed": reviewed,
        "converted_before_send": converted,
        "skipped_current_safety_gate": skipped_safety,
        "skipped_no_service_fit": skipped_no_service,
        "converted_preview": converted_preview,
        "already_sent_messages_modified": 0,
        "outbound_caps_changed": False,
        "eligibility_gate_relaxed": False,
        "paid_spend": False,
        "binding_authority_changed": False,
        "updated_at": _utcnow(),
    }
    state["service_revenue_ready_retrofit"] = report
    print({"service_revenue_ready_retrofit": report}, flush=True)
    return report


def _commercial_execution_with_ready_retrofit(state: Dict[str, Any]) -> Dict[str, Any]:
    _retrofit_ready_generic_messages(state)
    return dict(_ORIGINAL_COMMERCIAL_EXECUTION(state) or {})


if not getattr(outbound_engine, "_lumen_live_service_alignment_installed", False):
    outbound_engine._eligible = _eligible_with_live_service_alignment
    # outbound_engine's wrapper calls this module variable immediately before it runs its own
    # outbound tick. Putting the retrofit here guarantees existing ready rows are upgraded before
    # Commercial Execution has a chance to send them.
    outbound_engine._ORIGINAL_COMMERCIAL_EXECUTION = _commercial_execution_with_ready_retrofit
    outbound_engine._lumen_live_service_alignment_installed = True

print({
    "service_revenue_live_alignment": {
        "version": VERSION,
        "status": "installed",
        "timing": "eligibility_plus_immediately_before_commercial_send",
        "retrofits_only_unsent_ready_outbound_engine_rows": True,
        "eligibility_gate_relaxed": False,
        "outbound_caps_changed": False,
        "cooldown_bypassed": False,
        "paid_spend": False,
        "binding_authority_changed": False,
    }
}, flush=True)
