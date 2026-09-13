from __future__ import annotations

import html
from typing import Any, Dict, List


def _e(value: Any) -> str:
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
    try:
        return f"USD {float(value):,.2f}"
    except (TypeError, ValueError):
        return "USD 0.00"


def _commission_collected(state: Dict[str, Any]) -> float:
    total = 0.0
    for row in state.get("revenue_ledger", []) or []:
        if str(row.get("kind") or "") != "commission_settlement":
            continue
        if str(row.get("status") or "") not in {"realized", "realized_partial"}:
            continue
        total += max(0.0, _f(row.get("amount")))
    return round(total, 2)


def snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    listings = list(state.get("autonomous_listings", []) or [])
    published = [x for x in listings if x.get("status") == "published"]
    inquiries = list(state.get("market_inquiries", []) or [])
    conversations = list(state.get("market_conversations", []) or [])
    active_conversations = [x for x in conversations if x.get("status") not in {"converted_to_market_inquiry", "closed"}]
    candidate_accounts = list(state.get("candidate_accounts", []) or [])
    buyers = [x for x in candidate_accounts if x.get("type") == "buyer" and x.get("verified_company")]
    suppliers = [x for x in candidate_accounts if x.get("type") == "supplier" and x.get("verified_company")]
    funnel = ((state.get("business_kpis", {}) or {}).get("funnel", {}) or {})

    return {
        "published": published,
        "all_listings": listings,
        "inquiries": inquiries,
        "conversations": conversations,
        "active_conversations": active_conversations,
        "verified_buyers": buyers,
        "verified_suppliers": suppliers,
        "opportunities": _i(funnel.get("evidence_backed_opportunities"), len(state.get("market_opportunities", []) or [])),
        "real_offers": _i(funnel.get("real_offers")),
        "proposals": _i(funnel.get("proposals")),
        "close_ready": _i(funnel.get("close_ready")),
        "commission_collected_usd": _commission_collected(state),
        "updated_at": str((state.get("autonomous_distribution", {}) or {}).get("updated_at") or state.get("last_tick") or ""),
    }


