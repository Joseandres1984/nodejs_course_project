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


def render_safeguards(state: Dict[str, Any]) -> str:
    report = state.get("deal_safeguards_report", {}) or {}
    cases = state.get("deal_safeguard_cases", []) or []
    incidents = [x for x in state.get("commercial_incidents", []) or [] if x.get("status") not in {"resolved", "closed"}]
    if not report:
        return '<section class="sg-wrap"><div class="sg-eye">DEAL SAFEGUARDS · SAFE CLOSE</div><h2>Esperando evaluación de exposición</h2><p>El próximo ciclo materializará controles de cierre seguro y prevención de disputas.</p></section>'

    cards = ""
    for case in cases[:6]:
        structure = case.get("recommended_structure", {}) or {}
        cards += f'''
        <div class="sg-card {'danger' if case.get('mandatory_legal_review') else ''}">
          <div class="sg-head"><b>{_esc(case.get('deal_id'))}</b><span>{_f(case.get('safe_close_score')):.0f}/100</span></div>
          <div class="sg-meta">Exposición {_f(case.get('exposure_score')):.0f}% · {'REVISIÓN LEGAL' if case.get('mandatory_legal_review') else 'autónomo'}</div>
          <strong>{_esc(structure.get('title') or 'Sin estructura')}</strong>
          <small>{_esc(', '.join(case.get('critical_gaps') or []) or 'sin gaps críticos')}</small>
        </div>'''
    incident_html = "".join(
        f'<span class="sg-incident {_esc(x.get("severity"))}">{_esc(x.get("deal_id"))}: {_esc(", ".join(x.get("signals") or []))}</span>'
        for x in incidents[:8]
    ) or '<span class="sg-ok">Sin incidentes comerciales abiertos.</span>'

    return f'''
    <section class="sg-wrap">
      <div class="sg-top"><div><div class="sg-eye">DEAL SAFEGUARDS · SAFE CLOSE</div><h2>Cerrar bien, no cerrar a cualquier costo</h2><p>Busca simetría comprador↔proveedor, evita exposición por devoluciones/cancelaciones y congela concesiones ante reclamos.</p></div>
      <div class="sg-stats"><div><small>REVISADOS</small><b>{_esc(report.get('deals_reviewed', 0))}</b></div><div><small>BLOQUEADOS</small><b>{_esc(report.get('blocked', 0))}</b></div><div><small>LEGAL</small><b>{_esc(report.get('mandatory_legal_review', 0))}</b></div><div><small>INCIDENTES</small><b>{_esc(report.get('open_incidents', 0))}</b></div></div></div>
      <div class="sg-grid">{cards}</div>
      <div class="sg-incidents"><b>Incident Watch:</b> {incident_html}</div>
    </section>'''


def render_deal_safeguard_detail(state: Dict[str, Any], deal_id: str) -> str:
    case = (state.get("deal_safeguard_index", {}) or {}).get(str(deal_id), {}) or {}
    incidents = [x for x in state.get("commercial_incidents", []) or [] if str(x.get("deal_id")) == str(deal_id) and x.get("status") not in {"resolved", "closed"}]
    if not case:
        return '<section class="sg-detail"><h3>Deal Safeguards</h3><p>Sin evaluación persistida todavía.</p></section>'
    structure = case.get("recommended_structure", {}) or {}
    gaps = "".join(f'<span class="sg-chip">{_esc(x)}</span>' for x in case.get("critical_gaps", []) or []) or '<span class="sg-ok">Sin gaps críticos.</span>'
    risky = "".join(f'<span class="sg-chip danger">{_esc(x)}</span>' for x in case.get("high_risk_clause_signals", []) or []) or '<span class="sg-ok">Sin cláusulas de alto riesgo detectadas.</span>'
    inc = "".join(f'<div class="sg-incident-row"><b>{_esc(x.get("severity"))}</b><span>{_esc(", ".join(x.get("signals") or []))}</span></div>' for x in incidents) or '<div class="sg-ok">Sin incidentes abiertos.</div>'
    return f'''
    <section class="sg-detail">
      <div class="sg-detail-head"><div><div class="sg-eye">SAFE CLOSE</div><h3>Deal Safeguards</h3></div><div class="sg-score"><b>{_f(case.get('safe_close_score')):.0f}</b><span>/100</span></div></div>
      <div class="sg-structure"><small>ESTRUCTURA RECOMENDADA</small><b>{_esc(structure.get('title'))}</b><p>{_esc(structure.get('reason'))}</p></div>
      <div><small>Gaps críticos</small><div class="sg-chips">{gaps}</div></div>
      <div><small>Señales contractuales sensibles</small><div class="sg-chips">{risky}</div></div>
      <div><small>Incident Watch</small>{inc}</div>
      <footer>Detección preventiva, no conclusión jurídica. Términos vinculantes, devoluciones, indemnidades, penalidades y admisiones de responsabilidad siguen bajo control humano.</footer>
    </section>'''


