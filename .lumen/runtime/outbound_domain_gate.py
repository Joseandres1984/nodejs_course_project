from __future__ import annotations

import os
import re
from typing import Any, Dict

import https_mail_transport
import outbound_engine


VERSION = "1.2-production-sender-gate-zero-cost"
_REQUESTED_LIVE = os.getenv("LUMEN_OUTBOUND_LIVE", "false").strip().lower() == "true"
_ZERO_COST_MODE = os.getenv("LUMEN_ZERO_COST_MODE", "false").strip().lower() == "true"

_RESEND_API_KEY_PRESENT = bool(os.getenv("LUMEN_RESEND_API_KEY", "").strip())
_RESEND_SENDER = os.getenv("LUMEN_RESEND_FROM", "").strip()

_BREVO_API_KEY_PRESENT = bool(os.getenv("LUMEN_BREVO_API_KEY", "").strip())
_BREVO_SENDER = os.getenv("LUMEN_BREVO_FROM_EMAIL", "").strip()
_BREVO_SENDER_VERIFIED = os.getenv("LUMEN_BREVO_SENDER_VERIFIED", "false").strip().lower() == "true"


def _sender_email(value: str) -> str:
    text = str(value or "").strip().lower()
    bracket = re.search(r"<([^<>\s]+@[^<>\s]+)>", text)
    if bracket:
        return bracket.group(1)
    plain = re.search(r"([^\s<>]+@[^\s<>]+)", text)
    return plain.group(1) if plain else ""


_RESEND_EMAIL = _sender_email(_RESEND_SENDER)
_RESEND_DOMAIN = _RESEND_EMAIL.rsplit("@", 1)[-1] if "@" in _RESEND_EMAIL else ""
_RESEND_SANDBOX = _RESEND_DOMAIN == "resend.dev" or _RESEND_DOMAIN.endswith(".resend.dev")
_RESEND_PRODUCTION_READY = bool(_RESEND_API_KEY_PRESENT and _RESEND_DOMAIN and not _RESEND_SANDBOX)

_BREVO_EMAIL = _sender_email(_BREVO_SENDER)
_BREVO_DOMAIN = _BREVO_EMAIL.rsplit("@", 1)[-1] if "@" in _BREVO_EMAIL else ""
_BREVO_READY = bool(_BREVO_API_KEY_PRESENT and _BREVO_EMAIL and _BREVO_SENDER_VERIFIED)

# In Zero mode, an authenticated SMTP route is a legitimate production sender. zero_mail_runtime
# patches transport_status before this module loads and only reports authenticated_probe=True after
# a real login succeeds. This keeps the legacy Resend/Brevo gate intact outside Zero mode.
_SMTP_STATUS = dict(https_mail_transport.transport_status() or {}) if _ZERO_COST_MODE else {}
_SMTP_PROVIDER = str(_SMTP_STATUS.get("provider") or "").strip().lower()
_SMTP_EMAIL = _sender_email(str(_SMTP_STATUS.get("from") or ""))
_SMTP_DOMAIN = _SMTP_EMAIL.rsplit("@", 1)[-1] if "@" in _SMTP_EMAIL else ""
_ZERO_SMTP_READY = bool(
    _ZERO_COST_MODE
    and _SMTP_STATUS.get("ready")
    and _SMTP_STATUS.get("authenticated_probe")
    and _SMTP_PROVIDER in {"smtp", "gmail_smtp"}
    and _SMTP_EMAIL
)

# Production outbound may use either:
# 1) a verified custom-domain Resend sender;
# 2) a Brevo sender explicitly verified in the provider account; or
# 3) in LUMEN Zero only, the authenticated SMTP sender proven by zero_mail_runtime.
_PRODUCTION_SENDER_READY = bool(_RESEND_PRODUCTION_READY or _BREVO_READY or _ZERO_SMTP_READY)
_SELECTED_PROVIDER = (
    "resend" if _RESEND_PRODUCTION_READY
    else "brevo" if _BREVO_READY
    else _SMTP_PROVIDER if _ZERO_SMTP_READY
    else None
)
_SELECTED_DOMAIN = (
    _RESEND_DOMAIN if _RESEND_PRODUCTION_READY
    else _BREVO_DOMAIN if _BREVO_READY
    else _SMTP_DOMAIN if _ZERO_SMTP_READY
    else None
)

outbound_engine.LIVE = bool(_REQUESTED_LIVE and _PRODUCTION_SENDER_READY)
_ORIGINAL_TICK = outbound_engine.outbound_engine_tick


def gated_outbound_engine_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_TICK(state) or {})
    if outbound_engine.LIVE:
        blocker = None
    elif not _REQUESTED_LIVE:
        blocker = "outbound_live_disabled"
    elif _ZERO_COST_MODE and not _ZERO_SMTP_READY and not (_RESEND_PRODUCTION_READY or _BREVO_READY):
        blocker = "authenticated_zero_cost_smtp_required"
    elif _RESEND_API_KEY_PRESENT and _RESEND_SANDBOX and not _BREVO_READY:
        blocker = "verified_custom_resend_domain_or_verified_brevo_sender_required"
    elif _BREVO_API_KEY_PRESENT and not _BREVO_SENDER_VERIFIED:
        blocker = "brevo_sender_verification_required"
    else:
        blocker = "production_sender_not_ready"

    report.update({
        "domain_gate_version": VERSION,
        "live_requested": _REQUESTED_LIVE,
        "production_sender_ready": _PRODUCTION_SENDER_READY,
        "sender_provider": _SELECTED_PROVIDER,
        "sender_domain": _SELECTED_DOMAIN,
        "resend_sandbox_sender": _RESEND_SANDBOX,
        "brevo_sender_verified": _BREVO_SENDER_VERIFIED,
        "zero_cost_smtp_authenticated": _ZERO_SMTP_READY,
        "live": bool(outbound_engine.LIVE),
        "status": "active" if outbound_engine.LIVE else "prepared",
        "live_blocker": blocker,
        "sender_policy": "verified_https_provider_or_authenticated_zero_cost_smtp",
    })
    state["outbound_engine"] = report
    return report


if not getattr(outbound_engine, "_lumen_production_sender_gate_installed", False):
    outbound_engine.outbound_engine_tick = gated_outbound_engine_tick
    outbound_engine._lumen_production_sender_gate_installed = True

# Install Intelligence products, then harden their candidate quality before the outbound bridge
# captures the service tick. Only verified corporate contacts with matching domains enter this lane;
# research/news/job/social surfaces stay available as evidence sources but not acquisition targets.
import intelligence_revenue_runtime  # noqa: E402,F401
import intelligence_quality_gate_runtime  # noqa: E402,F401

# Revenue focus stays inside the same sender/domain/quality/risk/opt-out and volume gates.
# This only prioritizes already-qualified paid-service candidates within the existing caps.
import service_revenue_outbound_runtime  # noqa: E402,F401

# Add transparent launch pricing to those already-governed service messages. The wrapper is installed
# after the service-specific copy so it can append a non-binding starting price without bypassing
# targeting, quality, opt-out, sender, volume, contract or payment controls.
import offer_outbound_runtime  # noqa: E402,F401

# Guarantee that the service + Intelligence revenue engine executes after the main business cycle
# whenever Continuous Revenue Drive runs. This turns the new lane into deterministic cycle work,
# not an import-time side effect, while preserving every existing spend and binding-action gate.
import intelligence_cycle_bridge_runtime  # noqa: E402,F401
