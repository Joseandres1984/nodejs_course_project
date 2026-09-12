from __future__ import annotations

import html
from typing import Any, Dict


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def render_payment_rails(state: Dict[str, Any]) -> str:
    report = state.get("payment_rails", {}) or {}
    rails = report.get("rails", []) or []
    routes = report.get("routes", []) or []
    if not report:
        return '<section class="pr-wrap"><div class="pr-eye">MEDIOS DE COBRO</div><h2>Ruteo autónomo de cobros</h2><p>Esperando el primer ciclo.</p></section>'

    rail_rows = "".join(
        f'<div class="pr-row"><div><b>{_esc(x.get("label"))}</b><small>{_esc(x.get("scope"))} · {_esc(x.get("currency"))}</small></div>'
        f'<span class="pr-pill {"ok" if x.get("verified") else "warn"}">{"VERIFICADO" if x.get("verified") else "FALTA CONFIGURAR"}</span>'
        f'<small>{"auto" if x.get("auto_prepare") else "manual"}</small></div>'
        for x in rails
    ) or '<div class="pr-empty">Sin rieles disponibles.</div>'

    route_rows = "".join(
        f'<div class="pr-row"><div><b>{_esc(x.get("deal_id"))}</b><small>{_esc(x.get("buyer_country") or "país pendiente")}</small></div>'
        f'<span>{_esc(((x.get("selected_rail") or {}).get("label")) or "sin ruta")}</span>'
        f'<span class="pr-pill {"ok" if x.get("status")=="READY" else "warn"}">{_esc(x.get("status"))}</span></div>'
        for x in routes[:10]
    ) or '<div class="pr-empty">Todavía no hay deals con ruta de cobro.</div>'

    return f"""
    <section class="pr-wrap">
      <div class="pr-head">
        <div><div class="pr-eye">MEDIOS DE COBRO · TESORERÍA</div><h2>Ruteo autónomo de cobros</h2>
        <p>Argentina prioriza banco local; exterior prioriza Payoneer USD. Los datos sensibles nunca se muestran ni se persisten en el tablero.</p></div>
        <div class="pr-kpis"><div><b>{_esc(report.get('ready_routes',0))}</b><small>rutas listas</small></div><div><b>{_esc(report.get('setup_required',0))}</b><small>pendientes</small></div></div>
      </div>
      <div class="pr-grid">
        <div class="pr-box"><h3>Rieles configurables</h3>{rail_rows}</div>
        <div class="pr-box"><h3>Ruta elegida por operación</h3>{route_rows}</div>
      </div>
      <div class="pr-foot"><b>Principal internacional:</b> Payoneer USD · <b>Respaldo:</b> Wise USD · <b>Argentina:</b> banco local USD/ARS y Mercado Pago como alternativa.</div>
    </section>
    """


def css() -> str:
    return """
    <style>
    .pr-wrap{margin:14px 0;padding:20px;border:1px solid #264e5b;border-radius:20px;background:linear-gradient(135deg,#081418,#0d2026 60%,#0a171c);color:#e8fbff}.pr-eye{font-size:11px;letter-spacing:1.4px;color:#7fd8e8;font-weight:800}.pr-head{display:flex;justify-content:space-between;gap:16px}.pr-head h2{margin:5px 0 3px}.pr-head p{margin:0;color:#9cc1c8}.pr-kpis{display:flex;gap:8px}.pr-kpis>div{min-width:100px;padding:10px;border-radius:14px;background:#102a31;border:1px solid #28515d;text-align:center}.pr-kpis b{display:block;font-size:26px}.pr-kpis small{color:#94b8c0}.pr-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}.pr-box{padding:14px;border-radius:16px;background:#0c1b20;border:1px solid #21424b}.pr-box h3{margin:0 0 8px}.pr-row{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid #18343c}.pr-row:last-child{border-bottom:0}.pr-row>div{flex:1}.pr-row small{display:block;color:#7f9fa6}.pr-pill{font-size:10px;padding:5px 8px;border-radius:999px;background:#28343a}.pr-pill.ok{background:#173d35}.pr-pill.warn{background:#4a351a}.pr-foot{margin-top:12px;color:#8fadb4;font-size:11px}.pr-empty{color:#78959c;padding:8px 0}@media(max-width:800px){.pr-grid{grid-template-columns:1fr}.pr-head{flex-direction:column}.pr-kpis{width:100%}.pr-kpis>div{flex:1}}
    </style>
    """


def inject_payment_rails(page: str, state: Dict[str, Any]) -> str:
    block = css() + render_payment_rails(state)
    marker = "</main>"
    return page.replace(marker, block + marker, 1) if marker in page else page + block
