from __future__ import annotations

import os
import re
import smtplib
import ssl
from contextlib import suppress
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, Iterable, Tuple

import mail_connector
import distribution_operator


VERSION = "1.0-mail-resilience"
MAX_CANARY_RETRIES = max(0, min(3, int(os.getenv("LUMEN_MAIL_CANARY_MAX_RETRIES", "2"))))


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(state: Dict[str, Any], message: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": message})
    state["activity"] = state["activity"][:100]


def _gmailish(host: str, user: str) -> bool:
    host = str(host or "").lower()
    user = str(user or "").lower()
    return "gmail" in host or user.endswith("@gmail.com") or user.endswith("@googlemail.com")


def _password_candidates(host: str, user: str, password: str) -> list[str]:
    raw = str(password or "").strip()
    candidates = [raw] if raw else []
    if raw and _gmailish(host, user):
        compact = re.sub(r"\s+", "", raw)
        if compact and compact not in candidates:
            candidates.insert(0, compact)
    return candidates


def _routes() -> list[Tuple[str, int, bool, str]]:
    host = str(mail_connector.SMTP_HOST or "").strip()
    port = int(mail_connector.SMTP_PORT or 587)
    use_ssl = bool(mail_connector.SMTP_SSL)
    routes: list[Tuple[str, int, bool, str]] = []

    def add(h: str, p: int, s: bool, label: str) -> None:
        row = (h, p, s, label)
        if h and row not in routes:
            routes.append(row)

    add(host, port, use_ssl, "configured")
    if _gmailish(host, mail_connector.SMTP_USER):
        add("smtp.gmail.com", 587, False, "gmail_starttls_587")
        add("smtp.gmail.com", 465, True, "gmail_ssl_465")
    return routes


def _open_authenticated_client() -> tuple[smtplib.SMTP, str]:
    user = str(mail_connector.SMTP_USER or "").strip()
    password = str(mail_connector.SMTP_PASSWORD or "")
    if not user or not password:
        raise RuntimeError("smtp_credentials_missing")

    failures: list[str] = []
    context = ssl.create_default_context()
    for host, port, use_ssl, label in _routes():
        for candidate in _password_candidates(host, user, password):
            client = None
            try:
                if use_ssl:
                    client = smtplib.SMTP_SSL(host, port, timeout=25, context=context)
                    client.ehlo()
                else:
                    client = smtplib.SMTP(host, port, timeout=25)
                    client.ehlo()
                    if not client.has_extn("starttls"):
                        raise RuntimeError("smtp_starttls_not_advertised")
                    client.starttls(context=context)
                    client.ehlo()
                client.login(user, candidate)
                return client, label
            except Exception as exc:
                failures.append(f"{label}:{type(exc).__name__}:{str(exc)[:120]}")
                if client is not None:
                    with suppress(Exception):
                        client.quit()
    raise RuntimeError("smtp_auth_or_transport_failed | " + " | ".join(failures[-4:]))


def probe_transport() -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "version": VERSION,
        "checked_at": utcnow(),
        "configured": bool(mail_connector.connector_status().get("smtp_configured")),
        "ok": False,
        "provider": "gmail" if _gmailish(mail_connector.SMTP_HOST, mail_connector.SMTP_USER) else "smtp",
    }
    if not result["configured"]:
        result["error"] = "smtp_not_configured"
        return result
    client = None
    try:
        client, route = _open_authenticated_client()
        result.update({"ok": True, "route": route, "error": None})
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:420]}"
    finally:
        if client is not None:
            with suppress(Exception):
                client.quit()
    return result


def _safe_send_message(msg: EmailMessage) -> str:
    client = None
    try:
        client, route = _open_authenticated_client()
        # Authentication/transport fallbacks happen before DATA. Once DATA starts we never
        # try a second route automatically, avoiding duplicate delivery on ambiguous failures.
        refused = client.send_message(msg)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
        return route
    finally:
        if client is not None:
            with suppress(Exception):
                client.quit()


