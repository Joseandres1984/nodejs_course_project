from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo


VERSION = "1.0-canary"
PUBLIC_BASE_URL = (os.getenv("LUMEN_PUBLIC_BASE_URL") or "https://lumen-web-production-5755.up.railway.app").strip().rstrip("/")
MAX_EMAIL_CANARIES_PER_CYCLE = max(0, min(3, int(os.getenv("LUMEN_DISTRIBUTION_CANARY_EMAILS_PER_CYCLE", "1"))))
MAX_EMAIL_CANARIES_PER_DAY = max(0, min(12, int(os.getenv("LUMEN_DISTRIBUTION_CANARY_EMAILS_PER_DAY", "3"))))
AR_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
FREE_DOMAINS = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com", "live.com", "proton.me", "protonmail.com"}
SOCIAL_CHANNELS = {"instagram", "facebook", "linkedin_company"}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def local_day() -> str:
    return datetime.now(timezone.utc).astimezone(AR_TZ).date().isoformat()


def _clean(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _email_domain(email: str) -> str:
    value = _clean(email.lower(), 180)
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", value):
        return ""
    return value.rsplit("@", 1)[-1].removeprefix("www.")


def _job_id(key: str) -> str:
    return "DIST-" + hashlib.sha1(("LUMEN-DIST|" + key).encode("utf-8")).hexdigest()[:12].upper()


def _campaigns(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id") or ""): x for x in state.get("acquisition_campaigns", []) or [] if x.get("id")}


def _variant(campaign: Dict[str, Any], variant_id: str) -> Dict[str, Any]:
    return next((x for x in campaign.get("variants", []) or [] if str(x.get("id") or "") == variant_id), {})


def _proof_for_key(state: Dict[str, Any], queue_key: str) -> Dict[str, Any]:
    return next((x for x in state.get("distribution_proof_ledger", []) or [] if str(x.get("queue_key") or "") == queue_key), {})


def _external_receipt_for(state: Dict[str, Any], campaign_id: str, variant_id: str, channel: str) -> Dict[str, Any]:
    rows = [
        x for x in state.get("distribution_receipts", []) or []
        if str(x.get("campaign_id") or "") == campaign_id
        and str(x.get("variant_id") or "") == variant_id
        and str(x.get("channel") or "") == channel
        and (x.get("external_post_id") or x.get("external_url"))
    ]
    rows.sort(key=lambda x: str(x.get("received_at") or x.get("published_at") or ""), reverse=True)
    return rows[0] if rows else {}


def _ensure_jobs(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    jobs = state.setdefault("distribution_operator_jobs", [])
    by_key = {str(x.get("queue_key") or ""): x for x in jobs}
    for item in state.get("acquisition_distribution_queue", []) or []:
        key = str(item.get("key") or "")
        if not key:
            continue
        job = by_key.get(key)
        payload = dict(item.get("payload", {}) or {})
        tracking_path = str(payload.get("tracking_path") or "")
        tracking_url = str(payload.get("tracking_url") or (PUBLIC_BASE_URL + tracking_path if tracking_path.startswith("/") else ""))
        if not job:
            job = {
                "id": _job_id(key),
                "queue_key": key,
                "campaign_id": item.get("campaign_id"),
                "variant_id": item.get("variant_id"),
                "audience": item.get("audience"),
                "channel": item.get("channel"),
                "created_at": utcnow(),
                "attempts": 0,
            }
            jobs.append(job)
            by_key[key] = job
        job.update({
            "tracking_path": tracking_path,
            "tracking_url": tracking_url,
            "copy": payload.get("copy"),
            "subject": payload.get("subject"),
            "requires_connector": bool(payload.get("requires_authorized_connector")),
            "requires_budget_approval": bool(payload.get("requires_human_budget_approval")),
            "updated_at": utcnow(),
        })
        channel = str(job.get("channel") or "")
        proof = _proof_for_key(state, key)
        receipt = _external_receipt_for(state, str(job.get("campaign_id") or ""), str(job.get("variant_id") or ""), channel)
        if receipt and channel != "owned_market":
            job["status"] = "verified_published"
            job["external_url"] = receipt.get("external_url")
            job["external_post_id"] = receipt.get("external_post_id")
            job["provider"] = receipt.get("provider")
            job["published_at"] = receipt.get("published_at") or receipt.get("received_at")
        elif channel == "owned_market":
            job["status"] = "live_first_party"
            job["provider"] = "lumen_owned_market"
            job["external_url"] = PUBLIC_BASE_URL + "/market"
            job.setdefault("published_at", utcnow())
        elif channel == "paid_ads":
            job["status"] = "awaiting_budget_approval"
        elif channel in SOCIAL_CHANNELS:
            job["status"] = "awaiting_authorized_connector"
        elif channel == "email_b2b":
            job.setdefault("status", "awaiting_verified_recipient")
        else:
            job["status"] = str(proof.get("status") or "ready_for_dispatch")
    state["distribution_operator_jobs"] = jobs[-500:]
    return state["distribution_operator_jobs"]


def _risk_allows(state: Dict[str, Any], account: Dict[str, Any]) -> bool:
    risk = dict((state.get("counterparty_risk_index", {}) or {}).get(str(account.get("id") or ""), {}) or {})
    return risk.get("risk_tier") != "BLOCKED" and risk.get("can_outreach") is not False


def _eligible_accounts(state: Dict[str, Any], audience: str) -> List[Dict[str, Any]]:
    desired = "buyer" if audience == "buyer" else "supplier"
    opt_out = {str(x).strip().lower() for x in state.get("opt_out", []) or []}
    result: List[Dict[str, Any]] = []
    for account in state.get("candidate_accounts", []) or []:
        if str(account.get("type") or "") != desired:
            continue
        if not account.get("verified_company") or not account.get("verified_contact"):
            continue
        email = str(account.get("commercial_email") or "").strip().lower()
        domain = _email_domain(email)
        official = str(account.get("domain") or "").strip().lower().removeprefix("www.")
        if not email or not domain or domain in FREE_DOMAINS or email in opt_out:
            continue
        if official and domain != official and not domain.endswith("." + official):
            continue
        if not _risk_allows(state, account):
            continue
        result.append(account)
    result.sort(key=lambda x: (0 if x.get("direct_inbound_demand") else 1, -float(x.get("verification_score") or x.get("lead_score") or 0), str(x.get("id") or "")))
    return result


def _daily_canary_count(state: Dict[str, Any]) -> int:
    today = local_day()
    return sum(
        1 for x in state.get("outbox", []) or []
        if x.get("source") == "distribution_operator_canary" and str(x.get("canary_local_day") or "") == today
    )


def _queue_email_canaries(state: Dict[str, Any], jobs: List[Dict[str, Any]], dry_run: bool) -> Dict[str, int]:
    stats = {"eligible_jobs": 0, "queued": 0, "already_queued": 0, "no_verified_target": 0, "daily_cap_reached": 0}
    if dry_run or MAX_EMAIL_CANARIES_PER_CYCLE <= 0:
        return stats
    campaigns = _campaigns(state)
    outbox = state.setdefault("outbox", [])
    remaining_today = max(0, MAX_EMAIL_CANARIES_PER_DAY - _daily_canary_count(state))
    remaining_cycle = min(MAX_EMAIL_CANARIES_PER_CYCLE, remaining_today)
    used_targets = {str(x.get("contact") or "").strip().lower() for x in outbox if x.get("source") == "distribution_operator_canary"}
    if remaining_today <= 0:
        stats["daily_cap_reached"] = 1
        return stats

    for job in jobs:
        if remaining_cycle <= 0:
            break
        if job.get("channel") != "email_b2b" or job.get("status") == "verified_published":
            continue
        stats["eligible_jobs"] += 1
        existing = next((x for x in outbox if str(x.get("distribution_job_id") or "") == str(job.get("id") or "")), None)
        if existing:
            stats["already_queued"] += 1
            job["outbox_id"] = existing.get("id")
            job["status"] = "email_sent_verified" if existing.get("status") == "sent" else "email_" + str(existing.get("status") or "queued")
            continue
        audience = str(job.get("audience") or "")
        targets = [x for x in _eligible_accounts(state, audience) if str(x.get("commercial_email") or "").strip().lower() not in used_targets]
        if not targets:
            stats["no_verified_target"] += 1
            job["status"] = "awaiting_verified_recipient"
            continue
        target = targets[0]
        campaign = campaigns.get(str(job.get("campaign_id") or ""), {})
        variant = _variant(campaign, str(job.get("variant_id") or ""))
        email = str(target.get("commercial_email") or "").strip().lower()
        company = _clean(target.get("company_name") or target.get("name_hint") or target.get("domain") or "empresa", 160)
        subject = _clean(job.get("subject") or variant.get("headline") or campaign.get("headline") or "LUMEN B2B", 160)
        body = str(job.get("copy") or "").strip()
        if len(body) < 80:
            body = f"{variant.get('body') or campaign.get('body') or ''}\n\n{variant.get('cta') or campaign.get('cta') or 'Conocer más'}: {job.get('tracking_url') or ''}"
        oid = f"GROWTH-{len(outbox)+1:05d}"
        row = {
            "id": oid,
            "kind": "growth_canary_" + (audience if audience in {"buyer", "supplier", "partner"} else "b2b"),
            "counterparty": company,
            "counterparty_account_id": target.get("id"),
            "contact": email,
            "contact_verified": True,
            "subject": subject,
            "body": body,
            "category": target.get("category"),
            "status": "ready",
            "source": "distribution_operator_canary",
            "campaign_id": job.get("campaign_id"),
            "variant_id": job.get("variant_id"),
            "distribution_job_id": job.get("id"),
            "tracking_url": job.get("tracking_url"),
            "canary_local_day": local_day(),
            "created_at": utcnow(),
        }
        outbox.append(row)
        used_targets.add(email)
        job["outbox_id"] = oid
        job["target_account_id"] = target.get("id")
        job["target_company"] = company
        job["status"] = "email_queued_for_governed_outbound"
        stats["queued"] += 1
        remaining_cycle -= 1
    return stats


def _refresh_email_jobs(state: Dict[str, Any], jobs: List[Dict[str, Any]]) -> None:
    outbox = {str(x.get("id") or ""): x for x in state.get("outbox", []) or []}
    for job in jobs:
        oid = str(job.get("outbox_id") or "")
        if job.get("channel") != "email_b2b" or not oid:
            continue
        item = outbox.get(oid)
        if not item:
            continue
        status = str(item.get("status") or "")
        if status == "sent":
            job["status"] = "email_sent_verified"
            job["published_at"] = item.get("sent_at")
            job["provider"] = "smtp"
        elif status.startswith("blocked") or status == "send_failed":
            job["status"] = "email_" + status
            job["last_error"] = item.get("last_error") or "; ".join(item.get("quality_reasons", []) or [])
        else:
            job["status"] = "email_" + (status or "queued")


def _attribution_metrics(state: Dict[str, Any]) -> Dict[str, Any]:
    events = state.get("acquisition_events", []) or []
    leads = state.get("acquisition_leads", []) or []
    clicks = sum(1 for x in events if x.get("event") == "click")
    landing_views = sum(1 for x in events if x.get("event") == "landing_view")
    lead_ids = {str(x.get("research_lead_id") or "") for x in leads if x.get("research_lead_id")}
    linked_accounts = [x for x in state.get("candidate_accounts", []) or [] if str(x.get("source_lead_id") or "") in lead_ids]
    verified_accounts = [x for x in linked_accounts if x.get("verified_company")]
    account_ids = {str(x.get("id") or "") for x in linked_accounts if x.get("id")}
    opportunities = []
    for opp in state.get("market_opportunities", []) or []:
        refs = {str(opp.get(k) or "") for k in ("buyer_account_id", "supplier_account_id", "account_id")}
        if refs & account_ids:
            opportunities.append(opp)
    for opp in state.get("opportunities", []) or []:
        refs = {str(opp.get(k) or "") for k in ("buyer_account_id", "supplier_account_id", "account_id")}
        if refs & account_ids and opp not in opportunities:
            opportunities.append(opp)
    commissions = 0.0
    for row in state.get("commission_settlement_cases", []) or []:
        try:
            if str(row.get("source_campaign_id") or "").startswith("ACQ-"):
                commissions += float(row.get("amount_received") or row.get("commission_received") or 0)
        except Exception:
            pass
    return {
        "clicks": clicks,
        "landing_views": landing_views,
        "leads": len(leads),
        "linked_accounts": len(linked_accounts),
        "verified_companies": len(verified_accounts),
        "opportunities": len(opportunities),
        "commission_realized": round(commissions, 2),
    }


def _canary_rows(state: Dict[str, Any], jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    campaigns = _campaigns(state)
    events = state.get("acquisition_events", []) or []
    leads = state.get("acquisition_leads", []) or []
    rows = []
    for campaign in campaigns.values():
        if campaign.get("status") != "active":
            continue
        cid = str(campaign.get("id") or "")
        vid = str(campaign.get("champion_variant_id") or "")
        cj = [x for x in jobs if str(x.get("campaign_id") or "") == cid and str(x.get("variant_id") or "") == vid]
        clicks = sum(1 for x in events if x.get("event") == "click" and x.get("campaign_id") == cid and x.get("variant_id") == vid)
        lead_rows = [x for x in leads if x.get("campaign_id") == cid and x.get("variant_id") == vid]
        external = sum(1 for x in cj if x.get("status") == "verified_published" and x.get("channel") in SOCIAL_CHANNELS)
        sent_email = sum(1 for x in cj if x.get("status") == "email_sent_verified")
        owned = sum(1 for x in cj if x.get("status") == "live_first_party")
        stage = "lead_captured" if lead_rows else "clicked" if clicks else "distributed_external" if external or sent_email else "live_owned" if owned else "prepared"
        rows.append({
            "campaign_id": cid,
            "audience": campaign.get("audience"),
            "variant_id": vid,
            "stage": stage,
            "owned_live": owned,
            "external_verified": external,
            "email_sent": sent_email,
            "clicks": clicks,
            "leads": len(lead_rows),
            "tracking_url": next((x.get("tracking_url") for x in cj if x.get("tracking_url")), None),
            "updated_at": utcnow(),
        })
    return rows


def distribution_operator_tick(state: Dict[str, Any], *, dry_run: bool = False) -> Dict[str, Any]:
    jobs = _ensure_jobs(state)
    _refresh_email_jobs(state, jobs)
    email_stats = _queue_email_canaries(state, jobs, dry_run=dry_run)
    _refresh_email_jobs(state, jobs)
    metrics = _attribution_metrics(state)
    canaries = _canary_rows(state, jobs)
    status_counts: Dict[str, int] = {}
    for job in jobs:
        status = str(job.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    report = {
        "version": VERSION,
        "updated_at": utcnow(),
        "status": "dry_run" if dry_run else "active",
        "public_base_url": PUBLIC_BASE_URL,
        "jobs_total": len(jobs),
        "status_counts": status_counts,
        "owned_live": status_counts.get("live_first_party", 0),
        "external_verified": status_counts.get("verified_published", 0),
        "awaiting_connector": status_counts.get("awaiting_authorized_connector", 0),
        "awaiting_budget_approval": status_counts.get("awaiting_budget_approval", 0),
        "email_sent_verified": status_counts.get("email_sent_verified", 0),
        "email_canary": email_stats,
        "funnel": metrics,
        "canaries": canaries,
        "truth_rule": "distribution_requires_receipt; preparation_never_counts_as_external_publication",
        "connector_contract": "authorized connector must return provider + post_id/url + published_at; metrics may follow later",
        "paid_media_policy": "never_spend_without_human_approved_budget",
    }
    if not dry_run:
        state["distribution_operator"] = report
        state["distribution_canaries"] = canaries
        history = list(state.get("distribution_operator_history", []) or [])
        history.append({
            "updated_at": report["updated_at"],
            "owned_live": report["owned_live"],
            "external_verified": report["external_verified"],
            "awaiting_connector": report["awaiting_connector"],
            "email_sent_verified": report["email_sent_verified"],
            "clicks": metrics["clicks"],
            "leads": metrics["leads"],
            "verified_companies": metrics["verified_companies"],
            "opportunities": metrics["opportunities"],
        })
        state["distribution_operator_history"] = history[-100:]
    return report
