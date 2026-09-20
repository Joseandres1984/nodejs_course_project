from __future__ import annotations

"""Zero-cost watchdog compatibility.

The original production watchdog has two hard Postgres checks. In LUMEN Zero, Postgres is
intentionally absent and Cloudflare D1 is the canonical persistence layer. This adapter does not
hide those checks: it replaces them with a real D1 configuration check and an actual write/read
canary, then recomputes the watchdog score.
"""

import os
import uuid
from typing import Any, Dict

import d1_persistence_runtime as d1
import system_watchdog

VERSION = "1.0-zero-d1-watchdog"
_original_run = system_watchdog.run_system_watchdog


def _d1_configured() -> tuple[bool, str]:
    ready = bool(
        str(os.getenv("LUMEN_D1_ACCOUNT_ID") or "").strip()
        and str(os.getenv("LUMEN_D1_DATABASE_ID") or "").strip()
        and str(os.getenv("LUMEN_D1_API_TOKEN") or "").strip()
    )
    return ready, "Cloudflare D1 configurado" if ready else "faltan credenciales D1"


def _d1_roundtrip() -> tuple[bool, str]:
    token = "WD-D1-" + uuid.uuid4().hex[:16]
    try:
        d1._request({"batch": [
            {
                "sql": "CREATE TABLE IF NOT EXISTS lumen_watchdog_d1_canary (canary_key TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)",
                "params": [],
            },
            {
                "sql": "INSERT INTO lumen_watchdog_d1_canary(canary_key,payload,updated_at) VALUES ('runtime',?,datetime('now')) ON CONFLICT(canary_key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                "params": [token],
            },
        ]})
        result = d1._request({"sql": "SELECT payload FROM lumen_watchdog_d1_canary WHERE canary_key='runtime'", "params": []})
        statements = d1._result_statements(result)
        rows = d1._statement_rows(statements[0]) if statements else []
        got = str((rows[0] if rows else {}).get("payload") or "")
        if got != token:
            return False, "D1 respondió pero el valor escrito no volvió intacto"
        return True, "escritura + lectura Cloudflare D1 verificadas"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:260]}"


def _replace(checks: list[Dict[str, Any]], check_id: str, row: Dict[str, Any]) -> None:
    for idx, existing in enumerate(checks):
        if str(existing.get("id") or "") == check_id:
            checks[idx] = row
            return
    checks.insert(0, row)


def zero_run_system_watchdog(state: Dict[str, Any], db_status: Dict[str, Any] | None = None) -> Dict[str, Any]:
    report = dict(_original_run(state, db_status) or {})
    if str(os.getenv("LUMEN_ZERO_COST_MODE") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        return report

    checks = list(report.get("checks", []) or [])
    cfg_ok, cfg_detail = _d1_configured()
    rw_ok, rw_detail = _d1_roundtrip() if cfg_ok else (False, "D1 no configurado")
    _replace(
        checks,
        "db_config",
        system_watchdog._pass("db_config", "D1 configurado", cfg_detail)
        if cfg_ok
        else system_watchdog._fail("db_config", "D1 configurado", cfg_detail),
    )
    _replace(
        checks,
        "db_rw",
        system_watchdog._pass("db_rw", "Persistencia D1 lectura/escritura", rw_detail)
        if rw_ok
        else system_watchdog._fail("db_rw", "Persistencia D1 lectura/escritura", rw_detail),
    )
    passed = sum(1 for row in checks if row.get("status") == "pass")
    warnings = sum(1 for row in checks if row.get("status") == "warn")
    failed = sum(1 for row in checks if row.get("status") == "fail")
    total = len(checks)
    report.update(
        {
            "version": f"{report.get('version') or '1.0'}+{VERSION}",
            "status": "healthy" if failed == 0 else "degraded",
            "passed": passed,
            "warnings": warnings,
            "failed": failed,
            "total": total,
            "score_pct": round((passed + warnings * 0.5) / max(1, total) * 100, 1),
            "checks": checks,
            "persistence_backend": "cloudflare_d1",
            "legacy_postgres_checks_replaced": True,
            "note": "Watchdog Zero verifica D1 con un canary real; el resto de los gates técnicos y comerciales permanece sin cambios.",
        }
    )
    state["system_watchdog"] = report
    history = list(state.get("system_watchdog_history", []) or [])
    snapshot = {k: report[k] for k in ("updated_at", "status", "passed", "warnings", "failed", "total", "score_pct")}
    if history and history[-1].get("updated_at") == report.get("updated_at"):
        history[-1] = snapshot
    else:
        history.append(snapshot)
    state["system_watchdog_history"] = history[-100:]
    return report


system_watchdog.run_system_watchdog = zero_run_system_watchdog

print({"zero_watchdog_runtime": {"status": "installed", "version": VERSION, "backend": "cloudflare_d1"}}, flush=True)
