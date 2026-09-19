from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple


VERSION = "3.1-strict-outbound-eligibility-alignment"
ALLOWED_SOURCES = {"verified_account_fit", "intelligence_product_fit"}
TERMINAL_OR_POST_CONTACT = {"contacted", "replied", "diagnosis", "proposal_ready", "followup", "won", "lost"}

SERVICE_PRIORITY = {
    "SRV-QUOTECHECK": 18.0,
    "SRV-SUPPLIERCHECK": 16.0,
    "SRV-TENDER-HUNTER": 14.0,
    "SRV-SOURCING-EXPRESS": 12.0,
    "SRV-B2B-PROSPECTING": 10.0,
    "SRV-EXPORT-SCOUT": 8.0,
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _queueable_new_prospects(
    state: Dict[str, Any],
    prospects: Iterable[Dict[str, Any]],
    sequence_id_fn,
) -> List[Dict[str, Any]]:
    """Keep only prospects that can actually create a new outbound sequence now.

    The upstream outbound gate already enforces verified company/contact, corporate-domain
    matching, suppression, risk, recency and score. This additional check mirrors _queue_new's
    permanent sequence de-duplication so CRM attention is not spent on an account that the
    sender will skip anyway.
    """
    existing = {str(x.get("id") or "") for x in state.get("outbound_sequences", []) or [] if isinstance(x, dict)}
    rows: List[Dict[str, Any]] = []
    for prospect in prospects or []:
        account = prospect.get("account") or {}
        aid = str(account.get("id") or "").strip()
        email = str(prospect.get("email") or "").strip().lower()
        if not aid or not email:
            continue
        if str(sequence_id_fn(aid, email)) in existing:
            continue
        rows.append(prospect)
    return rows


def _existing_service_row(
    pipeline: Iterable[Dict[str, Any]], account_id: str, email: str
) -> Dict[str, Any] | None:
    candidates: List[Dict[str, Any]] = []
    target_email = str(email or "").strip().lower()
    for row in pipeline or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("source") or "") not in ALLOWED_SOURCES:
            continue
        if str(row.get("account_id") or "") != account_id:
            continue
        if str(row.get("stage") or "") in TERMINAL_OR_POST_CONTACT:
            continue
        row_email = str(row.get("email") or "").strip().lower()
        if row_email and row_email != target_email:
            continue
        if not row.get("service_id"):
            continue
        candidates.append(row)
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (
            -SERVICE_PRIORITY.get(str(row.get("service_id") or ""), 0.0),
            -_f(row.get("qualification_score")),
            str(row.get("id") or ""),
        )
    )
    return candidates[0]


def _rank_candidate(prospect: Dict[str, Any], service_id: str, qualification_score: float) -> float:
    return round(
        _f(prospect.get("score"))
        + (_f(qualification_score) * 0.20)
        + SERVICE_PRIORITY.get(str(service_id or ""), 0.0),
        2,
    )


