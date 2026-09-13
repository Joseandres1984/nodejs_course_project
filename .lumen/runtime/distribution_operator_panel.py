from __future__ import annotations

import html
from typing import Any, Dict, List


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _i(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _f(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(state.get("distribution_operator", {}) or {})
    return {
        "report": report,
        "jobs": list(state.get("distribution_operator_jobs", []) or []),
        "canaries": list(state.get("distribution_canaries", []) or report.get("canaries", []) or []),
        "history": list(state.get("distribution_operator_history", []) or []),
    }


def render_distribution_strip(state: Dict[str, Any]) -> str:
    s = snapshot(state)
    r = s["report"]
    funnel = dict(r.get("funnel", {}) or {})
    if not r:
        summary = "Esperando primer ciclo del operador"
        status = "pending"
    else:
        summary = (
            f"{_i(r.get('owned_live'))} propias live · {_i(r.get('external_verified'))} externas verificadas · "
            f"{_i(funnel.get('clicks'))} clicks · {_i(funnel.get('leads'))} leads"
        )
        status = "live" if _i(r.get("owned_live")) or _i(r.get("external_verified")) else "pending"
    return f"""
    <section class='distop-strip {status}'>
      <div><div class='do-eye'>DISTRIBUTION OPERATOR · CANARY</div><h2>¿LUMEN realmente salió a buscar audiencia?</h2><p>{_e(summary)}. Sólo cuenta publicación externa cuando existe comprobante del canal.</p></div>
      <div class='do-kpi'><small>Conector pendiente</small><b>{_i(r.get('awaiting_connector'))}</b></div>
      <a class='do-btn' href='/distribution-operator'>Ver distribución real</a>
    </section>
    """


def css() -> str:
    return """
    .distop-strip{margin:0 0 12px;padding:15px 16px;border:1px solid #31556b;border-radius:17px;background:linear-gradient(135deg,#081a25,#101d27);display:grid;grid-template-columns:1.5fr auto auto;gap:16px;align-items:center;color:#eef7fb}.distop-strip.live{border-color:#376b50;background:linear-gradient(135deg,#071923,#102417)}.do-eye{font-size:10px;font-weight:950;letter-spacing:.15em;color:#8bd8ff}.distop-strip h2{margin:4px 0;font-size:18px}.distop-strip p{margin:0;color:#94a9b5;font-size:11px;line-height:1.45}.do-kpi{min-width:110px;text-align:center;border:1px solid #294b5e;border-radius:12px;background:#08141b;padding:10px}.do-kpi small,.do-kpi b{display:block}.do-kpi small{font-size:9px;text-transform:uppercase;color:#7893a2}.do-kpi b{font-size:25px;margin-top:2px;color:#d7ff64}.do-btn{display:block;text-decoration:none;font-weight:950;padding:11px 14px;border-radius:10px;background:#d7ff64;color:#07100a!important;white-space:nowrap;text-align:center}@media(max-width:820px){.distop-strip{grid-template-columns:1fr}.do-kpi{text-align:left}.do-btn{width:100%}}
    """


def inject_distribution_strip(base_html: str, state: Dict[str, Any]) -> str:
    if "distop-strip" in base_html:
        return base_html
    out = base_html.replace("</head>", "<style>" + css() + "</style></head>", 1)
    return out.replace("<body>", "<body>" + render_distribution_strip(state), 1)


def _status_label(status: str) -> str:
    labels = {
        "live_first_party": "LIVE · CANAL PROPIO",
        "verified_published": "PUBLICADA · VERIFICADA",
        "awaiting_authorized_connector": "FALTA CONECTOR",
        "awaiting_budget_approval": "ESPERA PRESUPUESTO",
        "awaiting_verified_recipient": "BUSCANDO DESTINATARIO",
        "email_queued_for_governed_outbound": "EMAIL EN PIPELINE",
        "email_sent_verified": "EMAIL ENVIADO",
        "email_ready": "EMAIL LISTO",
        "email_blocked_quality": "EMAIL BLOQUEADO",
        "email_send_failed": "EMAIL FALLÓ",
    }
    return labels.get(status, status.replace("_", " ").upper())


def _job_cards(jobs: List[Dict[str, Any]]) -> str:
    if not jobs:
        return "<div class='empty'>Todavía no hay trabajos de distribución materializados.</div>"
    out = []
    rank = {"verified_published": 0, "email_sent_verified": 1, "live_first_party": 2, "email_queued_for_governed_outbound": 3, "awaiting_authorized_connector": 4, "awaiting_budget_approval": 5}
    rows = sorted(jobs, key=lambda x: (rank.get(str(x.get("status") or ""), 9), str(x.get("audience") or ""), str(x.get("channel") or "")))
    for job in rows:
        status = str(job.get("status") or "")
        url = str(job.get("external_url") or job.get("tracking_url") or "")
        link = f"<a href='{_e(url)}' target='_blank' rel='noopener'>Abrir evidencia ↗</a>" if url.startswith(("http://", "https://")) else ""
        out.append(f"""
        <article class='job {"ok" if status in {"verified_published","email_sent_verified","live_first_party"} else "wait"}'>
          <div class='row'><span>{_e(job.get('audience'))}</span><strong>{_e(job.get('channel'))}</strong><em>{_e(_status_label(status))}</em></div>
          <h3>{_e(job.get('campaign_id'))} · {_e(job.get('variant_id'))}</h3>
          <p>{_e(str(job.get('copy') or '')[:420])}</p>
          <div class='meta'>Tracking: {_e(job.get('tracking_url') or '—')} {link}</div>
          {f"<div class='meta'>Destino: {_e(job.get('target_company'))}</div>" if job.get('target_company') else ''}
          {f"<div class='err'>{_e(job.get('last_error'))}</div>" if job.get('last_error') else ''}
        </article>
        """)
    return "".join(out)


def _canary_cards(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<div class='empty'>El primer canario se materializará en el próximo ciclo.</div>"
    labels = {"buyer": "Compradores", "supplier": "Proveedores", "partner": "Tiendas partner"}
    return "".join(
        f"""
        <article class='canary'>
          <div class='aud'>{_e(labels.get(str(x.get('audience')), x.get('audience')))}</div>
          <h3>{_e(x.get('stage'))}</h3>
          <div class='mini'><span>Propio live <b>{_i(x.get('owned_live'))}</b></span><span>Externo <b>{_i(x.get('external_verified'))}</b></span><span>Email <b>{_i(x.get('email_sent'))}</b></span><span>Clicks <b>{_i(x.get('clicks'))}</b></span><span>Leads <b>{_i(x.get('leads'))}</b></span></div>
          <div class='track'>{_e(x.get('tracking_url') or '')}</div>
        </article>
        """ for x in rows
    )


def _history(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<div class='empty'>Sin historial todavía.</div>"
    return "".join(
        "<div class='hist'><span>{}</span><b>{} ext.</b><span>{} clicks</span><span>{} leads</span><span>{} verificadas</span><strong>{} opp.</strong></div>".format(
            _e(x.get("updated_at")), _i(x.get("external_verified")), _i(x.get("clicks")), _i(x.get("leads")), _i(x.get("verified_companies")), _i(x.get("opportunities"))
        ) for x in rows[-20:][::-1]
    )


def render_distribution_operator_page(state: Dict[str, Any]) -> str:
    s = snapshot(state)
    r = s["report"]
    f = dict(r.get("funnel", {}) or {})
    style = """
    :root{--bg:#061018;--panel:#0a1821;--line:#294b5e;--text:#edf7fb;--muted:#8da5b2;--lime:#d7ff64;--blue:#8bd8ff;--amber:#ffca7a;--red:#ff8c74}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 8% 0,#12344b 0,#061018 38%);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}.wrap{max-width:1240px;margin:auto;padding:26px 18px 70px}.top{display:flex;justify-content:space-between;gap:16px;align-items:end}.brand{font-weight:950;letter-spacing:.16em;color:var(--blue)}h1{font-size:40px;margin:8px 0}.sub{max-width:850px;color:var(--muted);line-height:1.5}.back{color:#9bdcff;text-decoration:none;border:1px solid #315467;border-radius:9px;padding:10px 12px;font-weight:900}.kpis{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin:20px 0}.kpi{border:1px solid var(--line);border-radius:13px;background:var(--panel);padding:12px}.kpi small,.kpi b{display:block}.kpi small{font-size:9px;text-transform:uppercase;color:#7893a2}.kpi b{font-size:24px;margin-top:4px}.truth{border:1px solid #615321;background:#171405;border-radius:12px;padding:13px;color:#d1d5bf;font-size:12px;line-height:1.5;margin-bottom:18px}.canaries{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin:10px 0 22px}.canary,.job{border:1px solid var(--line);border-radius:15px;background:#091820;padding:14px}.aud{font-size:10px;font-weight:950;letter-spacing:.12em;color:var(--blue);text-transform:uppercase}.canary h3{font-size:22px;margin:7px 0 12px}.mini{display:grid;grid-template-columns:repeat(5,1fr);gap:5px}.mini span{font-size:9px;color:#7993a1}.mini b{display:block;color:var(--lime);font-size:16px}.track{margin-top:11px;font:10px ui-monospace,monospace;color:#7292a4;word-break:break-all}.jobs{display:grid;grid-template-columns:1fr 1fr;gap:9px}.job.ok{border-color:#32624b}.job.wait{border-color:#4a5360}.row{display:flex;gap:8px;align-items:center}.row span,.row strong,.row em{font-size:9px;text-transform:uppercase}.row span{color:#8bd8ff}.row strong{color:#b6c8d2}.row em{margin-left:auto;color:var(--amber);font-style:normal;font-weight:900}.job.ok .row em{color:#a6e9c5}.job h3{font-size:14px;margin:9px 0}.job p{color:#9aadb7;font-size:11px;line-height:1.5;white-space:pre-line}.meta{font-size:10px;color:#728c9b;margin-top:7px;word-break:break-all}.meta a{color:#9bdcff}.err{font-size:10px;color:var(--red);margin-top:7px}.history{margin-top:22px;border:1px solid var(--line);border-radius:15px;background:#08161e;padding:12px}.hist{display:grid;grid-template-columns:1.5fr repeat(5,.7fr);gap:8px;border-bottom:1px solid #173543;padding:8px 0}.hist:last-child{border-bottom:0}.hist span{font-size:10px;color:#7893a2}.hist strong{color:var(--lime)}.empty{padding:18px;color:#7893a2}@media(max-width:1000px){.kpis{grid-template-columns:repeat(3,1fr)}.canaries,.jobs{grid-template-columns:1fr}}@media(max-width:600px){.kpis{grid-template-columns:1fr 1fr}.top{align-items:flex-start;flex-direction:column}.hist{grid-template-columns:1fr 1fr}}
    """
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='45'><title>LUMEN · Distribution Operator</title><style>{style}</style></head><body><main class='wrap'><section class='top'><div><div class='brand'>LUMEN · DISTRIBUTION OPERATOR</div><h1>Prueba comercial de punta a punta</h1><p class='sub'>Acá no alcanza con preparar contenido. LUMEN separa canal propio, email gobernado, publicación externa verificada y publicidad paga. Una red externa sólo cuenta cuando devuelve evidencia.</p></div><a class='back' href='/command-center'>← Command Center</a></section><section class='kpis'><div class='kpi'><small>Canal propio live</small><b>{_i(r.get('owned_live'))}</b></div><div class='kpi'><small>Externas verificadas</small><b>{_i(r.get('external_verified'))}</b></div><div class='kpi'><small>Esperan conector</small><b>{_i(r.get('awaiting_connector'))}</b></div><div class='kpi'><small>Emails enviados</small><b>{_i(r.get('email_sent_verified'))}</b></div><div class='kpi'><small>Clicks</small><b>{_i(f.get('clicks'))}</b></div><div class='kpi'><small>Leads</small><b>{_i(f.get('leads'))}</b></div><div class='kpi'><small>Oportunidades</small><b>{_i(f.get('opportunities'))}</b></div></section><div class='truth'><b>Regla de verdad:</b> preparada ≠ publicada; publicada ≠ vista; vista ≠ lead; lead ≠ negocio. Cada salto necesita evidencia. Publicidad paga permanece bloqueada sin presupuesto humano aprobado.</div><h2>Canarios activos</h2><section class='canaries'>{_canary_cards(s['canaries'])}</section><h2>Trabajos de distribución</h2><section class='jobs'>{_job_cards(s['jobs'])}</section><section class='history'><h2>Historial del embudo</h2>{_history(s['history'])}</section></main></body></html>"""
