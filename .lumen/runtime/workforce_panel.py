from __future__ import annotations

import html
from typing import Any, Dict


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _last(state: Dict[str, Any]) -> Dict[str, Any]:
    return (state.get("agent_workforce", {}) or {}).get("last_cycle", {}) or {}


def render_workforce_strip(state: Dict[str, Any]) -> str:
    workforce = state.get("agent_workforce", {}) or {}
    last = _last(state)
    roster = int(workforce.get("roster_count") or last.get("fleet_size") or 0)
    completed = int(last.get("assignments_completed") or 0)
    searches = int(last.get("web_searches") or 0)
    leads = int(last.get("new_research_leads") or 0)
    signals = int(last.get("new_market_signals") or 0)
    status = str(last.get("status") or "waiting")
    bottleneck = str(last.get("bottleneck") or "—")
    return f'''
    <section class="wf-strip">
      <div class="wf-head">
        <div><div class="wf-eyebrow">PLANTILLA DIGITAL AUTÓNOMA</div><h2>{roster or 50} agentes · {status}</h2><p>Meta-LUMEN reparte trabajo en paralelo. Las búsquedas externas siguen compartiendo presupuesto, evidencia y límites constitucionales.</p></div>
        <a class="wf-btn" href="/workforce">Ver equipo completo</a>
      </div>
      <div class="wf-kpis">
        <div><small>Asignaciones último ciclo</small><b>{completed}</b></div>
        <div><small>Búsquedas web paralelas</small><b>{searches}</b></div>
        <div><small>Leads nuevos</small><b>{leads}</b></div>
        <div><small>Señales Market</small><b>{signals}</b></div>
        <div><small>Cuello de botella</small><b>{_e(bottleneck)}</b></div>
      </div>
    </section>'''


def css() -> str:
    return '''
    .wf-strip{margin:0 0 12px;padding:16px;border:1px solid #315848;border-radius:18px;background:linear-gradient(135deg,#081b16,#0b1822 55%,#101b14);box-shadow:0 15px 38px #0006}.wf-head{display:flex;justify-content:space-between;gap:18px;align-items:center}.wf-eyebrow{font-size:10px;font-weight:900;letter-spacing:.16em;color:#7ce7b3}.wf-head h2{margin:4px 0;font-size:20px}.wf-head p{margin:0;color:#91a9b7;max-width:850px;font-size:12px}.wf-btn{display:inline-block;padding:9px 12px;border-radius:10px;background:#d7ff64;color:#071018!important;font-weight:900;text-decoration:none;white-space:nowrap}.wf-kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:12px}.wf-kpis>div{padding:10px;border:1px solid #1f4035;border-radius:11px;background:#071610}.wf-kpis small,.wf-kpis b{display:block}.wf-kpis small{color:#78998c;font-size:10px;text-transform:uppercase;letter-spacing:.08em}.wf-kpis b{margin-top:4px;font-size:16px;color:#eaf7ef}@media(max-width:900px){.wf-kpis{grid-template-columns:1fr 1fr}.wf-head{align-items:flex-start;flex-direction:column}.wf-btn{width:100%;text-align:center}}
    '''


def inject_workforce_strip(base_html: str, state: Dict[str, Any]) -> str:
    if 'wf-strip' in base_html:
        return base_html
    out = base_html.replace('</head>', '<style>' + css() + '</style></head>', 1)
    section = render_workforce_strip(state)
    marker = '<section class="cycle-journal-panel"'
    if marker in out:
        return out.replace(marker, section + marker, 1)
    return out.replace('<body>', '<body>' + section, 1)


