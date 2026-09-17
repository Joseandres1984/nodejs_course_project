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


def _money(value: Any) -> str:
    try:
        return f"USD {float(value):,.0f}"
    except (TypeError, ValueError):
        return "USD 0"


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


def render_expansion_panel(state: Dict[str, Any]) -> str:
    phase = state.get("expansion_phase", {}) or {}
    loop = (phase.get("revenue_loop", {}) or {}) if isinstance(phase, dict) else {}
    metrics = state.get("expansion_revenue_metrics", {}) or loop.get("metrics", {}) or {}
    roles = state.get("expansion_specialist_roles", []) or loop.get("specialist_roles", []) or []
    governance = phase.get("search_governance", {}) or loop.get("search_governance", {}) or {}
    guardrails = phase.get("guardrails", {}) or loop.get("authority", {}) or {}
    demand = phase.get("demand_radar", {}) or {}
    factory = phase.get("opportunity_factory", {}) or {}
    market_map = phase.get("market_map", {}) or {}
    status = str(phase.get("status") or "waiting_first_cycle")
    stage = str(loop.get("stage") or "waiting_first_cycle")

    metric_rows = [
        ("Empresas conocidas", metrics.get("companies_known", 0)),
        ("Catálogos indexados", metrics.get("catalogs_indexed", 0)),
        ("Productos conocidos", metrics.get("products_known", 0)),
        ("Necesidades detectadas", metrics.get("needs_detected", 0)),
        ("Oportunidades activas", metrics.get("opportunities_active", 0)),
        ("Compradores contactados", metrics.get("buyers_contacted", 0)),
        ("Proveedores contactados", metrics.get("suppliers_contacted", 0)),
        ("Respuestas", metrics.get("replies", 0)),
        ("Negociaciones", metrics.get("negotiations", 0)),
        ("Propuestas", metrics.get("proposals", 0)),
        ("Margen potencial", _money(metrics.get("margin_potential_usd", 0))),
        ("Ventas cerradas", metrics.get("sales_closed", 0)),
        ("Ingreso generado", _money(metrics.get("revenue_generated_usd", 0))),
    ]
    metric_html = "".join(
        f'<div class="ex-kpi"><span>{_e(label)}</span><b>{_e(value)}</b></div>' for label, value in metric_rows
    )
    role_html = "".join(
        f'<div class="ex-role"><span>{_e(x.get("role"))}</span><b>{_e(x.get("workload", 0))}</b><small>{_e(x.get("status") or "active")}</small></div>'
        for x in roles[:8] if isinstance(x, dict)
    ) or '<div class="ex-empty">Los agentes aparecerán después del primer ciclo de expansión.</div>'

    cap = governance.get("daily_provider_cap")
    cap_text = _e(cap if cap is not None else "—")
    spend_ok = guardrails.get("paid_spend_authority_changed") is False
    binding_ok = guardrails.get("binding_authority_changed") is False
    purchase_ok = guardrails.get("autonomous_purchase") is False
    safe = spend_ok and binding_ok and purchase_ok
    safety_text = "SIN NUEVA AUTORIDAD" if safe else "REVISAR GUARDRAILS"
    safety_class = "safe" if safe else "warn"

    return f'''
    <section class="expansion-panel">
      <div class="ex-head">
        <div><div class="ex-eyebrow">EXPANSION / REVENUE NETWORK</div><h2>Market Map → Demand Radar → Opportunity Factory → Sales Brain → Revenue Loop</h2><p>La expansión reutiliza memoria, catálogos y relaciones antes de buscar. Pipeline no cuenta como ingreso: sólo eventos realizados.</p></div>
        <div class="ex-state"><span>Estado</span><b>{_e(status)}</b><small>carril: {_e(stage)}</small></div>
      </div>
      <div class="ex-kpis">{metric_html}</div>
      <div class="ex-columns">
        <div class="ex-card"><h3>Agentes especializados</h3><div class="ex-roles">{role_html}</div></div>
        <div class="ex-card"><h3>Inteligencia de expansión</h3>
          <div class="ex-row"><span>Categorías conocidas</span><b>{_e(market_map.get('categories_known', 0))}</b></div>
          <div class="ex-row"><span>Demanda verificada</span><b>{_e(demand.get('verified_buyer_demand', 0))}</b></div>
          <div class="ex-row"><span>Señales con proveedores</span><b>{_e(demand.get('with_supplier_candidates', 0))}</b></div>
          <div class="ex-row"><span>Casos Opportunity Factory</span><b>{_e(factory.get('cases_total', 0))}</b></div>
          <div class="ex-row"><span>Listas para pipeline</span><b>{_e(factory.get('ready_for_pipeline', 0))}</b></div>
        </div>
        <div class="ex-card ex-guard"><h3>Governor de expansión</h3>
          <div class="ex-cap"><span>Tope diario proveedor</span><b>{cap_text}</b></div>
          <div class="ex-badge {safety_class}">{safety_text}</div>
          <p>Catálogo primero / buscador después: <b>{'ACTIVO' if governance.get('catalog_first_search_last') else 'pendiente'}</b>.</p>
          <p>Sin compras autónomas, sin nueva autoridad de gasto y sin nuevos compromisos vinculantes.</p>
        </div>
      </div>
    </section>'''


