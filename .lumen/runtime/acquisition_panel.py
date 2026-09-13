from __future__ import annotations

import html
from typing import Any, Dict, List


def _e(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _i(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    campaigns = list(state.get("acquisition_campaigns", []) or [])
    events = list(state.get("acquisition_events", []) or [])
    leads = list(state.get("acquisition_leads", []) or [])
    reach = list(state.get("market_reach_events", []) or [])
    queue = list(state.get("acquisition_distribution_queue", []) or [])
    clicks = sum(1 for x in events if x.get("event") == "click")
    landing = sum(1 for x in events if x.get("event") == "landing_view")
    market_views = sum(1 for x in reach if x.get("event") == "market_page_view")
    market_clicks = sum(1 for x in reach if x.get("event") == "listing_cta_click")
    return {
        "campaigns": campaigns,
        "campaigns_active": sum(1 for x in campaigns if x.get("status") == "active"),
        "variants": sum(len(x.get("variants", []) or []) for x in campaigns),
        "clicks": clicks,
        "landing_views": landing,
        "leads": len(leads),
        "market_views": market_views,
        "market_clicks": market_clicks,
        "queue": queue,
        "queue_ready": sum(1 for x in queue if str(x.get("status") or "").startswith("ready")),
        "conversion": round(len(leads) / max(1, clicks) * 100, 1),
    }


def render_acquisition_strip(state: Dict[str, Any]) -> str:
    s = snapshot(state)
    return f"""
    <section class='acq-strip'>
      <div><div class='acq-eye'>GROWTH · CAPTACIÓN AUTÓNOMA</div><h2>Compradores + proveedores + partners</h2><p>Campañas con links atribuibles, landing propia y aprendizaje por conversión real. Publicar afuera requiere canal autorizado; pauta paga requiere aprobación de presupuesto.</p></div>
      <div class='acq-stats'><span><small>Campañas</small><b>{s['campaigns_active']}</b></span><span><small>Clicks</small><b>{s['clicks']}</b></span><span><small>Leads</small><b>{s['leads']}</b></span><span><small>Market views</small><b>{s['market_views']}</b></span></div>
      <a class='acq-btn' href='/acquisition'>Ver captación</a>
    </section>
    """


def css() -> str:
    return """
    .acq-strip{margin:0 0 12px;padding:15px 16px;border:1px solid #5a4f20;border-radius:17px;background:linear-gradient(135deg,#171507,#0c1d12);display:grid;grid-template-columns:1.4fr 1fr auto;gap:14px;align-items:center;color:#edf7fb}.acq-eye{font-size:10px;font-weight:900;letter-spacing:.15em;color:#d7ff64}.acq-strip h2{margin:4px 0;font-size:18px}.acq-strip p{margin:0;color:#9aa991;font-size:11px;line-height:1.45}.acq-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.acq-stats span{border:1px solid #3d4825;border-radius:10px;background:#0a130b;padding:8px}.acq-stats small,.acq-stats b{display:block}.acq-stats small{font-size:9px;color:#87977a;text-transform:uppercase}.acq-stats b{font-size:17px;margin-top:2px}.acq-btn{display:block;text-decoration:none;font-weight:900;padding:11px 14px;border-radius:10px;background:#d7ff64;color:#07100a!important;white-space:nowrap;text-align:center}@media(max-width:980px){.acq-strip{grid-template-columns:1fr}.acq-stats{grid-template-columns:repeat(4,1fr)}}@media(max-width:620px){.acq-stats{grid-template-columns:1fr 1fr}}
    """


def inject_acquisition_strip(base_html: str, state: Dict[str, Any]) -> str:
    if "acq-strip" in base_html:
        return base_html
    out = base_html.replace("</head>", "<style>" + css() + "</style></head>", 1)
    return out.replace("<body>", "<body>" + render_acquisition_strip(state), 1)


def market_tracking_script() -> str:
    return r'''
<script id="lumen-market-reach-v1">
(() => {
  try { fetch('/track/market-view', {method:'POST', keepalive:true, credentials:'omit'}); } catch(_) {}
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a'); if (!a) return;
    const href = a.getAttribute('href') || '';
    if (!href.includes('/market/concierge?listing_id=')) return;
    try {
      const u = new URL(href, location.origin);
      const id = u.searchParams.get('listing_id') || '';
      fetch('/track/market-click?listing_id=' + encodeURIComponent(id), {method:'POST', keepalive:true, credentials:'omit'});
    } catch(_) {}
  });
})();
</script>
'''


def inject_public_acquisition_cta(base_html: str, state: Dict[str, Any]) -> str:
    campaigns = {str(x.get("audience") or ""): x for x in state.get("acquisition_campaigns", []) or []}
    cards: List[str] = []
    for audience, label, text in [
        ("buyer", "¿Necesitás comprar para tu empresa?", "Contale a LUMEN qué necesitás y empezamos a buscar alternativas."),
        ("supplier", "¿Sos proveedor B2B?", "Sumá tu empresa para recibir oportunidades compatibles."),
        ("partner", "¿Tenés una tienda o catálogo online?", "Explorá un modelo de derivación atribuible y comisión acordada."),
    ]:
        campaign = campaigns.get(audience)
        if not campaign:
            continue
        variants = campaign.get("variants", []) or []
        champion = next((x for x in variants if x.get("id") == campaign.get("champion_variant_id")), variants[0] if variants else None)
        if not champion:
            continue
        cards.append(f"<a class='acq-public-card' href='{_e(champion.get('tracking_path'))}'><b>{_e(label)}</b><span>{_e(text)}</span></a>")
    if not cards:
        return base_html
    block = "<section class='acq-public'><h2>Entrá a la red LUMEN</h2><div>" + "".join(cards) + "</div></section><style>.acq-public{margin:30px 0;padding:20px;border:1px solid #36515f;border-radius:18px;background:#08151d}.acq-public h2{margin:0 0 12px}.acq-public>div{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.acq-public-card{display:block;text-decoration:none;border:1px solid #294b5e;border-radius:13px;padding:14px;color:#eef7fb;background:#0a1d27}.acq-public-card b,.acq-public-card span{display:block}.acq-public-card b{color:#d7ff64}.acq-public-card span{font-size:12px;color:#9cb1bd;margin-top:6px;line-height:1.45}@media(max-width:720px){.acq-public>div{grid-template-columns:1fr}}</style>"
    out = base_html.replace("</main>", block + "</main>", 1)
    if "lumen-market-reach-v1" not in out:
        out = out.replace("</body>", market_tracking_script() + "</body>", 1)
    return out


def _campaign_cards(campaigns: List[Dict[str, Any]]) -> str:
    if not campaigns:
        return "<div class='empty'>Todavía no hay campañas activas.</div>"
    out = []
    for c in campaigns:
        variants = c.get("variants", []) or []
        champ = next((x for x in variants if x.get("id") == c.get("champion_variant_id")), variants[0] if variants else {})
        perf = champ.get("performance", {}) or {}
        out.append(f"""
        <article class='campaign'>
          <div class='tag'>{_e(c.get('audience'))}</div><h2>{_e(c.get('name'))}</h2>
          <h3>{_e(champ.get('headline'))}</h3><p>{_e(champ.get('body'))}</p>
          <div class='metrics'><span>Clicks <b>{_i(perf.get('clicks'))}</b></span><span>Leads <b>{_i(perf.get('submissions'))}</b></span><span>Conv. <b>{round(float(perf.get('click_to_lead_rate') or 0)*100,1)}%</b></span></div>
          <div class='link'>{_e(champ.get('tracking_path'))}</div>
          <small>Variante líder: {_e(champ.get('angle'))}. LUMEN puede rotarla si acumula tráfico sin conversión.</small>
        </article>""")
    return "".join(out)


def render_acquisition_page(state: Dict[str, Any]) -> str:
    s = snapshot(state)
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='45'><title>LUMEN · Growth Acquisition</title><style>
    :root{{--bg:#061018;--panel:#0c1c25;--line:#2b4d5f;--text:#eef7fb;--muted:#8da5b2;--lime:#d7ff64}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 12% 0,#17384b 0,#061018 36%);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}}.wrap{{max-width:1180px;margin:auto;padding:26px 18px 70px}}.top{{display:flex;justify-content:space-between;gap:12px;align-items:end}}.brand{{color:var(--lime);font-weight:950;letter-spacing:.16em}}h1{{font-size:36px;margin:8px 0}}.sub{{color:var(--muted);max-width:780px;line-height:1.5}}.btn{{text-decoration:none;color:#9bdcff;border:1px solid #315467;border-radius:9px;padding:10px 12px;font-weight:900}}.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:20px 0}}.stat,.campaign{{border:1px solid var(--line);background:linear-gradient(180deg,#0d202b,#08161e);border-radius:15px}}.stat{{padding:12px}}.stat small,.stat b{{display:block}}.stat small{{font-size:9px;color:#7993a1;text-transform:uppercase}}.stat b{{font-size:22px;margin-top:3px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.campaign{{padding:16px}}.tag{{font-size:9px;text-transform:uppercase;color:var(--lime);font-weight:900;letter-spacing:.12em}}.campaign h2{{font-size:14px;color:#9bdcff;margin:7px 0}}.campaign h3{{font-size:20px;line-height:1.18;margin:10px 0}}.campaign p{{color:#b4c6cf;font-size:12px;line-height:1.55}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:12px 0}}.metrics span{{font-size:10px;color:#829aa8;border:1px solid #234352;border-radius:8px;padding:7px}}.metrics b{{display:block;color:white;font-size:16px;margin-top:2px}}.link{{font:11px ui-monospace,monospace;color:#d7ff64;background:#07131a;padding:9px;border-radius:8px;overflow-wrap:anywhere}}.campaign small{{display:block;color:#708b99;line-height:1.5;margin-top:8px}}.note{{margin-top:18px;padding:15px;border:1px solid #5b4f22;border-radius:13px;background:#151306;color:#c5caa8;line-height:1.5}}@media(max-width:900px){{.grid{{grid-template-columns:1fr}}.stats{{grid-template-columns:repeat(3,1fr)}}.top{{align-items:flex-start;flex-direction:column}}}}@media(max-width:520px){{.stats{{grid-template-columns:1fr 1fr}}}}
    </style></head><body><main class='wrap'><section class='top'><div><div class='brand'>LUMEN · GROWTH ENGINE</div><h1>Captación autónoma medible</h1><p class='sub'>No alcanza con publicar. Esta capa crea mensajes por audiencia, links atribuibles, landing pages y aprendizaje por clicks → leads → empresas verificadas → negocio.</p></div><a class='btn' href='/command-center'>← Command Center</a></section><section class='stats'><div class='stat'><small>Campañas</small><b>{s['campaigns_active']}</b></div><div class='stat'><small>Variantes</small><b>{s['variants']}</b></div><div class='stat'><small>Clicks captación</small><b>{s['clicks']}</b></div><div class='stat'><small>Leads</small><b>{s['leads']}</b></div><div class='stat'><small>Market views</small><b>{s['market_views']}</b></div><div class='stat'><small>CTA Market</small><b>{s['market_clicks']}</b></div></section><section class='grid'>{_campaign_cards(s['campaigns'])}</section><div class='note'><b>Qué significa “llegó”:</b> publicado ≠ visto. LUMEN registra visitas y clicks en canales propios; para redes externas necesita datos del canal o un conector autorizado. Las campañas pagas nunca pueden gastar dinero sin aprobación de presupuesto.</div></main></body></html>"""
