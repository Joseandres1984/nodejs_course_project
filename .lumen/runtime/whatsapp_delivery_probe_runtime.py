from __future__ import annotations

from app import STATE, load_state, save_state
from whatsapp_probe import whatsapp_probe_tick

load_state()
report = dict(whatsapp_probe_tick(STATE) or {})
report["persisted"] = bool(save_state())
print({
    "whatsapp_delivery_probe": {
        "status": report.get("status"),
        "enabled": report.get("enabled"),
        "credentials_ready": report.get("credentials_ready"),
        "http_status": report.get("http_status"),
        "meta_error_code": report.get("meta_error_code"),
        "meta_error_subcode": report.get("meta_error_subcode"),
        "meta_error_type": report.get("meta_error_type"),
        "meta_error_message": report.get("meta_error_message"),
        "message_id_present": report.get("message_id_present"),
        "persisted": report.get("persisted"),
        "secrets_exposed": False,
    }
}, flush=True)
