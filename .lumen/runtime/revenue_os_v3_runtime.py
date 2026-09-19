from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List


VERSION = "3.0-first-cash-execution-ordering"

# These weights do not change outbound volume. They only order already-eligible,
# verified prospects so the scarce existing outbound slots favor low-friction
# revenue products first.
SERVICE_PRIORITY = {
    "SRV-QUOTECHECK": 18.0,
    "SRV-SUPPLIERCHECK": 16.0,
    "SRV-TENDER-HUNTER": 14.0,
    "SRV-SOURCING-EXPRESS": 12.0,
    "SRV-B2B-PROSPECTING": 10.0,
    "SRV-EXPORT-SCOUT": 8.0,
}

SERVICE_CTA = {
    "SRV-QUOTECHECK": "Para evaluarlo sin reunión, respondan con producto, cantidad, moneda y la cotización o importe recibido.",
    "SRV-SUPPLIERCHECK": "Para evaluarlo sin reunión, respondan con nombre o web del proveedor y país donde opera.",
    "SRV-TENDER-HUNTER": "Para armar el radar inicial, respondan con producto/rubro y geografía que quieren vigilar.",
    "SRV-SOURCING-EXPRESS": "Para iniciar la búsqueda, respondan con qué necesitan, cantidad aproximada y lugar de entrega.",
    "SRV-B2B-PROSPECTING": "Para evaluar encaje, respondan con producto/servicio, tipo de cliente buscado y geografía objetivo.",
    "SRV-EXPORT-SCOUT": "Para evaluar mercados, respondan con producto, país de origen y países que quieren explorar.",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def revenue_priority_score(prospect: Dict[str, Any]) -> float:
    """Score an already-eligible outbound prospect without widening eligibility."""
    base = _f(prospect.get("score"))
    ctx = prospect.get("service_revenue_context") or {}
    service_id = str(ctx.get("service_id") or "")
    if not prospect.get("service_revenue_ready") or not service_id:
        return base
    fit = _f(ctx.get("qualification_score"))
    return round(base + (fit * 0.20) + SERVICE_PRIORITY.get(service_id, 0.0), 2)


def order_revenue_prospects(prospects: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Put verified service-revenue prospects first, preserving all upstream gates."""
    rows = list(prospects or [])
    for row in rows:
        row["revenue_os_v3_priority"] = revenue_priority_score(row)
    rows.sort(
        key=lambda row: (
            0 if row.get("service_revenue_ready") else 1,
            -_f(row.get("revenue_os_v3_priority")),
            -_f(row.get("score")),
            str((row.get("account") or {}).get("id") or ""),
        )
    )
    return rows


def conversion_cta(service_id: str) -> str:
    return SERVICE_CTA.get(str(service_id or ""), "")


def pipeline_snapshot(state: Dict[str, Any]) -> Dict[str, int]:
    rows = [x for x in state.get("service_sales_pipeline", []) or [] if isinstance(x, dict)]
    return {
        "pipeline_total": len(rows),
        "outreach_prepared": sum(1 for x in rows if str(x.get("stage") or "") == "outreach_prepared"),
        "contacted": sum(1 for x in rows if x.get("contact_truth") == "provider_accepted"),
        "replied": sum(1 for x in rows if x.get("contact_truth") == "replied"),
        "inbound": sum(1 for x in rows if x.get("contact_truth") == "inbound_received"),
        "won": sum(1 for x in rows if str(x.get("stage") or "") == "won"),
    }


def install_and_prewarm() -> Dict[str, Any]:
    """Install the revenue bridge before the normal worker and pre-materialize CRM state.

    This function never sends mail, increases caps, spends money, accepts terms, or creates
    a binding commitment. It only fixes execution ordering and enriches messages that will
    still pass through the existing eligibility, communication, quality and COO gates.
    """
    report: Dict[str, Any] = {
        "version": VERSION,
        "status": "starting",
        "paid_spend": False,
        "outbound_caps_changed": False,
        "binding_authority_changed": False,
        "production_self_modify": False,
        "updated_at": _utcnow(),
    }
    try:
        # Import order is deliberate. Intelligence expands the service catalog; the quality
        # gate tightens candidate eligibility; then the existing outbound bridge captures
        # that fully-wrapped service tick; pricing finally wraps the service message.
        import service_revenue_runtime
        import intelligence_revenue_runtime  # noqa: F401
        import intelligence_quality_gate_runtime  # noqa: F401
        import service_revenue_outbound_runtime  # noqa: F401
        import offer_outbound_runtime  # noqa: F401
        import outbound_engine
        from app import STATE, load_state, save_state

        original_eligible = outbound_engine._eligible
        if not getattr(outbound_engine, "_lumen_revenue_os_v3_priority_installed", False):
            def revenue_os_eligible(state: Dict[str, Any]):
                return order_revenue_prospects(original_eligible(state))

            outbound_engine._eligible = revenue_os_eligible
            outbound_engine._lumen_revenue_os_v3_priority_installed = True

        original_message = outbound_engine._message_text
        if not getattr(outbound_engine, "_lumen_revenue_os_v3_cta_installed", False):
            def revenue_os_message(account: Dict[str, Any], variant: Dict[str, Any], tracking_url: str):
                kind, subject, body = original_message(account, variant, tracking_url)
                ctx = account.get("_lumen_service_revenue_context")
                if not isinstance(ctx, dict):
                    return kind, subject, body
                cta = conversion_cta(str(ctx.get("service_id") or ""))
                if not cta or cta in body:
                    return kind, subject, body
                return kind, subject, (body + "\n\n" + cta)[:5000]

            outbound_engine._message_text = revenue_os_message
            outbound_engine._lumen_revenue_os_v3_cta_installed = True

        loaded = bool(load_state())
        report["state_loaded"] = loaded
        if not loaded:
            report.update({"status": "degraded_fail_open", "reason": "state_unavailable"})
            print({"revenue_os_v3": report}, flush=True)
            return report

        before = pipeline_snapshot(STATE)
        summary = dict(service_revenue_runtime.service_revenue_tick(STATE) or {})
        after = pipeline_snapshot(STATE)

        state_row = {
            "version": VERSION,
            "status": "active",
            "mode": "first_cash_execution_before_worker_outbound",
            "before": before,
            "after": after,
            "service_pipeline_total": int(summary.get("pipeline_total") or after["pipeline_total"]),
            "service_outreach_prepared": int(summary.get("outreach_prepared") or after["outreach_prepared"]),
            "service_real_contacted": int(summary.get("real_contacted") or after["contacted"]),
            "same_outbound_daily_cap": int(getattr(outbound_engine, "MAX_NEW_PER_DAY", 0) or 0),
            "same_outbound_cycle_cap": int(getattr(outbound_engine, "MAX_NEW_PER_CYCLE", 0) or 0),
            "priority_services": list(SERVICE_PRIORITY),
            "conversion_cta_enabled": True,
            "paid_spend": False,
            "outbound_caps_changed": False,
            "binding_authority_changed": False,
            "truth_rule": "prepared_is_not_contacted; provider_accepted_is_not_reply; revenue_requires_paid_or_settled_evidence",
            "updated_at": _utcnow(),
        }
        STATE["revenue_os_v3"] = state_row
        persisted = bool(save_state())
        state_row["persisted"] = persisted
        report.update(state_row)
        report["status"] = "active" if persisted else "degraded_fail_open"
        print({"revenue_os_v3": report}, flush=True)
        return report
    except Exception as exc:
        report.update({
            "status": "degraded_fail_open",
            "reason": f"{type(exc).__name__}: {str(exc)[:300]}",
        })
        print({"revenue_os_v3": report}, flush=True)
        return report


# Production is opt-out so Railway can enable the fix by importing this module before
# worker_entry. Unit tests set LUMEN_REVENUE_OS_V3_AUTORUN=false to exercise pure helpers.
if os.getenv("LUMEN_REVENUE_OS_V3_AUTORUN", "true").strip().lower() not in {"0", "false", "no", "off"}:
    install_and_prewarm()
