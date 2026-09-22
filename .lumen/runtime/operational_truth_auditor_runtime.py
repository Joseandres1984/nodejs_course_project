from __future__ import annotations

"""Canonical operational truth auditor for LUMEN Zero.

Builds one end-of-cycle snapshot from primary persisted evidence instead of trusting every module's
own cached counters. It repairs only safe cumulative projections so dashboards, learning and
executive summaries can converge on the same truth while raw module snapshots remain auditable.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Set

import app
import canonical_revenue_truth_runtime

VERSION = "1.1-canonical-operational-truth"
SENT_STATUSES = {"sent", "provider_accepted", "delivered", "delivered_verified", "replied"}
DELIVERED_STATUSES = {"delivered", "delivered_verified", "replied"}
REALIZED_PAYMENT_STATUSES = {"paid", "settled", "received", "realized", "completed", "succeeded"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _s(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return " ".join(_s(value).lower().split())


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _rows(state: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    return [x for x in state.get(key, []) or [] if isinstance(x, dict)]


def _approval_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = state.get("instagram_publish_approvals")
    if isinstance(raw, dict):
        return [x for x in raw.values() if isinstance(x, dict)]
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _outbound_truth(state: Dict[str, Any]) -> Dict[str, Any]:
    outbox = _rows(state, "outbox")
    sent: Set[str] = set()
    delivered: Set[str] = set()
    failed: Set[str] = set()
    for i, row in enumerate(outbox):
        rid = _s(row.get("id")) or f"row:{i}"
        status = _norm(row.get("status"))
        if row.get("sent_at") or row.get("provider_accepted_at") or status in SENT_STATUSES:
            sent.add(rid)
        if row.get("delivered_at") or row.get("verified_delivery_at") or status in DELIVERED_STATUSES:
            delivered.add(rid)
        if status in {"failed", "send_failed", "blocked_quality"}:
            failed.add(rid)
    return {
        "provider_accepted_or_sent_cumulative": len(sent),
        "delivered_verified_cumulative": len(delivered),
        "failed_or_quality_blocked_cumulative": len(failed),
        "source": "outbox_rows_cumulative",
    }


def _instagram_truth(state: Dict[str, Any]) -> Dict[str, Any]:
    jobs = {
        _s(x.get("id")): x
        for x in _rows(state, "distribution_operator_jobs")
        if _s(x.get("id")) and _norm(x.get("channel")) == "instagram"
    }
    receipt_ids: Set[str] = set()
    for receipt in _rows(state, "distribution_receipts"):
        jid = _s(receipt.get("distribution_job_id"))
        if jid in jobs and (receipt.get("external_post_id") or receipt.get("external_url")):
            receipt_ids.add(jid)
    approval_published = {
        _s(x.get("job_id"))
        for x in _approval_rows(state)
        if _norm(x.get("status")) == "published" and _s(x.get("job_id")) in jobs
    }
    published = receipt_ids | approval_published
    return {
        "jobs_total": len(jobs),
        "published_cumulative": len(published),
        "published_job_ids": sorted(published),
        "source": "distribution_receipts_plus_published_approvals",
    }


def _payment_truth(state: Dict[str, Any]) -> Dict[str, Any]:
    multicurrency = state.get("multicurrency_runtime", {}) or {}
    ready = sorted({_s(x).upper() for x in multicurrency.get("ready_currencies", []) or [] if _s(x)})
    tx = []
    total_usd = 0.0
    for key in ("transactions", "service_revenue_transactions"):
        for row in _rows(state, key):
            status = _norm(row.get("status") or row.get("payment_status"))
            if status not in REALIZED_PAYMENT_STATUSES:
                continue
            amount = _f(row.get("amount_received_usd") or row.get("company_profit_usd") or row.get("profit_usd") or row.get("amount_usd") or row.get("revenue_usd"))
            if amount <= 0 and _s(row.get("currency")).upper() == "USD":
                amount = _f(row.get("company_profit") or row.get("profit") or row.get("amount"))
            if amount > 0:
                total_usd += amount
                tx.append(_s(row.get("id")) or f"{key}:{len(tx)+1}")
    return {
        "ready_currencies": ready,
        "setup_required_currencies": [x for x in ("ARS", "USD", "EUR") if x not in ready],
        "realized_revenue_evidence_usd": round(total_usd, 2),
        "realized_transaction_ids": tx[:50],
        "autonomous_payment": False,
        "source": "multicurrency_runtime_plus_settled_transactions",
    }


def _service_truth(state: Dict[str, Any]) -> Dict[str, Any]:
    rows = _rows(state, "service_sales_pipeline")
    if rows:
        stages = [_norm(x.get("stage")) for x in rows]
        real_contacted = sum(
            1 for x in rows
            if _norm(x.get("contact_truth")) in {"provider_accepted", "replied"}
            or _norm(x.get("stage")) in {"contacted", "replied", "diagnosis", "proposal_ready", "followup", "won"}
        )
        realized = 0.0
        for tx in _rows(state, "service_revenue_transactions"):
            if _norm(tx.get("status")) in {"paid", "settled", "completed"}:
                realized += max(0.0, _f(tx.get("amount_received_usd") or tx.get("revenue_usd")))
        return {
            "pipeline_total": len(rows),
            "outreach_prepared": sum(1 for s in stages if s == "outreach_prepared"),
            "real_contacted": real_contacted,
            "won": sum(1 for s in stages if s == "won"),
            "realized_service_revenue_usd": round(realized, 2),
            "source": "service_sales_pipeline_plus_service_revenue_transactions",
        }
    snap = state.get("service_growth_pipeline", {}) or {}
    return {
        "pipeline_total": int(snap.get("pipeline_total") or 0),
        "outreach_prepared": int(snap.get("outreach_prepared") or 0),
        "real_contacted": int(snap.get("real_contacted") or 0),
        "won": int(snap.get("won") or 0),
        "realized_service_revenue_usd": _f(snap.get("realized_service_revenue_usd")),
        "source": "service_growth_pipeline_snapshot_fallback",
    }


def _append_issue(issues: List[Dict[str, Any]], code: str, reported: Any, canonical: Any, scope: str = "cumulative") -> None:
    try:
        same = reported == canonical or float(reported) == float(canonical)
    except Exception:
        same = reported == canonical
    if not same:
        issues.append({"code": code, "reported": reported, "canonical": canonical, "scope": scope})


def _project_instagram_truth(state: Dict[str, Any], instagram: Dict[str, Any]) -> None:
    published = int(instagram.get("published_cumulative") or 0)

    control = state.setdefault("instagram_publish_control", {})
    control["published_total"] = published
    control["canonical_truth_source"] = instagram.get("source")
    control["canonical_truth_updated_at"] = _now()

    creative = state.setdefault("creative_distribution", {})
    creative["external_verified_published"] = max(int(creative.get("external_verified_published") or 0), published)
    creative["instagram_external_verified_published"] = published
    creative["canonical_truth_updated_at"] = _now()

    campaigns = state.get("acquisition_campaigns")
    if isinstance(campaigns, dict):
        editorial = campaigns.get("instagram_editorial")
        if isinstance(editorial, dict):
            learning = editorial.setdefault("learning", {})
            learning["published_total"] = published
            learning["published_total_source"] = "canonical_distribution_receipts"
            learning["canonical_truth_updated_at"] = _now()


def run_once(state: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if state is None:
        if not app.load_state():
            report = {"version": VERSION, "status": "state_unavailable", "updated_at": _now()}
            print({"operational_truth_auditor": report}, flush=True)
            return report
        state = app.STATE

    accounts = _rows(state, "candidate_accounts")
    verified = [x for x in accounts if x.get("verified_company")]
    buyers = [x for x in verified if x.get("type") == "buyer"]
    suppliers = [x for x in verified if x.get("type") == "supplier"]
    demand = [x for x in buyers if x.get("demand_signal")]
    verified_contacts = [
        x for x in verified
        if x.get("verified_contact") or x.get("commercial_channel_verified") or x.get("commercial_email_verified")
    ]

    revenue_truth = canonical_revenue_truth_runtime.canonical_revenue_truth_tick(state)
    rc = revenue_truth.get("counts", {}) or {}
    outbound = _outbound_truth(state)
    instagram = _instagram_truth(state)
    payments = _payment_truth(state)
    services = _service_truth(state)

    counts = {
        "research_leads": len(_rows(state, "research_leads")),
        "candidate_accounts": len(accounts),
        "verified_companies": len(verified),
        "verified_buyers": len(buyers),
        "verified_suppliers": len(suppliers),
        "verified_commercial_contacts": len(verified_contacts),
        "buyers_with_verified_demand": len(demand),
        "canonical_opportunities": int(rc.get("canonical_opportunities") or 0),
        "canonical_real_offers": int(rc.get("canonical_real_offers") or 0),
        "canonical_proposals": int(rc.get("canonical_proposals") or 0),
        "canonical_close_ready": int(rc.get("canonical_close_ready") or 0),
        "outbound_sent_cumulative": int(outbound["provider_accepted_or_sent_cumulative"]),
        "outbound_delivered_verified_cumulative": int(outbound["delivered_verified_cumulative"]),
        "instagram_published_cumulative": int(instagram["published_cumulative"]),
    }

    issues: List[Dict[str, Any]] = []
    funnel = state.get("business_funnel", {}) or {}
    _append_issue(issues, "funnel_verified_companies", funnel.get("verified_companies"), counts["verified_companies"])
    _append_issue(issues, "funnel_verified_buyers", funnel.get("verified_buyers"), counts["verified_buyers"])
    _append_issue(issues, "funnel_verified_suppliers", funnel.get("verified_suppliers"), counts["verified_suppliers"])
    _append_issue(issues, "funnel_buyers_with_demand", funnel.get("buyers_with_public_demand"), counts["buyers_with_verified_demand"])
    _append_issue(issues, "funnel_canonical_opportunities", funnel.get("evidence_backed_opportunities"), counts["canonical_opportunities"])
    _append_issue(issues, "funnel_canonical_proposals", funnel.get("proposals"), counts["canonical_proposals"])
    _append_issue(issues, "funnel_close_ready", funnel.get("close_ready"), counts["canonical_close_ready"])
    _append_issue(issues, "funnel_outbound_sent", funnel.get("outbound_sent"), counts["outbound_sent_cumulative"])
    publish_snap = state.get("instagram_publish_control", {}) or {}
    _append_issue(issues, "instagram_publish_total", publish_snap.get("published_total"), counts["instagram_published_cumulative"])

    funnel.update({
        "research_leads": counts["research_leads"],
        "candidate_accounts": counts["candidate_accounts"],
        "verified_companies": counts["verified_companies"],
        "verified_buyers": counts["verified_buyers"],
        "verified_suppliers": counts["verified_suppliers"],
        "verified_commercial_channels": counts["verified_commercial_contacts"],
        "verified_corporate_emails": counts["verified_commercial_contacts"],
        "buyers_with_public_demand": counts["buyers_with_verified_demand"],
        "evidence_backed_opportunities": counts["canonical_opportunities"],
        "real_offers": counts["canonical_real_offers"],
        "proposals": counts["canonical_proposals"],
        "close_ready": counts["canonical_close_ready"],
        "outbound_sent": counts["outbound_sent_cumulative"],
        "canonical_truth_version": VERSION,
        "canonical_truth_updated_at": _now(),
    })
    state["business_funnel"] = funnel
    _project_instagram_truth(state, instagram)

    status = "consistent" if not issues else "reconciled"
    report = {
        "version": VERSION,
        "status": status,
        "updated_at": _now(),
        "counts": counts,
        "revenue": {
            "recommended_lane": revenue_truth.get("recommended_lane"),
            "target_metric": revenue_truth.get("target_metric"),
            "reason": revenue_truth.get("reason"),
            "realized_revenue_evidence_usd": payments["realized_revenue_evidence_usd"],
        },
        "outbound": outbound,
        "instagram": instagram,
        "payments": payments,
        "services": services,
        "consistency": {
            "issues_found": len(issues),
            "issues": issues[:50],
            "raw_module_snapshots_preserved": True,
            "per_cycle_counters_are_not_compared_to_cumulative_counters": True,
            "safe_projection_repairs_applied": True,
        },
        "governance": {
            "source_of_truth": "primary_persisted_evidence_plus_canonical_revenue_lineage",
            "legacy_rows_preserved_for_audit": True,
            "binding_actions_human_gated": True,
            "thresholds_lowered": False,
        },
    }
    state["canonical_operational_truth"] = report
    readiness = state.setdefault("external_market_readiness", {})
    readiness["canonical_demand_gap"] = counts["buyers_with_verified_demand"] == 0
    readiness["canonical_truth_version"] = VERSION
    readiness["canonical_truth_updated_at"] = report["updated_at"]

    persisted = app.save_state()
    report["persisted"] = bool(persisted)
    print({"operational_truth_auditor": report}, flush=True)
    return report