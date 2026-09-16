from __future__ import annotations

"""Truthful owner-dashboard display patch.

Keeps stable internal/API fields while making the visible Command Center use the technical watchdog
as its current health source and ARS as the primary Argentina display currency. USD remains a
reference only when native ARS economics do not exist. No FX conversion is invented.

This module is imported first by lumen-web. It also installs a small persistence-performance patch:
reuse one PostgreSQL connection per web process and suppress duplicate state reloads occurring
within the same short dashboard request burst. Business state semantics remain unchanged.
"""

import re
import threading
import time
from typing import Any, Dict, Iterable

import psycopg
from psycopg.types.json import Jsonb

import app as _app


# ---------------------------------------------------------------------------
# Web persistence hot-path optimization
# ---------------------------------------------------------------------------
# The original persistence helpers opened a fresh PostgreSQL connection in
# ensure_db(), then another one in load_state()/save_state(). The Command Center
# invokes those helpers more than once during one page load (middleware + route +
# API refreshes), which turned connection setup into tens of seconds of latency.
#
# lumen-web is one process/replica today, so a process-local reusable connection
# is enough here. Access is serialized with an RLock. On any DB error the
# connection is discarded and the next call reconnects normally.
_DB_LOCK = threading.RLock()
_DB_CONN = None
_DB_SCHEMA_READY = False
_LAST_LOAD_MONO = 0.0
_STATE_CACHE_TTL_SECONDS = 2.0


def _reset_db_connection() -> None:
    global _DB_CONN, _DB_SCHEMA_READY
    conn = _DB_CONN
    _DB_CONN = None
    _DB_SCHEMA_READY = False
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def _db_connection():
    global _DB_CONN
    if _DB_CONN is None or bool(getattr(_DB_CONN, "closed", False)):
        _DB_CONN = psycopg.connect(
            _app.DATABASE_URL,
            autocommit=True,
            connect_timeout=10,
        )
    return _DB_CONN


def _fast_ensure_db() -> bool:
    global _DB_SCHEMA_READY
    if not _app.DATABASE_URL:
        return False
    with _DB_LOCK:
        try:
            conn = _db_connection()
            if not _DB_SCHEMA_READY:
                with conn.cursor() as cur:
                    cur.execute("""CREATE TABLE IF NOT EXISTS lumen_state (
                        state_key TEXT PRIMARY KEY, payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
                _DB_SCHEMA_READY = True
            _app.DB_STATUS.update({"connected": True, "last_error": None})
            return True
        except Exception as exc:
            _reset_db_connection()
            _app.DB_STATUS.update({"connected": False, "last_error": str(exc)[:180]})
            return False


def _fast_load_state(force: bool = False) -> bool:
    global _LAST_LOAD_MONO
    if not _app.DATABASE_URL:
        return False

    with _DB_LOCK:
        monotonic_now = time.monotonic()
        if (
            not force
            and _LAST_LOAD_MONO
            and monotonic_now - _LAST_LOAD_MONO < _STATE_CACHE_TTL_SECONDS
            and _app.DB_STATUS.get("connected")
        ):
            return True

        if not _fast_ensure_db():
            return False
        try:
            conn = _db_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM lumen_state WHERE state_key='global'")
                row = cur.fetchone()
            _LAST_LOAD_MONO = time.monotonic()
            if row and isinstance(row[0], dict):
                current = _app.default_state()
                current.update(row[0])
                _app.ensure_commerce_state(current)
                _app.STATE.clear()
                _app.STATE.update(current)
                _app.DB_STATUS.update({"connected": True, "last_error": None})
                return True
            return False
        except Exception as exc:
            _reset_db_connection()
            _app.DB_STATUS.update({"connected": False, "last_error": str(exc)[:180]})
            return False


def _fast_save_state() -> bool:
    global _LAST_LOAD_MONO
    if not _app.DATABASE_URL:
        return False
    with _DB_LOCK:
        if not _fast_ensure_db():
            return False
        try:
            conn = _db_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO lumen_state(state_key,payload,updated_at) VALUES ('global',%s,NOW())
                    ON CONFLICT (state_key) DO UPDATE SET payload=EXCLUDED.payload,updated_at=NOW()""",
                    (Jsonb(_app.STATE),),
                )
            _LAST_LOAD_MONO = time.monotonic()
            _app.DB_STATUS.update({"connected": True, "last_error": None})
            return True
        except Exception as exc:
            _reset_db_connection()
            _app.DB_STATUS.update({"connected": False, "last_error": str(exc)[:180]})
            return False


