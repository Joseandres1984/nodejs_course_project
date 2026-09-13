from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict

import outbound_engine
from https_mail_transport import transport_status

VERSION = "1.2-external-market-readiness"
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


def _legacy_provider_block(state: Dict[str, Any], provider: str | None) -> Dict[str, Any] | None:
    errors = []
    health = dict(state.get("mail_transport_health", {}) or {})
    if health.get("error"):
        errors.append(str(health.get("error")))
    for item in reversed(state.get("outbox", []) or []):
        if item.get("status") != "send_failed":
            continue
        error = str(item.get("last_error") or item.get("last_transport_error") or "")
        if error:
            errors.append(error)
        if len(errors) >= 8:
            break
    joined = "\n".join(errors).lower()
    if provider == "brevo" and (
        "unrecognised ip address" in joined
        or "unrecognized ip address" in joined
        or "authorised_ips" in joined
        or "authorized_ips" in joined
    ):
        return {
            "code": "brevo_api_ip_not_authorized",
            "detail": "Brevo está rechazando la API porque la IP de salida de Railway no está autorizada.",
        }
    return None


def _provider_block(state: Dict[str, Any], provider: str | None) -> Dict[str, Any] | None:
    # Outbound Recovery v1.2 runs a read-only live API probe every cycle. Prefer it over historical
    # send_failed records so a resolved provider issue clears automatically without manual state edits.
    outbound = dict(state.get("outbound_engine", {}) or {})
    if "provider_api_probe_ok" in outbound:
        if outbound.get("provider_api_probe_ok") is True:
            return None
        reason = str(outbound.get("provider_api_probe_reason") or "provider_api_probe_failed")
        status = outbound.get("provider_api_probe_http_status")
        low = reason.lower()
        if provider == "brevo" and (
            "unrecognised ip address" in low
            or "unrecognized ip address" in low
            or "authorised_ips" in low
            or "authorized_ips" in low
        ):
            return {
                "code": "brevo_api_ip_not_authorized",
                "detail": "Brevo está rechazando la API porque la IP de salida de Railway no está autorizada.",
            }
        return {
            "code": "mail_provider_api_probe_failed",
            "detail": f"El proveedor {provider or 'de email'} no pasó el probe API ({status or 'sin HTTP'}): {reason[:240]}",
        }
    return _legacy_provider_block(state, provider)


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
    provider_block = _provider_block(state, transport.get("provider"))
    configured = bool(transport.get("ready"))
    effective_transport_ready = configured and provider_block is None

    if provider_block:
        status = "BLOCKED"
        blocker = provider_block["code"]
    elif not configured:
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

    outbound_report = dict(state.get("outbound_engine", {}) or {})
    report = {
        "version": VERSION,
        "updated_at": utcnow(),
        "status": status,
        "primary_blocker": blocker,
        "mail_transport_configured": configured,
        "mail_transport_ready": effective_transport_ready,
        "mail_provider": transport.get("provider"),
        "mail_route": transport.get("route"),
        "mail_provider_block_detail": provider_block.get("detail") if provider_block else None,
        "provider_api_probe_ok": outbound_report.get("provider_api_probe_ok"),
        "provider_api_probe_http_status": outbound_report.get("provider_api_probe_http_status"),
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
            detail = report.get("mail_provider_block_detail") or f"Motivos principales: {top_reasons}."
            _add_event(
                state,
                f"external_block:{signature}",
                "HIGH",
                "Salida comercial externa bloqueada",
                f"LUMEN está online pero no puede alcanzar mercado por {blocker}. Elegibles={eligible}. {detail}",
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
