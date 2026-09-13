from __future__ import annotations

import html
from typing import Any, Dict


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _money_rate(value: Any) -> str:
    if value in {None, ""}:
        return "—"
    try:
        return f"{float(value):g}%"
    except (TypeError, ValueError):
        return _e(value)


def snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    stores = list(state.get("partner_stores", []) or [])
    offers = [x for x in state.get("partner_referral_offers", []) or [] if x.get("status") == "active"]
    events = list(state.get("partner_attribution_events", []) or [])
    return {
        "stores": stores,
        "active_partners": [x for x in stores if x.get("commercial_status") == "active_partner"],
        "affiliate_detected": [x for x in stores if x.get("commercial_status") == "affiliate_program_detected"],
        "prospects": [x for x in stores if x.get("commercial_status") == "prospect"],
        "offers": offers,
        "clicks": sum(1 for x in events if x.get("event") == "referral_click"),
        "report": state.get("partner_network", {}) or {},
    }


def render_partner_strip(state: Dict[str, Any]) -> str:
    s = snapshot(state)
    return f"""
    <section class='pn-strip'>
      <div><div class='pn-eye'>PARTNER / REFERRAL NETWORK</div><h2>Tiendas → productos → compradores → comisión</h2><p>LUMEN descubre comercios y catálogos, pero solo activa derivaciones monetizadas cuando existe un acuerdo/afiliación autorizado.</p></div>
      <div class='pn-kpis'><span><small>Tiendas</small><b>{len(s['stores'])}</b></span><span><small>Partners activos</small><b>{len(s['active_partners'])}</b></span><span><small>Ofertas atribuibles</small><b>{len(s['offers'])}</b></span><span><small>Clicks atribuidos</small><b>{s['clicks']}</b></span></div>
      <a class='pn-btn' href='/partners'>Ver red de partners</a>
    </section>"""


def css() -> str:
    return """
    .pn-strip{margin:0 0 12px;padding:15px 16px;border:1px solid #4b4d2a;border-radius:17px;background:linear-gradient(135deg,#17180b,#0d1a17);display:grid;grid-template-columns:1.3fr 1fr auto;gap:14px;align-items:center;color:#edf7fb}.pn-eye{font-size:10px;font-weight:900;letter-spacing:.15em;color:#d7ff64}.pn-strip h2{margin:4px 0;font-size:18px}.pn-strip p{margin:0;color:#91a99a;font-size:11px;line-height:1.45}.pn-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.pn-kpis span{border:1px solid #343e29;border-radius:10px;background:#0b120b;padding:8px}.pn-kpis small,.pn-kpis b{display:block}.pn-kpis small{font-size:9px;color:#819078;text-transform:uppercase;letter-spacing:.08em}.pn-kpis b{font-size:17px;margin-top:2px}.pn-btn{display:block;text-decoration:none;font-weight:900;padding:10px 12px;border-radius:9px;background:#d7ff64;color:#07100a!important;white-space:nowrap;text-align:center}@media(max-width:980px){.pn-strip{grid-template-columns:1fr}.pn-kpis{grid-template-columns:repeat(4,1fr)}}@media(max-width:620px){.pn-kpis{grid-template-columns:1fr 1fr}}
    """


def inject_partner_strip(base_html: str, state: Dict[str, Any]) -> str:
    if "pn-strip" in base_html:
        return base_html
    out = base_html.replace("</head>", "<style>" + css() + "</style></head>", 1)
    return out.replace("<body>", "<body>" + render_partner_strip(state), 1)


def inject_public_partner_offers(base_html: str, state: Dict[str, Any]) -> str:
    offers = [x for x in state.get("partner_referral_offers", []) or [] if x.get("status") == "active"]
    if not offers or "partner-offers-live" in base_html:
        return base_html
    cards = []
    for row in offers[:12]:
        prices = " · ".join(str(x) for x in row.get("price_mentions", [])[:2])
        rate = _money_rate(row.get("commission_rate"))
        cards.append(f"""
        <article class='card partner-offer-card'>
          <div class='id'>PARTNER · {_e(row.get('partner_domain'))}</div>
          <h2>{_e(row.get('title') or 'Producto de partner')}</h2>
          <p>{_e(row.get('category') or '')}</p>
          <div class='proof'>Proveedor asociado autorizado · atribución LUMEN activa</div>
          <p class='small'>{_e(prices or 'Precio y stock se confirman en la tienda original.')} El comprador paga al comercio y el comercio realiza la entrega. LUMEN percibe únicamente la comisión acordada.</p>
          <a class='cta' href='{_e(row.get('lumen_referral_path'))}' rel='nofollow sponsored'>Ir a la tienda original</a>
        </article>""")
    section = f"""<section id='partner-offers-live' style='margin-top:34px'><div class='brand'>LUMEN PARTNERS</div><h2 style='font-size:28px;margin:8px 0'>Productos de comercios asociados</h2><p class='lead' style='font-size:14px'>Estas derivaciones están habilitadas únicamente cuando existe un acuerdo de comisión o afiliación vigente. Cada salida pasa por LUMEN para registrar atribución.</p><section class='grid'>{''.join(cards)}</section></section>"""
    marker = "<div class='foot'>"
    if marker in base_html:
        return base_html.replace(marker, section + marker, 1)
    return base_html.replace("</main>", section + "</main>", 1)


