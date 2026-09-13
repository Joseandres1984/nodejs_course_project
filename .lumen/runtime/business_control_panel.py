from __future__ import annotations

import html
from typing import Any, Dict, Iterable

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


def _currency(row: Dict[str, Any]) -> str:
    for value in (
        row.get("currency"), row.get("commission_currency"), row.get("fee_currency"),
        (row.get("economics") or {}).get("currency"),
        (row.get("classification") or {}).get("currency"),
        (row.get("facts") or {}).get("currency"),
    ):
        text = str(value or "").strip().upper()
        if text in {"ARS", "USD", "EUR"}:
            return text
    return ""


def _first_amount(row: Dict[str, Any], keys: Iterable[str]) -> float:
    for key in keys:
        if row.get(key) not in (None, ""):
            return max(0.0, _f(row.get(key)))
    return 0.0


def _sum_native_ars(rows: Iterable[Dict[str, Any]], keys: Iterable[str], *, realized_only: bool = False) -> float:
    total = 0.0
    for row in rows or []:
        if _currency(row) != "ARS":
            continue
        if realized_only and str(row.get("status") or "").lower() not in {
            "realized", "realized_partial", "received", "paid", "settled", "completed"
        }:
            continue
        total += _first_amount(row, keys)
    return round(total, 2)


def _ars(value: Any) -> str:
    amount = _f(value)
    whole = f"{amount:,.0f}".replace(",", ".")
    return f"$ {whole} ARS"


def _native_ars_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    # Never relabel USD as ARS and never invent an FX conversion. These are only amounts whose
    # source data explicitly declares ARS.
    offers = list(state.get("offers", []) or [])
    transactions = list(state.get("transactions", []) or [])
    ledger = list(state.get("revenue_ledger", []) or [])
    documents = list(state.get("document_registry", []) or [])

    quoted = _sum_native_ars(offers, ("amount", "total", "price", "quoted_amount"))
    transacted = _sum_native_ars(
        transactions,
        ("amount", "transaction_value", "gross_amount", "sale_amount", "total"),
    )
    realized = _sum_native_ars(
        ledger,
        ("amount", "received_amount", "commission_amount"),
        realized_only=True,
    )
    documented = 0.0
    for doc in documents:
        facts = doc.get("facts") or {}
        if str(facts.get("currency") or "").strip().upper() != "ARS":
            continue
        documented += _first_amount(facts, ("amount", "total", "price"))

    return {
        "currency": "ARS",
        "quoted": quoted,
        "transacted": transacted,
        "realized": realized,
        "documented": round(documented, 2),
        "source_rule": "solo importes nativos ARS; sin conversión automática desde USD/EUR",
    }


