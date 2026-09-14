from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict

import distribution_operator
import mail_connector
import mail_resilience


VERSION = "1.2-branded-html-outbound"
SMTP_PLATFORM_BLOCKED = os.getenv("LUMEN_SMTP_PLATFORM_BLOCKED", "false").lower() == "true"
MAIL_PROVIDER = (os.getenv("LUMEN_MAIL_PROVIDER") or "auto").strip().lower()
RESEND_API_KEY = os.getenv("LUMEN_RESEND_API_KEY", "").strip()
RESEND_FROM = os.getenv("LUMEN_RESEND_FROM", "").strip()
BREVO_API_KEY = os.getenv("LUMEN_BREVO_API_KEY", "").strip()
BREVO_FROM_EMAIL = os.getenv("LUMEN_BREVO_FROM_EMAIL", "").strip()
BREVO_FROM_NAME = os.getenv("LUMEN_BREVO_FROM_NAME", "LUMEN B2B").strip() or "LUMEN B2B"
BREVO_SENDER_VERIFIED = os.getenv("LUMEN_BREVO_SENDER_VERIFIED", "false").lower() == "true"
MAX_HTTPS_RETRIES = max(0, min(3, int(os.getenv("LUMEN_HTTPS_MAIL_MAX_RETRIES", "2"))))


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(state: Dict[str, Any], message: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": message})
    state["activity"] = state["activity"][:100]


def _resend_ready() -> bool:
    return bool(RESEND_API_KEY and RESEND_FROM)


def _brevo_ready() -> bool:
    return bool(BREVO_API_KEY and BREVO_FROM_EMAIL and BREVO_SENDER_VERIFIED)


def transport_status() -> Dict[str, Any]:
    # Explicit selection prevents the Resend sandbox sender from shadowing a verified Brevo sender.
    if MAIL_PROVIDER == "brevo":
        if _brevo_ready():
            return {"ready": True, "provider": "brevo", "route": "https_api_443", "from": BREVO_FROM_EMAIL}
        return {
            "ready": False,
            "provider": "brevo",
            "route": "https_api_443",
            "smtp_platform_blocked": SMTP_PLATFORM_BLOCKED,
            "reason": "brevo_not_ready_or_sender_not_verified",
        }
    if MAIL_PROVIDER == "resend":
        if _resend_ready():
            return {"ready": True, "provider": "resend", "route": "https_api_443", "from": RESEND_FROM}
        return {
            "ready": False,
            "provider": "resend",
            "route": "https_api_443",
            "smtp_platform_blocked": SMTP_PLATFORM_BLOCKED,
            "reason": "resend_not_ready",
        }

    # Auto mode prefers a provider that is explicitly production-ready.
    if _brevo_ready():
        return {"ready": True, "provider": "brevo", "route": "https_api_443", "from": BREVO_FROM_EMAIL}
    if _resend_ready():
        return {"ready": True, "provider": "resend", "route": "https_api_443", "from": RESEND_FROM}
    return {
        "ready": False,
        "provider": None,
        "route": None,
        "smtp_platform_blocked": SMTP_PLATFORM_BLOCKED,
        "reason": "https_provider_not_configured",
    }


def _post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read(12000).decode("utf-8", errors="replace")
            if int(resp.status) < 200 or int(resp.status) >= 300:
                raise RuntimeError(f"http_{resp.status}:{raw[:500]}")
            try:
                return json.loads(raw) if raw else {}
            except Exception:
                return {"raw": raw[:500]}
    except urllib.error.HTTPError as exc:
        raw = exc.read(12000).decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(f"http_{exc.code}:{raw[:500]}") from exc


def _safe_tracking_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return ""
    return url


def _is_railway_url(value: str) -> bool:
    try:
        host = (urllib.parse.urlparse(value).hostname or "").lower()
    except Exception:
        return False
    return host.endswith(".up.railway.app") or host.endswith(".railway.app")


def _text_for_delivery(body: str, tracking_url: str) -> str:
    """Keep a useful text fallback without exposing infrastructure URLs to recipients."""
    text = str(body or "")
    url = _safe_tracking_url(tracking_url)
    if not url or not _is_railway_url(url):
        return text
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", text):
        if url in paragraph and paragraph.strip().lower().startswith("más información"):
            paragraphs.append("Más información: respondé este correo y con gusto te compartimos el acceso.")
        else:
            paragraphs.append(paragraph)
    return "\n\n".join(paragraphs)


def _paragraph_html(paragraph: str) -> str:
    escaped = html.escape(paragraph.strip(), quote=False).replace("\n", "<br>")
    return f'<p style="margin:0 0 18px 0;line-height:1.55;">{escaped}</p>' if escaped else ""


def _render_html(body: str, tracking_url: str) -> str:
    url = _safe_tracking_url(tracking_url)
    chunks = []
    cta_inserted = False
    for paragraph in re.split(r"\n\s*\n", str(body or "").strip()):
        stripped = paragraph.strip()
        if not stripped:
            continue
        if url and url in stripped and stripped.lower().startswith("más información"):
            safe_href = html.escape(url, quote=True)
            chunks.append(
                '<div style="margin:24px 0 26px 0;">'
                f'<a href="{safe_href}" style="display:inline-block;background:#172033;color:#ffffff;text-decoration:none;'
                'font-weight:700;padding:12px 20px;border-radius:8px;">Conocer LUMEN B2B</a>'
                '</div>'
            )
            cta_inserted = True
            continue
        if "Saludos cordiales," in stripped and "LUMEN B2B" in stripped:
            lines = [x.strip() for x in stripped.splitlines() if x.strip()]
            rendered = []
            for line in lines:
                safe = html.escape(line, quote=False)
                if line == "LUMEN B2B":
                    rendered.append(f'<strong style="font-size:17px;">{safe}</strong>')
                elif line == "Inteligencia comercial y oportunidades B2B":
                    rendered.append(f'<span style="font-weight:600;">{safe}</span>')
                else:
                    rendered.append(safe)
            chunks.append(
                '<div style="margin-top:28px;padding-top:18px;border-top:1px solid #e5e7eb;line-height:1.55;color:#374151;">'
                + "<br>".join(rendered)
                + "</div>"
            )
            continue
        chunks.append(_paragraph_html(stripped))

    if url and not cta_inserted:
        safe_href = html.escape(url, quote=True)
        chunks.append(
            '<div style="margin:24px 0 26px 0;">'
            f'<a href="{safe_href}" style="display:inline-block;background:#172033;color:#ffffff;text-decoration:none;'
            'font-weight:700;padding:12px 20px;border-radius:8px;">Conocer LUMEN B2B</a>'
            '</div>'
        )

    return (
        '<!doctype html><html><body style="margin:0;padding:0;background:#ffffff;">'
        '<div style="max-width:640px;margin:0 auto;padding:28px 22px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif;'
        'font-size:16px;color:#111827;">'
        + "".join(chunks)
        + '</div></body></html>'
    )


def _send_https(target: str, subject: str, body: str, html_body: str | None = None) -> tuple[str, str | None]:
    status = transport_status()
    provider = status.get("provider")
    if provider == "resend" and status.get("ready"):
        payload: Dict[str, Any] = {"from": RESEND_FROM, "to": [target], "subject": subject, "text": body}
        if html_body:
            payload["html"] = html_body
        result = _post_json(
            "https://api.resend.com/emails",
            payload,
            {"Authorization": f"Bearer {RESEND_API_KEY}"},
        )
        return "resend", str(result.get("id") or "") or None
    if provider == "brevo" and status.get("ready"):
        payload = {
            "sender": {"email": BREVO_FROM_EMAIL, "name": BREVO_FROM_NAME},
            "to": [{"email": target}],
            "subject": subject,
            "textContent": body,
        }
        if html_body:
            payload["htmlContent"] = html_body
        result = _post_json(
            "https://api.brevo.com/v3/smtp/email",
            payload,
            {"api-key": BREVO_API_KEY, "accept": "application/json"},
        )
        return "brevo", str(result.get("messageId") or result.get("message_id") or "") or None
    raise RuntimeError("https_email_provider_not_ready")


def https_send_pending(state: Dict[str, Any], live_outbound: bool) -> Dict[str, int]:
    status = transport_status()
    if not status.get("ready"):
        if SMTP_PLATFORM_BLOCKED:
            state["mail_transport_health"] = {
                "version": VERSION,
                "checked_at": utcnow(),
                "ok": False,
                "provider": status.get("provider"),
                "route": status.get("route"),
                "error": status.get("reason") or "smtp_blocked_by_hosting_platform; configure_resend_or_brevo_https",
            }
            return {"sent": 0, "blocked": 0, "failed": 0}
        return mail_resilience.resilient_send_pending(state, live_outbound)

    state.setdefault("outbox", [])
    state.setdefault("opt_out", [])
    stats = {"sent": 0, "blocked": 0, "failed": 0}
    try:
        from app import DB_STATUS, LIVE_OUTBOUND
        from go_live_orchestrator import go_live_tick, go_live_post_cycle
        launch = go_live_tick(state, DB_STATUS, bool(LIVE_OUTBOUND))
    except Exception as exc:
        _log(state, f"Go-Live Orchestrator no pudo evaluar salida HTTPS: {type(exc).__name__}: {str(exc)[:120]}")
        return stats

    coo = state.get("autonomous_coo", {}) or {}
    quality = state.get("quality_gate_stats", {}) or {}
    if not live_outbound or not launch.get("outbound_allowed"):
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
            item["last_error"] = "HTTPS Mail exige Communication Director + Quality Gate antes de enviar"
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
        tracking_url = _safe_tracking_url(item.get("tracking_url"))
        text_body = _text_for_delivery(body, tracking_url)
        html_body = _render_html(body, tracking_url)
        subject = str(item.get("subject") or "Consulta comercial")
        try:
            provider, message_id = _send_https(target, subject, text_body, html_body)
            item["status"] = "sent"
            item["sent_at"] = utcnow()
            item["email_provider"] = provider
            item["email_provider_message_id"] = message_id
            item["smtp_route"] = "https_api_443"
            item["email_format"] = "multipart_text_html"
            item["branded_cta"] = bool(tracking_url)
            item.pop("last_error", None)
            stats["sent"] += 1
            state["mail_transport_health"] = {
                "version": VERSION,
                "checked_at": utcnow(),
                "ok": True,
                "provider": provider,
                "route": "https_api_443",
            }
            _log(state, f"HTTPS Mail envió {item.get('id')} a {item.get('counterparty')} por {provider}.")
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:500]}"
            item["status"] = "send_failed"
            item["last_error"] = error
            item["failed_at"] = utcnow()
            stats["failed"] += 1
            state["mail_transport_health"] = {
                "version": VERSION,
                "checked_at": utcnow(),
                "ok": False,
                "provider": status.get("provider"),
                "route": "https_api_443",
                "error": error,
            }
            _log(state, f"HTTPS Mail no pudo enviar {item.get('id')}: {error[:260]}")
    go_live_post_cycle(state, stats, coo, quality)
    return stats


