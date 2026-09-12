from __future__ import annotations

import html
from typing import Any, Dict


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def render_closing_orchestrator(state: Dict[str, Any]) -> str:
    report = state.get("closing_orchestrator", {}) or {}
    packs = report.get("packs", []) or []
    if not report:
        return '<section class="co-wrap"><div class="co-eye">CIERRE REAL</div><h2>Orquestador de cierre</h2><p>Esperando el primer ciclo.</p></section>'

    cards = "".join(
        f'''<div class="co-card">
          <div class="co-top"><b>{_e(x.get("deal_id"))}</b><span class="co-pill {"ok" if x.get("status")=="READY_FOR_HUMAN_APPROVAL" else "warn"}">{_e(x.get("status"))}</span></div>
          <small>{_e(x.get("buyer") or "comprador")} · {_e(x.get("supplier") or "proveedor")}</small>
          <div class="co-line"><b>Modelo recomendado</b><span>{_e((x.get("revenue_model") or {}).get("recommended"))}</span></div>
          <div class="co-line"><b>Modelo confirmado</b><span>{"sí" if (x.get("revenue_model") or {}).get("confirmed") else "no"}</span></div>
          <div class="co-line"><b>Comisión/ingreso protegido</b><span>{"sí" if (x.get("fee_terms") or {}).get("secured") else "no"}</span></div>
          <div class="co-line"><b>Medio de cobro</b><span>{_e((((x.get("payment_route") or {}).get("selected_rail") or {}).get("label")) or "pendiente")}</span></div>
          <div class="co-line"><b>Safe Close</b><span>{_e(x.get("safe_close_score"))}</span></div>
          <div class="co-missing"><b>Faltantes:</b> {_e(", ".join(x.get("missing") or []) or "ninguno")}</div>
        </div>'''
        for x in packs[:10]
    ) or '<div class="co-empty">Todavía no hay paquetes de cierre.</div>'

    return f'''
    <section class="co-wrap">
      <div class="co-head">
        <div><div class="co-eye">CIERRE REAL · COMISIÓN PROTEGIDA</div><h2>Orquestador de cierre</h2>
        <p>LUMEN arma el paquete completo y solo te pide aprobación cuando modelo de ingresos, comisión, cobro, riesgo y controles están listos.</p></div>
        <div class="co-kpis"><div><b>{_e(report.get("ready_for_human_approval",0))}</b><small>listos para aprobar</small></div><div><b>{_e(report.get("blocked_risk",0))}</b><small>bloqueados por riesgo</small></div><div><b>{_e(report.get("clarifications_prepared",0))}</b><small>aclaraciones</small></div></div>
      </div>
      <div class="co-grid">{cards}</div>
      <div class="co-foot">Regla: LUMEN puede construir y negociar lo no vinculante; la aceptación contractual final sigue requiriendo aprobación humana.</div>
    </section>
    '''


def css() -> str:
    return '''<style>
    .co-wrap{margin:14px 0;padding:20px;border:1px solid #3d4d62;border-radius:20px;background:linear-gradient(135deg,#0c1119,#121a26 60%,#0b1119);color:#edf5ff}.co-eye{font-size:11px;letter-spacing:1.4px;color:#8dbbff;font-weight:800}.co-head{display:flex;justify-content:space-between;gap:16px}.co-head h2{margin:5px 0 3px}.co-head p{margin:0;color:#a8b7ca}.co-kpis{display:flex;gap:8px}.co-kpis>div{min-width:96px;padding:10px;border-radius:14px;background:#172131;border:1px solid #32455f;text-align:center}.co-kpis b{display:block;font-size:24px}.co-kpis small{color:#9badc5}.co-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:14px}.co-card{padding:14px;border-radius:16px;background:#101824;border:1px solid #2a3a50}.co-top{display:flex;justify-content:space-between;gap:8px}.co-card small{color:#90a2b9}.co-line{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-bottom:1px solid #1f2c3d;font-size:12px}.co-line span{text-align:right;color:#bdd1e8}.co-pill{font-size:10px;padding:5px 8px;border-radius:999px;background:#49351a}.co-pill.ok{background:#173d35}.co-missing{margin-top:8px;color:#d5a96b;font-size:11px}.co-foot{margin-top:12px;color:#92a4bb;font-size:11px}.co-empty{color:#8799af}@media(max-width:800px){.co-grid{grid-template-columns:1fr}.co-head{flex-direction:column}.co-kpis{width:100%}.co-kpis>div{flex:1}}
    </style>'''


def inject_closing_orchestrator(page: str, state: Dict[str, Any]) -> str:
    block = css() + render_closing_orchestrator(state)
    marker = "</main>"
    return page.replace(marker, block + marker, 1) if marker in page else page + block