def _ensure_seeded_rows(
    state: Dict[str, Any],
    service_runtime,
    prospect: Dict[str, Any],
) -> Tuple[Dict[str, Any] | None, bool]:
    account = prospect.get("account") or {}
    aid = str(account.get("id") or "").strip()
    email = str(prospect.get("email") or "").strip().lower()
    service = service_runtime._service_for(account)
    if not aid or not email or not service:
        return None, False

    service_id = str(service.get("id") or "")
    opp_id = service_runtime._opp_id(aid, service_id)
    pipeline_id = service_runtime._pipeline_id("verified_account_fit", opp_id, service_id)

    opportunities = state.setdefault("service_revenue_opportunities", [])
    opportunity = next((x for x in opportunities if isinstance(x, dict) and str(x.get("id") or "") == opp_id), None)
    if opportunity is None:
        opportunity = {
            "id": opp_id,
            "service_id": service_id,
            "service_name": service.get("name"),
            "account_id": aid,
            "company_name": service_runtime._clean(
                account.get("company_name")
                or account.get("name_hint")
                or account.get("domain")
                or account.get("official_domain")
                or "Empresa",
                180,
            ),
            "audience": service.get("audience"),
            "fit_score": service_runtime._score(account),
            "status": "prepared_not_sent",
            "commercial_email": email,
            "domain": service_runtime._clean(account.get("domain") or account.get("official_domain"), 180),
            "evidence": {
                "verified_company": bool(account.get("verified_company")),
                "verified_contact": bool(account.get("verified_contact")),
                "demand_signal": bool(account.get("demand_signal")),
                "direct_inbound_demand": bool(account.get("direct_inbound_demand")),
                "strict_outbound_eligible": True,
            },
            "price_status": "not_quoted_human_confirmation_required",
            "binding_terms_human_required": True,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        opportunities.append(opportunity)

    pipeline = state.setdefault("service_sales_pipeline", [])
    row = next((x for x in pipeline if isinstance(x, dict) and str(x.get("id") or "") == pipeline_id), None)
    seeded = row is None
    if row is None:
        company = str(opportunity.get("company_name") or "")
        row = service_runtime._base_pipeline_row(
            {},
            id=pipeline_id,
            source="verified_account_fit",
            source_id=opp_id,
            service_opportunity_id=opp_id,
            service_id=service_id,
            service_name=service.get("name"),
            account_id=aid,
            company_name=company,
            email=email,
            domain=opportunity.get("domain"),
            qualification_score=_f(opportunity.get("fit_score")),
            evidence=dict(opportunity.get("evidence") or {}),
            proactive_attention_active=False,
            inbound_priority=False,
            outreach_draft=service_runtime._outreach_draft(service_id, company),
            diagnostic_brief=service_runtime._diagnostic_brief(service_id, company),
        )
        pipeline.append(row)
    elif not row.get("email"):
        row["email"] = email

    return row, seeded


def align_strict_service_attention(
    state: Dict[str, Any],
    strict_prospects: Iterable[Dict[str, Any]],
    service_runtime,
) -> Dict[str, Any]:
    """Make proactive service attention a subset of genuinely queueable outbound prospects."""
    pipeline = [x for x in state.get("service_sales_pipeline", []) or [] if isinstance(x, dict)]
    queueable = list(strict_prospects or [])
    opportunity_count = len([x for x in state.get("service_revenue_opportunities", []) or [] if isinstance(x, dict)])
    attention_cap = max(1, int(math.ceil(max(1, opportunity_count) * float(service_runtime.SERVICE_LANE_SHARE_CAP))))

    ranked: List[Dict[str, Any]] = []
    for prospect in queueable:
        account = prospect.get("account") or {}
        aid = str(account.get("id") or "").strip()
        email = str(prospect.get("email") or "").strip().lower()
        if not aid or not email:
            continue
        existing = _existing_service_row(pipeline, aid, email)
        if existing:
            service_id = str(existing.get("service_id") or "")
            qualification = _f(existing.get("qualification_score"))
        else:
            service = service_runtime._service_for(account)
            if not service:
                continue
            service_id = str(service.get("id") or "")
            qualification = _f(service_runtime._score(account))
        ranked.append({
            "prospect": prospect,
            "existing": existing,
            "service_id": service_id,
            "qualification_score": qualification,
            "priority": _rank_candidate(prospect, service_id, qualification),
        })

    ranked.sort(
        key=lambda item: (
            -_f(item.get("priority")),
            -_f((item.get("prospect") or {}).get("score")),
            str((((item.get("prospect") or {}).get("account") or {}).get("id")) or ""),
        )
    )
    selected = ranked[:attention_cap]

    selected_ids = set()
    existing_matches = 0
    seeded_matches = 0
    for item in selected:
        prospect = item.get("prospect") or {}
        account = prospect.get("account") or {}
        aid = str(account.get("id") or "")
        email = str(prospect.get("email") or "").strip().lower()
        row = item.get("existing")
        seeded = False
        if row is None:
            row, seeded = _ensure_seeded_rows(state, service_runtime, prospect)
        else:
            existing_matches += 1
        if not isinstance(row, dict):
            continue
        if seeded:
            seeded_matches += 1
        row["email"] = email
        row["proactive_attention_active"] = True
        row["strict_outbound_eligible"] = True
        row["revenue_os_v31_priority"] = item.get("priority")
        row["next_action"] = "Usar el próximo cupo outbound disponible; no contar contacto hasta aceptación real del proveedor de email."
        if str(row.get("stage") or "") not in TERMINAL_OR_POST_CONTACT:
            service_runtime._advance(row, "outreach_prepared", "strict_queueable_service_fit_revenue_os_v31")
        selected_ids.add(str(row.get("id") or ""))

    released = 0
    for row in state.get("service_sales_pipeline", []) or []:
        if not isinstance(row, dict) or str(row.get("source") or "") not in ALLOWED_SOURCES:
            continue
        rid = str(row.get("id") or "")
        if rid in selected_ids:
            continue
        if row.get("proactive_attention_active"):
            released += 1
        row["proactive_attention_active"] = False
        row.pop("strict_outbound_eligible", None)
        row.pop("revenue_os_v31_priority", None)

    preview = []
    for item in selected[:5]:
        prospect = item.get("prospect") or {}
        account = prospect.get("account") or {}
        preview.append({
            "account_id": account.get("id"),
            "service_id": item.get("service_id"),
            "priority": item.get("priority"),
            "outbound_score": prospect.get("score"),
        })

    return {
        "attention_cap": attention_cap,
        "queueable_candidates": len(ranked),
        "selected_service_candidates": len(selected_ids),
        "existing_service_matches": existing_matches,
        "seeded_service_matches": seeded_matches,
        "released_nonqueueable_attention": released,
        "selected_preview": preview,
    }


def install() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "version": VERSION,
        "status": "starting",
        "paid_spend": False,
        "outbound_caps_changed": False,
        "binding_authority_changed": False,
        "production_self_modify": False,
        "updated_at": _utcnow(),
    }
    try:
        import outbound_engine
        import service_revenue_runtime
        import service_revenue_outbound_runtime
        from app import STATE, load_state, save_state

        if not load_state():
            report.update({"status": "degraded_fail_open", "reason": "state_unavailable"})
            print({"revenue_os_v31_alignment": report}, flush=True)
            return report

        strict = list(service_revenue_outbound_runtime._ORIGINAL_ELIGIBLE(STATE) or [])
        queueable = _queueable_new_prospects(STATE, strict, outbound_engine._sequence_id)
        alignment = align_strict_service_attention(STATE, queueable, service_revenue_runtime)

        report.update({
            "status": "active",
            "strict_outbound_eligible": len(strict),
            "strict_new_sequence_queueable": len(queueable),
            "same_outbound_daily_cap": int(outbound_engine.MAX_NEW_PER_DAY),
            "same_outbound_cycle_cap": int(outbound_engine.MAX_NEW_PER_CYCLE),
            "alignment": alignment,
            "truth_rule": "service_priority_is_subset_of_strict_queueable_outbound; prepared_is_not_contacted",
            "updated_at": _utcnow(),
        })
        STATE["revenue_os_v31_alignment"] = dict(report)
        persisted = bool(save_state())
        report["persisted"] = persisted
        report["status"] = "active" if persisted else "degraded_fail_open"
        print({"revenue_os_v31_alignment": report}, flush=True)
        return report
    except Exception as exc:
        report.update({"status": "degraded_fail_open", "reason": f"{type(exc).__name__}: {str(exc)[:300]}"})
        print({"revenue_os_v31_alignment": report}, flush=True)
        return report


if os.getenv("LUMEN_REVENUE_OS_V31_AUTORUN", "true").strip().lower() not in {"0", "false", "no", "off"}:
    install()
