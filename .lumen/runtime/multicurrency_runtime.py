from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from payment_rails import runtime_rails


VERSION = "1.0-multicurrency-truth"
SUPPORTED_CURRENCIES = ("ARS", "USD", "EUR")
PRIMARY_RAILS = {
    "ARS": ("mercadopago_ars", "prex_ars"),
    "USD": ("payoneer_usd", "arg_bank_usd", "wise_usd"),
    "EUR": ("prex_eur_iban",),
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _currency(row: Dict[str, Any]) -> str:
    econ = row.get("economics") if isinstance(row.get("economics"), dict) else {}
    trade = row.get("trade") if isinstance(row.get("trade"), dict) else {}
    for value in (
        row.get("currency"), row.get("commission_currency"), row.get("fee_currency"),
        row.get("settlement_currency"), econ.get("currency"), trade.get("currency"),
    ):
        code = str(value or "").strip().upper()
        if code in SUPPORTED_CURRENCIES:
            return code
    return ""


def _iter_commercial_rows(state: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for key in ("deals", "offers", "transactions", "revenue_ledger"):
        for row in state.get(key, []) or []:
            if isinstance(row, dict) and row.get("source") != "demo":
                yield row


def multicurrency_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    rails = runtime_rails()
    usage = {code: 0 for code in SUPPORTED_CURRENCIES}
    for row in _iter_commercial_rows(state):
        code = _currency(row)
        if code:
            usage[code] += 1

    matrix: Dict[str, Dict[str, Any]] = {}
    for code in SUPPORTED_CURRENCIES:
        ordered = [rails[name] for name in PRIMARY_RAILS[code] if name in rails]
        enabled = [row for row in ordered if row.get("enabled")]
        verified = [row for row in enabled if row.get("verified")]
        primary = verified[0] if verified else (enabled[0] if enabled else (ordered[0] if ordered else None))
        if verified:
            status = "READY"
        elif enabled:
            status = "SUPPORTED_RAIL_NOT_VERIFIED"
        else:
            status = "SUPPORTED_NO_ENABLED_RAIL"
        matrix[code] = {
            "currency": code,
            "supported": True,
            "commercial_processing_active": True,
            "rail_enabled": bool(enabled),
            "rail_verified": bool(verified),
            "ready_to_collect": bool(verified),
            "status": status,
            "primary_rail_code": (primary or {}).get("code"),
            "primary_rail_label": (primary or {}).get("label"),
            "commercial_rows_seen": usage[code],
        }

    report = {
        "version": VERSION,
        "updated_at": utcnow(),
        "status": "active",
        "supported_currencies": list(SUPPORTED_CURRENCIES),
        "currency_matrix": matrix,
        "ready_currencies": [code for code, row in matrix.items() if row.get("ready_to_collect")],
        "setup_required_currencies": [code for code, row in matrix.items() if not row.get("ready_to_collect")],
        "fx_policy": "native_currency_only_no_automatic_fx_conversion",
        "quote_policy": "preserve_documented_currency",
        "landed_cost_policy": "compare_only_when_currency_and_cost_basis_are_explicit",
        "guardrails": {
            "autonomous_currency_conversion": False,
            "autonomous_payment": False,
            "autonomous_fund_movement": False,
            "binding_terms_human_gated": True,
            "secrets_exposed": False,
        },
    }
    state["multicurrency_runtime"] = report
    return report