# Install before the rest of lumen-web imports main/journal/outbound modules, so
# their `from app import load_state, save_state` bindings receive the optimized
# functions too.
_app.ensure_db = _fast_ensure_db
_app.load_state = _fast_load_state
_app.save_state = _fast_save_state


import control_tower as _ct

_ORIGINAL_BUILD = _ct.build_control_tower
_ORIGINAL_RENDER = _ct.render_control_tower


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _currency(row: Dict[str, Any]) -> str:
    econ = row.get("economics") or {}
    for value in (
        row.get("currency"), row.get("commission_currency"), row.get("fee_currency"),
        econ.get("currency"), row.get("settlement_currency"),
    ):
        text = str(value or "").strip().upper()
        if text in {"ARS", "USD", "EUR"}:
            return text
    return ""


def _first(row: Dict[str, Any], keys: Iterable[str]) -> float | None:
    for key in keys:
        if row.get(key) not in (None, ""):
            try:
                return float(row.get(key))
            except (TypeError, ValueError):
                pass
    return None


def _native_ars_profit(state: Dict[str, Any]) -> Dict[str, Any]:
    expected = 0.0
    risk_adjusted = 0.0
    expected_rows = 0
    risk_rows = 0

    for deal in state.get("deals", []) or []:
        if deal.get("source") == "demo" or _currency(deal) != "ARS":
            continue
        econ = deal.get("economics") or {}
        expected_value = _first(deal, ("expected_company_profit", "expected_profit", "company_profit"))
        if expected_value is None:
            expected_value = _first(econ, ("expected_company_profit", "expected_profit", "company_profit"))
        if expected_value is not None:
            expected += max(0.0, expected_value)
            expected_rows += 1

        risk_value = _first(deal, ("risk_adjusted_expected_profit_ars", "risk_adjusted_expected_profit", "risk_adjusted_profit"))
        if risk_value is None:
            risk_value = _first(econ, ("risk_adjusted_expected_profit_ars", "risk_adjusted_expected_profit", "risk_adjusted_profit"))
        if risk_value is not None:
            risk_adjusted += max(0.0, risk_value)
            risk_rows += 1

    realized = 0.0
    realized_rows = 0
    realized_statuses = {"realized", "realized_partial", "received", "paid", "settled", "completed"}
    for row in state.get("revenue_ledger", []) or []:
        if _currency(row) != "ARS" or str(row.get("status") or "").lower() not in realized_statuses:
            continue
        amount = _first(row, ("amount", "received_amount", "commission_amount"))
        if amount is not None:
            realized += max(0.0, amount)
            realized_rows += 1

    return {
        "expected": round(expected, 2),
        "risk_adjusted": round(risk_adjusted, 2),
        "realized": round(realized, 2),
        "has_expected": expected_rows > 0,
        "has_risk_adjusted": risk_rows > 0,
        "has_realized": realized_rows > 0,
    }


def _ars_text(value: float) -> str:
    whole = f"{value:,.0f}".replace(",", ".")
    return f"$ {whole} ARS"


def _usd_ref(value: Any) -> str:
    return f"USD {_f(value):,.0f} ref."


