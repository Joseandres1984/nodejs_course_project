from __future__ import annotations

"""Ingest zero-cost public Worker inquiries from D1 into normal LUMEN state.

The public Worker writes a small append-only D1 queue. This bridge folds pending rows into the
existing service_inquiries collection so the original service-revenue, offer and learning engines
can process them without a separate business path.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

import app as lumen_app
import d1_persistence_runtime as d1

VERSION = "1.0-zero-public-inquiry-bridge"
MAX_BATCH = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows_from_result(result: Any) -> List[Dict[str, Any]]:
    statements = d1._result_statements(result)
    if not statements:
        return []
    return d1._statement_rows(statements[0])


def ingest_pending() -> Dict[str, Any]:
    report = {"version": VERSION, "status": "ok", "pending_seen": 0, "ingested": 0, "deduped": 0, "last_error": None, "updated_at": _now()}
    try:
        # Schema creation is idempotent and also makes the bridge safe before the first public form submission.
        d1._request({"batch": [
            {"sql": "CREATE TABLE IF NOT EXISTS lumen_public_inquiries (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, service_id TEXT NOT NULL, email TEXT NOT NULL, company TEXT, name TEXT, need TEXT NOT NULL, source TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT)", "params": []},
            {"sql": "CREATE INDEX IF NOT EXISTS idx_lumen_public_inquiries_pending ON lumen_public_inquiries(processed, created_at)", "params": []},
        ]})
        result = d1._request({"sql": "SELECT id,created_at,service_id,email,company,name,need,source FROM lumen_public_inquiries WHERE processed=0 ORDER BY created_at ASC LIMIT ?", "params": [MAX_BATCH]})
        rows = _rows_from_result(result)
        report["pending_seen"] = len(rows)
        if not rows:
            lumen_app.STATE["zero_public_inquiry_bridge"] = report
            return report
        if not lumen_app.load_state():
            raise RuntimeError("state_unavailable")
        target = list(lumen_app.STATE.get("service_inquiries", []) or [])
        known = {str(x.get("id") or "") for x in target if isinstance(x, dict)}
        processed_ids: list[str] = []
        for row in rows:
            rid = str(row.get("id") or "").strip()
            if not rid:
                continue
            processed_ids.append(rid)
            if rid in known:
                report["deduped"] += 1
                continue
            target.append({
                "id": rid,
                "service_id": str(row.get("service_id") or ""),
                "company": str(row.get("company") or ""),
                "name": str(row.get("name") or ""),
                "email": str(row.get("email") or "").lower(),
                "need": str(row.get("need") or ""),
                "source": str(row.get("source") or "lumen_zero_public_worker"),
                "status": "new_unverified",
                "evidence_status": "user_submitted_unverified",
                "binding_commitment": False,
                "payment_created": False,
                "created_at": str(row.get("created_at") or _now()),
            })
            known.add(rid)
            report["ingested"] += 1
        lumen_app.STATE["service_inquiries"] = target[-500:]
        lumen_app.STATE["zero_public_inquiry_bridge"] = report
        if not lumen_app.save_state():
            raise RuntimeError("state_persistence_failed")
        if processed_ids:
            batch = []
            for rid in processed_ids:
                batch.append({"sql": "UPDATE lumen_public_inquiries SET processed=1, processed_at=? WHERE id=?", "params": [_now(), rid]})
            d1._request({"batch": batch})
    except Exception as exc:
        report["status"] = "degraded_fail_open"
        report["last_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        lumen_app.STATE["zero_public_inquiry_bridge"] = report
    print({"zero_public_inquiry_bridge": report}, flush=True)
    return report
