from __future__ import annotations

import html
from typing import Any, Dict

LABELS = {
    "RECOVER_OPERATIONS": "RECUPERAR OPERACIÓN",
    "PROTECT_EXISTING_VALUE": "PROTEGER VALOR EXISTENTE",
    "COLLECT_REALIZED_VALUE": "COBRAR VALOR YA GANADO",
    "CLOSE_READY_VALUE": "CERRAR VALOR LISTO",
    "ACCELERATE_BEST_DEALS": "ACELERAR MEJORES NEGOCIOS",
    "DEFEND_MARGIN": "DEFENDER MARGEN",
    "BUILD_REVENUE_ENGINE": "CONSTRUIR MOTOR DE INGRESOS",
    "BUILD_EVIDENCE_AND_PIPELINE": "CONSTRUIR EVIDENCIA Y PIPELINE",
    "COLLECT_CASH": "COBRAR COMISIÓN",
    "REQUEST_CLOSE_APPROVAL": "PEDIR APROBACIÓN DE CIERRE",
    "COMPLETE_CLOSE_PACK": "COMPLETAR PAQUETE DE CIERRE",
    "REPAIR_CLOSE_RISK": "REPARAR RIESGO DE CIERRE",
    "ACCELERATE_DEAL": "ACELERAR NEGOCIO",
    "IMPROVE_MARGIN": "MEJORAR MARGEN",
    "IMPROVE_CONVERSION": "MEJORAR CONVERSIÓN",
    "REPAIR_TERMS": "CORREGIR TÉRMINOS",
    "COMPLETE_ECONOMICS": "COMPLETAR ECONOMÍA",
    "REPAIR_OR_PARK_RISK": "REPARAR O PAUSAR POR RIESGO",
    "PARK_DEAL": "ARCHIVAR NEGOCIO",
    "BUILD_PIPELINE": "CONSTRUIR PIPELINE",
    "VALIDATE_VENTURE": "VALIDAR NUEVA LÍNEA",
    "PURSUE_NOW": "HACER AHORA",
    "NEXT": "SIGUIENTE",
    "HOLD": "PAUSAR",
    "PARK": "ARCHIVAR",
    "documented_receivable": "cuenta por cobrar documentada",
    "risk_adjusted_expected_profit": "beneficio esperado ajustado por riesgo",
    "known_company_profit": "beneficio conocido",
    "venture_realized_profit_history": "beneficio histórico de la venture",
    "unknown_not_invented": "valor futuro no estimado",
    "profit_gap_context_not_expected_value": "contexto de brecha; no valor esperado",
    "CURRENT": "ACTUAL",
    "PARTIAL": "PARCIAL",
    "STALE": "VENCIDO",
    "CRITICAL_REFRESH": "REFRESCO CRÍTICO",
    "CALIBRATED": "CALIBRADO",
    "OVERCONFIDENT": "SOBRECONFIADO",
    "SLIGHTLY_OVERCONFIDENT": "ALGO SOBRECONFIADO",
    "UNDERCONFIDENT": "SUBCONFIADO",
    "INSUFFICIENT_SAMPLE": "MUESTRA INSUFICIENTE",
}


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _label(value: Any) -> str:
    raw = str(value or "")
    return LABELS.get(raw, raw.replace("_", " ").lower() if raw else "")


