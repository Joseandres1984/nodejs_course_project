from __future__ import annotations

import html
from typing import Any, Dict

import control_tower as _ct

VERSION = "1.0-command-center-revenue-v2"
_ORIGINAL_BUILD = _ct.build_control_tower
_ORIGINAL_RENDER = _ct.render_control_tower


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def revenue_v2_build(state: Dict[str, Any], db_status: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = dict(_ORIGINAL_BUILD(state, db_status) or {})
    allocator = state.get("revenue_allocator", {}) or {}
    budget = state.get("adaptive_search_budget", {}) or {}
    factory = state.get("opportunity_factory", {}) or {}
    funnel = state.get("revenue_funnel", {}) or {}
    learning = state.get("commercial_learning_v2", {}) or {}
    quote = state.get("quote_accelerator", {}) or {}
    snapshot["revenue_v2"] = {
        "allocator": allocator,
        "budget": budget,
        "factory": factory,
        "funnel": funnel,
        "learning": learning,
        "quote": quote,
    }
    state["control_tower"] = snapshot
    return snapshot


def _funnel_html(counts: Dict[str, Any]) -> str:
    stages = [
        ("Leads", "research_leads"), ("Empresas verificadas", "verified_companies"),
        ("Contactos verificados", "verified_contacts"), ("Compradores con demanda", "buyers_with_demand"),
        ("Oportunidades", "market_opportunities"), ("RFQ listas", "rfq_ready"),
        ("Cotizaciones", "quotes"), ("Ofertas reales", "real_offers"),
        ("Propuestas", "proposals"), ("Close-ready", "close_ready"), ("Realizado", "realized_events"),
    ]
    return "".join(
        f'<div class="rv2-stage"><span>{_esc(label)}</span><strong>{_i(counts.get(key))}</strong></div>'
        for label, key in stages
    )


def revenue_v2_render(snapshot: Dict[str, Any]) -> str:
    page = _ORIGINAL_RENDER(snapshot)
    data = snapshot.get("revenue_v2", {}) or {}
    allocator = data.get("allocator", {}) or {}
    budget = data.get("budget", {}) or {}
    factory = data.get("factory", {}) or {}
    funnel = data.get("funnel", {}) or {}
    learning = data.get("learning", {}) or {}
    quote = data.get("quote", {}) or {}
    anti = learning.get("anti_drift", {}) or {}
    experiments = learning.get("experiments", {}) or {}
    ttr = learning.get("time_to_revenue", {}) or {}
    sources = learning.get("source_reputation", {}) or {}
    board = learning.get("review_board", {}) or {}
    two = learning.get("two_brain", {}) or {}
    counts = funnel.get("counts", {}) or {}
    bottleneck = funnel.get("bottleneck", {}) or {}

    css = """
<style id="lumen-rv2-css">
.rv2{margin-top:14px}.rv2-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.rv2-two{display:grid;grid-template-columns:1.35fr .65fr;gap:10px;margin-top:10px}.rv2-stage{display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid #17303e}.rv2-stage:last-child{border-bottom:0}.rv2-stage strong{color:var(--lime)}.rv2-kpi{font-size:23px;font-weight:850;margin-top:6px}.rv2-line{font-size:11px;color:var(--muted);margin-top:5px;line-height:1.45}.rv2-warn{color:var(--warn)}.rv2-good{color:var(--good)}.rv2-bad{color:var(--bad)}
@media(max-width:1050px){.rv2-grid{grid-template-columns:1fr 1fr}.rv2-two{grid-template-columns:1fr}}
@media(max-width:620px){.rv2-grid,.rv2-two{grid-template-columns:1fr!important}.rv2-kpi{font-size:20px}}
</style>
"""
    if "lumen-rv2-css" not in page:
        page = page.replace("</head>", css + "</head>", 1)

    role_plan = allocator.get("actual_role_plan", {}) or {}
    top_roles = sorted(role_plan.items(), key=lambda kv: _i(kv[1]), reverse=True)[:4]
    roles_text = " · ".join(f"{k}: {v}" for k, v in top_roles) or "esperando ciclo"
    exp = experiments.get("active") or experiments.get("latest") or {}
    execution_pct = ((two.get("execution_brain") or {}).get("attention_pct"))
    exploration_pct = ((two.get("exploration_brain") or {}).get("attention_pct"))

    section = f"""
<section class="rv2">
  <div class="learning-heading"><h2>Revenue Execution v2</h2><div class="small">ejecución → conversión → aprendizaje → reasignación</div></div>
  <div class="rv2-grid">
    <div class="card"><div class="label">Revenue Allocator</div><div class="rv2-kpi lime">{_esc(allocator.get('lane') or 'esperando ciclo')}</div><div class="rv2-line">{_esc(allocator.get('reason') or '')}</div><div class="rv2-line">{_esc(roles_text)}</div></div>
    <div class="card"><div class="label">Search Budget adaptativo</div><div class="rv2-kpi">{_i(budget.get('general_pool_daily'))} / {_i(budget.get('demand_reserved_daily'))}</div><div class="rv2-line">general / demanda · total {_i(budget.get('total_daily_cap'))} sin aumento automático</div><div class="rv2-line">{_esc(budget.get('reason') or '')}</div></div>
    <div class="card"><div class="label">Opportunity Factory</div><div class="rv2-kpi blue">{_i(factory.get('enrichment_required'))}</div><div class="rv2-line">casos por enriquecer · {_i(factory.get('ready_for_pipeline'))} listos · {_i(factory.get('opportunities_materialized'))} materializados último ciclo</div></div>
    <div class="card"><div class="label">Supplier / Quote Accelerator</div><div class="rv2-kpi">{_i(quote.get('quote_priority_cases'))}</div><div class="rv2-line">casos prioritarios de cotización · límite de mensajes existente preservado</div></div>
  </div>
  <div class="rv2-two">
    <div class="card"><h2>Embudo causal real</h2>{_funnel_html(counts)}<div class="rv2-line">Cuello actual: <strong>{_esc(bottleneck.get('lane') or '—')}</strong> · {_esc(bottleneck.get('reason') or '')}</div></div>
    <div class="card"><h2>Control de estrategia</h2>
      <div class="rv2-stage"><span>Anti-drift</span><strong class="{'rv2-warn' if anti.get('status') == 'triggered' else 'rv2-good'}">{_esc(anti.get('status') or 'waiting')}</strong></div>
      <div class="rv2-stage"><span>Experimento</span><strong>{_esc(exp.get('status') or '—')}</strong></div>
      <div class="rv2-stage"><span>Casos estancados</span><strong>{_i(ttr.get('stale_cases'))}</strong></div>
      <div class="rv2-stage"><span>Fuentes champion</span><strong>{_i(sources.get('champions'))}</strong></div>
      <div class="rv2-stage"><span>Review Board</span><strong>{_esc(board.get('status') or '—')}</strong></div>
      <div class="rv2-line">Execution {_esc(execution_pct if execution_pct is not None else '—')}% · Exploration {_esc(exploration_pct if exploration_pct is not None else '—')}%</div>
      <div class="rv2-line">Cambios vinculantes, gasto, contratos y despliegues siguen fuera de la autoridad autónoma.</div>
    </div>
  </div>
</section>
"""
    if "Revenue Execution v2" not in page:
        page = page.replace("</body>", section + "</body>", 1)
    return page


_ct.build_control_tower = revenue_v2_build
_ct.render_control_tower = revenue_v2_render
print({"command_center_revenue_v2_runtime": {"version": VERSION, "status": "active"}}, flush=True)