def _inquiry_rows(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<div class='mo-empty'>Todavía no entraron consultas reales desde el Market.</div>"
    out = []
    for row in reversed(rows[-12:]):
        out.append(
            "<div class='mo-item'>"
            f"<div><b>{_e(row.get('company') or 'Comprador')}</b><span>{_e(row.get('category') or 'Sin categoría')}</span></div>"
            f"<div class='mo-right'><strong>{_e(row.get('quantity') or 'Cantidad a confirmar')}</strong><small>{_e(row.get('status') or 'new')}</small></div>"
            f"<p>{_e(row.get('need') or '')}</p>"
            "</div>"
        )
    return "".join(out)


def _listing_rows(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<div class='mo-empty'>LUMEN todavía no publicó oportunidades con evidencia suficiente.</div>"
    out = []
    for row in rows[:16]:
        evidence = row.get("evidence", {}) or {}
        out.append(
            "<div class='mo-item'>"
            f"<div><b>{_e(row.get('title') or row.get('category') or row.get('id') or 'Publicación')}</b>"
            f"<span>{_e(row.get('category') or '')}</span></div>"
            f"<div class='mo-right'><strong>Score {_f(row.get('score')):.0f}</strong>"
            f"<small>{_i(evidence.get('verified_suppliers'))} prov. verif. · {_i(evidence.get('demand_signals'))} señales</small></div>"
            "</div>"
        )
    return "".join(out)


def render_owner_market_strip(state: Dict[str, Any]) -> str:
    s = snapshot(state)
    return f"""
    <section class='market-owner-strip'>
      <div class='mo-strip-copy'>
        <div class='mo-eyebrow'>MARKET · VISTA DEL DUEÑO</div>
        <h2>Tu panel comercial, no la vidriera del cliente</h2>
        <p>Acá mirás qué publica LUMEN, qué demanda entra y cuánto avanza el negocio. La tienda pública queda separada.</p>
      </div>
      <div class='mo-strip-stats'>
        <span><small>Publicadas</small><b>{len(s['published'])}</b></span>
        <span><small>Consultas</small><b>{len(s['inquiries'])}</b></span>
        <span><small>Conversaciones</small><b>{len(s['active_conversations'])}</b></span>
        <span><small>Close-ready</small><b>{s['close_ready']}</b></span>
      </div>
      <div class='mo-strip-actions'><a class='mo-owner-btn' href='/market-owner'>Abrir panel comercial</a><a class='mo-public-btn' href='/market' target='_blank' rel='noopener'>Ver Market público ↗</a></div>
    </section>
    """


def css() -> str:
    return """
    .market-owner-strip{margin:0 0 12px;padding:15px 16px;border:1px solid #315467;border-radius:17px;background:linear-gradient(135deg,#081721,#0c202b);display:grid;grid-template-columns:1.4fr 1fr auto;gap:14px;align-items:center;color:#edf7fb}.mo-eyebrow{font-size:10px;font-weight:900;letter-spacing:.15em;color:#8bd8ff}.mo-strip-copy h2{margin:4px 0;font-size:18px}.mo-strip-copy p{margin:0;color:#8fa8b6;font-size:11px;line-height:1.45}.mo-strip-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.mo-strip-stats span{border:1px solid #1f3d4c;border-radius:10px;background:#07141c;padding:8px}.mo-strip-stats small,.mo-strip-stats b{display:block}.mo-strip-stats small{font-size:9px;color:#718d9d;text-transform:uppercase;letter-spacing:.08em}.mo-strip-stats b{font-size:17px;margin-top:2px}.mo-strip-actions{display:flex;flex-direction:column;gap:7px}.mo-owner-btn,.mo-public-btn{display:block;text-decoration:none;font-weight:900;padding:10px 12px;border-radius:9px;white-space:nowrap;text-align:center}.mo-owner-btn{background:#d7ff64;color:#07100a!important}.mo-public-btn{border:1px solid #315467;color:#9bdcff!important;background:#07141c}@media(max-width:980px){.market-owner-strip{grid-template-columns:1fr}.mo-strip-actions{flex-direction:row}.mo-strip-stats{grid-template-columns:repeat(4,1fr)}}@media(max-width:620px){.mo-strip-stats{grid-template-columns:1fr 1fr}.mo-strip-actions{flex-direction:column}}
    """


def inject_owner_market_strip(base_html: str, state: Dict[str, Any]) -> str:
    if "market-owner-strip" in base_html:
        return base_html
    out = base_html.replace("</head>", "<style>" + css() + "</style></head>", 1)
    return out.replace("<body>", "<body>" + render_owner_market_strip(state), 1)


def render_owner_market_page(state: Dict[str, Any]) -> str:
    s = snapshot(state)
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='45'><title>LUMEN · Panel comercial del Market</title><style>
    :root{{--bg:#061018;--panel:#0b1b26;--line:#214356;--muted:#8ca5b4;--text:#eef7fb;--lime:#d7ff64;--blue:#8bd8ff}}
    *{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 10% 0,#12334a 0,#061018 35%);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}}.wrap{{max-width:1180px;margin:auto;padding:24px 18px 70px}}.top{{display:flex;justify-content:space-between;gap:16px;align-items:flex-end}}.brand{{font-weight:950;letter-spacing:.16em;color:var(--lime)}}h1{{font-size:34px;margin:8px 0 5px}}.sub{{margin:0;color:var(--muted);max-width:760px;line-height:1.5}}.actions{{display:flex;gap:8px;flex-wrap:wrap}}.btn{{text-decoration:none;font-weight:900;border-radius:9px;padding:10px 13px}}.primary{{background:var(--lime);color:#07100a}}.secondary{{border:1px solid #315467;color:var(--blue)}}.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:20px 0}}.stat,.card{{background:linear-gradient(180deg,#0d1f2b,#081720);border:1px solid var(--line);border-radius:15px}}.stat{{padding:12px}}.stat small,.stat b{{display:block}}.stat small{{font-size:9px;color:#7894a4;text-transform:uppercase;letter-spacing:.09em}}.stat b{{font-size:22px;margin-top:4px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.card{{padding:16px}}.card h2{{font-size:15px;margin:0 0 10px}}.mo-item{{padding:10px 0;border-bottom:1px solid #173442;display:grid;grid-template-columns:1fr auto;gap:9px}}.mo-item:last-child{{border-bottom:0}}.mo-item b,.mo-item span,.mo-item strong,.mo-item small{{display:block}}.mo-item span,.mo-item small{{color:#7894a4;font-size:10px;margin-top:3px}}.mo-item p{{grid-column:1/-1;margin:0;color:#b7c8d1;font-size:11px;line-height:1.45}}.mo-right{{text-align:right}}.mo-empty{{padding:20px;border:1px dashed #315467;border-radius:11px;color:#7894a4;text-align:center}}.foot{{margin-top:16px;color:#668392;font-size:11px}}@media(max-width:900px){{.stats{{grid-template-columns:1fr 1fr 1fr}}.grid{{grid-template-columns:1fr}}.top{{align-items:flex-start;flex-direction:column}}}}@media(max-width:520px){{.stats{{grid-template-columns:1fr 1fr}}}}
    </style></head><body><main class='wrap'><section class='top'><div><div class='brand'>LUMEN · OWNER MARKET</div><h1>Panel comercial del Market</h1><p class='sub'>Esta es tu vista. No vendés ni completás formularios acá: observás qué está ofreciendo LUMEN, qué compradores entran y cómo avanza el embudo.</p></div><div class='actions'><a class='btn secondary' href='/command-center'>← Command Center</a><a class='btn primary' href='/market' target='_blank' rel='noopener'>Ver Market público ↗</a></div></section>
    <section class='stats'>
      <div class='stat'><small>Publicaciones</small><b>{len(s['published'])}</b></div>
      <div class='stat'><small>Consultas</small><b>{len(s['inquiries'])}</b></div>
      <div class='stat'><small>Conversaciones activas</small><b>{len(s['active_conversations'])}</b></div>
      <div class='stat'><small>Compradores verificados</small><b>{len(s['verified_buyers'])}</b></div>
      <div class='stat'><small>Proveedores verificados</small><b>{len(s['verified_suppliers'])}</b></div>
      <div class='stat'><small>Comisión cobrada</small><b>{_money(s['commission_collected_usd'])}</b></div>
    </section>
    <section class='grid'>
      <div class='card'><h2>Demanda entrante desde LUMEN Market</h2>{_inquiry_rows(s['inquiries'])}</div>
      <div class='card'><h2>Qué está mostrando LUMEN al mercado</h2>{_listing_rows(s['published'])}</div>
      <div class='card'><h2>Embudo comercial</h2><div class='mo-item'><div><b>Oportunidades con evidencia</b><span>Demanda + oferta suficiente</span></div><div class='mo-right'><strong>{s['opportunities']}</strong></div></div><div class='mo-item'><div><b>Cotizaciones reales</b><span>Ofertas recibidas y normalizadas</span></div><div class='mo-right'><strong>{s['real_offers']}</strong></div></div><div class='mo-item'><div><b>Propuestas</b><span>Propuestas comerciales generadas</span></div><div class='mo-right'><strong>{s['proposals']}</strong></div></div><div class='mo-item'><div><b>Listas para cierre</b><span>Solo antes de acciones vinculantes</span></div><div class='mo-right'><strong>{s['close_ready']}</strong></div></div></div>
      <div class='card'><h2>Separación de roles</h2><div class='mo-item'><div><b>Vos</b><span>mirás decisiones, demanda, pipeline, cierres y comisión</span></div></div><div class='mo-item'><div><b>Cliente</b><span>entra al Market público y habla con LUMEN</span></div></div><div class='mo-item'><div><b>LUMEN</b><span>ordena la necesidad, investiga, conecta, sigue y empuja el negocio</span></div></div></div>
    </section><div class='foot'>Actualización automática cada 45 s · Estado: {_e(s['updated_at'] or 'en curso')}</div></main></body></html>"""
