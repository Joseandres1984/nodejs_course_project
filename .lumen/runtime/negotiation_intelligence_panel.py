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


def render_negotiation_intelligence(state: Dict[str, Any]) -> str:
    report = state.get("negotiation_intelligence", {}) or {}
    if not report:
        return '<section class="ni-wrap"><div class="ni-eye">NEGOTIATION INTELLIGENCE 2.0</div><h2>Counterparty Behavioral Memory</h2><p>Esperando el primer ciclo de aprendizaje.</p></section>'

    primary = report.get("primary_plan", {}) or {}
    proactive = report.get("proactive_execution", {}) or {}
    plans = report.get("plans", []) or []
    profiles = report.get("profiles", []) or []

    plan_html = "".join(
        f'<div class="ni-row"><b>{_esc(x.get("deal_id"))}</b><span class="ni-tag">{_esc(x.get("strategy"))}</span><span>{_esc(x.get("objective"))}</span><small>round {_esc(x.get("negotiation_rounds"))}/{_esc(x.get("max_autonomous_rounds"))} · conf. {_f(x.get("supplier_confidence"))*100:.0f}%</small></div>'
        for x in plans[:8]
    ) or '<div class="ni-empty">Sin deals negociables.</div>'

    prof_html = "".join(
        f'<div class="ni-prof"><div><b>{_esc(x.get("name"))}</b><small>{_esc(x.get("type"))} · {_esc(x.get("account_id"))}</small></div><span>{_esc(x.get("observed_supplier_flexibility") or x.get("observed_buyer_priority") or "unknown")}</span><strong>{_f(x.get("confidence"))*100:.0f}%</strong></div>'
        for x in profiles[:8]
    ) or '<div class="ni-empty">Todavía no hay memoria conductual suficiente.</div>'

    return f"""
    <section class="ni-wrap">
      <div class="ni-head">
        <div><div class="ni-eye">NEGOTIATION INTELLIGENCE 2.0</div><h2>Counterparty Behavioral Memory</h2><p>Aprende qué pedir, cuándo insistir y cuándo dejar de presionar usando solo evidencia observada.</p></div>
        <div class="ni-kpi"><b>{_esc(report.get('personalized_profiles',0))}</b><small>perfiles personalizados</small></div>
      </div>
      <div class="ni-primary">
        <small>ESTRATEGIA #1</small><h3>{_esc(primary.get('strategy') or 'SIN PLAN')}</h3>
        <p>{_esc(primary.get('reason') or '')}</p>
        <div><span>Deal {_esc(primary.get('deal_id'))}</span><span>Objetivo {_esc(primary.get('objective'))}</span><span>Buyer: {_esc(primary.get('buyer_observed_priority'))}</span><span>Supplier: {_esc(primary.get('supplier_observed_flexibility'))}</span></div>
      </div>
      <div class="ni-grid">
        <div class="ni-box"><h3>Planes por deal</h3>{plan_html}</div>
        <div class="ni-box"><h3>Memoria de contrapartes</h3>{prof_html}</div>
      </div>
      <div class="ni-foot">Negociación proactiva preparada este ciclo: <b>{_esc(proactive.get('created',0))}</b>. Máximo una por ciclo; máximo dos rondas autónomas por proveedor/deal. Sin competencia, urgencia ni concesiones inventadas.</div>
    </section>
    """


def css() -> str:
    return """
    <style>
    .ni-wrap{margin:14px 0;padding:20px;border:1px solid #4a3f69;border-radius:20px;background:linear-gradient(135deg,#100d19,#171126 55%,#11101c);color:#f1edff}.ni-eye{font-size:11px;letter-spacing:1.4px;color:#c5a7ff;font-weight:800}.ni-head{display:flex;justify-content:space-between;gap:16px}.ni-head h2{margin:5px 0 3px}.ni-head p,.ni-primary p{color:#b9aecb;margin:0}.ni-kpi{text-align:center;min-width:130px;padding:12px;border-radius:15px;background:#211833;border:1px solid #4b3970}.ni-kpi b{font-size:30px;display:block}.ni-kpi small{color:#a996bd}.ni-primary{margin-top:14px;padding:15px;border-radius:16px;background:#1b1529;border:1px solid #49386b}.ni-primary small{color:#c8adff;font-weight:800}.ni-primary h3{margin:5px 0}.ni-primary div{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}.ni-primary div span,.ni-tag{font-size:10px;padding:5px 8px;border-radius:999px;background:#2b2141}.ni-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.ni-box{padding:14px;border-radius:16px;background:#171220;border:1px solid #352a4a}.ni-box h3{margin:0 0 10px}.ni-row,.ni-prof{display:flex;align-items:center;gap:8px;border-bottom:1px solid #2c233b;padding:8px 0}.ni-row:last-child,.ni-prof:last-child{border-bottom:0}.ni-row>b{min-width:80px}.ni-row>small{margin-left:auto;color:#998bab}.ni-prof>div{flex:1}.ni-prof small{display:block;color:#897b9b}.ni-prof strong{min-width:42px;text-align:right}.ni-prof>span{font-size:10px;color:#cbbbec}.ni-foot{margin-top:12px;color:#9f92b1;font-size:11px}.ni-empty{color:#8d819e;padding:8px 0}@media(max-width:800px){.ni-grid{grid-template-columns:1fr}.ni-head{flex-direction:column}.ni-kpi{width:100%;box-sizing:border-box}}
    </style>
    """


def inject_negotiation_intelligence(page: str, state: Dict[str, Any]) -> str:
    block = css() + render_negotiation_intelligence(state)
    marker = "</main>"
    return page.replace(marker, block + marker, 1) if marker in page else page + block
