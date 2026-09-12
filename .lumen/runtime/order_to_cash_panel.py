from __future__ import annotations

import html
from typing import Any, Dict


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


STAGE_LABELS = {
    "INCIDENT_HOLD": "PAUSA POR INCIDENTE",
    "COLLECTION_DUE": "COBRO VENCIDO",
    "ACCEPTANCE_CONFIRMATION": "CONFIRMAR RECEPCIÓN",
    "PAYMENT_EVIDENCE_GAP": "FALTA VENCIMIENTO",
    "DELIVERY_EVIDENCE_GAP": "FALTA EVIDENCIA DE ENTREGA",
    "CUSTOMER_SUCCESS": "SEGUIMIENTO POSTVENTA",
    "CUSTOMER_SUCCESS_PENDING": "POSTVENTA EN ESPERA",
    "PAYMENT_MONITORING": "MONITOREO DE PAGO",
    "ACCEPTED_PENDING_INVOICE": "ACEPTADO / FACTURACIÓN PENDIENTE",
}


def render_order_to_cash(state: Dict[str, Any]) -> str:
    report = state.get("order_to_cash", {}) or {}
    if not report:
        return """
        <section class="otc-wrap"><div class="otc-eye">POSTVENTA · COBRANZA · ÉXITO DEL CLIENTE</div>
        <h2>De la operación al cobro</h2><p>Esperando el primer ciclo sobre transacciones reales.</p></section>"""
    cases = report.get("cases", []) or []
    primary = report.get("primary_case", {}) or {}
    stage_counts = report.get("stage_counts", {}) or {}
    rows = "".join(
        f'<div class="otc-row"><div><b>{_esc(x.get("transaction_id"))}</b><small>{_esc(x.get("buyer"))}</small></div>'
        f'<span class="otc-tag">{_esc(STAGE_LABELS.get(str(x.get("stage")), x.get("stage")))}</span>'
        f'<span>USD {_f(x.get("company_profit_usd")):,.0f}</span></div>'
        for x in cases[:8]
    ) or '<div class="otc-empty">No hay transacciones reales en postventa.</div>'
    stages = "".join(
        f'<span class="otc-pill">{_esc(STAGE_LABELS.get(str(k), k))}: <b>{_esc(v)}</b></span>'
        for k, v in sorted(stage_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
    )
    primary_stage = STAGE_LABELS.get(str(primary.get("stage")), primary.get("stage") or "SIN CASOS")
    return f"""
    <section class="otc-wrap">
      <div class="otc-head">
        <div><div class="otc-eye">POSTVENTA · COBRANZA · ÉXITO DEL CLIENTE</div><h2>De la operación al cobro</h2>
        <p>Entrega, aceptación, factura, cobro y expansión de cuenta sobre evidencia real.</p></div>
        <div class="otc-score"><small>CASOS ACTIVOS</small><b>{len(cases)}</b></div>
      </div>
      <div class="otc-primary"><small>PRÓXIMA PRIORIDAD</small><h3>{_esc(primary_stage)}</h3><p>{_esc(primary.get("next_action") or "Sin acción postventa pendiente")}</p>
      <div><span>Transacción {_esc(primary.get("transaction_id") or "—")}</span><span>Mensajes preparados: {_esc(report.get("messages_prepared", 0))}</span></div></div>
      <div class="otc-stages">{stages}</div>
      <div class="otc-box"><h3>Cartera postventa</h3>{rows}</div>
      <div class="otc-foot">Solo transacciones reales. Sin amenazas de cobro, penalidades inventadas, admisión de responsabilidad, devoluciones o reembolsos automáticos.</div>
    </section>
    """


def css() -> str:
    return """
    <style>
    .otc-wrap{margin:14px 0;padding:20px;border:1px solid #31533d;border-radius:20px;background:linear-gradient(135deg,#071710,#0b1f17 58%,#091712);color:#eefbf2}
    .otc-head{display:flex;justify-content:space-between;gap:16px}.otc-eye{font-size:11px;letter-spacing:1.4px;color:#8be9af;font-weight:800}.otc-head h2{margin:5px 0 3px;font-size:24px}.otc-head p,.otc-primary p{color:#a8c8b4;margin:0}.otc-score{min-width:115px;text-align:center;padding:12px;border-radius:15px;background:#102c1d;border:1px solid #37634a}.otc-score small{display:block;color:#8caf98;font-size:9px}.otc-score b{font-size:34px}
    .otc-primary{margin-top:14px;padding:15px;border-radius:16px;background:#10281b;border:1px solid #315f44}.otc-primary small{color:#88e4ad;font-weight:800}.otc-primary h3{margin:5px 0}.otc-primary div{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.otc-primary div span,.otc-pill{font-size:11px;padding:5px 8px;border-radius:999px;background:#163825}
    .otc-stages{display:flex;gap:7px;flex-wrap:wrap;margin:12px 0}.otc-box{padding:14px;border-radius:16px;background:#0a1c12;border:1px solid #234a33}.otc-box h3{margin:0 0 8px;font-size:14px}.otc-row{display:flex;gap:10px;align-items:center;padding:9px 0;border-bottom:1px solid #1b3b29}.otc-row:last-child{border-bottom:0}.otc-row div{flex:1}.otc-row small{display:block;color:#80a18c}.otc-row>span:last-child{color:#b8d8c3}.otc-tag{font-size:10px;padding:4px 7px;border-radius:999px;background:#1b4930;color:#a8f0c0}.otc-foot,.otc-empty{margin-top:10px;color:#7fa08a;font-size:11px}
    @media(max-width:800px){.otc-head{flex-direction:column}.otc-score{width:100%}.otc-row{align-items:flex-start;flex-wrap:wrap}}
    </style>
    """


def inject_order_to_cash(page: str, state: Dict[str, Any]) -> str:
    block = css() + render_order_to_cash(state)
    marker = "</main>"
    if marker in page:
        return page.replace(marker, block + marker, 1)
    return page + block
