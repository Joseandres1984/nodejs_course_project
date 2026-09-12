from __future__ import annotations

import html
from typing import Any, Dict


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.0f}%"
    except (TypeError, ValueError):
        return "0%"


def _mode_class(mode: str) -> str:
    if mode == "RECOVERY": return "mo-red"
    if mode == "PROTECT_CASH": return "mo-amber"
    if mode in {"CLOSE_REVENUE", "REVENUE_EXECUTION", "PIPELINE_EXECUTION"}: return "mo-lime"
    if mode == "CONTROLLED_GROWTH": return "mo-blue"
    return "mo-neutral"


def render_master_panel(state: Dict[str, Any]) -> str:
    gov = state.get("master_governance", {}) or {}
    constitution = state.get("operating_constitution", {}) or {}
    mode = str(gov.get("company_mode") or "NOT_EVALUATED")
    switches = gov.get("kill_switches", {}) or {}
    resources = gov.get("resource_plan", {}) or {}
    conflicts = gov.get("conflicts_resolved", []) or []
    caps = state.get("constitutional_runtime_caps", {}) or {}

    switch_html = "".join(
        f'<span class="mo-switch {"on" if bool(v) else "off"}">{_e(k)}: {"ON" if bool(v) else "off"}</span>'
        for k, v in switches.items() if isinstance(v, bool)
    )
    conflict_html = "".join(
        f'<div class="mo-conflict"><b>{_e(x.get("conflict"))}</b><span>{_e(x.get("requesting_engine"))} → {_e(x.get("resolution"))}</span><small>Bloqueado/priorizado por {_e(x.get("blocked_by"))}</small></div>'
        for x in conflicts[:6]
    ) or '<div class="mo-empty">Sin conflictos materiales activos: los motores están alineados.</div>'

    priorities = constitution.get("priority_order", []) or []
    priority_html = "".join(
        f'<div class="mo-priority"><b>#{_e(x.get("rank"))}</b><span>{_e(x.get("principle"))}</span></div>' for x in priorities[:7]
    )

    return f'''
    <section class="master-panel">
      <div class="mo-head">
        <div><div class="mo-eyebrow">OPERATING CONSTITUTION · MASTER ORCHESTRATOR</div><h1>Company Mode: <span class="{_mode_class(mode)}">{_e(mode)}</span></h1><p>{_e(gov.get('reason') or 'Aún sin arbitraje publicado.')}</p></div>
        <div class="mo-winner"><small>Motor que prevalece</small><b>{_e(gov.get('winning_engine') or '—')}</b><small>Constitución v{_e(gov.get('constitution_version') or constitution.get('version') or '—')}</small></div>
      </div>
      <div class="mo-grid">
        <div class="mo-card"><h3>Asignación de recursos</h3>
          <div class="mo-row"><span>Core research</span><b>{_pct(resources.get('core_research_pct'))}</b></div>
          <div class="mo-row"><span>Deep Dive</span><b>{_pct(resources.get('deep_dive_pct'))}</b></div>
          <div class="mo-row"><span>Expansion</span><b>{_pct(resources.get('expansion_pct'))}</b></div>
          <div class="mo-row"><span>Exploration</span><b>{_pct(resources.get('exploration_pct'))}</b></div>
          <div class="mo-row"><span>Mission queries/ciclo</span><b>{_e(resources.get('mission_queries_cap', 0))}</b></div>
          <div class="mo-row"><span>Expansion queries/ciclo</span><b>{_e(resources.get('expansion_queries_cap', 0))}</b></div>
          <div class="mo-row"><span>Outbound efectivo/ciclo</span><b>{_e(caps.get('effective_outbound_cap', resources.get('outbound_cap', 0)))}</b></div>
        </div>
        <div class="mo-card"><h3>Kill-switches constitucionales</h3><div class="mo-switches">{switch_html or '<span class="mo-switch off">sin switches publicados</span>'}</div><p class="mo-note">Ningún switch autoriza gasto. Contratos, pagos, órdenes y compromisos vinculantes continúan siendo humanos.</p></div>
        <div class="mo-card"><h3>Conflictos resueltos</h3>{conflict_html}</div>
      </div>
      <details class="mo-constitution"><summary>Ver jerarquía constitucional</summary><div class="mo-priorities">{priority_html}</div><p>{_e(constitution.get('supreme_objective') or '')}</p></details>
    </section>'''


def css() -> str:
    return '''
    .master-panel{margin:0 0 12px;padding:18px;border-radius:19px;border:1px solid #364d72;background:linear-gradient(135deg,#0a1220,#0b1822 45%,#121720);box-shadow:0 18px 45px #0007}.mo-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-end}.mo-eyebrow{font-size:10px;font-weight:900;letter-spacing:.17em;color:#80cfff}.mo-head h1{margin:5px 0;font-size:22px}.mo-head p{margin:0;color:#9eb1bd;max-width:790px}.mo-winner{padding:10px 12px;border:1px solid #29435a;border-radius:12px;background:#07111a;min-width:230px}.mo-winner small,.mo-winner b{display:block}.mo-winner small{color:#7591a2}.mo-winner b{margin:3px 0 6px}.mo-grid{display:grid;grid-template-columns:1fr 1fr 1.2fr;gap:10px;margin-top:14px}.mo-card{padding:12px;border:1px solid #1c3446;border-radius:13px;background:#09151e}.mo-card h3{margin:0 0 8px;font-size:12px}.mo-row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #162b39}.mo-row:last-child{border:0}.mo-switches{display:flex;flex-wrap:wrap;gap:5px}.mo-switch{font-size:10px;padding:5px 7px;border-radius:999px;border:1px solid #29485b}.mo-switch.on{color:#ffb0b0;border-color:#743c3c;background:#261313}.mo-switch.off{color:#7ce7b3;border-color:#315d48}.mo-note{font-size:10px;color:#708998;line-height:1.45}.mo-conflict{padding:8px 0;border-bottom:1px solid #18303e}.mo-conflict b,.mo-conflict span,.mo-conflict small{display:block}.mo-conflict span{color:#c1d0d8;font-size:11px;margin-top:2px}.mo-conflict small{color:#6e8795;margin-top:2px}.mo-empty{color:#7ce7b3;font-size:11px}.mo-constitution{margin-top:10px;border-top:1px solid #1c3446;padding-top:9px;color:#8ba4b2}.mo-constitution summary{cursor:pointer;color:#bcd5e2}.mo-priorities{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}.mo-priority{display:flex;gap:5px;padding:5px 7px;border:1px solid #29485b;border-radius:8px;font-size:10px}.mo-red{color:#ff8c8c}.mo-amber{color:#ffd36a}.mo-lime{color:#d7ff64}.mo-blue{color:#80cfff}.mo-neutral{color:#b9cad4}@media(max-width:950px){.mo-head{align-items:flex-start;flex-direction:column}.mo-grid{grid-template-columns:1fr}.mo-winner{width:100%}}
    '''


def inject_master_panel(base_html: str, state: Dict[str, Any]) -> str:
    section = render_master_panel(state)
    out = base_html.replace('</head>', '<style>' + css() + '</style></head>', 1)
    marker = '<section class="cockpit-wrap">'
    if marker in out:
        return out.replace(marker, section + marker, 1)
    return out.replace('<body>', '<body>' + section, 1)
