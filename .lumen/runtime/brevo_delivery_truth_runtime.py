from __future__ import annotations

"""Verified Brevo delivery truth for governed outbound.

Brevo accepts a message through the send API before recipient delivery is known. This runtime
polls Brevo's transactional event report for a small bounded number of already-sent messages and
records delivered/bounce/open/click evidence without changing send caps or outreach authority.
"""

from datetime import timedelta
from typing import Any, Dict, List
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import outbound_engine

VERSION = "2.0-revenue-sprint-brevo-delivery-truth"
MAX_BREVO_CHECKS_PER_CYCLE = 3
RECHECK_MINUTES = 20
BREVO_API_KEY = os.getenv("LUMEN_BREVO_API_KEY", "").strip()

_ORIGINAL_CHECK_DELIVERY = outbound_engine._check_delivery


def _events(message_id: str) -> List[Dict[str, Any]]:
    if not BREVO_API_KEY or not message_id:
        return []
    query = urllib.parse.urlencode({"messageId": message_id, "limit": 20, "sort": "desc"})
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/statistics/events?" + query,
        headers={"api-key": BREVO_API_KEY, "accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read(30000).decode("utf-8", errors="replace") or "{}")
            rows = payload.get("events", []) or []
            return [x for x in rows if isinstance(x, dict)]
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return []


def _due(item: Dict[str, Any]) -> bool:
    checked = outbound_engine._parse(item.get("brevo_provider_checked_at"))
    if not checked:
        return True
    return outbound_engine.utcnow_dt() - checked >= timedelta(minutes=RECHECK_MINUTES)


def _brevo_delivery_checks(state: Dict[str, Any]) -> int:
    if not BREVO_API_KEY:
        state["brevo_delivery_truth"] = {
            "version": VERSION,
            "status": "not_configured",
            "checked": 0,
            "updated_at": outbound_engine.utcnow(),
        }
        return 0

    checked = 0
    delivered_now = 0
    suppressions = state.setdefault("email_suppression", [])
    suppressed = {
        str(x.get("email") if isinstance(x, dict) else x).strip().lower()
        for x in suppressions
    }
    bad_events = {"hard_bounce", "blocked", "invalid", "spam", "error"}

    for item in state.get("outbox", []) or []:
        if checked >= MAX_BREVO_CHECKS_PER_CYCLE:
            break
        if item.get("source") != "outbound_engine":
            continue
        if str(item.get("email_provider") or "").lower() != "brevo":
            continue
        if str(item.get("status") or "").lower() not in {"sent", "delivered"}:
            continue
        message_id = str(item.get("email_provider_message_id") or "").strip()
        if not message_id or not _due(item):
            continue

        rows = _events(message_id)
        checked += 1
        item["brevo_provider_checked_at"] = outbound_engine.utcnow()
        if not rows:
            continue

        event_names = [str(x.get("event") or "").strip().lower() for x in rows if x.get("event")]
        item["brevo_events_seen"] = list(dict.fromkeys(event_names))[:20]
        latest = event_names[0] if event_names else ""
        if latest:
            item["provider_last_event"] = latest

        delivered = next((x for x in rows if str(x.get("event") or "").lower() == "delivered"), None)
        if delivered and not item.get("delivered_at"):
            item["delivered_at"] = str(delivered.get("date") or outbound_engine.utcnow())
            item["delivery_verified"] = True
            item["delivery_evidence_source"] = "brevo_transactional_event_api"
            delivered_now += 1

        if any(x in {"opened", "unique_opened", "proxy_open", "unique_proxy_open", "first_opening"} for x in event_names):
            item["open_observed"] = True
        if any(x in {"click", "clicked", "unique_click"} for x in event_names):
            item["click_observed"] = True

        bad = next((x for x in event_names if x in bad_events), None)
        if bad:
            email = str(item.get("contact") or "").strip().lower()
            item["delivery_failure_verified"] = True
            item["delivery_failure_event"] = bad
            if email and email not in suppressed:
                suppressions.append({
                    "email": email,
                    "reason": f"brevo_{bad}",
                    "created_at": outbound_engine.utcnow(),
                })
                suppressed.add(email)

    state["email_suppression"] = suppressions[-1000:]
    delivered_total = sum(
        1 for x in state.get("outbox", []) or []
        if x.get("source") == "outbound_engine" and x.get("delivered_at")
    )
    state["brevo_delivery_truth"] = {
        "version": VERSION,
        "status": "active",
        "checked": checked,
        "delivered_new": delivered_now,
        "delivered_verified_total": delivered_total,
        "max_checks_per_cycle": MAX_BREVO_CHECKS_PER_CYCLE,
        "provider": "brevo",
        "paid_spend": False,
        "updated_at": outbound_engine.utcnow(),
    }
    return checked


def _delivery_checks_with_brevo(state: Dict[str, Any]) -> int:
    original = int(_ORIGINAL_CHECK_DELIVERY(state) or 0)
    brevo = _brevo_delivery_checks(state)
    return original + brevo


if not getattr(outbound_engine, "_lumen_brevo_delivery_truth_installed", False):
    outbound_engine._check_delivery = _delivery_checks_with_brevo
    outbound_engine._lumen_brevo_delivery_truth_installed = True

print({
    "brevo_delivery_truth_runtime": {
        "version": VERSION,
        "status": "installed",
        "max_checks_per_cycle": MAX_BREVO_CHECKS_PER_CYCLE,
        "provider_event_api": True,
        "send_caps_changed": False,
        "paid_spend": False,
        "binding_authority_changed": False,
    }
}, flush=True)