def render_partner_page(state: Dict[str, Any]) -> str:
    s = snapshot(state)
    store_rows = []
    for store in sorted(s["stores"], key=lambda x: (x.get("commercial_status") != "active_partner", -len(x.get("catalog_products", []) or []), str(x.get("domain") or "")))[:80]:
        status = str(store.get("commercial_status") or "prospect")
        products = len(store.get("catalog_products", []) or [])
        source = ", ".join(store.get("source_families", [])[:3])
        store_rows.append(
            f"<tr><td><b>{_e(store.get('name') or store.get('domain'))}</b><small>{_e(store.get('domain'))}</small></td><td>{_e(status)}</td><td>{products}</td><td>{_e(source)}</td><td>{_money_rate(store.get('commission_rate'))}</td><td>{_e(store.get('next_action'))}</td></tr>"
        )
    offer_rows = []
    for row in s["offers"][:80]:
        offer_rows.append(
            f"<tr><td>{_e(row.get('id'))}</td><td>{_e(row.get('title'))}</td><td>{_e(row.get('partner_domain'))}</td><td>{_money_rate(row.get('commission_rate'))}</td><td>{int(row.get('clicks') or 0)}</td><td><code>{_e(row.get('lumen_referral_path'))}</code></td></tr>"
        )
    report = s["report"]
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='45'><title>LUMEN · Partner Network</title><style>
    :root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#061018;color:#edf7fb;font:14px Inter,system-ui,-apple-system;padding:20px}}.wrap{{max-width:1450px;margin:auto}}a{{color:#9edcff;text-decoration:none}}.top{{display:flex;justify-content:space-between;gap:16px;align-items:end}}h1{{font-size:34px;margin:5px 0}}.muted,small{{color:#8199a7}}.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:18px 0}}.stat,.panel{{background:#0b1822;border:1px solid #214052;border-radius:14px;padding:13px}}.stat small,.stat b{{display:block}}.stat small{{font-size:9px;text-transform:uppercase;letter-spacing:.08em}}.stat b{{font-size:22px;color:#d7ff64;margin-top:4px}}.panel{{margin-top:10px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #18313f;text-align:left;vertical-align:top}}th{{font-size:9px;color:#7794a4;text-transform:uppercase}}td small{{display:block;margin-top:3px}}code{{font-size:11px;color:#d7ff64}}.notice{{padding:12px;border:1px solid #5b5426;background:#1b190b;border-radius:11px;color:#d5d1a6}}@media(max-width:900px){{.stats{{grid-template-columns:1fr 1fr 1fr}}.top{{align-items:flex-start;flex-direction:column}}}}@media(max-width:600px){{.stats{{grid-template-columns:1fr 1fr}}}}
    </style></head><body><main class='wrap'><div class='top'><div><div class='muted'>LUMEN · PARTNER / REFERRAL ENGINE</div><h1>Red de comercios asociados</h1><p class='muted'>Descubrimiento de tiendas, productos indexados, acuerdos, derivaciones atribuibles y comisión.</p></div><div><a href='/command-center'>← Command Center</a> · <a href='/market-owner'>Market gestión</a></div></div>
    <section class='stats'><div class='stat'><small>Tiendas mapeadas</small><b>{len(s['stores'])}</b></div><div class='stat'><small>Partners activos</small><b>{len(s['active_partners'])}</b></div><div class='stat'><small>Afiliación detectada</small><b>{len(s['affiliate_detected'])}</b></div><div class='stat'><small>Prospectos</small><b>{len(s['prospects'])}</b></div><div class='stat'><small>Ofertas activas</small><b>{len(s['offers'])}</b></div><div class='stat'><small>Clicks atribuidos</small><b>{s['clicks']}</b></div></section>
    <div class='notice'>Regla comercial: encontrar una tienda no autoriza a LUMEN a presentarse como partner. Las ofertas derivadas y el código /go/… solo se activan con un acuerdo/afiliación vigente. El comprador paga a la tienda; la tienda entrega; LUMEN cobra únicamente su comisión.</div>
    <section class='panel'><h2>Tiendas y catálogos</h2><div style='overflow:auto'><table><thead><tr><th>Tienda</th><th>Estado</th><th>Productos</th><th>Origen</th><th>Comisión</th><th>Próximo paso</th></tr></thead><tbody>{''.join(store_rows) or '<tr><td colspan="6">Aún no hay tiendas mapeadas.</td></tr>'}</tbody></table></div></section>
    <section class='panel'><h2>Ofertas con atribución habilitada</h2><div style='overflow:auto'><table><thead><tr><th>ID</th><th>Producto</th><th>Partner</th><th>Comisión</th><th>Clicks</th><th>Enlace LUMEN</th></tr></thead><tbody>{''.join(offer_rows) or '<tr><td colspan="6">Todavía no hay ofertas monetizables: falta un acuerdo de partner/afiliado activo.</td></tr>'}</tbody></table></div></section>
    <p class='muted'>Último ciclo: {_e(report.get('updated_at') or 'sin ejecutar')} · búsquedas usadas: {_e(report.get('searches_used') or 0)} · presupuesto partner restante: {_e(report.get('partner_search_budget_remaining') or 0)}</p>
    </main></body></html>"""
