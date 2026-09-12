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


def _money(value: Any) -> str:
    if value is None:
        return "no cuantificado"
    try:
        return f"USD {float(value):,.0f}"
    except (TypeError, ValueError):
        return "no cuantificado"


def render_strategy_simulator(state: Dict[str, Any]) -> str:
    twin = state.get("strategy_simulator", {}) or {}
    if not twin:
        return '<section class="twin-wrap"><div class="twin-eyebrow">STRATEGY SIMULATOR · DIGITAL TWIN</div><h2>Esperando el primer ciclo del simulador</h2><p>El worker todavía no persistió escenarios del Digital Twin.</p></section>'

    recommended = twin.get("recommended_scenario") or {}
    active = twin.get("active_experiment") or {}
    scenarios = twin.get("scenarios", []) or []
    completed = twin.get("completed_experiments", []) or []
    overlay = state.get("strategy_experiment_overlay", {}) or {}

    cards = ""
    for row in scenarios[:5]:
        mv = (row.get("marginal_value") or {}).get("marginal_expected_profit_per_successful_stage_unit_usd")
        blocked = bool(row.get("constitutional_block"))
        cards += f'''
        <div class="twin-card {'blocked' if blocked else ''}">
          <div class="twin-card-head"><b>{_esc(row.get('title') or row.get('id'))}</b><span>{_f(row.get('simulation_score')):.1f}/100</span></div>
          <div class="twin-meta">Evidencia {_f(row.get('evidence_strength'))*100:.0f}% · Fit {_f(row.get('bottleneck_fit')):.0f}% · Riesgo {_esc(row.get('risk'))}</div>
          <div class="twin-value">Valor marginal downstream: <b>{_money(mv)}</b></div>
          <div class="twin-small">{_esc('bloqueado constitucionalmente' if blocked else row.get('interpretation') or '')}</div>
        </div>'''

    exp_html = '<div class="twin-empty">No hay experimento automático activo. LUMEN espera evidencia suficiente.</div>'
    if active:
        exp_html = f'''
        <div class="twin-exp">
          <div><span>EXPERIMENTO ACTIVO</span><h3>{_esc(active.get('title') or active.get('scenario_id'))}</h3></div>
          <div class="twin-exp-grid">
            <div><small>ID</small><b>{_esc(active.get('id'))}</b></div>
            <div><small>Hasta ciclo</small><b>{_esc(active.get('hold_until_cycle'))}</b></div>
            <div><small>Evidencia</small><b>{_f(active.get('evidence_strength'))*100:.0f}%</b></div>
            <div><small>Overlay</small><b>{'APLICADO' if overlay.get('applied') else 'NO APLICADO'}</b></div>
          </div>
          <p>{_esc(active.get('rule'))}</p>
        </div>'''

    history = ""
    for row in completed[-4:][::-1]:
        history += f'<span class="twin-outcome {_esc(row.get("outcome"))}">{_esc(row.get("scenario_id"))}: {_esc(row.get("outcome"))}</span>'
    if not history:
        history = '<span class="twin-muted">Todavía no hay experimentos completos.</span>'

    return f'''
    <section class="twin-wrap">
      <div class="twin-top">
        <div><div class="twin-eyebrow">STRATEGY SIMULATOR · DIGITAL TWIN</div><h2>Probar antes de mover la empresa</h2><p>Escenarios con evidencia observada. No confunde sensibilidad con predicción ni asignación con resultado garantizado.</p></div>
        <div class="twin-rec"><small>RECOMENDADO AHORA</small><b>{_esc(recommended.get('title') or 'sin escenario')}</b><span>{_f(recommended.get('simulation_score')):.1f}/100</span></div>
      </div>
      {exp_html}
      <div class="twin-grid">{cards}</div>
      <div class="twin-history"><b>Aprendizaje de experimentos:</b> {history}</div>
      <div class="twin-foot">{_esc(twin.get('confidence_rule'))}<br>{_esc(twin.get('financial_rule'))}</div>
    </section>'''


def css() -> str:
    return '''
    .twin-wrap{margin:12px 0;padding:18px;border:1px solid #3d4770;border-radius:19px;background:linear-gradient(135deg,#101426,#0a1420 55%,#12101f);box-shadow:0 16px 42px #0006}.twin-top{display:flex;justify-content:space-between;gap:16px;align-items:flex-end}.twin-eyebrow{font-size:10px;letter-spacing:.17em;font-weight:900;color:#91a7ff}.twin-wrap h2{margin:5px 0 4px;font-size:21px}.twin-wrap p{color:#9eacc7;margin:0}.twin-rec{min-width:230px;border:1px solid #46568d;border-radius:12px;padding:11px;background:#0b1020}.twin-rec small{display:block;color:#7e91c7;font-size:9px}.twin-rec b{display:block;margin-top:3px}.twin-rec span{display:block;color:#91a7ff;font-weight:900;font-size:19px;margin-top:4px}.twin-exp{margin-top:13px;border:1px solid #466f66;border-radius:13px;padding:12px;background:#0a1818}.twin-exp span{font-size:9px;letter-spacing:.12em;color:#70dec6;font-weight:900}.twin-exp h3{margin:3px 0 9px}.twin-exp-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.twin-exp-grid>div{background:#071011;border-radius:8px;padding:7px}.twin-exp-grid small{display:block;color:#64837d}.twin-exp p{margin-top:8px;font-size:11px}.twin-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}.twin-card{border:1px solid #2c395d;border-radius:11px;padding:10px;background:#0a1020}.twin-card.blocked{opacity:.62;border-color:#5d3737}.twin-card-head{display:flex;justify-content:space-between;gap:8px}.twin-card-head span{color:#91a7ff;font-weight:900}.twin-meta,.twin-small{font-size:10px;color:#7887a7;margin-top:5px}.twin-value{font-size:11px;margin-top:7px}.twin-history{margin-top:11px;font-size:11px;color:#9eacc7}.twin-outcome{display:inline-block;margin:3px;padding:4px 7px;border-radius:99px;border:1px solid #3f4e75}.twin-outcome.supported{color:#78e2b4;border-color:#356a55}.twin-outcome.negative{color:#ff9c9c;border-color:#6d3d3d}.twin-outcome.inconclusive{color:#f0d083;border-color:#705f39}.twin-muted{color:#667590}.twin-foot{margin-top:9px;padding-top:8px;border-top:1px solid #252f4a;color:#657493;font-size:9px;line-height:1.5}.twin-empty{margin-top:12px;padding:12px;border:1px dashed #3d4770;border-radius:10px;color:#91a7ff}@media(max-width:900px){.twin-top{flex-direction:column;align-items:flex-start}.twin-rec{width:100%;box-sizing:border-box}.twin-grid{grid-template-columns:1fr}.twin-exp-grid{grid-template-columns:1fr 1fr}}
    '''


def inject_strategy_simulator(base_html: str, state: Dict[str, Any]) -> str:
    out = base_html.replace('</head>', '<style>' + css() + '</style></head>', 1)
    return out.replace('</body>', render_strategy_simulator(state) + '</body>', 1)
