from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from datetime import timedelta
from typing import Any, Dict

import mail_connector
import outbound_engine
from https_mail_transport import SMTP_PLATFORM_BLOCKED, transport_status

VERSION = "1.3-outbound-recovery"
MAX_RECOVERY_PER_CYCLE = 2
MAX_RECOVERY_RETRIES = 2
_ORIGINAL_TICK = outbound_engine.outbound_engine_tick


def _suppressed(state: Dict[str, Any], email: str) -> bool:
    target = str(email or "").strip().lower()
    if not target:
        return True
    if target in {str(x).strip().lower() for x in state.get("opt_out", []) or []}:
        return True
    for row in state.get("email_suppression", []) or []:
        if isinstance(row, dict) and str(row.get("email") or "").strip().lower() == target:
            return True
        if isinstance(row, str) and row.strip().lower() == target:
            return True
    return False


def _successful_recent_contact(state: Dict[str, Any], email: str) -> bool:
    """Only a verified successful send opens the recontact cooldown."""
    target = str(email or "").strip().lower()
    cutoff = outbound_engine.utcnow_dt() - timedelta(days=outbound_engine.RECONTACT_DAYS)
    for item in reversed(state.get("outbox", []) or []):
        if str(item.get("contact") or "").strip().lower() != target:
            continue
        if item.get("source") not in {"outbound_engine", "distribution_operator_canary"}:
            continue
        if str(item.get("status") or "") not in {"sent", "delivered"}:
            continue
        when = outbound_engine._parse(item.get("delivered_at") or item.get("sent_at"))
        if when and when >= cutoff:
            return True
    return False


# Patch eligibility semantics before the original Outbound Engine evaluates prospects.
outbound_engine._recently_contacted = _successful_recent_contact


def _smtp_auth_probe() -> Dict[str, Any]:
    """Authenticate to the configured SMTP server without sending a message."""
    if SMTP_PLATFORM_BLOCKED:
        return {"ok": False, "provider": "smtp", "reason": "smtp_platform_blocked"}
    status = mail_connector.connector_status()
    if not status.get("smtp_configured"):
        return {"ok": False, "provider": "smtp", "reason": "smtp_not_configured"}

    route = "smtp_ssl" if mail_connector.SMTP_SSL else "smtp_starttls"
    server = None
    try:
        context = ssl.create_default_context()
        if mail_connector.SMTP_SSL:
            server = smtplib.SMTP_SSL(
                mail_connector.SMTP_HOST,
                mail_connector.SMTP_PORT,
                timeout=20,
                context=context,
            )
        else:
            server = smtplib.SMTP(mail_connector.SMTP_HOST, mail_connector.SMTP_PORT, timeout=20)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
        server.login(mail_connector.SMTP_USER, mail_connector.SMTP_PASSWORD)
        server.quit()
        server = None
        return {"ok": True, "provider": "smtp", "route": route, "reason": None}
    except Exception as exc:
        if server is not None:
            try:
                server.close()
            except Exception:
                pass
        return {
            "ok": False,
            "provider": "smtp",
            "route": route,
            "reason": f"{type(exc).__name__}: {str(exc)[:400]}",
        }


def _provider_api_probe() -> Dict[str, Any]:
    """Read-only transport probe so provider/auth failures do not consume delivery retries."""
    transport = transport_status()
    provider = str(transport.get("provider") or "")
    if not transport.get("ready"):
        # The zero-cost runtime can use authenticated SMTP directly. Validate it without sending,
        # instead of requiring a paid/third-party HTTPS mail provider just to clear readiness.
        if not SMTP_PLATFORM_BLOCKED and mail_connector.connector_status().get("smtp_configured"):
            return _smtp_auth_probe()
        return {"ok": False, "provider": provider or None, "reason": transport.get("reason") or "transport_not_configured"}
    if provider != "brevo":
        # Resend/custom providers do not currently require a separate IP-allowlist probe here.
        return {
            "ok": True,
            "provider": provider or None,
            "route": transport.get("route"),
            "reason": None,
        }

    api_key = os.getenv("LUMEN_BREVO_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "provider": "brevo", "reason": "brevo_api_key_missing"}
    req = urllib.request.Request(
        "https://api.brevo.com/v3/account",
        headers={"api-key": api_key, "accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read(4000).decode("utf-8", errors="replace")
            if 200 <= int(resp.status) < 300:
                return {
                    "ok": True,
                    "provider": "brevo",
                    "route": transport.get("route"),
                    "http_status": int(resp.status),
                    "reason": None,
                }
            return {"ok": False, "provider": "brevo", "http_status": int(resp.status), "reason": raw[:500]}
    except urllib.error.HTTPError as exc:
        raw = exc.read(4000).decode("utf-8", errors="replace") if exc.fp else ""
        reason = raw[:500] or f"http_{exc.code}"
        try:
            parsed = json.loads(raw) if raw else {}
            reason = str(parsed.get("message") or parsed.get("code") or reason)[:500]
        except Exception:
            pass
        return {"ok": False, "provider": "brevo", "http_status": int(exc.code), "reason": reason}
    except Exception as exc:
        return {"ok": False, "provider": "brevo", "reason": f"{type(exc).__name__}: {str(exc)[:400]}"}


def _recover_failed_outbound(state: Dict[str, Any], probe: Dict[str, Any]) -> int:
    if not probe.get("ok"):
        return 0

    recovered = 0
    for item in state.get("outbox", []) or []:
        if recovered >= MAX_RECOVERY_PER_CYCLE:
            break
        if item.get("source") != "outbound_engine" or item.get("status") != "send_failed":
            continue
        if int(item.get("https_recovery_count") or 0) >= MAX_RECOVERY_RETRIES:
            continue
        email = str(item.get("contact") or "").strip().lower()
        if not item.get("contact_verified") or _suppressed(state, email):
            continue
        # Preserve existing communication and quality gates. We never revive a message that did not
        # already pass them; this is transport recovery, not a way around commercial governance.
        if item.get("quality_gate") != "passed" or not item.get("communication_reviewed"):
            continue

        item["https_recovery_count"] = int(item.get("https_recovery_count") or 0) + 1
        item["last_transport_error"] = item.pop("last_error", None)
        item["status"] = "ready"
        item["recovery_reason"] = "previous_delivery_failed_before_verified_contact; retry_same_message_after_provider_probe_ok"
        recovered += 1
    return recovered


def recovery_outbound_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    probe = _provider_api_probe()
    recovered = _recover_failed_outbound(state, probe)
    report = dict(_ORIGINAL_TICK(state) or {})
    report["recovery_runtime_version"] = VERSION
    report["failed_messages_requeued"] = recovered
    report["transport_ready_for_recovery"] = bool(probe.get("ok"))
    report["provider_api_probe_ok"] = bool(probe.get("ok"))
    report["provider_api_probe_provider"] = probe.get("provider")
    report["provider_api_probe_route"] = probe.get("route")
    report["provider_api_probe_http_status"] = probe.get("http_status")
    report["provider_api_probe_reason"] = probe.get("reason")
    report["recent_contact_policy"] = "sent_or_delivered_only"
    state["outbound_engine"] = report
    return report


if not getattr(outbound_engine, "_lumen_outbound_recovery_installed", False):
    outbound_engine.outbound_engine_tick = recovery_outbound_tick
    outbound_engine._lumen_outbound_recovery_installed = True
