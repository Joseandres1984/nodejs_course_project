from __future__ import annotations

import html
from typing import Any, Dict

from autonomy_operating_system import build_autonomy_snapshot


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _report(state: Dict[str, Any]) -> Dict[str, Any]:
    return state.get("autonomy_operating_system", {}) or build_autonomy_snapshot(state, mutate=False)


def render_autonomy_strip(state: Dict[str, Any]) -> str:
    r = _report(state)
    primary = r.get("primary_action") or {}
    stages = r.get("stage_counts", {}) or {}
    return f"""
    <section class="auto-strip">
      <div class="auto-head">
        <div><small>AUTONOMÍA OPERATIVA</small><h2>Una sola cola de ejecución</h2><p>{_esc(primary.get('next_action') or 'Esperando evidencia suficiente para priorizar la siguiente acción.')}</p></div>
        <a class="auto-open" href="/autonomia">Ver autonomía</a>
      </div>
      <div class="auto-stats">
        <div><small>CASOS ACTIVOS</small><b>{int(r.get('cases_total') or 0)}</b><span>normalizados</span></div>
        <div><small>COTIZACIÓN+</small><b>{sum(int(stages.get(x) or 0) for x in ('COTIZACION','OFERTA','NEGOCIACION','CIERRE','COBRO'))}</b><span>casos avanzados</span></div>
        <div><small>JOSÉ</small><b>{int(r.get('human_decisions_count') or 0)}</b><span>decisiones reales</span></div>
        <div><small>EVENTOS</small><b>{int(r.get('events_created') or 0)}</b><span>cambios del último ciclo</span></div>
      </div>
    </section>
    """


def render_autonomy_page(state: Dict[str, Any]) -> str:
    r = _report(state)
    actions = r.get("top_actions", []) or []
    rows = "".join(
        f'<div class="auto-row"><div><b>{_esc(x.get("stage"))} · {_esc(x.get("title"))}</b><p>{_esc(x.get("next_action"))}</p><small>{_esc(x.get("category"))} · prioridad {_esc(x.get("priority"))} · dueño {_esc(x.get("owner"))}</small></div><span>{_esc(x.get("deadline") or "sin vencimiento estructurado")}</span></div>'
        for x in actions
    ) or '<div class="auto-empty">Todavía no hay casos con evidencia suficiente.</div>'
    stages = r.get("stage_counts", {}) or {}
    stage_html = "".join(f'<div><small>{_esc(k)}</small><b>{int(stages.get(k) or 0)}</b></div>' for k in ("DEMANDA","COMPRADOR","REQUISITOS","PROVEEDORES","COTIZACION","OFERTA","NEGOCIACION","CIERRE","COBRO"))
    weights = r.get("procurement_category_weights", {}) or {}
    weight_html = "".join(f'<div class="auto-row"><div><b>{_esc(k)}</b><small>peso adaptativo</small></div><span>{_esc(v)}</span></div>' for k,v in sorted(weights.items(), key=lambda i:i[1], reverse=True)) or '<div class="auto-empty">Sin aprendizaje por categoría todavía.</div>'
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LUMEN · Autonomía</title>{css()}</head><body><main class="auto-page"><a class="back" href="/command-center">← Centro de Control</a><header><small>AUTONOMÍA OPERATIVA · LUMEN</small><h1>Empresa en ejecución</h1><p>Un estado, una próxima acción y un responsable por caso. Los compromisos vinculantes siguen requiriendo aprobación humana.</p></header><section class="stage-grid">{stage_html}</section><section><h2>Próximas acciones</h2>{rows}</section><section><h2>Asignación adaptativa de investigación</h2>{weight_html}</section></main></body></html>"""


def inject_autonomy_strip(page: str, state: Dict[str, Any]) -> str:
    if "AUTONOMÍA OPERATIVA" in page:
        return page
    block = css() + render_autonomy_strip(state)
    marker = '<div class="grid hero">'
    if marker in page:
        return page.replace(marker, block + marker, 1)
    marker = '<div class="hero grid">'
    if marker in page:
        return page.replace(marker, block + marker, 1)
    return page + block


def css() -> str:
    return """<style>.auto-strip{margin:0 0 12px;padding:17px;border:1px solid #22536a;border-radius:18px;background:linear-gradient(135deg,#071822,#0b2633 55%,#0a171f)}.auto-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}.auto-head small,header small{font-size:10px;letter-spacing:.16em;color:#80cfff}.auto-head h2{font-size:20px;margin:5px 0 4px}.auto-head p{margin:0;color:#b9cad5;line-height:1.45}.auto-open{white-space:nowrap;background:#80cfff;color:#061018!important;padding:9px 12px;border-radius:999px;font-weight:800}.auto-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:14px}.auto-stats>div,.stage-grid>div{border:1px solid #23495c;background:#0b1b24;border-radius:12px;padding:10px}.auto-stats small,.stage-grid small{display:block;color:#789bad;font-size:9px}.auto-stats b,.stage-grid b{display:block;color:#80cfff;font-size:22px;margin-top:3px}.auto-stats span{display:block;color:#738c98;font-size:9px}.auto-page{max-width:1180px;margin:auto;padding:22px}.back{color:#80cfff;text-decoration:none}header{margin:20px 0;padding:22px;border:1px solid #22536a;border-radius:18px;background:#0a1b25}header h1{font-size:32px;margin:5px 0}header p{color:#adc3cf}.stage-grid{display:grid;grid-template-columns:repeat(9,1fr);gap:7px;margin:12px 0 18px}.auto-page section{background:#0b1822;border:1px solid #1a3a4b;border-radius:16px;padding:16px;margin:12px 0}.auto-row{display:flex;justify-content:space-between;gap:16px;padding:11px 0;border-bottom:1px solid #17303e}.auto-row:last-child{border-bottom:0}.auto-row p{margin:5px 0;color:#b9cbd5;font-size:12px}.auto-row small{color:#7892a2}.auto-row>span{color:#80cfff;font-size:11px;white-space:nowrap}.auto-empty{padding:14px;color:#88a2b3}@media(max-width:850px){.stage-grid{grid-template-columns:repeat(3,1fr)}.auto-stats{grid-template-columns:1fr 1fr}}@media(max-width:520px){.auto-head{flex-direction:column}.auto-open{width:100%;text-align:center;box-sizing:border-box}.auto-row{flex-direction:column}.stage-grid{grid-template-columns:repeat(3,1fr)}}</style>"""
