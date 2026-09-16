from __future__ import annotations

"""Surface LUMEN's parallel paid-services pipeline in the owner Command Center.

Read-only presentation. Prepared drafts are never displayed as contacted clients;
commission and service revenue remain separate.
"""

import html
from typing import Any, Dict

from fastapi import Request
from fastapi.responses import Response

from app import STATE, load_state
from outbound_web import app
from service_revenue_runtime import SERVICE_CATALOG, SERVICE_LANE_SHARE_CAP

VERSION = "2.0-command-center-service-pipeline"


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
        q = [x for x in state.get("service_inquiries", []) or [] if isinstance(x, dict)]
        inquiries = {
            "total": len(q),
            "new": sum(1 for x in q if str(x.get("status") or "") in {"new", "new_unverified"}),
            "qualified": sum(1 for x in q if str(x.get("status") or "") == "qualified"),
            "converted": sum(1 for x in q if str(x.get("status") or "") in {"won", "contracted", "paid"}),
        }

    catalog = state.get("service_catalog", []) or SERVICE_CATALOG
    active = [x for x in catalog if isinstance(x, dict) and str(x.get("status") or "") == "active"]
    prepared_rows = [
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
    commission_realized = max(0.0, _f(finance.get("realized_profit_usd")))
    pipeline = [x for x in state.get("service_sales_pipeline", []) or [] if isinstance(x, dict)]

    def count_stage(stage: str) -> int:
        return sum(1 for x in pipeline if str(x.get("stage") or "") == stage)

    return {
        "status": runtime.get("status") or "active",
        "active_services": active,
        "active_count": len(active),
        "prepared": _i(runtime.get("prepared_service_opportunities"), len(prepared_rows)),
        "pipeline_total": _i(runtime.get("pipeline_total"), len(pipeline)),
        "verification_required": _i(runtime.get("verification_required"), count_stage("verification_required")),
        "qualified_waiting": _i(runtime.get("qualified_waiting"), count_stage("qualified")),
        "outreach_prepared": _i(runtime.get("outreach_prepared"), count_stage("outreach_prepared")),
        "real_contacted": _i(runtime.get("real_contacted"), sum(1 for x in pipeline if x.get("contact_truth") == "provider_accepted")),
        "inbound_service_leads": _i(runtime.get("inbound_service_leads"), sum(1 for x in pipeline if x.get("contact_truth") == "inbound_received")),
        "replies": _i(runtime.get("replies"), sum(1 for x in pipeline if x.get("contact_truth") == "replied")),
        "diagnosis": _i(runtime.get("diagnosis"), count_stage("diagnosis")),
        "proposal_drafts": _i(runtime.get("proposal_drafts"), sum(1 for x in pipeline if x.get("proposal_draft_status") == "prepared_nonbinding")),
        "proposal_sent_verified": _i(runtime.get("proposal_sent_verified")),
        "followups_due": _i(runtime.get("followups_due"), sum(1 for x in pipeline if x.get("followup_due"))),
        "won": _i(runtime.get("won"), count_stage("won")),
        "execution_ready": _i(runtime.get("execution_ready"), len(state.get("service_execution_queue", []) or [])),
        "attention_active": _i(runtime.get("outbound_attention_active")),
        "attention_cap": _i(runtime.get("outbound_attention_cap")),
        "inquiries_total": _i(inquiries.get("total")),
        "inquiries_new": _i(inquiries.get("new")),
        "inquiries_qualified": _i(inquiries.get("qualified")),
        "inquiries_converted": _i(inquiries.get("converted")),
        "service_realized_usd": round(service_realized, 2),
        "commission_realized_usd": round(commission_realized, 2),
        "share_cap_pct": round(_f(runtime.get("service_lane_share_cap"), SERVICE_LANE_SHARE_CAP) * 100),
        "commission_preserved": runtime.get("commission_business_preserved") is not False,
        "primary_action": runtime.get("primary_service_action") or "Mantener el carril de servicios activo sin desplazar operaciones/comisiones.",
    }


def _css() -> str:
    return """
<style id="lumen-services-cc-css">
.svc-section{margin:0 0 14px}.svc-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.svc-badge{display:inline-block;border:1px solid #d7ff6455;background:#d7ff6412;color:#d7ff64;border-radius:999px;padding:5px 9px;font-size:10px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}.svc-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin-top:14px}.svc-revenue{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}.svc-mini{background:#07151b;border:1px solid #23404b;border-radius:12px;padding:12px}.svc-list{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.svc-pill{border:1px solid #31505d;background:#102630;border-radius:999px;padding:6px 9px;font-size:11px;color:#c9d8df}.svc-note{font-size:11px;color:var(--muted);margin-top:8px;line-height:1.45}.svc-button{display:inline-block;background:#d7ff64;color:#071018!important;border-radius:9px;padding:10px 14px;font-weight:900;text-decoration:none!important;white-space:nowrap}.svc-zero{color:#9fb2bb}.svc-flow{margin-top:12px;border:1px solid #23404b;background:#07151b;border-radius:12px;padding:12px}.svc-action{font-size:12px;color:#dbe8ec;font-weight:750}.svc-truth{font-size:10px;color:#8fa6b0;margin-top:6px}
@media(max-width:1050px){.svc-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:700px){.svc-grid{grid-template-columns:1fr 1fr}.svc-head{flex-direction:column}.svc-revenue{grid-template-columns:1fr}}
</style>
"""


def _money(value: float) -> str:
    return f"USD {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _metric(label: str, value: Any, note: str = "", cls: str = "") -> str:
    return f'<div><div class="label">{_esc(label)}</div><div class="metric {cls}">{_esc(value)}</div>' + (f'<div class="svc-note">{_esc(note)}</div>' if note else "") + '</div>'


def _section(data: Dict[str, Any]) -> str:
    names = "".join(f'<span class="svc-pill">{_esc(x.get("name") or x.get("id") or "Servicio")}</span>' for x in data.get("active_services", [])) or '<span class="svc-pill">Sin servicios activos</span>'
    metrics = "".join([
        _metric("Pipeline total", data.get("pipeline_total"), "CRM de servicios"),
        _metric("A verificar", data.get("verification_required"), "identidad/necesidad"),
        _metric("Borradores outbound", data.get("outreach_prepared"), "preparados, no contactados", "lime"),
        _metric("Contactados reales", data.get("real_contacted"), "aceptación de proveedor"),
        _metric("Inbound servicios", data.get("inbound_service_leads"), "web + Instagram", "good"),
        _metric("Respuestas", data.get("replies"), "respuesta verificada"),
        _metric("Diagnóstico", data.get("diagnosis"), "necesidad en análisis"),
        _metric("Borradores propuesta", data.get("proposal_drafts"), "no vinculantes"),
        _metric("Propuestas enviadas", data.get("proposal_sent_verified"), "entrega verificada"),
        _metric("Seguimientos", data.get("followups_due"), "vencidos/para actuar"),
        _metric("Ganados", data.get("won"), "cierre explícito", "good"),
        _metric("Ejecución lista", data.get("execution_ready"), "sólo tras cierre"),
    ])
    return f"""
<section class="svc-section" id="lumen-services-revenue-card">
  <div class="card">
    <div class="svc-head">
      <div><span class="svc-badge">Segunda vía de ingresos</span><h2 style="margin:7px 0 3px">Servicios LUMEN · CRM comercial</h2><div class="svc-note">Captación → calificación → contacto → diagnóstico → propuesta → seguimiento → cierre → ejecución. Sin mezclar preparación con resultados reales.</div></div>
      <a class="svc-button" href="/services">Abrir Servicios</a>
    </div>
    <div class="svc-grid">{metrics}</div>
    <div class="svc-flow"><div class="label">Acción prioritaria</div><div class="svc-action">{_esc(data.get('primary_action'))}</div><div class="svc-truth">Atención proactiva: {_i(data.get('attention_active'))}/{_i(data.get('attention_cap'))} · límite del carril: {_i(data.get('share_cap_pct'))}% · consultas entrantes se priorizan sin convertirlas automáticamente en ventas.</div></div>
    <div class="svc-revenue">
      <div class="svc-mini"><div class="label">Ingreso realizado · Servicios</div><div class="metric {'good' if _f(data.get('service_realized_usd')) > 0 else 'svc-zero'}">{_money(_f(data.get('service_realized_usd')))}</div></div>
      <div class="svc-mini"><div class="label">Resultado realizado · Operaciones/Comisiones</div><div class="metric {'good' if _f(data.get('commission_realized_usd')) > 0 else 'svc-zero'}">{_money(_f(data.get('commission_realized_usd')))}</div></div>
    </div>
    <div class="svc-list">{names}</div>
    <div class="svc-note">Candidatos de servicio preparados: <strong>{_i(data.get('prepared'))}</strong> · consultas web: <strong>{_i(data.get('inquiries_total'))}</strong> · calificadas: <strong>{_i(data.get('inquiries_qualified'))}</strong> · comisiones preservadas: <strong>{'sí' if data.get('commission_preserved') else 'revisar'}</strong>. Precio final, contrato y pago siguen requiriendo decisión humana.</div>
  </div>
</section>
"""


def inject_services(page: str, state: Dict[str, Any]) -> str:
    if "lumen-services-cc-css" not in page:
        page = page.replace("</head>", _css() + "</head>", 1)
    if "lumen-services-revenue-card" not in page:
        section = _section(_snapshot(state))
        marker = '<div class="grid hero">'
        page = page.replace(marker, section + marker, 1) if marker in page else page.replace("</body>", section + "</body>", 1)
    return page


@app.middleware("http")
async def command_center_services_injector(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/command-center" or "text/html" not in str(response.headers.get("content-type") or ""):
        return response
    try:
        load_state()
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = inject_services(body.decode("utf-8", errors="replace"), STATE)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        print({"command_center_services_injector": {"status": "applied", "visible": "lumen-services-revenue-card" in text, "pipeline_truth": True, "prepared_is_not_contacted": True}}, flush=True)
        return Response(content=text, status_code=response.status_code, headers=headers, media_type="text/html")
    except Exception as exc:
        print({"command_center_services_injector": {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}}, flush=True)
        return response


print({"command_center_services_runtime": {"version": VERSION, "status": "active", "route": "/command-center", "services_route": "/services", "pipeline_truth": True, "separate_commission_and_service_revenue": True, "share_cap_pct": round(SERVICE_LANE_SHARE_CAP * 100)}}, flush=True)