def render_currency_strip(state: Dict[str, Any]) -> str:
    ars = _native_ars_summary(state)
    return f"""
    <section class="ars-strip">
      <div class="ars-main"><small>MONEDA OPERATIVA · ARGENTINA</small><b>ARS · PESOS ARGENTINOS</b><span>Los USD quedan como referencia normalizada cuando el motor económico todavía trabaja en dólares.</span></div>
      <div><small>COTIZACIONES ARS</small><b>{_ars(ars['quoted'])}</b></div>
      <div><small>OPERACIONES ARS</small><b>{_ars(ars['transacted'])}</b></div>
      <div><small>INGRESOS REALIZADOS ARS</small><b>{_ars(ars['realized'])}</b></div>
      <div class="ars-rule"><small>REGLA</small><b>Sin FX inventado</b><span>{_esc(ars['source_rule'])}</span></div>
    </section>
    """


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
        f'<div class="bc-row"><b>{_esc(x.get("deal_id"))}</b><span class="bc-tag {_esc(x.get("capital_action"))}">{_esc(x.get("capital_action"))}</span><span>Cap {_f(x.get("capital_priority_score")):.0f} · RA USD ref. {_f(x.get("risk_adjusted_expected_profit_usd")):,.0f} · margen {_f(x.get("margin_pct")):.1f}% / {_f(x.get("defended_target_margin_pct")):.1f}%</span></div>'
        for x in rows[:8]
    ) or '<div class="bc-empty">Sin deals con economía suficiente.</div>'

    cats_html = "".join(
        f'<div class="bc-row"><b>{_esc(x.get("category"))}</b><span>RA USD ref. {_f(x.get("risk_adjusted_expected_profit_usd")):,.0f}</span><span>efic. {_f(x.get("modeled_capital_efficiency"))*100:.1f}%</span></div>'
        for x in categories[:6]
    ) or '<div class="bc-empty">Sin categorías económicas todavía.</div>'

    return f"""
    <section class="bc-wrap">
      <div class="bc-head">
        <div><div class="bc-eye">BUSINESS CONTROLLER · CAPITAL & MARGIN INTELLIGENCE</div><h2>Control económico autónomo</h2><p>ARS es la moneda operativa visible en Argentina. Las métricas USD de esta sección son referencias normalizadas y no se convierten a pesos sin una fuente de FX verificada.</p></div>
        <div class="bc-score"><small>CONTROL SCORE</small><b>{_f(controller.get('company_control_score')):.0f}</b><span>/100</span></div>
      </div>
      <div class="bc-grid four">
        <div><small>MODO</small><strong>{_esc(controller.get('control_mode') or '—')}</strong></div>
        <div><small>ACELERAR</small><strong>{_esc(summary.get('accelerate',0))}</strong></div>
        <div><small>MEJORAR MARGEN</small><strong>{_esc(summary.get('improve_margin',0))}</strong></div>
        <div><small>HOLD RIESGO</small><strong>{_esc(summary.get('hold_risk',0))}</strong></div>
      </div>
      <div class="bc-priority"><small>ORDEN DEL CONTROLLER</small><h3>{_esc(controller.get('control_mode') or 'Sin intervención')}</h3><p>{_esc(controller.get('reason'))}</p><div><span>Δ RA profit USD ref. {_f(signals.get('risk_profit_delta')):,.0f}</span><span>Δ Safe {_f(signals.get('safe_close_delta')):.1f}</span><span>{'ACTIVIDAD SIN VALOR' if signals.get('activity_without_value') else 'actividad controlada'}</span></div></div>
      <div class="bc-priority"><small>PRIORIDAD DE CAPITAL</small><h3>{_esc(primary.get('deal_id') or 'Sin deal económico')}</h3><p>{_esc(primary.get('reason'))}</p><div><span>{_esc(primary.get('action'))}</span><span>Capital score {_f(primary.get('capital_priority_score')):.0f}</span><span>margen objetivo {_f(primary.get('defended_target_margin_pct')):.1f}%</span></div></div>
      <div class="bc-grid two"><div class="bc-box"><h3>Deals por oportunidad económica</h3>{deals_html}</div><div class="bc-box"><h3>Categorías por retorno</h3>{cats_html}</div></div>
      <div class="bc-foot">Intervención: <b>{_esc(intervention.get('id') or 'ninguna')}</b> · hold hasta ciclo {_esc(intervention.get('hold_until_cycle') or '—')} · overlay {'APLICADO' if (controller.get('intervention_overlay') or {}).get('applied') else 'sin cambio'}. No autoriza capital, pagos, órdenes ni contratos.</div>
    </section>
    """


