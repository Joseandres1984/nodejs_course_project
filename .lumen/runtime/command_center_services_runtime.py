from __future__ import annotations

"""Surface LUMEN's parallel paid-services revenue lane in the owner Command Center.

This is a read-only presentation layer. It never creates offers, prices, contracts,
payments or outbound actions. Commission revenue and service revenue stay separate.
"""

import html
from typing import Any, Dict

from fastapi import Request
from fastapi.responses import Response

from app import STATE, load_state
from outbound_web import app
from service_revenue_runtime import SERVICE_CATALOG, SERVICE_LANE_SHARE_CAP

VERSION = "1.0-command-center-services"


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


def _snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    runtime = dict(state.get("service_revenue_runtime", {}) or {})
    inquiries = dict(runtime.get("service_inquiries", {}) or {})
    if not inquiries:
        rows = [x for x in state.get("service_inquiries", []) or [] if isinstance(x, dict)]
        inquiries = {
            "total": len(rows),
            "new": sum(1 for x in rows if str(x.get("status") or "") in {"new", "new_unverified"}),
            "qualified": sum(1 for x in rows if str(x.get("status") or "") == "qualified"),
            "converted": sum(1 for x in rows if str(x.get("status") or "") in {"won", "contracted", "paid"}),
        }

    catalog = state.get("service_catalog", []) or SERVICE_CATALOG
    active = [x for x in catalog if isinstance(x, dict) and str(x.get("status") or "") == "active"]
    opportunities = [
        x for x in state.get("service_revenue_opportunities", []) or []
        if isinstance(x, dict) and str(x.get("status") or "") == "prepared_not_sent"
    ]

    service_realized = _f(runtime.get("realized_service_revenue_usd"))
    if service_realized <= 0:
        for row in state.get("service_revenue_transactions", []) or []:
            if not isinstance(row, dict) or str(row.get("status") or "").lower() not in {"paid", "settled", "completed"}:
                continue
            service_realized += max(0.0, _f(row.get("amount_received_usd") or row.get("revenue_usd")))

    finance = dict((state.get("business_kpis", {}) or {}).get("finance", {}) or {})
    commission_realized = _f(finance.get("realized_profit_usd"))

    return {
        "status": runtime.get("status") or "active",
        "active_services": active,
        "active_count": len(active),
        "prepared": _i(runtime.get("prepared_service_opportunities"), len(opportunities)),
        "inquiries_total": _i(inquiries.get("total")),
        "inquiries_new": _i(inquiries.get("new")),
        "inquiries_qualified": _i(inquiries.get("qualified")),
        "inquiries_converted": _i(inquiries.get("converted")),
        "service_realized_usd": round(service_realized, 2),
        "commission_realized_usd": round(max(0.0, commission_realized), 2),
        "share_cap_pct": round(_f(runtime.get("service_lane_share_cap"), SERVICE_LANE_SHARE_CAP) * 100),
        "commission_preserved": runtime.get("commission_business_preserved") is not False,
    }


def _css() -> str:
    return """
<style id="lumen-services-cc-css">
.svc-section{margin:0 0 14px}.svc-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.svc-badge{display:inline-block;border:1px solid #d7ff6455;background:#d7ff6412;color:#d7ff64;border-radius:999px;padding:5px 9px;font-size:10px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}.svc-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:14px}.svc-revenue{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}.svc-mini{background:#07151b;border:1px solid #23404b;border-radius:12px;padding:12px}.svc-name{font-weight:850;color:#e8f0f4}.svc-list{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.svc-pill{border:1px solid #31505d;background:#102630;border-radius:999px;padding:6px 9px;font-size:11px;color:#c9d8df}.svc-note{font-size:11px;color:var(--muted);margin-top:10px;line-height:1.5}.svc-button{display:inline-block;background:#d7ff64;color:#071018!important;border-radius:9px;padding:10px 14px;font-weight:900;text-decoration:none!important;white-space:nowrap}.svc-zero{color:#9fb2bb}.svc-good{color:var(--good)}
@media(max-width:900px){.svc-grid{grid-template-columns:1fr 1fr}.svc-head{flex-direction:column}.svc-revenue{grid-template-columns:1fr 1fr}}
@media(max-width:620px){.svc-grid,.svc-revenue{grid-template-columns:1fr 1fr}}
</style>
"""


