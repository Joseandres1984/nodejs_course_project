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


def render_closer(state: Dict[str, Any]) -> str:
    closer = state.get("closer_orchestrator", {}) or {}
    if not closer:
        return '<section class="cl-wrap"><div class="cl-eye">AUTONOMOUS CLOSER</div><h2>Closer comercial</h2><p>Esperando el primer ciclo del Closer.</p></section>'

    primary = closer.get("primary_lane") or {}
    objection = primary.get("objection") or {}
    gate = closer.get("outbound_gate") or {}
    active = closer.get("active_lanes") or []
    lanes = "".join(
        f'<div class="cl-row"><b>{_esc(x.get("opportunity_id") or x.get("lane_id"))}</b>'
        f'<span>{_esc(x.get("category") or "—")}</span>'
        f'<span class="cl-stage">{_esc(x.get("stage") or "—")}</span>'
        f'<strong>{_f(x.get("score")):.0f}</strong></div>'
        for x in active[:4]
    ) or '<div class="cl-empty">Todavía no hay una oportunidad elegible para el Closer.</div>'

    human = bool(closer.get("human_action_required"))
    status_class = "human" if human else "auto"
    status_text = "TU OK FINAL" if human else "AUTÓNOMO"

    return f"""
    <section class="cl-wrap">
      <div class="cl-head">
        <div><div class="cl-eye">AUTONOMOUS CLOSER · SALES COMMAND</div><h2>Closer comercial</h2>
        <p>Una sola conducción desde demanda verificada hasta paquete de cierre, con especialistas de evidencia, cotización, negociación, riesgo y cobro debajo.</p></div>
        <div class="cl-mode {status_class}"><small>{status_text}</small><b>{_esc(closer.get('status') or '—')}</b></div>
      </div>
      <div class="cl-kpis">
        <div><small>GO-LIVE</small><b>{_esc(closer.get('go_live_stage') or '—')}</b></div>
        <div><small>CARRILES ACTIVOS</small><b>{len(active)} / {_esc(closer.get('lane_cap') or 0)}</b></div>
        <div><small>ELEGIBLES</small><b>{_esc(closer.get('eligible_lanes') or 0)}</b></div>
        <div><small>FOCO COBRO</small><b>{_esc(closer.get('collection_focus') or 'standard')}</b></div>
      </div>
      <div class="cl-grid">
        <div class="cl-box">
          <h3>Venta principal</h3>
          <div class="cl-primary"><span>Oportunidad</span><b>{_esc(primary.get('opportunity_id') or '—')}</b></div>
          <div class="cl-primary"><span>Deal</span><b>{_esc(primary.get('deal_id') or 'todavía no materializado')}</b></div>
          <div class="cl-primary"><span>Etapa</span><b>{_esc(primary.get('stage') or '—')}</b></div>
          <div class="cl-primary"><span>Score</span><b>{_f(primary.get('score')):.0f}/100</b></div>
          <div class="cl-primary"><span>Objeción</span><b>{_esc(objection.get('kind') or 'ninguna')}</b></div>
          <div class="cl-next"><small>SIGUIENTE JUGADA</small><strong>{_esc(closer.get('primary_next_action') or 'Buscar demanda verificable')}</strong></div>
        </div>
        <div class="cl-box"><h3>Carriles de venta activos</h3>{lanes}
          <div class="cl-gate"><span>permitidos <b>{_esc(gate.get('allowed',0))}</b></span><span>en espera <b>{_esc(gate.get('held',0))}</b></span><span>liberados <b>{_esc(gate.get('released',0))}</b></span></div>
        </div>
      </div>
      <div class="cl-foot">CANARY mantiene una conversación comercial principal estable; seguimiento máximo 2 veces y sin apilar mensajes. Objeciones de precio atacan primero costo/condiciones proveedor. Contratos, órdenes, pagos y compromisos vinculantes siguen requiriendo autorización humana.</div>
    </section>
    """


def css() -> str:
    return """
    <style>
    .cl-wrap{margin:14px 0;padding:20px;border:1px solid #36506b;border-radius:20px;background:linear-gradient(135deg,#07111d,#0b1d2d 55%,#07131e);color:#edf7ff}.cl-head{display:flex;justify-content:space-between;gap:16px}.cl-eye{font-size:11px;letter-spacing:1.5px;color:#73c8ff;font-weight:900}.cl-head h2{margin:5px 0 3px}.cl-head p{margin:0;color:#9bb5c8;max-width:760px}.cl-mode{min-width:180px;padding:12px;border-radius:14px;text-align:center;border:1px solid #31546e;background:#0e2535}.cl-mode small{display:block;font-size:9px;letter-spacing:1.2px}.cl-mode b{display:block;margin-top:4px}.cl-mode.auto small{color:#7ce7b3}.cl-mode.human{border-color:#76622e;background:#2a220d}.cl-mode.human small{color:#ffd36a}.cl-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-top:13px}.cl-kpis>div{padding:11px;border-radius:12px;background:#0b1c29;border:1px solid #254258}.cl-kpis small{display:block;color:#7697ad;font-size:9px}.cl-kpis b{display:block;margin-top:4px}.cl-grid{display:grid;grid-template-columns:1fr 1.2fr;gap:10px;margin-top:12px}.cl-box{padding:14px;border-radius:14px;background:#091923;border:1px solid #223d51}.cl-box h3{margin:0 0 10px}.cl-primary{display:flex;justify-content:space-between;gap:10px;padding:7px 0;border-bottom:1px solid #183346}.cl-primary span{color:#7997ab}.cl-next{margin-top:12px;padding:11px;border-left:3px solid #73c8ff;background:#0d2535}.cl-next small{display:block;color:#7da7c1}.cl-next strong{display:block;margin-top:4px}.cl-row{display:grid;grid-template-columns:1.1fr 1.4fr 1.1fr 48px;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid #183346}.cl-row:last-child{border-bottom:0}.cl-row span{color:#8aa9bc}.cl-stage{font-size:10px}.cl-row strong{text-align:right;color:#7ce7b3}.cl-gate{display:flex;gap:8px;flex-wrap:wrap;margin-top:11px}.cl-gate span{padding:5px 8px;border-radius:999px;background:#10293a;color:#8fb4ca;font-size:10px}.cl-foot{margin-top:12px;color:#7899ad;font-size:10px}.cl-empty{color:#7899ad}@media(max-width:800px){.cl-head{flex-direction:column}.cl-mode{width:100%;box-sizing:border-box}.cl-kpis,.cl-grid{grid-template-columns:1fr}.cl-row{grid-template-columns:1fr 1fr}.cl-row strong{text-align:left}}
    </style>
    """
