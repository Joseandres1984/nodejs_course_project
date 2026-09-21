from __future__ import annotations

"""Runtime display truth patch for LUMEN Command Center.

Python imports sitecustomize automatically at process startup when this runtime directory is on
sys.path (Railway runs with .lumen/runtime as the service root).  The patch keeps the stable API
keys intact while making the owner dashboard show current technical health and native ARS amounts
without inventing FX conversions.
"""

import re
from typing import Any, Dict, Iterable

try:
    import control_tower as _ct
except Exception as exc:  # fail open: never prevent LUMEN from starting because of a UI patch
    print({"command_center_truth_patch": {"status": "import_failed", "error": f"{type(exc).__name__}: {str(exc)[:180]}"}}, flush=True)
else:
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

        # If an ARS deal has expected profit but not a dedicated risk-adjusted field, do not fabricate one.
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
        # Main dashboard health means current system health. Operational debt remains visible separately.
        company["health_score"] = round(technical_score, 1)

        coo = state.get("autonomous_coo", {}) or {}
        attention = dict(coo.get("operational_attention", {}) or {})
        company["operational_attention"] = attention

        ars = _native_ars_profit(state)
        money["native_ars"] = ars
        money["display_currency"] = "ARS"
        money["usd_is_reference_only"] = True

        snapshot["company"] = company
        snapshot["money"] = money
        state["control_tower"] = snapshot
        return snapshot

    def truthful_render_control_tower(snapshot: Dict[str, Any]) -> str:
        html = _ORIGINAL_RENDER(snapshot)
        company = snapshot.get("company", {}) or {}
        money = snapshot.get("money", {}) or {}
        ars = money.get("native_ars", {}) or {}

        html = html.replace('<div class="label">Salud operacional</div>', '<div class="label">Salud técnica actual</div>', 1)

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
            html = health_pattern.sub(r'\1<div class="small">' + note + r'</div>\2', html, count=1)

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
        html = re.sub(
            r'<div class="card"><div class="label">Beneficio esperado · riesgo ajustado</div>.*?</div>\s*</div>',
            expected_card,
            html,
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
        html = re.sub(
            r'<div class="card"><div class="label">Beneficio realizado</div>.*?</div>\s*</div>',
            realized_card,
            html,
            count=1,
            flags=re.DOTALL,
        )
        return html

    _ct.build_control_tower = truthful_build_control_tower
    _ct.render_control_tower = truthful_render_control_tower
    print({"command_center_truth_patch": {"status": "active", "health": "watchdog_primary", "currency": "ARS_native_USD_reference"}}, flush=True)

# Instagram approval hardening is deliberately isolated from the dashboard patch above.  It installs
# an import hook only for the Instagram approval bridge/publisher and remains fail-closed if loading
# ever fails, so it cannot block the rest of LUMEN from starting.
try:
    import instagram_approval_freeze_runtime as _instagram_approval_freeze_runtime  # noqa: F401
except Exception as exc:
    print({"instagram_approval_identity": {"status": "install_failed_fail_closed", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}}, flush=True)