def _money(value: float) -> str:
    return f"USD {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _section(data: Dict[str, Any]) -> str:
    names = "".join(
        f'<span class="svc-pill">{_esc(x.get("name") or x.get("id") or "Servicio")}</span>'
        for x in data.get("active_services", [])
    ) or '<span class="svc-pill">Sin servicios activos</span>'
    preserved = "sí" if data.get("commission_preserved") else "revisar"
    return f"""
<section class="svc-section" id="lumen-services-revenue-card">
  <div class="card">
    <div class="svc-head">
      <div>
        <span class="svc-badge">Segunda vía de ingresos</span>
        <h2 style="margin:7px 0 3px">Servicios LUMEN</h2>
        <div class="svc-note">Sourcing y prospección pagos funcionan en paralelo al negocio de operaciones y comisiones.</div>
      </div>
      <a class="svc-button" href="/services">Abrir Servicios</a>
    </div>

    <div class="svc-grid">
      <div><div class="label">Servicios activos</div><div class="metric good">{_i(data.get('active_count'))}</div></div>
      <div><div class="label">Consultas recibidas</div><div class="metric">{_i(data.get('inquiries_total'))}</div><div class="svc-note">Nuevas: {_i(data.get('inquiries_new'))}</div></div>
      <div><div class="label">Oportunidades preparadas</div><div class="metric lime">{_i(data.get('prepared'))}</div><div class="svc-note">No equivalen a clientes ni ventas.</div></div>
      <div><div class="label">Consultas convertidas</div><div class="metric">{_i(data.get('inquiries_converted'))}</div><div class="svc-note">Calificadas: {_i(data.get('inquiries_qualified'))}</div></div>
    </div>

    <div class="svc-revenue">
      <div class="svc-mini"><div class="label">Ingreso realizado · Servicios</div><div class="metric {'good' if _f(data.get('service_realized_usd')) > 0 else 'svc-zero'}">{_money(_f(data.get('service_realized_usd')))}</div></div>
      <div class="svc-mini"><div class="label">Resultado realizado · Operaciones/Comisiones</div><div class="metric {'good' if _f(data.get('commission_realized_usd')) > 0 else 'svc-zero'}">{_money(_f(data.get('commission_realized_usd')))}</div></div>
    </div>

    <div class="svc-list">{names}</div>
    <div class="svc-note">Comisiones preservadas: <strong>{_esc(preserved)}</strong> · atención máxima del carril de servicios: <strong>{_i(data.get('share_cap_pct'))}%</strong> · precios, contratos y pagos siguen requiriendo decisión humana. Los dos ingresos se muestran separados.</div>
  </div>
</section>
"""


def inject_services(page: str, state: Dict[str, Any]) -> str:
    if "lumen-services-cc-css" not in page:
        page = page.replace("</head>", _css() + "</head>", 1)
    if "lumen-services-revenue-card" not in page:
        section = _section(_snapshot(state))
        # Put it next to the top operational strips, before the normal hero metrics.
        marker = '<div class="grid hero">'
        if marker in page:
            page = page.replace(marker, section + marker, 1)
        else:
            page = page.replace("</body>", section + "</body>", 1)
    return page


@app.middleware("http")
async def command_center_services_injector(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/command-center":
        return response
    if "text/html" not in str(response.headers.get("content-type") or ""):
        return response
    try:
        load_state()
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8", errors="replace")
        text = inject_services(text, STATE)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        print({
            "command_center_services_injector": {
                "status": "applied",
                "visible": "lumen-services-revenue-card" in text,
                "services_link": 'href="/services"' in text,
                "separate_revenue_truth": True,
            }
        }, flush=True)
        return Response(content=text, status_code=response.status_code, headers=headers, media_type="text/html")
    except Exception as exc:
        print({"command_center_services_injector": {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}}, flush=True)
        return response


print({
    "command_center_services_runtime": {
        "version": VERSION,
        "status": "active",
        "route": "/command-center",
        "services_route": "/services",
        "separate_commission_and_service_revenue": True,
        "share_cap_pct": round(SERVICE_LANE_SHARE_CAP * 100),
    }
}, flush=True)