def css() -> str:
    return '''
    .sg-wrap,.sg-detail{margin:12px 0;padding:18px;border:1px solid #5a4031;border-radius:18px;background:linear-gradient(135deg,#1b120d,#11161d);box-shadow:0 14px 36px #0006}.sg-top,.sg-detail-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-end}.sg-eye{font-size:10px;letter-spacing:.16em;font-weight:900;color:#f4ad74}.sg-wrap h2,.sg-detail h3{margin:5px 0}.sg-wrap p,.sg-detail p{color:#a99b91}.sg-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.sg-stats div{min-width:74px;padding:8px;border:1px solid #49382e;border-radius:10px;background:#120d0a}.sg-stats small{display:block;color:#8e7566;font-size:8px}.sg-stats b{font-size:18px}.sg-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}.sg-card{padding:10px;border:1px solid #49382e;border-radius:11px;background:#120d0a}.sg-card.danger{border-color:#793f3f}.sg-head{display:flex;justify-content:space-between}.sg-head span{color:#f4ad74;font-weight:900}.sg-meta,.sg-card small{display:block;color:#8f827a;font-size:10px;margin-top:4px}.sg-card strong{display:block;margin-top:7px}.sg-incidents{margin-top:10px;font-size:11px}.sg-incident,.sg-chip{display:inline-block;margin:3px;padding:4px 7px;border:1px solid #674c3d;border-radius:99px}.sg-incident.high,.sg-incident.critical,.sg-chip.danger{color:#ff9b9b;border-color:#704040}.sg-ok{color:#75d6aa}.sg-score b{font-size:34px;color:#f4ad74}.sg-score span{color:#8f827a}.sg-structure{margin:12px 0;padding:12px;border:1px solid #49382e;border-radius:11px;background:#120d0a}.sg-structure small,.sg-detail>div>small{display:block;color:#8f827a;font-size:9px}.sg-structure b{display:block;margin-top:4px}.sg-chips{margin:5px 0 11px}.sg-incident-row{display:flex;gap:8px;padding:6px 0;border-bottom:1px solid #30251f}.sg-incident-row b{color:#ff9b9b}.sg-detail footer{margin-top:12px;color:#756b65;font-size:9px;border-top:1px solid #30251f;padding-top:8px}@media(max-width:900px){.sg-top,.sg-detail-head{flex-direction:column;align-items:flex-start}.sg-stats{grid-template-columns:1fr 1fr}.sg-grid{grid-template-columns:1fr}}
    '''


def inject_safeguards(base_html: str, state: Dict[str, Any]) -> str:
    out = base_html.replace('</head>', '<style>' + css() + '</style></head>', 1)
    return out.replace('</body>', render_safeguards(state) + '</body>', 1)


def inject_deal_safeguards(base_html: str, state: Dict[str, Any], deal_id: str) -> str:
    out = base_html.replace('</head>', '<style>' + css() + '</style></head>', 1)
    return out.replace('</body>', render_deal_safeguard_detail(state, deal_id) + '</body>', 1)
