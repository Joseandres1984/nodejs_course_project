from __future__ import annotations

"""Bridge signed Instagram webhook events from Cloudflare D1 into LUMEN Zero.

The public Cloudflare Worker is intentionally tiny: it verifies Meta's HMAC signature and stores
accepted payloads in D1. This runtime consumes those rows only after the normal LUMEN state has
loaded, feeds them through the existing Instagram Operator, persists the resulting inbox state,
and only then acknowledges the source rows as processed. No reply or publish action is performed.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import app as lumen_app
import d1_persistence_runtime as d1

VERSION = "1.0-zero-d1-instagram-webhook-bridge"
MAX_EVENTS_PER_LOAD = 20
MAX_AUDIT_ROWS = 100

_ORIGINAL_LOAD_STATE = lumen_app.load_state
_ORIGINAL_SAVE_STATE = lumen_app.save_state
_INGESTING = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_schema() -> None:
    d1._request(
        {
            "batch": [
                {
                    "sql": "CREATE TABLE IF NOT EXISTS lumen_instagram_webhook_events (id TEXT PRIMARY KEY, received_at TEXT NOT NULL, event_object TEXT, entry_id TEXT, event_types TEXT, payload TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT)",
                    "params": [],
                },
                {
                    "sql": "CREATE INDEX IF NOT EXISTS idx_lumen_instagram_webhook_pending ON lumen_instagram_webhook_events(processed, received_at)",
                    "params": [],
                },
            ]
        }
    )


def _first_statement_rows(result: Any) -> List[Dict[str, Any]]:
    statements = d1._result_statements(result)
    if not statements:
        return []
    return d1._statement_rows(statements[0])


def _pending_rows() -> List[Dict[str, Any]]:
    _ensure_schema()
    result = d1._request(
        {
            "sql": "SELECT id, received_at, event_object, entry_id, event_types, payload FROM lumen_instagram_webhook_events WHERE processed = 0 ORDER BY received_at ASC LIMIT ?",
            "params": [MAX_EVENTS_PER_LOAD],
        }
    )
    return _first_statement_rows(result)


def _mark_processed(event_ids: List[str]) -> None:
    clean_ids = [str(x).strip() for x in event_ids if str(x).strip()]
    if not clean_ids:
        return
    processed_at = _now_iso()
    d1._request(
        {
            "batch": [
                {
                    "sql": "UPDATE lumen_instagram_webhook_events SET processed = 1, processed_at = ? WHERE id = ? AND processed = 0",
                    "params": [processed_at, event_id],
                }
                for event_id in clean_ids
            ]
        }
    )


def _append_audit(row: Dict[str, Any], created: int) -> None:
    audits = list(lumen_app.STATE.get("instagram_webhook_events", []) or [])
    event_id = str(row.get("id") or "")
    if event_id and any(str(x.get("webhook_event_id") or "") == event_id for x in audits if isinstance(x, dict)):
        return
    audits.insert(
        0,
        {
            "webhook_event_id": event_id,
            "received_at": row.get("received_at"),
            "object": row.get("event_object"),
            "entry_id": row.get("entry_id"),
            "event_types": row.get("event_types"),
            "operator_created": int(created or 0),
            "source": "cloudflare_d1_signed_webhook",
        },
    )
    lumen_app.STATE["instagram_webhook_events"] = audits[:MAX_AUDIT_ROWS]


def ingest_pending_instagram_webhooks() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "version": VERSION,
        "status": "ok",
        "events_read": 0,
        "events_processed": 0,
        "operator_created": 0,
        "persisted": False,
        "source_rows_acked": 0,
        "errors": 0,
        "updated_at": _now_iso(),
    }

    try:
        rows = _pending_rows()
    except Exception as exc:
        report.update(
            {
                "status": "degraded_fail_open",
                "errors": 1,
                "error_type": type(exc).__name__,
            }
        )
        print({"instagram_webhook_d1_bridge": report}, flush=True)
        return report

    report["events_read"] = len(rows)
    if not rows:
        lumen_app.STATE["instagram_webhook_ingest"] = report
        print({"instagram_webhook_d1_bridge": report}, flush=True)
        return report

    successful_ids: List[str] = []
    try:
        # Lazy import avoids changing the production import graph. The existing operator is the
        # single normalization/classification implementation for webhook and polling sources.
        from instagram_operator import process_instagram_webhook

        for row in rows:
            try:
                payload = json.loads(str(row.get("payload") or "{}"))
                if not isinstance(payload, dict):
                    raise ValueError("payload_not_object")
                created_result = process_instagram_webhook(payload, persist=False)
                created = int((created_result or {}).get("created") or 0)
                _append_audit(row, created)
                successful_ids.append(str(row.get("id") or ""))
                report["events_processed"] += 1
                report["operator_created"] += created
            except Exception:
                # Leave failed rows pending for a later run; never drop a signed inbound event.
                report["errors"] += 1

        lumen_app.STATE["instagram_webhook_ingest"] = dict(report)
        if successful_ids:
            persisted = bool(_ORIGINAL_SAVE_STATE())
            report["persisted"] = persisted
            if persisted:
                _mark_processed(successful_ids)
                report["source_rows_acked"] = len(successful_ids)
            else:
                report["status"] = "state_persist_failed"
        if report["errors"]:
            report["status"] = "partial" if successful_ids else "error"
    except Exception as exc:
        report.update(
            {
                "status": "degraded_fail_open",
                "errors": max(1, int(report.get("errors") or 0)),
                "error_type": type(exc).__name__,
            }
        )

    # Persist the final summary on the next normal state save; do not make a second write solely
    # for counters. Message text or raw webhook payloads are never printed to Actions logs.
    lumen_app.STATE["instagram_webhook_ingest"] = dict(report)
    print({"instagram_webhook_d1_bridge": report}, flush=True)
    return report


def load_state_with_instagram_webhooks() -> bool:
    global _INGESTING
    loaded = bool(_ORIGINAL_LOAD_STATE())
    if not loaded or _INGESTING:
        return loaded
    _INGESTING = True
    try:
        ingest_pending_instagram_webhooks()
    finally:
        _INGESTING = False
    return loaded


# Install before production modules capture app.load_state. This changes only the zero-cost entry
# path; the original Railway/production module remains untouched.
lumen_app.load_state = load_state_with_instagram_webhooks

print(
    {
        "instagram_webhook_d1_bridge_install": {
            "version": VERSION,
            "status": "installed",
            "max_events_per_load": MAX_EVENTS_PER_LOAD,
            "auto_reply": False,
            "auto_publish": False,
        }
    },
    flush=True,
)