def render_workforce_page(state: Dict[str, Any]) -> str:
    workforce = state.get("agent_workforce", {}) or {}
    roster = list(workforce.get("roster", []) or [])
    last = _last(state)
    results = list(workforce.get("last_results", []) or [])
    history = list(workforce.get("recent_cycles", []) or [])[::-1]
    role_counts: Dict[str, int] = {}
    titles: Dict[str, str] = {}
    for row in roster:
        role = str(row.get("role") or "unknown")
        role_counts[role] = role_counts.get(role, 0) + 1
        titles[role] = str(row.get("title") or role)
    role_cards = ''.join(
        f'<div class="card"><small>{_e(titles.get(role, role))}</small><b>{count}</b><span>{_e(role)}</span></div>'
        for role, count in role_counts.items()
    ) or '<div class="empty">La plantilla se inicializa en el próximo ciclo.</div>'

    result_rows = ''.join(
        '<tr>'
        f'<td>{_e(row.get("agent_id"))}</td><td>{_e(row.get("role"))}</td><td>{_e(row.get("kind"))}</td>'
        f'<td>{"OK" if row.get("ok") else "ERROR"}</td><td>{_e(row.get("finding"))}</td>'
        '</tr>'
        for row in results
    ) or '<tr><td colspan="5" class="empty">Sin resultados todavía.</td></tr>'

    hist_rows = ''.join(
        '<tr>'
        f'<td>{_e(row.get("completed_at"))}</td><td>{_e(row.get("company_cycle"))}</td>'
        f'<td>{_e(row.get("assignments_completed"))}</td><td>{_e(row.get("web_searches"))}</td>'
        f'<td>{_e(row.get("new_research_leads"))}</td><td>{_e(row.get("new_market_signals"))}</td>'
        f'<td>{_e(row.get("bottleneck"))}</td>'
        '</tr>'
        for row in history
    ) or '<tr><td colspan="7" class="empty">El historial aparecerá después del primer ciclo.</td></tr>'

    findings = ''.join(f'<li>{_e(x)}</li>' for x in (last.get("top_findings") or [])) or '<li>Sin hallazgos todavía.</li>'
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LUMEN · Plantilla digital</title><style>
    :root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#061018;color:#edf7fb;font:14px Inter,system-ui,-apple-system;padding:20px}}.wrap{{max-width:1450px;margin:auto}}a{{color:#8fd4ff;text-decoration:none}}.top{{display:flex;justify-content:space-between;gap:15px;align-items:end;margin-bottom:16px}}h1{{margin:4px 0;font-size:30px}}.muted{{color:#829ba9}}.hero{{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}}.metric,.card,.panel{{background:#0b1822;border:1px solid #1c3b4b;border-radius:14px;padding:13px}}.metric small,.card small{{display:block;color:#7693a3;text-transform:uppercase;font-size:10px;letter-spacing:.08em}}.metric b,.card b{{display:block;font-size:23px;margin-top:5px;color:#d7ff64}}.card span{{font-size:10px;color:#678392}}.roles{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:10px}}.panel{{margin-top:10px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #17313f;text-align:left;vertical-align:top}}th{{color:#7e9bab;font-size:10px;text-transform:uppercase}}ul{{margin:8px 0 0;padding-left:20px}}li{{margin:5px 0;color:#b9cbd5}}.empty{{color:#7893a3}}@media(max-width:980px){{.hero{{grid-template-columns:1fr 1fr 1fr}}.roles{{grid-template-columns:1fr 1fr}}.top{{align-items:flex-start;flex-direction:column}}}}@media(max-width:620px){{body{{padding:10px}}.hero{{grid-template-columns:1fr 1fr}}table{{font-size:11px}}}}
    </style></head><body><main class="wrap"><div class="top"><div><div class="muted">LUMEN · ORGANIZACIÓN AUTÓNOMA</div><h1>Plantilla digital</h1><div class="muted">50 especialistas coordinados por Meta-LUMEN. Paralelismo alto, gasto y autoridad centralizados.</div></div><div><a href="/command-center">← Command Center</a></div></div>
    <section class="hero">
      <div class="metric"><small>Plantilla</small><b>{_e(workforce.get('roster_count') or last.get('fleet_size') or 50)}</b></div>
      <div class="metric"><small>Asignaciones</small><b>{_e(last.get('assignments_completed') or 0)}</b></div>
      <div class="metric"><small>Búsquedas web</small><b>{_e(last.get('web_searches') or 0)}</b></div>
      <div class="metric"><small>Leads nuevos</small><b>{_e(last.get('new_research_leads') or 0)}</b></div>
      <div class="metric"><small>Señales Market</small><b>{_e(last.get('new_market_signals') or 0)}</b></div>
      <div class="metric"><small>Errores</small><b>{_e(last.get('errors') or 0)}</b></div>
    </section>
    <section class="roles">{role_cards}</section>
    <section class="panel"><h2>Qué detectó el equipo</h2><ul>{findings}</ul><p class="muted">Cuello de botella actual: <b>{_e(last.get('bottleneck') or '—')}</b>. Presupuesto general de búsqueda restante: {_e(last.get('search_budget_after_general') or 0)}; reserva retail restante: {_e(last.get('retail_reserved_remaining') or 0)}.</p></section>
    <section class="panel"><h2>Últimas asignaciones</h2><div style="overflow:auto"><table><thead><tr><th>Agente</th><th>Rol</th><th>Trabajo</th><th>Estado</th><th>Resultado</th></tr></thead><tbody>{result_rows}</tbody></table></div></section>
    <section class="panel"><h2>Historial de la plantilla</h2><div style="overflow:auto"><table><thead><tr><th>Hora</th><th>Ciclo</th><th>Asignaciones</th><th>Búsquedas</th><th>Leads</th><th>Señales</th><th>Foco</th></tr></thead><tbody>{hist_rows}</tbody></table></div></section>
    </main></body></html>'''
