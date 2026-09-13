from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict

import outbound_engine
from https_mail_transport import transport_status

VERSION = "1.0-external-market-readiness"
MAX_EVENTS = 400


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _reason(account: Dict[str, Any], state: Dict[str, Any]) -> str | None:
    if str(account.get("type") or "") not in {"buyer", "supplier"}:
        return "unsupported_account_type"
    if not account.get("verified_company"):
        return "company_not_verified"
    if not account.get("verified_contact"):
        return "contact_not_verified"
    email = str(account.get("commercial_email") or "").strip().lower()
    domain = outbound_engine._email_domain(email)
    official = str(account.get("domain") or "").strip().lower().removeprefix("www.")
    if not domain:
        return "no_valid_email"
    if domain in outbound_engine.FREE_DOMAINS:
        return "free_mail_domain"
    if official and domain != official and not domain.endswith("." + official):
        return "email_domain_mismatch"
    if str(account.get("contact_policy") or "public_corporate_channels_only") != "public_corporate_channels_only":
        return "contact_policy_block"
    if outbound_engine._suppressed(state, email):
        return "suppressed_or_optout"
    if not outbound_engine._risk_allows(state, account):
        return "counterparty_risk_block"
    relation = outbound_engine._relationship(state, account, email)
    if relation.get("opted_out") or relation.get("relationship_state") in {"do_not_contact", "cooldown"}:
        return "relationship_cooldown"
    if outbound_engine._recently_contacted(state, email):
        return "recent_contact_window"
    score, _ = outbound_engine._score(state, account)
    if score < outbound_engine.MIN_SCORE:
        return "below_outbound_score"
    return None


def _add_event(state: Dict[str, Any], key: str, severity: str, title: str, summary: str) -> None:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]
    event_id = f"EXT-{digest}"
    events = state.setdefault("notification_events", [])
    events.append({
        "id": event_id,
        "key": key,
        "severity": severity,
        "kind": "external_market_readiness",
        "title": title,
        "summary": summary,
        "created_at": utcnow(),
    })
    state["notification_events"] = events[-MAX_EVENTS:]


def external_market_readiness_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    transport = transport_status()
    accounts = list(state.get("candidate_accounts", []) or [])
    commercial_accounts = [x for x in accounts if str(x.get("type") or "") in {"buyer", "supplier"}]
    reason_counts: Dict[str, int] = {}
    eligible = 0
    for account in commercial_accounts:
        reason = _reason(account, state)
        if reason is None:
            eligible += 1
        else:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    outbox = list(state.get("outbox", []) or [])
    sent = sum(1 for x in outbox if x.get("status") in {"sent", "delivered"})
    ready = sum(1 for x in outbox if x.get("status") == "ready")
    failed = sum(1 for x in outbox if x.get("status") == "send_failed")
    external_receipts = len(state.get("distribution_receipts", []) or [])
    social_jobs = list(state.get("distribution_operator_jobs", []) or [])
    awaiting_connector = sum(1 for x in social_jobs if x.get("status") == "awaiting_authorized_connector")

    live_requested = bool(getattr(outbound_engine, "LIVE", False))
    if not transport.get("ready"):
        status = "BLOCKED"
        blocker = "mail_transport_not_ready"
    elif not live_requested:
        status = "BLOCKED"
        blocker = "outbound_live_disabled"
    elif eligible <= 0:
        status = "BLOCKED"
        blocker = "no_eligible_external_prospects"
    else:
        status = "READY" if sent == 0 else "ACTIVE"
        blocker = None

    report = {
        "version": VERSION,
        "updated_at": utcnow(),
        "status": status,
        "primary_blocker": blocker,
        "mail_transport_ready": bool(transport.get("ready")),
        "mail_provider": transport.get("provider"),
        "mail_route": transport.get("route"),
        "outbound_live": live_requested,
        "commercial_accounts": len(commercial_accounts),
        "eligible_external_prospects": eligible,
        "ineligibility_reasons": dict(sorted(reason_counts.items(), key=lambda kv: kv[1], reverse=True)),
        "outbox_ready": ready,
        "outbox_sent_or_delivered": sent,
        "outbox_failed": failed,
        "external_distribution_receipts": external_receipts,
        "social_jobs_awaiting_authorized_connector": awaiting_connector,
    }

    previous = dict(state.get("external_market_readiness", {}) or {})
    previous_signature = f"{previous.get('status')}|{previous.get('primary_blocker')}|{previous.get('eligible_external_prospects')}"
    signature = f"{status}|{blocker}|{eligible}"
    if signature != previous_signature:
        if status == "BLOCKED":
            top_reasons = ", ".join(f"{k}={v}" for k, v in list(report["ineligibility_reasons"].items())[:4]) or "sin diagnóstico adicional"
            _add_event(
                state,
                f"external_block:{signature}",
                "HIGH",
                "Salida comercial externa bloqueada",
                f"LUMEN está online pero no puede alcanzar mercado por {blocker}. Elegibles={eligible}. Motivos principales: {top_reasons}.",
            )
        elif status == "READY":
            _add_event(
                state,
                f"external_ready:{signature}",
                "INFO",
                "Salida comercial externa lista",
                f"Transporte {transport.get('provider')} listo y {eligible} prospecto(s) elegible(s). Falta convertir esa capacidad en envío verificado.",
            )
        else:
            _add_event(
                state,
                f"external_active:{signature}",
                "INFO",
                "Salida comercial externa activa",
                f"LUMEN ya registra {sent} envío(s) externo(s) y {eligible} prospecto(s) elegible(s).",
            )

    state["external_market_readiness"] = report
    return report
