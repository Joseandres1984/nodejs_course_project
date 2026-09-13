from __future__ import annotations

import html
from typing import Any, Dict

from fastapi import Depends
from fastapi.responses import HTMLResponse

from journal_main import app
from app import STATE, auth, load_state


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _startup_outbound_snapshot() -> None:
    try:
        loaded = load_state()
        report = dict(STATE.get("outbound_engine", {}) or {})
        transport = dict(STATE.get("mail_transport_health", {}) or {})
        print({
            "startup_outbound_engine": {
                "state_loaded": bool(loaded),
                "version": report.get("version"),
                "status": report.get("status"),
                "live": bool(report.get("live")),
                "eligible_prospects": int(report.get("eligible_prospects") or 0),
                "messages_total": int(report.get("messages_total") or 0),
                "sent_total": int(report.get("sent_total") or 0),
                "delivered_verified": int(report.get("delivered_verified") or 0),
                "send_failed": int(report.get("send_failed") or 0),
                "replies_detected": int(report.get("replies_detected") or 0),
                "daily_remaining": int(report.get("daily_remaining") or 0),
                "mail_transport_ok": bool(transport.get("ok")),
                "mail_provider": transport.get("provider"),
            }
        }, flush=True)
    except Exception as exc:
        print({"startup_outbound_engine": {"status": "unavailable", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}}, flush=True)


_startup_outbound_snapshot()


@app.get("/health/outbound", include_in_schema=False)
def outbound_health():
    loaded = load_state()
    report = dict(STATE.get("outbound_engine", {}) or {})
    transport = dict(STATE.get("mail_transport_health", {}) or {})
    ok = bool(loaded and report.get("version") == "1.0" and report.get("status") in {"active", "prepared"})
    return {
        "ok": ok,
        "version": report.get("version"),
        "status": report.get("status"),
        "live": bool(report.get("live")),
        "eligible_prospects": int(report.get("eligible_prospects") or 0),
        "messages_total": int(report.get("messages_total") or 0),
        "sent_total": int(report.get("sent_total") or 0),
        "delivered_verified": int(report.get("delivered_verified") or 0),
        "send_failed": int(report.get("send_failed") or 0),
        "replies_detected": int(report.get("replies_detected") or 0),
        "campaign_variant_clicks": int(report.get("campaign_variant_clicks") or 0),
        "leads_same_contact": int(report.get("leads_same_contact") or 0),
        "linked_opportunities": int(report.get("linked_opportunities") or 0),
        "daily_new": int(report.get("daily_new") or 0),
        "daily_cap": int(report.get("daily_cap") or 0),
        "daily_remaining": int(report.get("daily_remaining") or 0),
        "mail_transport_ok": bool(transport.get("ok")),
        "mail_provider": transport.get("provider"),
        "mail_route": transport.get("route"),
        "updated_at": report.get("updated_at"),
        "truth_note": "sent and delivered are reported separately; delivery is counted only from provider evidence",
    }


@app.get("/outbound-engine", response_class=HTMLResponse, include_in_schema=False)
def outbound_dashboard(_=Depends(auth)):
    load_state()
    r: Dict[str, Any] = dict(STATE.get("outbound_engine", {}) or {})
    prospects = list(STATE.get("outbound_engine_prospects", []) or [])[:50]
    sequences = list(STATE.get("outbound_sequences", []) or [])[-100:]
    prospect_rows = "".join(
        f"<tr><td>{_esc(x.get('company'))}</td><td>{_esc(x.get('role'))}</td><td>{_esc(x.get('category'))}</td><td>{_esc(x.get('score'))}</td><td>{_esc(', '.join(x.get('reasons', []) or []))}</td></tr>"
        for x in prospects
    ) or "<tr><td colspan='5'>Sin prospectos elegibles en este ciclo.</td></tr>"
    seq_rows = "".join(
        f"<tr><td>{_esc(x.get('company'))}</td><td>{_esc(x.get('role'))}</td><td>{_esc(x.get('category'))}</td><td>{_esc(x.get('target_score'))}</td><td>{_esc(x.get('status'))}</td><td>{_esc(x.get('sent_messages'))}</td><td>{_esc(x.get('delivered_messages'))}</td><td>{'sí' if x.get('reply_detected') else 'no'}</td></tr>"
        for x in reversed(sequences)
    ) or "<tr><td colspan='8'>Todavía no hay secuencias creadas.</td></tr>"
    return HTMLResponse(f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>LUMEN · Outbound Engine</title><style>body{{font-family:Arial,sans-serif;background:#061117;color:#e8f0f4;margin:0}}main{{max-width:1250px;margin:auto;padding:24px}}a{{color:#b7ff4a}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}}.card{{background:#0b1d25;border:1px solid #23404b;border-radius:14px;padding:15px}}.card b{{font-size:25px}}table{{width:100%;border-collapse:collapse;margin-top:12px;font-size:13px}}th,td{{border-bottom:1px solid #213843;padding:9px;text-align:left;vertical-align:top}}th{{color:#9fb2bb}}</style></head>
<body><main><p><a href='/command-center'>← Command Center</a></p><h1>Outbound Engine · Captación B2B</h1>
<p>Prospección únicamente sobre empresas y emails corporativos públicos verificados. Cada mensaje sigue pasando por Communication Director, Quality Gate y COO antes de Resend.</p>
<div class='grid'>
<div class='card'><span>Estado</span><br><b>{_esc(r.get('status'))}</b></div>
<div class='card'><span>Elegibles</span><br><b>{int(r.get('eligible_prospects') or 0)}</b></div>
<div class='card'><span>Enviados</span><br><b>{int(r.get('sent_total') or 0)}</b></div>
<div class='card'><span>Entregados verificados</span><br><b>{int(r.get('delivered_verified') or 0)}</b></div>
<div class='card'><span>Respuestas</span><br><b>{int(r.get('replies_detected') or 0)}</b></div>
<div class='card'><span>Leads mismo contacto</span><br><b>{int(r.get('leads_same_contact') or 0)}</b></div>
<div class='card'><span>Oportunidades vinculadas</span><br><b>{int(r.get('linked_opportunities') or 0)}</b></div>
<div class='card'><span>Cupo hoy</span><br><b>{int(r.get('daily_remaining') or 0)}/{int(r.get('daily_cap') or 0)}</b></div>
</div>
<h2>Prospectos priorizados</h2><table><thead><tr><th>Empresa</th><th>Rol</th><th>Categoría</th><th>Score</th><th>Evidencia</th></tr></thead><tbody>{prospect_rows}</tbody></table>
<h2>Secuencias</h2><table><thead><tr><th>Empresa</th><th>Rol</th><th>Categoría</th><th>Score</th><th>Estado</th><th>Enviados</th><th>Entregados</th><th>Respuesta</th></tr></thead><tbody>{seq_rows}</tbody></table>
<p><strong>Regla:</strong> enviado ≠ entregado ≠ respondido ≠ oportunidad. Cada etapa necesita evidencia propia.</p></main></body></html>""")
