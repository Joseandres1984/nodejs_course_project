from __future__ import annotations

"""Zero-cost watchdog compatibility.

The original production watchdog has two hard Postgres checks and a legacy Python-worker
heartbeat. In LUMEN Zero, Postgres is intentionally absent, Cloudflare D1 is canonical, and the
hourly autonomous cycle is driven by the Cloudflare A2A Worker cron. This adapter replaces the
legacy persistence checks with real D1 checks and the legacy heartbeat with actual Cloudflare-cron
telemetry from lumen_opportunity_runs.
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import d1_persistence_runtime as d1
import system_watchdog

VERSION = "1.1-zero-d1-cloudflare-cron-watchdog"
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


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _cloudflare_cron_heartbeat() -> tuple[str, str]:
    """Return pass/warn/fail using the real hourly Cloudflare cron telemetry.

    The A2A Worker runs at minute 7 of every hour. A small scheduling/network delay is normal, so
    <=80 minutes is healthy, 80-140 minutes is warning, and >140 minutes is a real missed-cycle
    failure. A fresh run whose opportunity scan itself ended as failed remains a warning: the cron
    is alive, but its first commercial discovery stage needs attention.
    """
    try:
        result = d1._request({
            "sql": "SELECT started_at,finished_at,status FROM lumen_opportunity_runs ORDER BY started_at DESC LIMIT 1",
            "params": [],
        })
        statements = d1._result_statements(result)
        rows = d1._statement_rows(statements[0]) if statements else []
        if not rows:
            return "warn", "cron Cloudflare configurado pero todavía no hay ejecución registrada"

        row = rows[0]
        stamp = _parse_iso(row.get("finished_at") or row.get("started_at"))
        if stamp is None:
            return "warn", "último cron existe pero su timestamp no es interpretable"

        age_min = max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds() / 60.0)
        run_status = str(row.get("status") or "unknown").lower()
        detail = f"último cron Cloudflare hace {age_min:.1f} min · estado {run_status}"

        if age_min <= 80:
            if run_status == "failed":
                return "warn", detail + " · scheduler vivo, escaneo inicial falló"
            return "pass", detail
        if age_min <= 140:
            return "warn", detail + " · revisar si el próximo cron se demora"
        return "fail", detail + " · cron horario no está corriendo con la frecuencia esperada"
    except Exception as exc:
        return "warn", f"no se pudo leer telemetría del cron Cloudflare: {type(exc).__name__}: {str(exc)[:220]}"


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

    cron_status, cron_detail = _cloudflare_cron_heartbeat() if cfg_ok else ("fail", "D1 no configurado; no se puede verificar cron")
    if cron_status == "pass":
        cron_row = system_watchdog._pass("heartbeat", "Cron Cloudflare con pulso reciente", cron_detail)
    elif cron_status == "warn":
        cron_row = system_watchdog._warn("heartbeat", "Cron Cloudflare con pulso reciente", cron_detail)
    else:
        cron_row = system_watchdog._fail("heartbeat", "Cron Cloudflare con pulso reciente", cron_detail)
    _replace(checks, "heartbeat", cron_row)

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
            "heartbeat_backend": "cloudflare_cron_d1_telemetry",
            "legacy_postgres_checks_replaced": True,
            "legacy_python_heartbeat_replaced": True,
            "note": "Watchdog Zero verifica D1 con canary real y el cron horario de Cloudflare con telemetría real; el resto de los gates técnicos y comerciales permanece sin cambios.",
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

print({"zero_watchdog_runtime": {"status": "installed", "version": VERSION, "backend": "cloudflare_d1", "heartbeat": "cloudflare_cron_d1_telemetry"}}, flush=True)
