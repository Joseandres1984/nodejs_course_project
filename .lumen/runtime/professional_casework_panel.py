from __future__ import annotations

import html
from typing import Any, Dict, List


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _report(state: Dict[str, Any]) -> Dict[str, Any]:
    return state.get("professional_casework", {}) or {}


def render_casework_strip(state: Dict[str, Any]) -> str:
    report = _report(state)
    statuses = report.get("status_counts", {}) or {}
    cases = list(state.get("professional_cases", []) or [])
    active = sum(1 for x in cases if x.get("status") in {"active", "waiting_budget"})
    ready = int(statuses.get("ready_for_handoff") or 0)
    worked = int(report.get("cases_worked") or 0)
    searches = int(report.get("searches_used") or 0)
    return f'''
    <section class="pc-strip">
      <div class="pc-head">
        <div><div class="pc-eyebrow">DEEP WORK PROFESIONAL</div><h2>{active} expedientes activos · {ready} listos para handoff</h2><p>Cada caso conserva dueño, historial, evidencia, etapa y próximo paso. No se abandona porque una búsqueda no alcance.</p></div>
        <a class="pc-btn" href="/casework">Ver expedientes</a>
      </div>
      <div class="pc-kpis">
        <div><small>Trabajados último ciclo</small><b>{worked}</b></div>
        <div><small>Búsquedas profundas</small><b>{searches}</b></div>
        <div><small>En espera de evidencia</small><b>{int(statuses.get('waiting_budget') or 0)}</b></div>
        <div><small>Listos para RevOps</small><b>{ready}</b></div>
      </div>
    </section>'''


def css() -> str:
    return '''
    .pc-strip{margin:0 0 12px;padding:16px;border:1px solid #5a4b2b;border-radius:18px;background:linear-gradient(135deg,#171308,#101822 60%,#171108);box-shadow:0 15px 38px #0006}.pc-head{display:flex;justify-content:space-between;gap:18px;align-items:center}.pc-eyebrow{font-size:10px;font-weight:900;letter-spacing:.16em;color:#ffd978}.pc-head h2{margin:4px 0;font-size:20px}.pc-head p{margin:0;color:#a7a08c;max-width:880px;font-size:12px}.pc-btn{display:inline-block;padding:9px 12px;border-radius:10px;background:#ffd978;color:#171108!important;font-weight:900;text-decoration:none;white-space:nowrap}.pc-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px}.pc-kpis>div{padding:10px;border:1px solid #433b25;border-radius:11px;background:#121007}.pc-kpis small,.pc-kpis b{display:block}.pc-kpis small{color:#9d9271;font-size:10px;text-transform:uppercase;letter-spacing:.08em}.pc-kpis b{margin-top:4px;font-size:16px;color:#fff2c6}@media(max-width:900px){.pc-kpis{grid-template-columns:1fr 1fr}.pc-head{align-items:flex-start;flex-direction:column}.pc-btn{width:100%;text-align:center}}
    '''


def inject_casework_strip(base_html: str, state: Dict[str, Any]) -> str:
    if 'pc-strip' in base_html:
        return base_html
    out = base_html.replace('</head>', '<style>' + css() + '</style></head>', 1)
    section = render_casework_strip(state)
    marker = '<section class="wf-strip"'
    if marker in out:
        return out.replace(marker, section + marker, 1)
    return out.replace('<body>', '<body>' + section, 1)


def _case_rows(cases: List[Dict[str, Any]]) -> str:
    rows = []
    for case in cases:
        facts = case.get("facts", {}) or {}
        thesis = facts.get("commercial_thesis", {}) or {}
        readiness = thesis.get("readiness_score")
        rows.append(
            '<tr>'
            f'<td><b>{_e(case.get("id"))}</b><br><span class="muted">{_e(case.get("owner_agent_id"))}</span></td>'
            f'<td>{_e(case.get("subject_kind"))}</td>'
            f'<td><b>{_e(case.get("title"))}</b><br><span class="muted">{_e(case.get("category"))}</span></td>'
            f'<td>{_e(case.get("stage"))}<br><span class="muted">{_e(case.get("progress_pct") or 0)}%</span></td>'
            f'<td>{_e(case.get("status"))}</td>'
            f'<td>{len(case.get("evidence", []) or [])}</td>'
            f'<td>{_e(readiness if readiness is not None else "—")}</td>'
            f'<td>{_e(case.get("next_action"))}</td>'
            '</tr>'
        )
    return ''.join(rows) or '<tr><td colspan="8" class="muted">Todavía no hay expedientes profesionales.</td></tr>'