def _requeue_failed_for_https(state: Dict[str, Any]) -> int:
    if not transport_status().get("ready"):
        return 0
    count = 0
    for item in state.get("outbox", []) or []:
        if item.get("source") != "distribution_operator_canary" or item.get("status") != "send_failed":
            continue
        if int(item.get("https_retry_count") or 0) >= MAX_HTTPS_RETRIES:
            continue
        item["https_retry_count"] = int(item.get("https_retry_count") or 0) + 1
        item["https_retry_at"] = utcnow()
        item["last_error_previous"] = item.pop("last_error", None)
        item["status"] = "ready"
        count += 1
    return count


def https_distribution_tick(state: Dict[str, Any], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    status = transport_status()
    if status.get("ready"):
        requeued = _requeue_failed_for_https(state)
        report = dict(mail_resilience._original_distribution_tick(state, *args, **kwargs) or {})
        report["mail_resilience"] = {
            "version": VERSION,
            "transport_ok": True,
            "provider": status.get("provider"),
            "transport_route": "https_api_443",
            "requeued": requeued,
            "max_canary_retries": MAX_HTTPS_RETRIES,
        }
    elif SMTP_PLATFORM_BLOCKED:
        report = dict(mail_resilience._original_distribution_tick(state, *args, **kwargs) or {})
        report["mail_resilience"] = {
            "version": VERSION,
            "transport_ok": False,
            "provider": status.get("provider"),
            "transport_route": status.get("route"),
            "requeued": 0,
            "transport_error": status.get("reason") or "smtp_blocked_by_hosting_platform; https_provider_not_configured",
            "max_canary_retries": MAX_HTTPS_RETRIES,
        }
    else:
        report = dict(mail_resilience.resilient_distribution_tick(state, *args, **kwargs) or {})
    state["distribution_operator"] = report
    return report


mail_connector.send_pending = https_send_pending
distribution_operator.distribution_operator_tick = https_distribution_tick
