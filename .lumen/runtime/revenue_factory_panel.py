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
        return "—"
    try:
        return f"USD {float(value):,.0f}"
    except (TypeError, ValueError):
        return "—"


def render_revenue_factory_panel(state: Dict[str, Any]) -> str:
    factory = state.get("revenue_factory", {}) or {}
    target = factory.get("target", {}) or {}
    plan = factory.get("reverse_plan", {}) or {}
    directive = factory.get("directive", {}) or {}
    economics = factory.get("economics", {}) or {}
    allocation = factory.get("category_allocation", {}) or {}
    funnel = factory.get("funnel_model", []) or []

    target_value = target.get("monthly_profit_target_usd")
    coverage = factory.get("target_coverage_pct")
    gap = plan.get("profit_gap_usd")
    mature = sum(1 for x in funnel if x.get("sample_sufficient"))
    total = len(funnel)
    maturity_pct = round(mature / total * 100, 1) if total else 0

    target_note = target.get("note") or (
        "Objetivo explícito configurado." if target.get("source") == "explicit_env" else "Objetivo adaptativo basado en evidencia disponible."
    )
    actions = factory.get("factory_actions", []) or []
    action_html = "".join(
        f'<div class="rf-row"><span>{_esc(x.get("title"))}</span><b>{_esc(x.get("gap") if x.get("gap") is not None else "—")}</b></div>'
        for x in actions[:5]
    ) or '<div class="rf-empty">Sin brecha operativa prioritaria detectada.</div>'

    scale = allocation.get("scale", []) or []
    pause = allocation.get("pause", []) or []
    scale_html = "".join(f'<span class="rf-pill scale">ESCALAR · {_esc(x.get("category"))}</span>' for x in scale[:4])
    pause_html = "".join(f'<span class="rf-pill pause">PAUSAR · {_esc(x.get("category"))}</span>' for x in pause[:4])
    allocation_html = scale_html + pause_html or '<span class="rf-muted">Todavía no hay suficiente evidencia para escalar/pausar categorías con alta confianza.</span>'

    coverage_text = "—" if coverage is None else f"{coverage:.1f}%"
    confidence = economics.get("planning_profit_confidence") or "unknown"

    return f'''
    <section class="rf-wrap">
      <div class="rf-head"><div><div class="rf-eyebrow">AUTONOMOUS REVENUE FACTORY</div><h2>De objetivo económico a trabajo concreto</h2><p>Convierte beneficio objetivo → transacciones → propuestas → cotizaciones → oportunidades. Las conversiones sin muestra suficiente no se extrapolan.</p></div><div class="rf-directive"><span>Movimiento #1</span><b>{_esc(directive.get('title') or 'Construir más evidencia económica')}</b></div></div>
      <div class="rf-kpis">
        <div><span>Objetivo mensual</span><b>{_money(target_value)}</b><small>{_esc(target.get('source') or 'sin establecer')}</small></div>
        <div><span>Beneficio realizado</span><b>{_money(factory.get('realized_profit_usd'))}</b><small>solo operaciones reales</small></div>
        <div><span>Cobertura</span><b>{coverage_text}</b><small>{_esc(plan.get('status') or 'sin reverse plan')}</small></div>
        <div><span>Brecha</span><b>{_money(gap)}</b><small>confianza unitaria: {_esc(confidence)}</small></div>
        <div><span>Madurez de conversiones</span><b>{maturity_pct:.0f}%</b><small>{mature}/{total} etapas con muestra suficiente</small></div>
      </div>
      <div class="rf-columns"><div><h3>Trabajo que falta producir</h3>{action_html}</div><div><h3>Asignación por categoría</h3><div class="rf-pills">{allocation_html}</div><div class="rf-note">{_esc(target_note)}</div></div></div>
    </section>'''


def revenue_factory_css() -> str:
    return '''
    .rf-wrap{margin:0 0 12px;padding:17px;border:1px solid #31516a;border-radius:18px;background:linear-gradient(135deg,#081923,#0b121a 62%,#11170e)}.rf-head{display:flex;justify-content:space-between;gap:20px;align-items:flex-end}.rf-eyebrow{font-size:10px;letter-spacing:.18em;color:#80cfff;font-weight:900}.rf-head h2{font-size:20px;margin:4px 0}.rf-head p{max-width:760px;color:#8ea9b8;margin:0}.rf-directive{max-width:420px;padding:10px;border-left:3px solid #d7ff64;background:#101a13}.rf-directive span{display:block;font-size:9px;color:#829a88;text-transform:uppercase}.rf-directive b{font-size:13px}.rf-kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:14px}.rf-kpis>div{padding:10px;border:1px solid #1f3e50;border-radius:10px;background:#07131b}.rf-kpis span,.rf-kpis small{display:block;color:#829dac;font-size:9px}.rf-kpis b{display:block;font-size:18px;color:#d7ff64;margin:3px 0}.rf-columns{display:grid;grid-template-columns:1.1fr .9fr;gap:12px;margin-top:12px}.rf-columns h3{margin:0 0 8px;font-size:12px}.rf-row{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid #17303e}.rf-row b{color:#80cfff}.rf-pill{display:inline-block;border-radius:99px;padding:5px 8px;margin:2px;font-size:9px;font-weight:800}.rf-pill.scale{border:1px solid #315d48;color:#7ce7b3}.rf-pill.pause{border:1px solid #6a3d3d;color:#ff9f9f}.rf-muted,.rf-note{font-size:10px;color:#7892a0}.rf-note{margin-top:8px}.rf-empty{padding:12px;border:1px dashed #31516a;color:#80cfff;border-radius:9px}@media(max-width:1000px){.rf-head{align-items:flex-start;flex-direction:column}.rf-kpis{grid-template-columns:1fr 1fr}.rf-columns{grid-template-columns:1fr}}
    '''


def inject_revenue_factory(base_html: str, state: Dict[str, Any]) -> str:
    section = render_revenue_factory_panel(state)
    css = '<style>' + revenue_factory_css() + '</style>'
    out = base_html.replace('</head>', css + '</head>', 1)
    marker = '<section class="cockpit-wrap">'
    if marker in out:
        # Put the revenue factory immediately after Approval Cockpit by locating its closing section.
        cockpit_start = out.find(marker)
        cockpit_end = out.find('</section>', cockpit_start)
        if cockpit_end >= 0:
            cockpit_end += len('</section>')
            out = out[:cockpit_end] + section + out[cockpit_end:]
            return out
    body_marker = '<div class="grid hero">'
    if body_marker in out:
        return out.replace(body_marker, section + body_marker, 1)
    return out.replace('<body>', '<body>' + section, 1)