def render_casework_page(state: Dict[str, Any]) -> str:
    report = _report(state)
    cases = list(state.get("professional_cases", []) or [])
    cases.sort(key=lambda x: ({"ready_for_handoff": 0, "active": 1, "waiting_budget": 2}.get(str(x.get("status")), 3), str(x.get("last_worked_at") or "")), reverse=False)
    histories = list(state.get("professional_casework_history", []) or [])[::-1][:24]
    hist_rows = ''.join(
        '<tr>'
        f'<td>{_e(x.get("updated_at"))}</td><td>{_e(x.get("cases_total"))}</td><td>{_e(x.get("cases_worked"))}</td>'
        f'<td>{_e(x.get("searches_used"))}</td><td>{_e(x.get("ready_for_handoff"))}</td><td>{_e(x.get("waiting_budget"))}</td>'
        '</tr>' for x in histories
    ) or '<tr><td colspan="6" class="muted">Sin historial todavía.</td></tr>'
    outcomes = report.get("outcomes", {}) or {}
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LUMEN · Deep Work profesional</title><style>
    :root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#061018;color:#edf7fb;font:14px Inter,system-ui,-apple-system;padding:20px}}.wrap{{max-width:1500px;margin:auto}}a{{color:#8fd4ff;text-decoration:none}}.top{{display:flex;justify-content:space-between;gap:16px;align-items:end;margin-bottom:16px}}h1{{margin:4px 0;font-size:30px}}.muted{{color:#829ba9}}.hero{{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}}.metric,.panel{{background:#0b1822;border:1px solid #1c3b4b;border-radius:14px;padding:13px}}.metric small{{display:block;color:#7693a3;text-transform:uppercase;font-size:10px;letter-spacing:.08em}}.metric b{{display:block;font-size:23px;margin-top:5px;color:#ffd978}}.panel{{margin-top:10px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid #17313f;text-align:left;vertical-align:top}}th{{color:#7e9bab;font-size:10px;text-transform:uppercase}}@media(max-width:980px){{.hero{{grid-template-columns:1fr 1fr 1fr}}.top{{align-items:flex-start;flex-direction:column}}}}@media(max-width:620px){{body{{padding:10px}}.hero{{grid-template-columns:1fr 1fr}}table{{font-size:11px}}}}
    </style></head><body><main class="wrap"><div class="top"><div><div class="muted">LUMEN · EXPEDIENTES COMERCIALES PERSISTENTES</div><h1>Deep Work profesional</h1><div class="muted">El agente conserva el caso entre ciclos, junta evidencia y cierra brechas antes de entregarlo a RevOps.</div></div><div><a href="/workforce">← Plantilla</a> · <a href="/command-center">Command Center</a></div></div>
    <section class="hero">
      <div class="metric"><small>Expedientes</small><b>{_e(report.get('cases_total') or 0)}</b></div>
      <div class="metric"><small>Trabajados</small><b>{_e(report.get('cases_worked') or 0)}</b></div>
      <div class="metric"><small>Avances</small><b>{_e(outcomes.get('advanced') or 0)}</b></div>
      <div class="metric"><small>Listos</small><b>{_e(report.get('ready_for_handoff') or 0)}</b></div>
      <div class="metric"><small>Búsquedas deep</small><b>{_e(report.get('searches_used') or 0)}</b></div>
      <div class="metric"><small>Presupuesto deep restante</small><b>{_e(report.get('deep_search_budget_remaining') or 0)}</b></div>
    </section>
    <section class="panel"><h2>Expedientes</h2><div style="overflow:auto"><table><thead><tr><th>Caso / dueño</th><th>Tipo</th><th>Empresa / categoría</th><th>Etapa</th><th>Estado</th><th>Evidencias</th><th>Readiness</th><th>Próximo paso</th></tr></thead><tbody>{_case_rows(cases)}</tbody></table></div></section>
    <section class="panel"><h2>Historial de trabajo profundo</h2><div style="overflow:auto"><table><thead><tr><th>Hora</th><th>Total</th><th>Trabajados</th><th>Búsquedas</th><th>Listos</th><th>Esperando</th></tr></thead><tbody>{hist_rows}</tbody></table></div></section>
    </main></body></html>'''