def resilient_send_pending(state: Dict[str, Any], live_outbound: bool) -> Dict[str, int]:
    state.setdefault("outbox", [])
    state.setdefault("opt_out", [])
    stats = {"sent": 0, "blocked": 0, "failed": 0}

    try:
        from app import DB_STATUS, LIVE_OUTBOUND
        from go_live_orchestrator import go_live_tick, go_live_post_cycle
        launch = go_live_tick(state, DB_STATUS, bool(LIVE_OUTBOUND))
    except Exception as exc:
        _log(state, f"Go-Live Orchestrator no pudo evaluar salida: {type(exc).__name__}: {str(exc)[:120]}")
        return stats

    coo = state.get("autonomous_coo", {}) or {}
    quality = state.get("quality_gate_stats", {}) or {}
    if not live_outbound or not launch.get("outbound_allowed"):
        go_live_post_cycle(state, stats, coo, quality)
        return stats

    status = mail_connector.connector_status()
    if not status.get("smtp_configured"):
        _log(state, "Mail Connector: salida real habilitada pero SMTP todavía no está configurado.")
        go_live_post_cycle(state, stats, coo, quality)
        return stats

    limit = max(1, int(state.get("policies", {}).get("max_outbound_per_tick", 3)))
    for item in state["outbox"]:
        if stats["sent"] >= limit:
            break
        if item.get("status") != "ready":
            continue
        if item.get("quality_gate") != "passed" or not item.get("communication_reviewed"):
            item["status"] = "blocked_quality"
            item["last_error"] = "Mail Connector exige Communication Director + Quality Gate antes de enviar"
            stats["blocked"] += 1
            continue

        target = str(item.get("contact") or "").strip().lower()
        if not target or not item.get("contact_verified") or target in {str(x).lower() for x in state["opt_out"]}:
            item["status"] = "blocked"
            stats["blocked"] += 1
            continue

        body = str(item.get("body") or "")
        if mail_connector.DISCLOSE_AUTOMATION:
            body += "\n\n—\nLUMEN B2B\nMensaje comercial gestionado con asistencia automatizada."
        msg = EmailMessage()
        msg["From"] = str(mail_connector.SMTP_FROM or mail_connector.SMTP_USER).strip()
        msg["To"] = target
        msg["Subject"] = str(item.get("subject") or "Consulta comercial")
        msg.set_content(body)

        try:
            route = _safe_send_message(msg)
            item["status"] = "sent"
            item["sent_at"] = utcnow()
            item["smtp_route"] = route
            item.pop("last_error", None)
            stats["sent"] += 1
            state["mail_transport_health"] = {
                "version": VERSION,
                "checked_at": utcnow(),
                "ok": True,
                "route": route,
                "provider": "gmail" if _gmailish(mail_connector.SMTP_HOST, mail_connector.SMTP_USER) else "smtp",
            }
            _log(state, f"Mail Connector envió {item.get('id')} a {item.get('counterparty')} por {route}.")
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:420]}"
            item["status"] = "send_failed"
            item["last_error"] = error
            item["failed_at"] = utcnow()
            stats["failed"] += 1
            state["mail_transport_health"] = {
                "version": VERSION,
                "checked_at": utcnow(),
                "ok": False,
                "provider": "gmail" if _gmailish(mail_connector.SMTP_HOST, mail_connector.SMTP_USER) else "smtp",
                "error": error,
            }
            _log(state, f"Mail Connector no pudo enviar {item.get('id')}: {error[:260]}")

    go_live_post_cycle(state, stats, coo, quality)
    return stats


def _failed_canaries(state: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for item in state.get("outbox", []) or []:
        if item.get("source") != "distribution_operator_canary":
            continue
        if item.get("status") != "send_failed":
            continue
        if int(item.get("smtp_retry_count") or 0) >= MAX_CANARY_RETRIES:
            continue
        yield item


def _prepare_safe_retries(state: Dict[str, Any]) -> Dict[str, Any]:
    failed = list(_failed_canaries(state))
    if not failed:
        return {"failed_canaries": 0, "requeued": 0, "probe": None}

    probe = probe_transport()
    state["mail_transport_health"] = probe
    if not probe.get("ok"):
        _log(state, f"Mail Resilience: SMTP todavía no supera el probe: {str(probe.get('error') or '')[:260]}")
        return {"failed_canaries": len(failed), "requeued": 0, "probe": probe}

    requeued = 0
    for item in failed:
        item["smtp_retry_count"] = int(item.get("smtp_retry_count") or 0) + 1
        item["smtp_retry_at"] = utcnow()
        item["status"] = "ready"
        item["last_error_previous"] = item.pop("last_error", None)
        requeued += 1
    if requeued:
        _log(state, f"Mail Resilience: probe SMTP OK; {requeued} canario(s) reencolado(s) con retry acotado.")
    return {"failed_canaries": len(failed), "requeued": requeued, "probe": probe}


_original_distribution_tick = distribution_operator.distribution_operator_tick


def resilient_distribution_tick(state: Dict[str, Any], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    recovery = _prepare_safe_retries(state)
    report = dict(_original_distribution_tick(state, *args, **kwargs) or {})
    report["mail_resilience"] = {
        "version": VERSION,
        "failed_canaries": recovery.get("failed_canaries", 0),
        "requeued": recovery.get("requeued", 0),
        "transport_ok": (recovery.get("probe") or {}).get("ok") if recovery.get("probe") else None,
        "transport_route": (recovery.get("probe") or {}).get("route") if recovery.get("probe") else None,
        "transport_error": (recovery.get("probe") or {}).get("error") if recovery.get("probe") else None,
        "max_canary_retries": MAX_CANARY_RETRIES,
    }
    state["distribution_operator"] = report
    return report


# Normalize Google app-password formatting for both SMTP and IMAP without exposing the secret.
if _gmailish(mail_connector.SMTP_HOST, mail_connector.SMTP_USER):
    mail_connector.SMTP_PASSWORD = re.sub(r"\s+", "", str(mail_connector.SMTP_PASSWORD or ""))
if _gmailish(mail_connector.IMAP_HOST, mail_connector.IMAP_USER):
    mail_connector.IMAP_PASSWORD = re.sub(r"\s+", "", str(mail_connector.IMAP_PASSWORD or ""))

mail_connector.send_pending = resilient_send_pending
distribution_operator.distribution_operator_tick = resilient_distribution_tick