def truthful_build_control_tower(state: Dict[str, Any], db_status: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = dict(_ORIGINAL_BUILD(state, db_status) or {})
    company = dict(snapshot.get("company", {}) or {})
    money = dict(snapshot.get("money", {}) or {})

    operational_score = _f(company.get("health_score"), 0.0)
    watchdog = state.get("system_watchdog", {}) or {}
    watchdog_total = int(watchdog.get("total") or 0)
    watchdog_failed = int(watchdog.get("failed") or 0)
    technical_score = _f(watchdog.get("score_pct"), operational_score) if watchdog_total > 0 else operational_score

    company["operational_health_score"] = round(operational_score, 1)
    company["technical_health_score"] = round(technical_score, 1)
    company["technical_health_source"] = "system_watchdog" if watchdog_total > 0 else "autonomous_coo"
    company["technical_checks"] = watchdog_total
    company["technical_failures"] = watchdog_failed
    company["health_score"] = round(technical_score, 1)

    coo = state.get("autonomous_coo", {}) or {}
    company["operational_attention"] = dict(coo.get("operational_attention", {}) or {})

    money["native_ars"] = _native_ars_profit(state)
    money["display_currency"] = "ARS"
    money["usd_is_reference_only"] = True

    snapshot["company"] = company
    snapshot["money"] = money
    state["control_tower"] = snapshot
    return snapshot


def truthful_render_control_tower(snapshot: Dict[str, Any]) -> str:
    page = _ORIGINAL_RENDER(snapshot)
    company = snapshot.get("company", {}) or {}
    money = snapshot.get("money", {}) or {}
    ars = money.get("native_ars", {}) or {}

    page = page.replace('<div class="label">Salud operacional</div>', '<div class="label">Salud técnica actual</div>', 1)

    tech = _f(company.get("technical_health_score"), _f(company.get("health_score")))
    operational = _f(company.get("operational_health_score"), tech)
    attention = company.get("operational_attention", {}) or {}
    historical = int(attention.get("historical_delivery_reviews") or 0)
    if abs(tech - operational) >= 0.1 or historical:
        note = f"Operativa: {operational:.0f}/100"
        if historical:
            note += f" · {historical} revisión histórica separada"
        health_pattern = re.compile(
            r'(<div class="card"><div class="label">Salud técnica actual</div>.*?<div class="statusline">.*?</div>)(</div>)',
            re.DOTALL,
        )
        page = health_pattern.sub(r'\1<div class="small">' + note + r'</div>\2', page, count=1)

    usd_risk = money.get("risk_adjusted_expected_profit_usd")
    usd_expected = money.get("expected_profit_usd")
    usd_realized = money.get("realized_profit_usd")

    if ars.get("has_risk_adjusted"):
        risk_main = _ars_text(_f(ars.get("risk_adjusted")))
    elif _f(usd_risk) == 0:
        risk_main = _ars_text(0)
    else:
        risk_main = "ARS —"

    if ars.get("has_expected"):
        expected_line = f"Esperado bruto: {_ars_text(_f(ars.get('expected')))} · {_usd_ref(usd_expected)}"
    else:
        expected_line = f"Esperado bruto ARS: {'$ 0 ARS' if _f(usd_expected) == 0 else 'sin conversión FX'} · {_usd_ref(usd_expected)}"

    expected_card = (
        '<div class="card"><div class="label">Beneficio esperado · riesgo ajustado</div>'
        f'<div class="metric lime">{risk_main}</div>'
        f'<div class="small">{expected_line}</div></div>'
    )
    page = re.sub(
        r'<div class="card"><div class="label">Beneficio esperado · riesgo ajustado</div>.*?</div>\s*</div>',
        expected_card,
        page,
        count=1,
        flags=re.DOTALL,
    )

    if ars.get("has_realized"):
        realized_main = _ars_text(_f(ars.get("realized")))
        realized_line = f"Realizado nativo ARS · {_usd_ref(usd_realized)}"
    elif _f(usd_realized) == 0:
        realized_main = _ars_text(0)
        realized_line = "Solo resultados reales; simulaciones excluidas. · USD 0 ref."
    else:
        realized_main = "ARS —"
        realized_line = f"Sin conversión FX verificada · {_usd_ref(usd_realized)}"

    realized_card = (
        '<div class="card"><div class="label">Beneficio realizado</div>'
        f'<div class="metric good">{realized_main}</div>'
        f'<div class="small">{realized_line}</div></div>'
    )
    page = re.sub(
        r'<div class="card"><div class="label">Beneficio realizado</div>.*?</div>\s*</div>',
        realized_card,
        page,
        count=1,
        flags=re.DOTALL,
    )
    return page


_ct.build_control_tower = truthful_build_control_tower
_ct.render_control_tower = truthful_render_control_tower
print({
    "command_center_truth_runtime": {
        "status": "active",
        "health": "watchdog_primary",
        "currency": "ARS_native_USD_reference",
        "persistence_hotpath": "reused_connection_ttl_2s",
    }
}, flush=True)
