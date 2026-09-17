from __future__ import annotations

import html
from typing import Any, Dict

# Register the public LUMEN landing page when the web application starts.
import landing_public  # noqa: F401


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _status(value: Any) -> str:
    return {
        "READY": "LISTO",
        "RAIL_SETUP_REQUIRED": "FALTA CONFIGURAR",
        "COUNTRY_REQUIRED": "FALTA PAÍS",
        "NO_RAIL_AVAILABLE": "SIN RIEL DISPONIBLE",
        "CURRENCY_MISMATCH": "MONEDA NO COINCIDE",
        "SUPPORTED_RAIL_NOT_VERIFIED": "SOPORTADA · RIEL SIN VERIFICAR",
        "SUPPORTED_NO_ENABLED_RAIL": "SOPORTADA · RIEL DESHABILITADO",
    }.get(str(value or ""), str(value or ""))


def _scope(value: Any) -> str:
    return {"domestic": "local", "international": "internacional", "international_eur": "internacional EUR"}.get(str(value or ""), str(value or ""))


def _currency_cards(state: Dict[str, Any], rails: list[Dict[str, Any]]) -> str:
    runtime = state.get("multicurrency_runtime", {}) or {}
    matrix = runtime.get("currency_matrix", {}) or {}
    if not matrix:
        for code in ("ARS", "USD", "EUR"):
            related = [x for x in rails if str(x.get("currency") or "").upper() == code and x.get("enabled")]
            verified = [x for x in related if x.get("verified")]
            primary = verified[0] if verified else (related[0] if related else {})
            matrix[code] = {
                "currency": code,
                "supported": True,
                "commercial_processing_active": True,
                "rail_enabled": bool(related),
                "rail_verified": bool(verified),
                "ready_to_collect": bool(verified),
                "status": "READY" if verified else "SUPPORTED_RAIL_NOT_VERIFIED",
                "primary_rail_label": primary.get("label"),
            }
    cards = []
    for code in ("ARS", "USD", "EUR"):
        row = matrix.get(code, {}) or {}
        ready = bool(row.get("ready_to_collect"))
        rail_enabled = bool(row.get("rail_enabled"))
        if ready:
            badge, cls = "LISTA PARA COBRAR", "ok"
        elif rail_enabled:
            badge, cls = "RIEL SIN VERIFICAR", "warn"
        else:
            badge, cls = "RIEL PENDIENTE", "warn"
        cards.append(
            f'<div class="pr-currency"><div><small>MONEDA SOPORTADA</small><b>{_esc(code)}</b></div>'
            f'<span class="pr-pill {cls}">{badge}</span>'
            f'<p>{_esc(row.get("primary_rail_label") or "sin riel seleccionado")}</p></div>'
        )
    return "".join(cards)