def css() -> str:
    return '''
    .master-panel{margin:0 0 12px;padding:18px;border-radius:19px;border:1px solid #364d72;background:linear-gradient(135deg,#0a1220,#0b1822 45%,#121720);box-shadow:0 18px 45px #0007}.mo-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-end}.mo-eyebrow{font-size:10px;font-weight:900;letter-spacing:.17em;color:#80cfff}.mo-head h1{margin:5px 0;font-size:22px}.mo-head p{margin:0;color:#9eb1bd;max-width:790px}.mo-winner{padding:10px 12px;border:1px solid #29435a;border-radius:12px;background:#07111a;min-width:230px}.mo-winner small,.mo-winner b{display:block}.mo-winner small{color:#7591a2}.mo-winner b{margin:3px 0 6px}.mo-grid{display:grid;grid-template-columns:1fr 1fr 1.2fr;gap:10px;margin-top:14px}.mo-card{padding:12px;border:1px solid #1c3446;border-radius:13px;background:#09151e}.mo-card h3{margin:0 0 8px;font-size:12px}.mo-row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #162b39}.mo-row:last-child{border:0}.mo-switches{display:flex;flex-wrap:wrap;gap:5px}.mo-switch{font-size:10px;padding:5px 7px;border-radius:999px;border:1px solid #29485b}.mo-switch.on{color:#ffb0b0;border-color:#743c3c;background:#261313}.mo-switch.off{color:#7ce7b3;border-color:#315d48}.mo-note{font-size:10px;color:#708998;line-height:1.45}.mo-conflict{padding:8px 0;border-bottom:1px solid #18303e}.mo-conflict b,.mo-conflict span,.mo-conflict small{display:block}.mo-conflict span{color:#c1d0d8;font-size:11px;margin-top:2px}.mo-conflict small{color:#6e8795;margin-top:2px}.mo-empty{color:#7ce7b3;font-size:11px}.mo-constitution{margin-top:10px;border-top:1px solid #1c3446;padding-top:9px;color:#8ba4b2}.mo-constitution summary{cursor:pointer;color:#bcd5e2}.mo-priorities{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}.mo-priority{display:flex;gap:5px;padding:5px 7px;border:1px solid #29485b;border-radius:8px;font-size:10px}.mo-red{color:#ff8c8c}.mo-amber{color:#ffd36a}.mo-lime{color:#d7ff64}.mo-blue{color:#80cfff}.mo-neutral{color:#b9cad4}
    .expansion-panel{margin:0 0 12px;padding:18px;border-radius:19px;border:1px solid #365f55;background:linear-gradient(135deg,#07171a,#0b1822 58%,#121b12);box-shadow:0 18px 45px #0007}.ex-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-end}.ex-eyebrow{font-size:10px;font-weight:900;letter-spacing:.17em;color:#7ce7b3}.ex-head h2{margin:5px 0;font-size:20px}.ex-head p{margin:0;color:#93aeb4;max-width:820px}.ex-state{min-width:220px;padding:10px 12px;border:1px solid #315d48;border-radius:12px;background:#071411}.ex-state span,.ex-state b,.ex-state small{display:block}.ex-state span,.ex-state small{font-size:9px;color:#7c9b8d}.ex-state b{margin:3px 0;color:#d7ff64}.ex-kpis{display:grid;grid-template-columns:repeat(7,1fr);gap:7px;margin-top:14px}.ex-kpi{padding:10px;border:1px solid #1d3d3a;border-radius:10px;background:#071318}.ex-kpi span{display:block;font-size:9px;color:#7f9da5}.ex-kpi b{display:block;margin-top:4px;font-size:17px;color:#d7ff64}.ex-columns{display:grid;grid-template-columns:1.3fr .8fr .9fr;gap:10px;margin-top:10px}.ex-card{padding:12px;border:1px solid #1d3d3a;border-radius:12px;background:#08151a}.ex-card h3{font-size:12px;margin:0 0 9px}.ex-roles{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.ex-role{padding:8px;border:1px solid #20483e;border-radius:8px}.ex-role span,.ex-role b,.ex-role small{display:block}.ex-role span{font-size:9px;color:#94aaa4}.ex-role b{font-size:17px;color:#80cfff}.ex-role small{font-size:8px;color:#6d8e82}.ex-row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #17332e}.ex-row:last-child{border:0}.ex-cap{display:flex;justify-content:space-between;align-items:center;padding:8px 0}.ex-cap b{font-size:22px;color:#d7ff64}.ex-badge{display:inline-block;padding:6px 8px;border-radius:999px;font-size:9px;font-weight:900}.ex-badge.safe{border:1px solid #315d48;color:#7ce7b3}.ex-badge.warn{border:1px solid #743c3c;color:#ff9f9f}.ex-guard p{font-size:10px;color:#809ba0;line-height:1.45}.ex-empty{font-size:10px;color:#78959a;padding:9px;border:1px dashed #315d48;border-radius:8px}
    @media(max-width:1150px){.ex-kpis{grid-template-columns:repeat(4,1fr)}.ex-columns{grid-template-columns:1fr}.ex-roles{grid-template-columns:repeat(4,1fr)}}@media(max-width:950px){.mo-head,.ex-head{align-items:flex-start;flex-direction:column}.mo-grid{grid-template-columns:1fr}.mo-winner,.ex-state{width:100%}}@media(max-width:650px){.ex-kpis{grid-template-columns:1fr 1fr}.ex-roles{grid-template-columns:1fr 1fr}}
    '''


def inject_master_panel(base_html: str, state: Dict[str, Any]) -> str:
    section = render_master_panel(state) + render_expansion_panel(state)
    out = base_html.replace('</head>', '<style>' + css() + '</style></head>', 1)
    marker = '<section class="cockpit-wrap">'
    if marker in out:
        return out.replace(marker, section + marker, 1)
    return out.replace('<body>', '<body>' + section, 1)
