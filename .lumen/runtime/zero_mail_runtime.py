from __future__ import annotations

"""Zero-cost authenticated SMTP bridge for LUMEN.

The production mail stack prefers Brevo/Resend HTTPS transports because Railway could block SMTP.
GitHub-hosted LUMEN Zero has an authenticated Gmail SMTP route, so this adapter exposes that route
as a first-class transport after a read-only login probe. It does not send a probe message and it
does not bypass any existing communication, quality, opt-out, go-live, or per-cycle limits.
"""

from typing import Any, Dict

import distribution_operator
import https_mail_transport
import mail_connector
import mail_resilience


VERSION = "1.0-zero-cost-smtp-bridge"
_SMTP_PROVIDERS = {"smtp", "gmail_smtp"}
_probe_cache: Dict[str, Any] | None = None
_original_transport_status = https_mail_transport.transport_status
_original_https_send_pending = https_mail_transport.https_send_pending
_original_https_distribution_tick = https_mail_transport.https_distribution_tick


def _smtp_allowed() -> bool:
    if bool(getattr(https_mail_transport, "SMTP_PLATFORM_BLOCKED", False)):
        return False
    selected = str(getattr(https_mail_transport, "MAIL_PROVIDER", "auto") or "auto").strip().lower()
    return selected in {"auto", "smtp", "gmail", "gmail_smtp"}


def _smtp_probe() -> Dict[str, Any]:
    global _probe_cache
    if _probe_cache is None:
        _probe_cache = dict(mail_resilience.probe_transport() or {})
    return dict(_probe_cache)


def zero_transport_status() -> Dict[str, Any]:
    # Keep a configured production HTTPS provider as the first choice.
    upstream = dict(_original_transport_status() or {})
    if upstream.get("ready"):
        return upstream
    if not _smtp_allowed():
        return upstream

    probe = _smtp_probe()
    if probe.get("ok"):
        provider = "gmail_smtp" if str(probe.get("provider") or "").lower() == "gmail" else "smtp"
        return {
            "ready": True,
            "provider": provider,
            "route": str(probe.get("route") or "authenticated_smtp"),
            "from": str(mail_connector.SMTP_FROM or mail_connector.SMTP_USER or "").strip(),
            "authenticated_probe": True,
            "zero_cost_mode": True,
        }

    if probe.get("configured"):
        return {
            "ready": False,
            "provider": "gmail_smtp" if str(probe.get("provider") or "").lower() == "gmail" else "smtp",
            "route": probe.get("route"),
            "smtp_platform_blocked": False,
            "reason": "smtp_authenticated_probe_failed",
            "zero_cost_mode": True,
        }
    return upstream


def zero_send_pending(state: Dict[str, Any], live_outbound: bool) -> Dict[str, int]:
    status = zero_transport_status()
    if status.get("ready") and status.get("provider") in _SMTP_PROVIDERS:
        # This path retains Communication Director, Quality Gate, opt-out, contact verification,
        # Go-Live and max_outbound_per_tick checks inside resilient_send_pending.
        return mail_resilience.resilient_send_pending(state, live_outbound)
    return _original_https_send_pending(state, live_outbound)


def zero_distribution_tick(state: Dict[str, Any], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    status = zero_transport_status()
    if status.get("ready") and status.get("provider") in _SMTP_PROVIDERS:
        report = dict(mail_resilience.resilient_distribution_tick(state, *args, **kwargs) or {})
        resilience = dict(report.get("mail_resilience", {}) or {})
        resilience.update(
            {
                "version": VERSION,
                "transport_ok": True,
                "provider": status.get("provider"),
                "transport_route": status.get("route"),
                "transport_error": None,
                "authenticated_probe": True,
            }
        )
        report["mail_resilience"] = resilience
        state["distribution_operator"] = report
        return report
    return _original_https_distribution_tick(state, *args, **kwargs)


# Patch before worker_entry imports the downstream readiness/recovery modules. Those modules use
# `from https_mail_transport import transport_status`, so they capture this zero-cost-aware function.
https_mail_transport.transport_status = zero_transport_status
https_mail_transport.https_send_pending = zero_send_pending
https_mail_transport.https_distribution_tick = zero_distribution_tick
mail_connector.send_pending = zero_send_pending
distribution_operator.distribution_operator_tick = zero_distribution_tick

print(
    {
        "zero_mail_runtime": {
            "status": "installed",
            "version": VERSION,
            "probe_message_sent": False,
            "smtp_platform_blocked": bool(getattr(https_mail_transport, "SMTP_PLATFORM_BLOCKED", False)),
        }
    }
)
