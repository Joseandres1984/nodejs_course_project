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


def render_treasury(state: Dict[str, Any]) -> str:
    settlement = state.get("commission_settlement", {}) or {}
    treasury = state.get("growth_treasury", {}) or {}
    cases = settlement.get("cases", []) or []
    candidates = treasury.get("investment_candidates", []) or []
    setup = settlement.get("settlement_setup", {}) or {}

    setup_state = "CONFIGURADO" if setup.get("instructions_verified") else "CONFIGURACIÓN PENDIENTE"
    setup_cls = "ok" if setup.get("instructions_verified") else "warn"

    cases_html = "".join(
        f'<div class="tr-row"><div><b>{_esc(x.get("transaction_id"))}</b><small>{_esc(x.get("buyer"))}</small></div><span>{_esc(x.get("status"))}</span><strong>USD {_f(x.get("expected_amount_usd")):,.0f}</strong><small>{_esc(x.get("next_action"))}</small></div>'
        for x in cases[:7]
    ) or '<div class="tr-empty">Todavía no hay comisiones reales para liquidar.</div>'

    candidates_html = "".join(
        f'<div class="tr-tool"><div><b>{_esc(x.get("title"))}</b><small>{_esc(x.get("reason"))}</small></div><strong>{_f(x.get("priority_score")):.0f}/100</strong></div>'
        for x in candidates[:5]
    ) or '<div class="tr-empty">Sin inversiones de herramientas priorizadas.</div>'

    primary = treasury.get("primary_candidate", {}) or {}
    rate_reasons = treasury.get("rate_reasons", []) or []

    return f"""
    <section class="tr-wrap">
      <div class="tr-head">
        <div>
          <div class="tr-eye">INGRESOS · COMISIONES · TESORERÍA DE CRECIMIENTO</div>
          <h2>Del cierre al cobro y del cobro al crecimiento</h2>
          <p>LUMEN separa venta, comisión devengada, comisión efectivamente cobrada y presupuesto de reinversión.</p>
        </div>
        <div class="tr-setup {setup_cls}"><small>DESTINO DE COBRO</small><b>{setup_state}</b><span>{_esc(setup.get('destination_label') or 'sin etiqueta configurada')}</span></div>
      </div>

      <div class="tr-kpis">
        <div><small>COMISIONES ESPERADAS</small><b>USD {_f(settlement.get('expected_commissions_usd')):,.0f}</b></div>
        <div><small>COMISIONES COBRADAS</small><b class="green">USD {_f(settlement.get('received_commissions_usd')):,.0f}</b></div>
        <div><small>PENDIENTES</small><b>USD {_f(settlement.get('outstanding_commissions_usd')):,.0f}</b></div>
        <div><small>REINVERSIÓN PLANIFICADA</small><b>{_f(treasury.get('reinvestment_rate_pct')):.1f}%</b></div>
        <div><small>SOBRE DE CRECIMIENTO</small><b class="lime">USD {_f(treasury.get('available_reinvestment_envelope_usd')):,.0f}</b></div>
      </div>

      <div class="tr-grid">
        <div class="tr-box"><h3>Liquidación de comisiones</h3>{cases_html}</div>
        <div class="tr-box"><h3>Inversiones que podrían hacer crecer LUMEN</h3>{candidates_html}</div>
      </div>

      <div class="tr-primary"><small>PRIORIDAD DE CRECIMIENTO</small><b>{_esc(primary.get('title') or 'Sin inversión prioritaria')}</b><span>{_esc(primary.get('expected_effect') or '')}</span></div>
      <div class="tr-foot">Motivo del porcentaje actual: {_esc(' · '.join(str(x) for x in rate_reasons) or 'sin beneficio realizado suficiente todavía')}. Ninguna suscripción, compra, transferencia o inversión se ejecuta sin aprobación financiera humana.</div>
    </section>
    """


def css() -> str:
    return """
    <style>
    .tr-wrap{margin:14px 0;padding:20px;border:1px solid #315b4d;border-radius:20px;background:linear-gradient(135deg,#081511,#0d2019 55%,#0a1713);color:#eefbf5}.tr-eye{font-size:11px;letter-spacing:1.3px;color:#8fe0b9;font-weight:800}.tr-head{display:flex;justify-content:space-between;gap:16px}.tr-head h2{margin:5px 0 3px}.tr-head p{margin:0;color:#9fbbb0}.tr-setup{min-width:210px;padding:12px;border-radius:14px;border:1px solid #315b4d;background:#10241c}.tr-setup.warn{border-color:#725f2b;background:#211d10}.tr-setup small,.tr-setup span{display:block;color:#99afa6}.tr-setup b{display:block;margin:4px 0}.tr-kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:9px;margin-top:14px}.tr-kpis>div{padding:12px;border-radius:14px;background:#0f211b;border:1px solid #27493e}.tr-kpis small{display:block;color:#8da89e;font-size:9px}.tr-kpis b{display:block;font-size:20px;margin-top:4px}.tr-kpis .green{color:#8be0b3}.tr-kpis .lime{color:#d4f76d}.tr-grid{display:grid;grid-template-columns:1.1fr .9fr;gap:12px;margin-top:12px}.tr-box{padding:14px;border-radius:16px;background:#0c1c16;border:1px solid #27483d}.tr-box h3{margin:0 0 8px}.tr-row{display:grid;grid-template-columns:1.1fr .7fr .7fr 1.5fr;gap:8px;align-items:center;border-bottom:1px solid #1e3a31;padding:8px 0}.tr-row:last-child{border-bottom:0}.tr-row small{color:#88a197}.tr-row div small{display:block}.tr-tool{display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid #1e3a31;padding:9px 0}.tr-tool:last-child{border-bottom:0}.tr-tool small{display:block;color:#8da59b;margin-top:3px}.tr-tool strong{color:#d4f76d;white-space:nowrap}.tr-primary{margin-top:12px;padding:12px;border-radius:14px;background:#12291f;border:1px solid #315b4d}.tr-primary small,.tr-primary span{display:block;color:#99b3a8}.tr-primary b{display:block;margin:4px 0}.tr-foot{margin-top:10px;color:#8da69b;font-size:11px}.tr-empty{color:#81978e;padding:10px 0}@media(max-width:950px){.tr-kpis{grid-template-columns:1fr 1fr}.tr-grid{grid-template-columns:1fr}.tr-head{flex-direction:column}.tr-setup{width:100%;box-sizing:border-box}.tr-row{grid-template-columns:1fr 1fr}}
    </style>
    """


def inject_treasury(page: str, state: Dict[str, Any]) -> str:
    block = css() + render_treasury(state)
    marker = "</main>"
    return page.replace(marker, block + marker, 1) if marker in page else page + block