def css() -> str:
    return """
    <style>
    .ars-strip{margin:0 0 12px;padding:13px 14px;border:1px solid #2e6650;border-radius:17px;background:linear-gradient(135deg,#071b15,#10251d 55%,#07161a);display:grid;grid-template-columns:1.4fr repeat(4,minmax(0,1fr));gap:9px;align-items:stretch;color:#edf9f2}.ars-strip>div{padding:9px 10px;border:1px solid #244c3d;border-radius:12px;background:#091a15}.ars-strip small{display:block;font-size:9px;letter-spacing:.1em;color:#7eb99e}.ars-strip b{display:block;margin-top:4px;font-size:16px;color:#d7ff64}.ars-strip span{display:block;margin-top:4px;color:#88aa9a;font-size:9px;line-height:1.35}.ars-main b{font-size:20px}.ars-rule b{color:#9cdcc0}
    .bc-wrap{margin:14px 0;padding:20px;border:1px solid #4b3c24;border-radius:20px;background:linear-gradient(135deg,#171209,#21180b 55%,#141008);color:#fff5dc}.bc-head{display:flex;justify-content:space-between;gap:14px}.bc-eye{font-size:11px;letter-spacing:1.4px;color:#efc46f;font-weight:800}.bc-head h2{margin:5px 0 3px}.bc-head p,.bc-priority p{color:#cbbd9f;margin:0}.bc-score{min-width:115px;text-align:center;padding:12px;border-radius:15px;background:#2a1e0d;border:1px solid #6c5122}.bc-score small{display:block;color:#c9a96c;font-size:9px}.bc-score b{font-size:34px}.bc-score span{color:#9c8967}.bc-grid{display:grid;gap:10px;margin-top:12px}.bc-grid.four{grid-template-columns:repeat(4,minmax(0,1fr))}.bc-grid.two{grid-template-columns:repeat(2,minmax(0,1fr))}.bc-grid.four>div,.bc-box{padding:12px;border-radius:14px;background:#21180c;border:1px solid #49381d}.bc-grid small{display:block;color:#aa936c;font-size:9px}.bc-grid strong{display:block;margin-top:4px;font-size:17px}.bc-priority{margin-top:12px;padding:14px;border-radius:15px;background:#261b0d;border:1px solid #60471d}.bc-priority small{color:#efc46f;font-weight:800}.bc-priority h3{margin:4px 0}.bc-priority div{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px}.bc-priority div span,.bc-tag{font-size:10px;padding:4px 7px;border-radius:999px;background:#3a2a13}.bc-box h3{margin:0 0 8px;font-size:14px}.bc-row{display:flex;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid #3a2a16}.bc-row:last-child{border-bottom:0}.bc-row>b{min-width:88px}.bc-row>span:last-child{margin-left:auto;color:#bba98a;font-size:10px}.bc-tag.ACCELERATE{background:#173d29;color:#a6f1c4}.bc-tag.IMPROVE_MARGIN,.bc-tag.IMPROVE_CONVERSION,.bc-tag.REPAIR_TERMS{background:#4a3915;color:#ffe09a}.bc-tag.HOLD_RISK,.bc-tag.DEPRIORITIZE{background:#4a2323;color:#ffb0b0}.bc-foot{margin-top:12px;color:#aa9878;font-size:10px}.bc-empty{color:#a99270}.bc-wrap h3{color:#fff5dc}@media(max-width:1000px){.ars-strip{grid-template-columns:1fr 1fr}.ars-main{grid-column:1/-1}}@media(max-width:800px){.bc-grid.four,.bc-grid.two{grid-template-columns:1fr}.bc-head{flex-direction:column}.bc-score{width:100%;box-sizing:border-box}.bc-row{align-items:flex-start;flex-wrap:wrap}.bc-row>span:last-child{margin-left:0;width:100%}}@media(max-width:560px){.ars-strip{grid-template-columns:1fr}.ars-main{grid-column:auto}}
    </style>
    """


def inject_business_control(page: str, state: Dict[str, Any]) -> str:
    styles = css()
    currency_strip = render_currency_strip(state)
    # Put ARS at the top of the command center so the operating currency is visible immediately.
    if '<div class="wrap">' in page:
        page = page.replace('<div class="wrap">', '<div class="wrap">' + currency_strip, 1)
    elif "<body>" in page:
        page = page.replace("<body>", "<body>" + currency_strip, 1)

    block = (
        go_live_css() + render_go_live(state)
        + closer_css() + render_closer(state)
        + goal_portfolio_css() + render_goal_portfolio(state)
        + styles + render_business_control(state)
    )
    marker = "</main>"
    if marker in page:
        return page.replace(marker, block + marker, 1)
    return page + block