def render_payment_rails(state: Dict[str, Any]) -> str:
    report = state.get("payment_rails", {}) or {}
    rails = report.get("rails", []) or []
    routes = report.get("routes", []) or []
    multicurrency = state.get("multicurrency_runtime", {}) or {}
    if not report:
        return '<section class="pr-wrap"><div class="pr-eye">MEDIOS DE COBRO</div><h2>Ruteo multimoneda</h2><p>Esperando el primer ciclo.</p></section>'

    rail_rows = "".join(
        f'<div class="pr-row"><div><b>{_esc(x.get("label"))}</b><small>{_esc(_scope(x.get("scope")))} · {_esc(x.get("currency"))}</small></div>'
        f'<span class="pr-pill {"ok" if x.get("verified") else "warn"}">{"VERIFICADO" if x.get("verified") else "FALTA VERIFICAR"}</span>'
        f'<small>{"preparación automática" if x.get("auto_prepare") else "preparación manual"}</small></div>'
        for x in rails
    ) or '<div class="pr-empty">Sin rieles disponibles.</div>'

    route_rows = "".join(
        f'<div class="pr-row"><div><b>{_esc(x.get("deal_id"))}</b><small>{_esc(x.get("buyer_country") or "país pendiente")} · {_esc(x.get("currency_hint") or "moneda pendiente")}</small></div>'
        f'<span>{_esc(((x.get("selected_rail") or {}).get("label")) or "sin ruta")}</span>'
        f'<span class="pr-pill {"ok" if x.get("status")=="READY" else "warn"}">{_esc(_status(x.get("status")))}</span></div>'
        for x in routes[:10]
    ) or '<div class="pr-empty">Todavía no hay operaciones con ruta de cobro.</div>'

    ready_codes = ", ".join(multicurrency.get("ready_currencies", []) or []) or "ninguna todavía"
    setup_codes = ", ".join(multicurrency.get("setup_required_currencies", []) or []) or "ninguna"

    return f"""
    <section class="pr-wrap">
      <div class="pr-head">
        <div><div class="pr-eye">MULTIMONEDA · TESORERÍA</div><h2>ARS · USD · EUR de punta a punta</h2>
        <p>LUMEN conserva la moneda documentada y separa soporte técnico de disponibilidad real para cobrar. No inventa conversiones FX.</p></div>
        <div class="pr-kpis"><div><b>{_esc(report.get('ready_routes',0))}</b><small>rutas listas</small></div><div><b>{_esc(report.get('setup_required',0))}</b><small>rutas pendientes</small></div></div>
      </div>
      <div class="pr-currencies">{_currency_cards(state, rails)}</div>
      <div class="pr-grid">
        <div class="pr-box"><h3>Medios configurados</h3>{rail_rows}</div>
        <div class="pr-box"><h3>Ruta elegida por operación</h3>{route_rows}</div>
      </div>
      <div class="pr-foot"><b>Listas para cobrar:</b> {_esc(ready_codes)} · <b>requieren verificación/configuración:</b> {_esc(setup_codes)}.<br>
      ARS: Mercado Pago / Prex · USD: Payoneer / cuenta USD compatible · EUR: Prex vIBAN/SEPA. Compras, pagos, movimiento de fondos y términos vinculantes continúan bajo control humano.</div>
    </section>
    """


def css() -> str:
    return """
    <style>
    .pr-wrap{margin:14px 0;padding:20px;border:1px solid #264e5b;border-radius:20px;background:linear-gradient(135deg,#081418,#0d2026 60%,#0a171c);color:#e8fbff}.pr-eye{font-size:11px;letter-spacing:1.4px;color:#7fd8e8;font-weight:800}.pr-head{display:flex;justify-content:space-between;gap:16px}.pr-head h2{margin:5px 0 3px}.pr-head p{margin:0;color:#9cc1c8}.pr-kpis{display:flex;gap:8px}.pr-kpis>div{min-width:100px;padding:10px;border-radius:14px;background:#102a31;border:1px solid #28515d;text-align:center}.pr-kpis b{display:block;font-size:26px}.pr-kpis small{color:#94b8c0}.pr-currencies{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:14px}.pr-currency{padding:13px;border-radius:15px;background:#0b1c22;border:1px solid #28515d}.pr-currency>div{display:flex;justify-content:space-between;align-items:end;gap:8px}.pr-currency small{color:#789ca5;font-size:9px;letter-spacing:.08em}.pr-currency b{font-size:26px}.pr-currency p{margin:8px 0 0;color:#8eb0b7;font-size:11px}.pr-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}.pr-box{padding:14px;border-radius:16px;background:#0c1b20;border:1px solid #21424b}.pr-box h3{margin:0 0 8px}.pr-row{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid #18343c}.pr-row:last-child{border-bottom:0}.pr-row>div{flex:1}.pr-row small{display:block;color:#7f9fa6}.pr-pill{font-size:10px;padding:5px 8px;border-radius:999px;background:#28343a;white-space:nowrap}.pr-pill.ok{background:#173d35;color:#b7ffd9}.pr-pill.warn{background:#4a351a;color:#ffe1a4}.pr-foot{margin-top:12px;color:#8fadb4;font-size:11px;line-height:1.5}.pr-empty{color:#78959c;padding:8px 0}@media(max-width:800px){.pr-grid,.pr-currencies{grid-template-columns:1fr}.pr-head{flex-direction:column}.pr-kpis{width:100%}.pr-kpis>div{flex:1}}
    </style>
    """


def inject_payment_rails(page: str, state: Dict[str, Any]) -> str:
    block = css() + render_payment_rails(state)
    marker = "</main>"
    return page.replace(marker, block + marker, 1) if marker in page else page + block
