from __future__ import annotations

import html
from typing import Any, Dict

from fastapi import Request
from fastapi.responses import Response

from app import STATE, load_state
from outbound_web import app
import commercial_offer_engine_runtime as offer_engine
from intelligence_revenue_runtime import INTELLIGENCE_CATALOG


VERSION = "1.1-command-center-intelligence-offers"


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value: Any) -> str:
    return f"USD {_f(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    rt = dict(state.get("intelligence_revenue_runtime", {}) or {})
    pricing = dict(state.get("commercial_offer_engine", {}) or {})
    candidates = [x for x in state.get("intelligence_revenue_candidates", []) or [] if isinstance(x, dict)]
    cases = [x for x in state.get("intelligence_cases", []) or [] if isinstance(x, dict)]
    queue = [x for x in state.get("intelligence_work_queue", []) or [] if isinstance(x, dict)]
    pipeline = [
        x for x in state.get("service_sales_pipeline", []) or []
        if isinstance(x, dict) and x.get("intelligence_revenue")
    ]
    by_product: Dict[str, int] = {str(x["id"]): 0 for x in INTELLIGENCE_CATALOG}
    for row in candidates:
        sid = str(row.get("service_id") or "")
        if sid in by_product:
            by_product[sid] += 1
    priced_pipeline = [
        x for x in state.get("service_sales_pipeline", []) or []
        if isinstance(x, dict) and isinstance(x.get("recommended_offer"), dict)
    ]
    return {
        "status": rt.get("status") or "initializing",
        "products": len(INTELLIGENCE_CATALOG),
        "candidates": _i(rt.get("verified_product_fit_candidates"), len(candidates)),
        "cases": _i(rt.get("public_inquiries"), len(cases)),
        "attention": _i(rt.get("outbound_attention_active"), sum(1 for x in pipeline if x.get("proactive_attention_active"))),
        "attention_cap": _i(rt.get("outbound_attention_cap"), 6),
        "contacted": _i(rt.get("real_contacted"), sum(1 for x in pipeline if x.get("contact_truth") == "provider_accepted")),
        "replies": _i(rt.get("replies"), sum(1 for x in pipeline if x.get("contact_truth") == "replied")),
        "queue": _i(rt.get("work_queue"), len(queue)),
        "revenue": _f(rt.get("realized_intelligence_revenue_usd")),
        "searches": _i(rt.get("searches_used")),
        "paid_spend": bool(rt.get("paid_spend")),
        "by_product": by_product,
        "pricing_mode": pricing.get("pricing_mode") or offer_engine.PRICING_MODE,
        "pricebook_services": _i(pricing.get("active_pricebook_services"), len(offer_engine.PRICEBOOK)),
        "priced_pipeline": len(priced_pipeline),
        "offers_for_inquiries": _i(pricing.get("offers_recommended_for_inquiries")),
        "pricing_review_due": list(pricing.get("pricing_review_due_services", []) or []),
        "starting_prices": {sid: item.get("public_from_usd") for sid, item in offer_engine.PRICEBOOK.items()},
    }


def _css() -> str:
    return """
<style id="lumen-intelligence-cc-css">
.intel-section{margin:0 0 14px}.intel-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.intel-badge{display:inline-block;border:1px solid #73d8ff55;background:#73d8ff12;color:#73d8ff;border-radius:999px;padding:5px 9px;font-size:10px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}.intel-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin-top:14px}.intel-mini{background:#07151b;border:1px solid #23404b;border-radius:12px;padding:12px}.intel-list{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.intel-pill{border:1px solid #31505d;background:#102630;border-radius:999px;padding:6px 9px;font-size:11px;color:#c9d8df}.intel-price{border-color:#d7ff6466;color:#d7ff64;background:#d7ff640d}.intel-note{font-size:11px;color:var(--muted);margin-top:8px;line-height:1.45}.intel-button{display:inline-block;background:#73d8ff;color:#061117!important;border-radius:9px;padding:10px 14px;font-weight:900;text-decoration:none!important;white-space:nowrap}.intel-truth{margin-top:12px;border:1px solid #23404b;background:#07151b;border-radius:12px;padding:12px;font-size:11px;color:#aebfc6}
@media(max-width:1050px){.intel-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:700px){.intel-grid{grid-template-columns:1fr 1fr}.intel-head{flex-direction:column}}
</style>
"""


def _metric(label: str, value: Any, note: str = "", cls: str = "") -> str:
    return f'<div><div class="label">{_esc(label)}</div><div class="metric {cls}">{_esc(value)}</div>' + (f'<div class="intel-note">{_esc(note)}</div>' if note else "") + '</div>'


