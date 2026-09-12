from __future__ import annotations

import html
from typing import Any, Dict

from portfolio_goal_panel import render_goal_portfolio, css as goal_portfolio_css
from go_live_panel import render_go_live, css as go_live_css
from closer_panel import render_closer, css as closer_css


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def render_business_control(state: Dict[str, Any]) -> str:
    controller = state.get("business_controller", {}) or {}
    capital = state.get("capital_margin_intelligence", {}) or {}
    if not controller and not capital:
        return '<section class="bc-wrap"><div class="bc-eye">BUSINESS CONTROLLER · CAPITAL INTELLIGENCE</div><h2>Control económico autónomo</h2><p>Esperando el primer ciclo.</p></section>'

    primary = capital.get("primary_directive", {}) or {}
    summary = capital.get("summary", {}) or {}
    intervention = controller.get("active_intervention", {}) or {}
    signals = controller.get("signals", {}) or {}
    rows = capital.get("deal_capital_rankings", []) or []
    categories = capital.get("category_capital_rankings", []) or []

    deals_html = "".join(
        f'<div class="bc-row"><b>{_esc(x.get("deal_id"))}</b><span class="bc-tag {_esc(x.get("capital_action"))}">{_esc(x.get("capital_action"))}</span><span>Cap {_f(x.get("capital_priority_score")):.0f} · RA USD {_f(x.get("risk_adjusted_expected_profit_usd")):,.0f} · margen {_f(x.get("margin_pct")):.1f}% / {_f(x.get("defended_target_margin_pct")):.1f}%</span></div>'
        for x in rows[:8]
    ) or '<div class="bc-empty">Sin deals con economía suficiente.</div>'

    cats_html = "".join(
        f'<div class="bc-row"><b>{_esc(x.get("category"))}</b><span>RA USD {_f(x.get("risk_adjusted_expected_profit_usd")):,.0f}</span><span>efic. {_f(x.get("modeled_capital_efficiency"))*100:.1f}%</span></div>'
        for x in categories[:6]
    ) or '<div class="bc-empty">Sin categorías económicas todavía.</div>'

    return f"""
    <section class="bc-wrap">
      <div class="bc-head">
        <div><div class="bc-eye">BUSINESS CONTROLLER · CAPITAL & MARGIN INTELLIGENCE</div><h2>Control económico autónomo</h2><p>Corrige actividad, margen, conversión y asignación de atención con memoria entre ciclos.</p></div>
        <div class="bc-score"><small>CONTROL SCORE</small><b>{_f(controller.get('company_control_score')):.0f}</b><span>/100</span></div>
      </div>
      <div class="bc-grid four">
        <div><small>MODO</small><strong>{_esc(controller.get('control_mode') or '—')}</strong></div>
        <div><small>ACELERAR</small><strong>{_esc(summary.get('accelerate',0))}</strong></div>
        <div><small>MEJORAR MARGEN</small><strong>{_esc(summary.get('improve_margin',0))}</strong></div>
        <div><small>HOLD RIESGO</small><strong>{_esc(summary.get('hold_risk',0))}</strong></div>
      </div>
      <div class="bc-priority"><small>ORDEN DEL CONTROLLER</small><h3>{_esc(controller.get('control_mode') or 'Sin intervención')}</h3><p>{_esc(controller.get('reason'))}</p><div><span>Δ RA profit USD {_f(signals.get('risk_profit_delta')):,.0f}</span><span>Δ Safe {_f(signals.get('safe_close_delta')):.1f}</span><span>{'ACTIVIDAD SIN VALOR' if signals.get('activity_without_value') else 'actividad controlada'}</span></div></div>
      <div class="bc-priority"><small>PRIORIDAD DE CAPITAL</small><h3>{_esc(primary.get('deal_id') or 'Sin deal económico')}</h3><p>{_esc(primary.get('reason'))}</p><div><span>{_esc(primary.get('action'))}</span><span>Capital score {_f(primary.get('capital_priority_score')):.0f}</span><span>margen objetivo {_f(primary.get('defended_target_margin_pct')):.1f}%</span></div></div>
      <div class="bc-grid two"><div class="bc-box"><h3>Deals por oportunidad económica</h3>{deals_html}</div><div class="bc-box"><h3>Categorías por retorno</h3>{cats_html}</div></div>
      <div class="bc-foot">Intervención: <b>{_esc(intervention.get('id') or 'ninguna')}</b> · hold hasta ciclo {_esc(intervention.get('hold_until_cycle') or '—')} · overlay {'APLICADO' if (controller.get('intervention_overlay') or {}).get('applied') else 'sin cambio'}. No autoriza capital, pagos, órdenes ni contratos.</div>
    </section>
    """


