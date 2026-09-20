from __future__ import annotations

"""Cloudflare D1 backend for the legacy Postgres cycle journal.

The journal's entry-building and HTML rendering stay unchanged. Only the storage primitives are
replaced, so LUMEN Zero keeps a queryable cycle-by-cycle audit history without Railway/Postgres.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import cycle_journal
import d1_persistence_runtime as d1

VERSION = "1.0-zero-d1-cycle-journal"


def _rows(result: Any) -> List[Dict[str, Any]]:
    statements = d1._result_statements(result)
    if not statements:
        return []
    return d1._statement_rows(statements[0])


def ensure_cycle_journal_db() -> bool:
    try:
        d1._request({"batch": [
            {
                "sql": "CREATE TABLE IF NOT EXISTS lumen_cycle_journal (cycle INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL, local_time TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL)",
                "params": [],
            },
            {
                "sql": "CREATE INDEX IF NOT EXISTS lumen_cycle_journal_recorded_idx ON lumen_cycle_journal(recorded_at DESC)",
                "params": [],
            },
        ]})
        return True
    except Exception:
        return False


def _previous_payload(cycle: int) -> Dict[str, Any]:
    if not ensure_cycle_journal_db():
        return {}
    try:
        result = d1._request({
            "sql": "SELECT payload FROM lumen_cycle_journal WHERE cycle < ? ORDER BY cycle DESC LIMIT 1",
            "params": [int(cycle)],
        })
        rows = _rows(result)
        if not rows:
            return {}
        raw = rows[0].get("payload")
        if isinstance(raw, dict):
            return raw
        return json.loads(str(raw or "{}"))
    except Exception:
        return {}


def record_cycle(state: Dict[str, Any], *, source: str = "worker") -> Dict[str, Any]:
    cycle = cycle_journal._i(state.get("ticks"))
    if cycle <= 0:
        return {"stored": False, "reason": "cycle_not_started"}
    if not ensure_cycle_journal_db():
        return {"stored": False, "reason": "d1_journal_unavailable", "cycle": cycle}
    previous = _previous_payload(cycle)
    entry = cycle_journal.build_cycle_entry(state, source=source, previous=previous)
    now = datetime.now(timezone.utc).isoformat()
    try:
        d1._request({
            "sql": "INSERT INTO lumen_cycle_journal(cycle,recorded_at,local_time,status,source,payload) VALUES(?,?,?,?,?,?) ON CONFLICT(cycle) DO UPDATE SET recorded_at=excluded.recorded_at,local_time=excluded.local_time,status=excluded.status,source=excluded.source,payload=excluded.payload",
            "params": [cycle, now, entry["local_time"], entry["status"], source, json.dumps(entry, ensure_ascii=False, separators=(",", ":"))],
        })
        return {"stored": True, "cycle": cycle, "entry": entry, "backend": "cloudflare_d1"}
    except Exception as exc:
        return {"stored": False, "reason": f"{type(exc).__name__}: {str(exc)[:180]}", "cycle": cycle, "backend": "cloudflare_d1"}


def cycle_exists(cycle: int) -> bool:
    if cycle <= 0 or not ensure_cycle_journal_db():
        return False
    try:
        result = d1._request({"sql": "SELECT 1 AS ok FROM lumen_cycle_journal WHERE cycle=? LIMIT 1", "params": [int(cycle)]})
        return bool(_rows(result))
    except Exception:
        return False


def bootstrap_current_cycle(state: Dict[str, Any]) -> Dict[str, Any]:
    cycle = cycle_journal._i(state.get("ticks"))
    if cycle <= 0:
        return {"stored": False, "reason": "cycle_not_started"}
    if cycle_exists(cycle):
        return {"stored": False, "reason": "already_recorded", "cycle": cycle, "backend": "cloudflare_d1"}
    return record_cycle(state, source="bootstrap_current_state")


def fetch_cycles(*, page: int = 1, per_page: int = 50) -> Dict[str, Any]:
    page = max(1, cycle_journal._i(page, 1))
    per_page = max(1, min(100, cycle_journal._i(per_page, 50)))
    if not ensure_cycle_journal_db():
        return {"available": False, "backend": "cloudflare_d1", "page": page, "per_page": per_page, "total": 0, "rows": []}
    offset = (page - 1) * per_page
    try:
        stats_result = d1._request({"sql": "SELECT COUNT(*) AS total, MIN(cycle) AS first_cycle, MAX(cycle) AS last_cycle FROM lumen_cycle_journal", "params": []})
        stats_rows = _rows(stats_result)
        stats = stats_rows[0] if stats_rows else {}
        rows_result = d1._request({
            "sql": "SELECT cycle,recorded_at,local_time,status,source,payload FROM lumen_cycle_journal ORDER BY cycle DESC LIMIT ? OFFSET ?",
            "params": [per_page, offset],
        })
        raw_rows = _rows(rows_result)
        rows = []
        for raw in raw_rows:
            try:
                item = json.loads(str(raw.get("payload") or "{}"))
            except Exception:
                item = {}
            item.setdefault("cycle", raw.get("cycle"))
            item.setdefault("local_time", raw.get("local_time"))
            item.setdefault("status", raw.get("status"))
            item.setdefault("source", raw.get("source"))
            item["db_recorded_at"] = str(raw.get("recorded_at") or "")
            rows.append(item)
        total = cycle_journal._i(stats.get("total"))
        return {
            "available": True,
            "backend": "cloudflare_d1",
            "version": VERSION,
            "page": page,
            "per_page": per_page,
            "total": total,
            "first_cycle": stats.get("first_cycle"),
            "last_cycle": stats.get("last_cycle"),
            "pages": max(1, (total + per_page - 1) // per_page),
            "rows": rows,
        }
    except Exception as exc:
        return {"available": False, "backend": "cloudflare_d1", "error": f"{type(exc).__name__}: {str(exc)[:180]}", "page": page, "per_page": per_page, "total": 0, "rows": []}


cycle_journal.ensure_cycle_journal_db = ensure_cycle_journal_db
cycle_journal._previous_payload = _previous_payload
cycle_journal.record_cycle = record_cycle
cycle_journal.cycle_exists = cycle_exists
cycle_journal.bootstrap_current_cycle = bootstrap_current_cycle
cycle_journal.fetch_cycles = fetch_cycles

print({"zero_cycle_journal_runtime": {"status": "installed", "version": VERSION, "backend": "cloudflare_d1"}}, flush=True)
