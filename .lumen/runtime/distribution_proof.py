from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _key(campaign_id: str, variant_id: str, channel: str) -> str:
    raw = f"{campaign_id}|{variant_id}|{channel}"
    return "DST-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14].upper()


def _receipt_score(row: Dict[str, Any]) -> int:
    score = 0
    if row.get("external_post_id"):
        score += 35
    if row.get("external_url"):
        score += 35
    if row.get("published_at"):
        score += 20
    if row.get("provider"):
        score += 10
    return min(100, score)


def record_distribution_receipt(
    state: Dict[str, Any],
    *,
    campaign_id: str,
    variant_id: str,
    channel: str,
    provider: str = "",
    external_post_id: str = "",
    external_url: str = "",
    published_at: str = "",
    impressions: int = 0,
    clicks: int = 0,
    status: str = "published",
    source: str = "authorized_connector",
) -> Dict[str, Any]:
    receipts = state.setdefault("distribution_receipts", [])
    rid_seed = f"{campaign_id}|{variant_id}|{channel}|{external_post_id}|{external_url}"
    rid = "DRC-" + hashlib.sha1(rid_seed.encode("utf-8")).hexdigest()[:16].upper()
    existing = next((x for x in receipts if x.get("id") == rid), None)
    row = {
        "id": rid,
        "campaign_id": campaign_id,
        "variant_id": variant_id,
        "channel": channel,
        "provider": provider,
        "external_post_id": external_post_id,
        "external_url": external_url,
        "published_at": published_at or utcnow(),
        "impressions": max(0, int(impressions or 0)),
        "clicks": max(0, int(clicks or 0)),
        "status": status,
        "source": source,
        "received_at": utcnow(),
    }
    row["proof_score"] = _receipt_score(row)
    if existing:
        existing.update(row)
        return existing
    receipts.append(row)
    state["distribution_receipts"] = receipts[-5000:]
    return row


def _campaign_clicks(state: Dict[str, Any], campaign_id: str, variant_id: str) -> int:
    return sum(
        1 for x in state.get("acquisition_events", []) or []
        if x.get("event") == "click" and str(x.get("campaign_id") or "") == campaign_id and str(x.get("variant_id") or "") == variant_id
    )


def _campaign_leads(state: Dict[str, Any], campaign_id: str, variant_id: str) -> int:
    return sum(
        1 for x in state.get("acquisition_leads", []) or []
        if str(x.get("campaign_id") or "") == campaign_id and str(x.get("variant_id") or "") == variant_id
    )


def _receipt_for(state: Dict[str, Any], campaign_id: str, variant_id: str, channel: str) -> Optional[Dict[str, Any]]:
    rows = [
        x for x in state.get("distribution_receipts", []) or []
        if str(x.get("campaign_id") or "") == campaign_id
        and str(x.get("variant_id") or "") == variant_id
        and str(x.get("channel") or "") == channel
    ]
    if not rows:
        return None
    rows.sort(key=lambda x: str(x.get("received_at") or ""), reverse=True)
    return rows[0]


def distribution_proof_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    queue = list(state.get("acquisition_distribution_queue", []) or [])
    ledger = state.setdefault("distribution_proof_ledger", [])
    by_key = {str(x.get("id") or ""): x for x in ledger}
    created = updated = 0

    for item in queue:
        campaign_id = str(item.get("campaign_id") or "")
        variant_id = str(item.get("variant_id") or "")
        channel = str(item.get("channel") or "")
        if not campaign_id or not variant_id or not channel:
            continue
        did = _key(campaign_id, variant_id, channel)
        payload = item.get("payload", {}) or {}
        receipt = _receipt_for(state, campaign_id, variant_id, channel)
        requires_connector = bool(payload.get("requires_authorized_connector"))
        requires_budget = bool(payload.get("requires_human_budget_approval"))

        if receipt and int(receipt.get("proof_score") or 0) >= 70:
            status = "verified_published"
            proof_level = "external_receipt"
        elif channel == "owned_market":
            status = "published_owned_channel"
            proof_level = "first_party_live"
        elif requires_budget:
            status = "awaiting_budget_approval"
            proof_level = "prepared_only"
        elif requires_connector:
            status = "awaiting_authorized_connector"
            proof_level = "prepared_only"
        else:
            status = "ready_for_dispatch"
            proof_level = "prepared_only"

        row = {
            "id": did,
            "campaign_id": campaign_id,
            "variant_id": variant_id,
            "audience": item.get("audience"),
            "channel": channel,
            "status": status,
            "proof_level": proof_level,
            "queue_status": item.get("status"),
            "requires_connector": requires_connector,
            "requires_budget_approval": requires_budget,
            "tracking_path": str(payload.get("tracking_path") or ""),
            "external_url": (receipt or {}).get("external_url") or "",
            "external_post_id": (receipt or {}).get("external_post_id") or "",
            "provider": (receipt or {}).get("provider") or "",
            "published_at": (receipt or {}).get("published_at") or (utcnow() if channel == "owned_market" else ""),
            "impressions": int((receipt or {}).get("impressions") or 0),
            "external_clicks": int((receipt or {}).get("clicks") or 0),
            "tracked_clicks": _campaign_clicks(state, campaign_id, variant_id),
            "tracked_leads": _campaign_leads(state, campaign_id, variant_id),
            "proof_score": int((receipt or {}).get("proof_score") or (100 if channel == "owned_market" else 0)),
            "updated_at": utcnow(),
        }
        existing = by_key.get(did)
        if existing:
            first = existing.get("created_at") or utcnow()
            existing.update(row)
            existing["created_at"] = first
            updated += 1
        else:
            row["created_at"] = utcnow()
            ledger.append(row)
            by_key[did] = row
            created += 1

    state["distribution_proof_ledger"] = ledger[-1500:]
    verified = [x for x in ledger if x.get("status") == "verified_published"]
    owned = [x for x in ledger if x.get("status") == "published_owned_channel"]
    waiting_connector = [x for x in ledger if x.get("status") == "awaiting_authorized_connector"]
    waiting_budget = [x for x in ledger if x.get("status") == "awaiting_budget_approval"]
    report = {
        "version": "1.0-proof-ledger",
        "updated_at": utcnow(),
        "ledger_total": len(ledger),
        "created": created,
        "updated": updated,
        "external_verified_published": len(verified),
        "owned_live": len(owned),
        "awaiting_connector": len(waiting_connector),
        "awaiting_budget_approval": len(waiting_budget),
        "external_impressions_verified": sum(int(x.get("impressions") or 0) for x in verified),
        "external_clicks_verified": sum(int(x.get("external_clicks") or 0) for x in verified),
        "tracked_campaign_clicks": sum(int(x.get("tracked_clicks") or 0) for x in ledger),
        "tracked_campaign_leads": sum(int(x.get("tracked_leads") or 0) for x in ledger),
        "truth_rule": "prepared_is_not_published_published_is_not_seen_without_evidence",
    }
    state["distribution_proof"] = report
    return report