def _money(value: Any) -> str:
    if value in (None, ""):
        return "—"
    try:
        return f"USD {float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _pct(value: Any) -> str:
    try:
        return f"{float(value)*100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def render_goal_portfolio(state: Dict[str, Any]) -> str:
    goal = state.get("autonomous_goal_planner", {}) or {}
    portfolio = state.get("portfolio_optimizer", {}) or {}
    truth = state.get("data_truth_engine", {}) or {}
    calibration = state.get("decision_calibration", {}) or {}
    improvement = state.get("self_improvement_lab", {}) or {}
    active = goal.get("active_goal", {}) or {}
    signals = goal.get("signals", {}) or {}
    target = goal.get("target", {}) or {}
    selected = portfolio.get("selected_actions", []) or []
    primary = portfolio.get("primary_action", {}) or {}
    primary_improvement = improvement.get("primary_proposal", {}) or {}

    rows = "".join(
        f'<div class="pg-row"><div class="pg-rank">#{_esc(x.get("rank"))}</div><div class="pg-main"><b>{_esc(x.get("title"))}</b>'
        f'<small>{_esc(_label(x.get("kind")))} · {_esc(_label(x.get("portfolio_decision")))}</small></div>'
        f'<div class="pg-money">{_money(x.get("economic_value_usd"))}<small>{_esc(_label(x.get("value_type")))}</small></div>'
        f'<div class="pg-score">{_esc(x.get("portfolio_priority_score"))}<small>prioridad</small></div></div>'
        for x in selected[:8]
    ) or '<div class="pg-empty">Todavía no hay acciones económicas comparables.</div>'

    milestones = "".join(
        f'<span class="pg-chip">{_esc(_label(x.get("code")))}: {_esc(x.get("current_gap") if x.get("current_gap") is not None else x.get("current"))}</span>'
        for x in (goal.get("milestones", []) or [])[:8]
    ) or '<span class="pg-chip">Sin hitos pendientes</span>'

    engine_rows = "".join(
        f'<div class="qa-row"><b>{_esc(x.get("engine"))}</b><span>{_esc(_label(x.get("status")))}</span><span>conf. {_pct(x.get("average_confidence"))} / éxito {_pct(x.get("observed_success_rate"))}</span></div>'
        for x in (calibration.get("engine_profiles", []) or [])[:6]
    ) or '<div class="pg-empty">Todavía no hay muestra suficiente para calibrar motores.</div>'

    improvement_rows = "".join(
        f'<div class="qa-row"><b>{_esc(x.get("title"))}</b><span>{"PRUEBA AUTÓNOMA" if x.get("autonomous_test_allowed") else "PROPUESTA CONTROLADA"}</span><span>prioridad {_esc(x.get("priority_score"))}</span></div>'
        for x in (improvement.get("proposals", []) or [])[:5]
    ) or '<div class="pg-empty">Sin propuestas de mejora todavía.</div>'

    return f"""
    <section class="pg-wrap">
      <div class="pg-head">
        <div><div class="pg-eye">CEREBRO ECONÓMICO SUPERIOR</div><h2>Meta Autónoma + Optimizador de Cartera</h2>
        <p>LUMEN compara caja, cierres, margen, riesgo, pipeline y nuevas líneas para decidir dónde vale más la pena usar su capacidad.</p></div>
        <div class="pg-status"><b>{_esc(_label(active.get('code') or 'SIN META'))}</b><small>{_esc(active.get('reason') or '')}</small></div>
      </div>
      <div class="pg-kpis">
        <div><small>Objetivo</small><b>{_money(target.get('amount_usd'))}</b></div>
        <div><small>Beneficio cobrado</small><b>{_money(signals.get('realized_cash_profit_usd'))}</b></div>
        <div><small>Brecha</small><b>{_money(signals.get('profit_gap_usd'))}</b></div>
        <div><small>Por cobrar</small><b>{_money(signals.get('overdue_or_partial_commissions_usd'))}</b></div>
        <div><small>Cierres listos</small><b>{_esc(signals.get('close_packs_ready',0))}</b></div>
      </div>
      <div class="pg-grid">
        <div class="pg-box"><h3>Orden económica actual</h3>
          <div class="pg-primary"><b>{_esc(primary.get('title') or 'Sin prioridad todavía')}</b><small>{_esc(primary.get('reason') or '')}</small>
          <div><span>{_esc(_label(primary.get('kind') or ''))}</span><strong>{_esc(primary.get('portfolio_priority_score') or '—')}/100</strong></div></div>
          <div class="pg-milestones">{milestones}</div>
        </div>
        <div class="pg-box"><h3>Cartera priorizada</h3>{rows}</div>
      </div>
      <div class="qa-wrap">
        <div class="qa-head"><div><div class="pg-eye">CALIDAD DE AUTONOMÍA</div><h3>Verdad · Calibración · Auto‑Mejora</h3></div>
          <div class="qa-score"><small>VERDAD PROMEDIO</small><b>{_esc(truth.get('average_truth_score','—'))}</b><span>/100</span></div>
        </div>
        <div class="qa-kpis">
          <div><small>Refrescos críticos</small><b>{_esc(truth.get('critical_refresh',0))}</b></div>
          <div><small>Datos parciales/vencidos</small><b>{_esc(truth.get('stale_or_partial',0))}</b></div>
          <div><small>Decisiones calibradas</small><b>{_esc(calibration.get('resolved_decisions',0))}</b></div>
          <div><small>Brier global</small><b>{_esc(calibration.get('overall_brier_score') if calibration.get('overall_brier_score') is not None else '—')}</b></div>
          <div><small>Mejoras propuestas</small><b>{_esc(len(improvement.get('proposals',[]) or []))}</b></div>
        </div>
        <div class="pg-grid">
          <div class="pg-box"><h3>Calibración por motor</h3>{engine_rows}</div>
          <div class="pg-box"><h3>Laboratorio de Auto‑Mejora</h3>
            <div class="pg-primary"><b>{_esc(primary_improvement.get('title') or 'Seguir aprendiendo')}</b><small>{_esc(primary_improvement.get('reason') or 'Esperando evidencia suficiente.')}</small>
            <div><span>{_esc(primary_improvement.get('area') or 'aprendizaje')}</span><strong>{_esc(primary_improvement.get('priority_score') or '—')}</strong></div></div>
            <div class="qa-list">{improvement_rows}</div>
          </div>
        </div>
        <div class="pg-foot">LUMEN puede diagnosticar y ejecutar pruebas reversibles de baja autoridad. Los cambios de código pueden proponerse y prepararse, pero nunca se auto‑despliegan a producción.</div>
      </div>
      <div class="pg-foot">El puntaje de cartera es un ranking heurístico de costo de oportunidad; no es una probabilidad de éxito ni un ROI garantizado. La Constitución, Cierre Seguro, Auditor Interno y las aprobaciones vinculantes siguen teniendo prioridad.</div>
    </section>
    """