def css() -> str:
    return """
    <style>
    .bc-wrap{margin:14px 0;padding:20px;border:1px solid #4b3c24;border-radius:20px;background:linear-gradient(135deg,#171209,#21180b 55%,#141008);color:#fff5dc}.bc-head{display:flex;justify-content:space-between;gap:14px}.bc-eye{font-size:11px;letter-spacing:1.4px;color:#efc46f;font-weight:800}.bc-head h2{margin:5px 0 3px}.bc-head p,.bc-priority p{color:#cbbd9f;margin:0}.bc-score{min-width:115px;text-align:center;padding:12px;border-radius:15px;background:#2a1e0d;border:1px solid #6c5122}.bc-score small{display:block;color:#c9a96c;font-size:9px}.bc-score b{font-size:34px}.bc-score span{color:#9c8967}.bc-grid{display:grid;gap:10px;margin-top:12px}.bc-grid.four{grid-template-columns:repeat(4,minmax(0,1fr))}.bc-grid.two{grid-template-columns:repeat(2,minmax(0,1fr))}.bc-grid.four>div,.bc-box{padding:12px;border-radius:14px;background:#21180c;border:1px solid #49381d}.bc-grid small{display:block;color:#aa936c;font-size:9px}.bc-grid strong{display:block;margin-top:4px;font-size:17px}.bc-priority{margin-top:12px;padding:14px;border-radius:15px;background:#261b0d;border:1px solid #60471d}.bc-priority small{color:#efc46f;font-weight:800}.bc-priority h3{margin:4px 0}.bc-priority div{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px}.bc-priority div span,.bc-tag{font-size:10px;padding:4px 7px;border-radius:999px;background:#3a2a13}.bc-box h3{margin:0 0 8px;font-size:14px}.bc-row{display:flex;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid #3a2a16}.bc-row:last-child{border-bottom:0}.bc-row>b{min-width:88px}.bc-row>span:last-child{margin-left:auto;color:#bba98a;font-size:10px}.bc-tag.ACCELERATE{background:#173d29;color:#a6f1c4}.bc-tag.IMPROVE_MARGIN,.bc-tag.IMPROVE_CONVERSION,.bc-tag.REPAIR_TERMS{background:#4a3915;color:#ffe09a}.bc-tag.HOLD_RISK,.bc-tag.DEPRIORITIZE{background:#4a2323;color:#ffb0b0}.bc-foot{margin-top:12px;color:#aa9878;font-size:10px}.bc-empty{color:#a99270}.bc-wrap h3{color:#fff5dc}@media(max-width:800px){.bc-grid.four,.bc-grid.two{grid-template-columns:1fr}.bc-head{flex-direction:column}.bc-score{width:100%;box-sizing:border-box}.bc-row{align-items:flex-start;flex-wrap:wrap}.bc-row>span:last-child{margin-left:0;width:100%}}
    </style>
    """


def inject_business_control(page: str, state: Dict[str, Any]) -> str:
    block = (
        go_live_css() + render_go_live(state)
        + closer_css() + render_closer(state)
        + goal_portfolio_css() + render_goal_portfolio(state)
        + css() + render_business_control(state)
    )
    marker = "</main>"
    if marker in page:
        return page.replace(marker, block + marker, 1)
    return page + block