def _section(data: Dict[str, Any]) -> str:
    product_pills = []
    counts = data.get("by_product", {}) or {}
    for item in INTELLIGENCE_CATALOG:
        product_pills.append(f'<span class="intel-pill">{_esc(item["name"])} · {_i(counts.get(item["id"]))} candidatos</span>')
    price_pills = []
    for sid, item in offer_engine.PRICEBOOK.items():
        price_pills.append(f'<span class="intel-pill intel-price">{_esc(item.get("name"))} · desde USD {_i(item.get("public_from_usd"))}</span>')
    metrics = "".join([
        _metric("Productos Intelligence", data.get("products"), "activos"),
        _metric("Servicios con precio", data.get("pricebook_services"), "pricebook de lanzamiento", "lime"),
        _metric("Candidatos", data.get("candidates"), "empresa + contacto verificados", "lime"),
        _metric("Atención outbound", f"{_i(data.get('attention'))}/{_i(data.get('attention_cap'))}", "dentro del límite actual"),
        _metric("Casos inbound", data.get("cases"), "consulta real recibida", "good"),
        _metric("CRM con oferta", data.get("priced_pipeline"), "paquete recomendado no vinculante"),
        _metric("Ofertas inbound", data.get("offers_for_inquiries"), "recomendación automática"),
        _metric("Contactados reales", data.get("contacted"), "aceptación del proveedor"),
        _metric("Respuestas", data.get("replies"), "respuesta verificada"),
        _metric("Búsquedas pagas", data.get("searches"), "sin gasto nuevo"),
        _metric("Gasto nuevo", "USD 0" if not data.get("paid_spend") else "REVISAR", "motor sin presupuesto pago"),
        _metric("Ingreso realizado", _money(data.get("revenue")), "sólo pagos reales", "good" if _f(data.get("revenue")) > 0 else ""),
    ])
    review_note = "Ninguno" if not data.get("pricing_review_due") else ", ".join(data.get("pricing_review_due") or [])
    return f"""
<section class="intel-section" id="lumen-intelligence-revenue-card">
  <div class="card">
    <div class="intel-head">
      <div><span class="intel-badge">Monetización + pricing</span><h2 style="margin:7px 0 3px">LUMEN Intelligence · Revenue & Offer Engine</h2><div class="intel-note">QuoteCheck + SupplierCheck + Sourcing + Prospección + Export Scout + Tender Hunter. El motor selecciona paquete por complejidad; precio final y términos siguen bajo aprobación humana.</div></div>
      <a class="intel-button" href="/services">Ver ofertas</a>
    </div>
    <div class="intel-grid">{metrics}</div>
    <div class="intel-list">{''.join(price_pills)}</div>
    <div class="intel-list">{''.join(product_pills)}</div>
    <div class="intel-truth"><strong>Pricing mode:</strong> {_esc(data.get('pricing_mode'))}. <strong>Revisión de precios pendiente:</strong> {_esc(review_note)}. Regla comercial: bajar alcance antes de bajar precio; LUMEN no aplica descuentos autónomos. Candidato ≠ contacto, contacto ≠ respuesta y oportunidad ≠ ingreso. Contrato, pago, precio final y compromiso vinculante requieren decisión humana.</div>
  </div>
</section>
"""


def inject_intelligence(page: str, state: Dict[str, Any]) -> str:
    if "lumen-intelligence-cc-css" not in page:
        page = page.replace("</head>", _css() + "</head>", 1)
    if "lumen-intelligence-revenue-card" not in page:
        section = _section(_snapshot(state))
        marker = '<section class="svc-section" id="lumen-services-revenue-card">'
        if marker in page:
            page = page.replace(marker, section + marker, 1)
        else:
            fallback = '<div class="grid hero">'
            page = page.replace(fallback, section + fallback, 1) if fallback in page else page.replace("</body>", section + "</body>", 1)
    return page


@app.middleware("http")
async def command_center_intelligence_injector(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/command-center" or "text/html" not in str(response.headers.get("content-type") or ""):
        return response
    try:
        load_state()
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = inject_intelligence(body.decode("utf-8", errors="replace"), STATE)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        print({
            "command_center_intelligence": {
                "version": VERSION,
                "status": "applied",
                "visible": "lumen-intelligence-revenue-card" in text,
                "offer_engine": offer_engine.VERSION,
                "paid_spend": False,
            }
        }, flush=True)
        return Response(content=text, status_code=response.status_code, headers=headers, media_type="text/html")
    except Exception as exc:
        print({"command_center_intelligence": {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}}, flush=True)
        return response


print({
    "command_center_intelligence_runtime": {
        "version": VERSION,
        "status": "active",
        "route": "/command-center",
        "intelligence_route": "/intelligence",
        "products": len(INTELLIGENCE_CATALOG),
        "pricebook_services": len(offer_engine.PRICEBOOK),
        "offer_engine": offer_engine.VERSION,
        "paid_spend": False,
    }
}, flush=True)