def css() -> str:
    return """
    <style>
    .pg-wrap{margin:14px 0;padding:20px;border:1px solid #41512b;border-radius:20px;background:linear-gradient(135deg,#11170b,#1b2410 62%,#11160d);color:#f0f7df}.pg-eye{font-size:11px;letter-spacing:1.5px;color:#bdd77d;font-weight:800}.pg-head,.qa-head{display:flex;justify-content:space-between;gap:16px}.pg-head h2{margin:5px 0 4px}.pg-head p{margin:0;color:#aebd8f}.pg-status{max-width:390px;padding:12px 14px;background:#202b14;border:1px solid #465a2a;border-radius:15px}.pg-status b,.pg-status small{display:block}.pg-status small{margin-top:5px;color:#a8b98a}.pg-kpis,.qa-kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:14px 0}.pg-kpis>div,.qa-kpis>div{padding:11px;border-radius:14px;background:#1b2413;border:1px solid #394923}.pg-kpis small,.qa-kpis small,.pg-money small,.pg-score small,.pg-main small{display:block;color:#91a375}.pg-kpis b,.qa-kpis b{display:block;margin-top:4px;font-size:18px}.pg-grid{display:grid;grid-template-columns:.8fr 1.2fr;gap:12px}.pg-box{padding:14px;border-radius:16px;background:#171e11;border:1px solid #34431f}.pg-box h3{margin:0 0 9px}.pg-primary{padding:12px;border-radius:13px;background:#202a16}.pg-primary small{display:block;color:#9aaa7f;margin-top:5px}.pg-primary div{display:flex;justify-content:space-between;margin-top:10px}.pg-primary span{color:#c0d48e}.pg-primary strong{font-size:20px}.pg-row{display:grid;grid-template-columns:34px 1fr 145px 62px;gap:8px;align-items:center;padding:9px 0;border-bottom:1px solid #2a371c}.pg-row:last-child{border-bottom:0}.pg-rank{font-weight:800;color:#b8cf7d}.pg-money{text-align:right}.pg-score{text-align:right;font-weight:800}.pg-milestones{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}.pg-chip{font-size:10px;padding:5px 8px;border-radius:999px;background:#27331a;color:#b8c993}.pg-foot{margin-top:12px;color:#889b6d;font-size:11px}.pg-empty{color:#899974;padding:8px 0}.qa-wrap{margin-top:16px;padding-top:16px;border-top:1px solid #34431f}.qa-head h3{margin:4px 0}.qa-score{min-width:120px;text-align:center;padding:10px;border-radius:14px;background:#202b14;border:1px solid #465a2a}.qa-score small{display:block;color:#91a375;font-size:9px}.qa-score b{font-size:30px}.qa-score span{color:#84956d}.qa-row{display:grid;grid-template-columns:1.2fr .65fr 1fr;gap:8px;padding:8px 0;border-bottom:1px solid #2a371c;align-items:center}.qa-row:last-child{border-bottom:0}.qa-row span{font-size:10px;color:#9eaf83}.qa-list{margin-top:8px}@media(max-width:850px){.pg-head,.qa-head{flex-direction:column}.pg-kpis,.qa-kpis{grid-template-columns:1fr 1fr}.pg-grid{grid-template-columns:1fr}.pg-row,.qa-row{grid-template-columns:28px 1fr}.qa-row{grid-template-columns:1fr}.pg-money,.pg-score{text-align:left}}
    </style>
    """


def inject_goal_portfolio(page: str, state: Dict[str, Any]) -> str:
    block = css() + render_goal_portfolio(state)
    marker = "</main>"
    return page.replace(marker, block + marker, 1) if marker in page else page + block
