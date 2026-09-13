from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict

COMMAND_CENTER_URL = os.getenv(
    "LUMEN_COMMAND_CENTER_URL",
    "https://lumen-web-production-5755.up.railway.app/command-center",
).strip()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _cfg() -> Dict[str, str]:
    return {
        "enabled": os.getenv("LUMEN_WHATSAPP_ENABLED", "false").strip(),
        "test_only": os.getenv("LUMEN_WHATSAPP_TEST_ONLY", "false").strip(),
        "phone_number_id": os.getenv("LUMEN_WHATSAPP_PHONE_NUMBER_ID", "").strip(),
        "to": os.getenv("LUMEN_WHATSAPP_TO", "").strip(),
        "access_token": os.getenv("LUMEN_WHATSAPP_ACCESS_TOKEN", "").strip(),
        "graph_version": os.getenv("LUMEN_WHATSAPP_GRAPH_VERSION", "").strip(),
        "test_id": os.getenv("LUMEN_WHATSAPP_TEST_ID", "probe-v1").strip() or "probe-v1",
    }


def _safe_meta_error(raw: str) -> Dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
        error = data.get("error") or {}
        return {
            "meta_error_code": error.get("code"),
            "meta_error_subcode": error.get("error_subcode"),
            "meta_error_type": str(error.get("type") or "")[:100] or None,
            "meta_error_message": " ".join(str(error.get("message") or "").split())[:600] or None,
        }
    except Exception:
        return {"meta_error_message": "unparseable_meta_error"}


def whatsapp_probe_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _cfg()
    test_only = _truthy(cfg["test_only"])
    enabled = _truthy(cfg["enabled"])
    credentials_ready = bool(cfg["phone_number_id"] and cfg["to"] and cfg["access_token"] and cfg["graph_version"])

    report: Dict[str, Any] = {
        "updated_at": utcnow(),
        "test_only": test_only,
        "enabled": enabled,
        "credentials_ready": credentials_ready,
        "secrets_exposed": False,
        "status": "inactive",
    }
    if not test_only:
        state["whatsapp_probe"] = report
        return report

    marker_key = f"whatsapp_probe|{cfg['test_id']}"
    history = state.setdefault("whatsapp_probe_history", [])
    existing = next((x for x in history if str(x.get("key") or "") == marker_key), None)
    if existing and existing.get("status") == "sent":
        report.update({"status": "already_sent", "sent_at": existing.get("sent_at")})
        state["whatsapp_probe"] = report
        return report

    if not enabled or not credentials_ready:
        report["status"] = "not_ready"
        state["whatsapp_probe"] = report
        return report

    body = (
        "LUMEN · PRUEBA OK\n"
        "WhatsApp quedó conectado correctamente. Desde ahora LUMEN podrá avisarte eventos importantes.\n"
        f"Command Center: {COMMAND_CENTER_URL}"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": cfg["to"],
        "type": "text",
        "text": {"preview_url": True, "body": body},
    }
    url = f"https://graph.facebook.com/{cfg['graph_version']}/{cfg['phone_number_id']}/messages"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg['access_token']}",
            "Content-Type": "application/json",
        },
    )

    attempt = {
        "key": marker_key,
        "attempted_at": utcnow(),
        "status": "failed",
    }
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
            message_id = ((data.get("messages") or [{}])[0] or {}).get("id")
            attempt.update({"status": "sent", "sent_at": utcnow(), "message_id": message_id, "http_status": int(response.status)})
            report.update({"status": "sent", "message_id_present": bool(message_id), "http_status": int(response.status)})
    except urllib.error.HTTPError as exc:
        raw = exc.read(8000).decode("utf-8", errors="replace") if exc.fp else ""
        safe_error = _safe_meta_error(raw)
        attempt.update({"error": f"HTTPError:{exc.code}", "http_status": int(exc.code), **safe_error})
        report.update({"status": "failed", "error": f"HTTPError:{exc.code}", "http_status": int(exc.code), **safe_error})
    except Exception as exc:
        attempt["error"] = type(exc).__name__
        report.update({"status": "failed", "error": type(exc).__name__})

    if existing:
        existing.update(attempt)
    else:
        history.append(attempt)
        state["whatsapp_probe_history"] = history[-20:]
    state["whatsapp_probe"] = report
    return report
