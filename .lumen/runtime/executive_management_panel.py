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


def render_executive_management(state: Dict[str, Any]) -> str:
    report = state.get("autonomous_management", {}) or {}
    if not report:
        return """
        <section class="em-wrap"><div class="em-eyebrow">AUTONOMOUS EXECUTIVE MANAGEMENT</div>
        <h2>Gestión empresarial continua</h2><p>Esperando el primer ciclo de management.</p></section>"""

    primary = report.get("primary_management_priority", {}) or {}
    departments = report.get("department_scorecards", []) or []
    programs = report.get("active_improvement_programs", []) or []
    deals = report.get("deal_portfolio", []) or []
    categories = report.get("category_portfolio", []) or []
    overlay = report.get("resource_overlay", {}) or {}

    dept_html = "".join(
        f'<div class="em-dept {_esc(x.get("status"))}"><div><b>{_esc(x.get("department"))}</b><small>{_esc(x.get("owner_engine"))}</small></div><strong>{_f(x.get("score")):.0f}</strong></div>'
        for x in departments[:9]
    ) or '<div class="em-empty">Sin scorecards.</div>'

    programs_html = "".join(
        f'<div class="em-program"><b>{_esc(x.get("department"))}</b><span>{_esc(x.get("objective"))}</span><small>{_f(x.get("current_score"), _f(x.get("baseline_score"))):.0f} → objetivo {_f(x.get("target_score")):.0f} · revisión ciclo {_esc(x.get("review_cycle"))}</small></div>'
        for x in programs[:6]
    ) or '<div class="em-empty">No hay programa autónomo activo.</div>'

    deal_html = "".join(
        f'<div class="em-row"><b>{_esc(x.get("deal_id"))}</b><span class="tag {_esc(x.get("disposition"))}">{_esc(x.get("disposition"))}</span><span>Money {_f(x.get("money_score")):.0f} · Safe {_f(x.get("safe_close_score")):.0f}</span></div>'
        for x in deals[:8]
    ) or '<div class="em-empty">Sin deals reales para administrar.</div>'

    cat_html = "".join(
        f'<div class="em-row"><b>{_esc(x.get("category"))}</b><span class="tag {_esc(x.get("management_action"))}">{_esc(x.get("management_action"))}</span><span>score {_f(x.get("learned_score")):.0f} · conf. {_f(x.get("confidence"))*100:.0f}%</span></div>'
        for x in categories[:8]
    ) or '<div class="em-empty">Todavía no hay suficiente aprendizaje por categoría.</div>'

    return f"""
    <section class="em-wrap">
      <div class="em-head">
        <div>
          <div class="em-eyebrow">AUTONOMOUS EXECUTIVE MANAGEMENT</div>
          <h2>CEO operativo de LUMEN</h2>
          <p>Administra departamentos, portfolio y mejora continua bajo la Constitución.</p>
        </div>
        <div class="em-score"><small>MANAGEMENT SCORE</small><b>{_f(report.get("company_management_score")):.0f}</b><span>/100</span></div>
      </div>

      <div class="em-priority">
        <small>PRIORIDAD DE GESTIÓN</small>
        <h3>{_esc(primary.get("title") or "Sin prioridad")}</h3>
        <p>{_esc(primary.get("reason"))}</p>
        <div><span>{_esc(primary.get("department"))}</span><span>Prioridad {_f(primary.get("priority")):.0f}</span><span>{'AUTÓNOMO' if primary.get('autonomous', True) else 'REQUIERE HUMANO'}</span></div>
      </div>

      <div class="em-grid two">
        <div class="em-box"><h3>Departamentos</h3>{dept_html}</div>
        <div class="em-box"><h3>Programas de mejora</h3>{programs_html}</div>
      </div>
      <div class="em-grid two">
        <div class="em-box"><h3>Portfolio de deals</h3>{deal_html}</div>
        <div class="em-box"><h3>Portfolio de categorías</h3>{cat_html}</div>
      </div>
      <div class="em-foot">Overlay de recursos: <b>{'APLICADO' if overlay.get('applied') else 'SIN CAMBIO'}</b> · {_esc(overlay.get('reason'))}. Nunca amplía caps, gasto ni autoridad vinculante.</div>
    </section>
    """


def executive_management_css() -> str:
    return """
    <style>
    .em-wrap{margin:14px 0;padding:20px;border:1px solid #25445a;border-radius:20px;background:linear-gradient(135deg,#07131d,#0a1822 55%,#09151b);color:#eaf7ff}
    .em-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.em-eyebrow{font-size:11px;letter-spacing:1.5px;color:#7bdff2;font-weight:800}.em-head h2{margin:5px 0 3px;font-size:25px}.em-head p,.em-priority p{color:#a9becb;margin:0}
    .em-score{min-width:115px;text-align:center;padding:12px;border-radius:15px;background:#0d2230;border:1px solid #28536a}.em-score small{display:block;color:#81a6b8;font-size:9px}.em-score b{font-size:34px}.em-score span{color:#7f9aa8}
    .em-priority{margin-top:14px;padding:15px;border-radius:16px;background:#0c202c;border:1px solid #25516b}.em-priority small{color:#70d7ef;font-weight:800}.em-priority h3{margin:5px 0}.em-priority div{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.em-priority div span{font-size:11px;padding:5px 8px;border-radius:999px;background:#112d3b}
    .em-grid{display:grid;gap:12px;margin-top:12px}.em-grid.two{grid-template-columns:repeat(2,minmax(0,1fr))}.em-box{padding:14px;border-radius:16px;background:#091a24;border:1px solid #183c4e}.em-box h3{margin:0 0 10px;font-size:14px}
    .em-dept,.em-row{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid #143140}.em-dept:last-child,.em-row:last-child{border-bottom:0}.em-dept div{flex:1}.em-dept small{display:block;color:#7896a6}.em-dept strong{font-size:18px}.em-dept.critical strong{color:#ff9a9a}.em-dept.repair strong{color:#ffd98a}.em-dept.strong strong{color:#91efc2}
    .em-program{padding:8px 0;border-bottom:1px solid #143140}.em-program b,.em-program span,.em-program small{display:block}.em-program span{color:#d6e6ef}.em-program small{color:#7896a6;margin-top:3px}
    .em-row b{min-width:90px}.em-row>span:last-child{margin-left:auto;color:#8da8b6;font-size:11px}.tag{font-size:10px;padding:4px 7px;border-radius:999px;background:#143447}.tag.PURSUE,.tag.SCALE{background:#123d2f;color:#9cf4c5}.tag.REPAIR_RISK,.tag.REPAIR{background:#493815;color:#ffe09a}.tag.HOLD_RISK,.tag.PAUSE{background:#4a2424;color:#ffb0b0}.tag.PARK{background:#303641;color:#bcc7d0}
    .em-foot{margin-top:12px;font-size:11px;color:#819cab}.em-empty{color:#819cab;padding:8px 0}
    @media(max-width:800px){.em-grid.two{grid-template-columns:1fr}.em-head{flex-direction:column}.em-score{width:100%;box-sizing:border-box}}
    </style>
    """


def inject_executive_management(page: str, state: Dict[str, Any]) -> str:
    block = executive_management_css() + render_executive_management(state)
    marker = "</main>"
    if marker in page:
        return page.replace(marker, block + marker, 1)
    return page + block
