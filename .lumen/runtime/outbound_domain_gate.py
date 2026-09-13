from __future__ import annotations

import os
import re
from typing import Any, Dict

import outbound_engine


VERSION = "1.0-production-sender-gate"
_REQUESTED_LIVE = os.getenv("LUMEN_OUTBOUND_LIVE", "false").strip().lower() == "true"
_RESEND_API_KEY_PRESENT = bool(os.getenv("LUMEN_RESEND_API_KEY", "").strip())
_SENDER = os.getenv("LUMEN_RESEND_FROM", "").strip()


def _sender_email(value: str) -> str:
    text = str(value or "").strip().lower()
    bracket = re.search(r"<([^<>\s]+@[^<>\s]+)>", text)
    if bracket:
        return bracket.group(1)
    plain = re.search(r"([^\s<>]+@[^\s<>]+)", text)
    return plain.group(1) if plain else ""


_SENDER_EMAIL = _sender_email(_SENDER)
_SENDER_DOMAIN = _SENDER_EMAIL.rsplit("@", 1)[-1] if "@" in _SENDER_EMAIL else ""
_SANDBOX_SENDER = _SENDER_DOMAIN == "resend.dev" or _SENDER_DOMAIN.endswith(".resend.dev")
_PRODUCTION_SENDER_READY = bool(_RESEND_API_KEY_PRESENT and _SENDER_DOMAIN and not _SANDBOX_SENDER)

# Fail closed: test-domain credentials can prove the HTTPS integration, but they must never
# be treated as production-ready cold outbound. A verified custom sending domain is required.
outbound_engine.LIVE = bool(_REQUESTED_LIVE and _PRODUCTION_SENDER_READY)
_ORIGINAL_TICK = outbound_engine.outbound_engine_tick


def gated_outbound_engine_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_TICK(state) or {})
    report.update({
        "domain_gate_version": VERSION,
        "live_requested": _REQUESTED_LIVE,
        "production_sender_ready": _PRODUCTION_SENDER_READY,
        "sender_domain": _SENDER_DOMAIN or None,
        "sandbox_sender": _SANDBOX_SENDER,
        "live": bool(outbound_engine.LIVE),
        "status": "active" if outbound_engine.LIVE else "prepared",
        "live_blocker": (
            None
            if outbound_engine.LIVE
            else "outbound_live_disabled"
            if not _REQUESTED_LIVE
            else "verified_custom_resend_domain_required"
            if _SANDBOX_SENDER
            else "production_resend_sender_not_ready"
        ),
        "sender_policy": "verified_custom_domain_required_for_external_prospects",
    })
    state["outbound_engine"] = report
    return report


if not getattr(outbound_engine, "_lumen_production_sender_gate_installed", False):
    outbound_engine.outbound_engine_tick = gated_outbound_engine_tick
    outbound_engine._lumen_production_sender_gate_installed = True
