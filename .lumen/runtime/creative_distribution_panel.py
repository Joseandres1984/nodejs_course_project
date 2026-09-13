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


def _f(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    assets = list(state.get("creative_assets", []) or [])
    proof = list(state.get("distribution_proof_ledger", []) or [])
    return {
        "assets": assets,
        "proof": proof,
        "factory": dict(state.get("creative_factory", {}) or {}),
        "dist": dict(state.get("distribution_proof", {}) or {}),
        "champions": [x for x in assets if x.get("is_champion")],
        "external_verified": [x for x in proof if x.get("status") == "verified_published"],
        "awaiting_connector": [x for x in proof if x.get("status") == "awaiting_authorized_connector"],
    }


def render_growth_ops_strip(state: Dict[str, Any]) -> str:
    s = snapshot(state)
    return f"""
    <section class='growthops-strip'>
      <div><div class='go-eye'>CREATIVE FACTORY · DISTRIBUTION PROOF</div><h2>Crear excelente + demostrar que realmente salió</h2><p>Preparado, publicado, visto, click y lead son estados distintos. LUMEN no cuenta una publicación externa sin evidencia.</p></div>
      <div class='go-stats'><span><small>Creatividades</small><b>{len(s['assets'])}</b></span><span><small>Champions</small><b>{len(s['champions'])}</b></span><span><small>Externas verificadas</small><b>{len(s['external_verified'])}</b></span><span><small>Esperando canal</small><b>{len(s['awaiting_connector'])}</b></span></div>
      <div class='go-actions'><a href='/creative-factory'>Ver creatividades</a><a href='/distribution-proof'>Ver comprobantes</a></div>
    </section>
    """


def strip_css() -> str:
    return """
    .growthops-strip{margin:0 0 12px;padding:15px 16px;border:1px solid #453c70;border-radius:17px;background:linear-gradient(135deg,#111024,#0a1d24);display:grid;grid-template-columns:1.4fr 1fr auto;gap:14px;align-items:center;color:#edf7fb}.go-eye{font-size:10px;font-weight:900;letter-spacing:.15em;color:#c9b7ff}.growthops-strip h2{margin:4px 0;font-size:18px}.growthops-strip p{margin:0;color:#9ca9b8;font-size:11px;line-height:1.45}.go-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.go-stats span{border:1px solid #302d50;border-radius:10px;background:#0a111b;padding:8px}.go-stats small,.go-stats b{display:block}.go-stats small{font-size:9px;color:#857fa8;text-transform:uppercase}.go-stats b{font-size:17px;margin-top:2px}.go-actions{display:flex;flex-direction:column;gap:7px}.go-actions a{display:block;text-decoration:none;font-weight:900;padding:10px 12px;border-radius:9px;background:#c9b7ff;color:#0a0812!important;text-align:center;white-space:nowrap}.go-actions a:last-child{background:#0a111b;color:#b8e8ff!important;border:1px solid #315467}@media(max-width:980px){.growthops-strip{grid-template-columns:1fr}.go-stats{grid-template-columns:repeat(4,1fr)}.go-actions{flex-direction:row}}@media(max-width:620px){.go-stats{grid-template-columns:1fr 1fr}.go-actions{flex-direction:column}}
    """


def inject_growth_ops_strip(base_html: str, state: Dict[str, Any]) -> str:
    if "growthops-strip" in base_html:
        return base_html
    out = base_html.replace("</head>", "<style>" + strip_css() + "</style></head>", 1)
    return out.replace("<body>", "<body>" + render_growth_ops_strip(state), 1)


def _creative_cards(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<div class='empty'>La fábrica todavía no generó piezas.</div>"
    out = []
    for row in rows[:36]:
        direction = row.get("visual_direction", {}) or {}
        ratio = "story" if _i(row.get("height")) > _i(row.get("width")) else "landscape" if _i(row.get("width")) > _i(row.get("height")) else "square"
        badge = "CHAMPION" if row.get("is_champion") else "EXPERIMENTO"
        out.append(f"""
        <article class='creative-card'>
          <div class='preview {ratio}'><div class='preview-eye'>{_e(row.get('eyebrow'))}</div><h3>{_e(row.get('headline'))}</h3><p>{_e(row.get('body'))}</p><div class='proofline'>{_e(row.get('credibility_line'))}</div><div class='cta'>{_e(row.get('cta'))}</div><div class='brandmark'>LUMEN</div></div>
          <div class='meta'><div class='tag'>{badge} · {_e(row.get('format_label'))}</div><b>{_e(row.get('campaign_id'))} · {_e(row.get('angle'))}</b><span>{_i(row.get('width'))}×{_i(row.get('height'))} · calidad {_f(row.get('quality_score')):.0f}/100</span><p>{_e(direction.get('motif'))}</p><code>{_e(row.get('tracking_path'))}</code></div>
        </article>""")
    return "".join(out)


def render_creative_factory_page(state: Dict[str, Any]) -> str:
    s = snapshot(state)
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='45'><title>LUMEN · Creative Factory</title><style>
    :root{{--text:#eef7fb;--muted:#8ea4b1;--line:#294b5e;--lime:#d7ff64;--violet:#c9b7ff}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 10% 0,#20204b 0,#061018 38%);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}}.wrap{{max-width:1240px;margin:auto;padding:26px 18px 70px}}.top{{display:flex;justify-content:space-between;gap:14px;align-items:end}}.brand{{color:var(--violet);font-weight:950;letter-spacing:.16em}}h1{{font-size:38px;margin:8px 0}}.sub{{color:var(--muted);max-width:800px;line-height:1.5}}.btn{{text-decoration:none;color:#9bdcff;border:1px solid #315467;border-radius:9px;padding:10px 12px;font-weight:900}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:20px 0}}.stat{{background:#0a1821;border:1px solid var(--line);border-radius:13px;padding:12px}}.stat small,.stat b{{display:block}}.stat small{{font-size:9px;color:#7893a2;text-transform:uppercase}}.stat b{{font-size:22px;margin-top:3px}}.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}}.creative-card{{display:grid;grid-template-columns:1.05fr .95fr;gap:12px;background:linear-gradient(180deg,#0d202b,#08151d);border:1px solid var(--line);border-radius:17px;padding:12px}}.preview{{position:relative;overflow:hidden;border-radius:13px;background:radial-gradient(circle at 80% 20%,#243e55 0,#0a141d 42%,#080d14 100%);border:1px solid #34536a;padding:18px;min-height:260px;display:flex;flex-direction:column;justify-content:center}}.preview.story{{min-height:390px}}.preview-eye{{font-size:10px;font-weight:950;letter-spacing:.15em;color:#9bdcff}}.preview h3{{font-size:clamp(22px,3vw,34px);line-height:1.03;margin:10px 0}}.preview p{{color:#b7c6cf;font-size:12px;line-height:1.5;max-width:95%}}.proofline{{font-size:10px;color:#d7ff64;font-weight:800;margin:8px 0 12px}}.cta{{align-self:flex-start;background:#d7ff64;color:#07100a;border-radius:9px;padding:9px 12px;font-weight:950}}.brandmark{{position:absolute;right:14px;bottom:12px;font-weight:950;letter-spacing:.16em;color:#ffffff66;font-size:10px}}.meta{{padding:5px 3px}}.tag{{font-size:9px;color:var(--violet);font-weight:950;letter-spacing:.12em;margin-bottom:8px}}.meta b,.meta span,.meta code{{display:block}}.meta b{{font-size:13px}}.meta span{{font-size:10px;color:#7f98a6;margin-top:6px}}.meta p{{font-size:11px;line-height:1.5;color:#a9bac4}}.meta code{{font-size:10px;color:#d7ff64;background:#061018;border-radius:7px;padding:8px;overflow-wrap:anywhere}}.empty{{padding:25px;border:1px dashed #34536a;border-radius:14px;color:#8098a5}}@media(max-width:960px){{.grid{{grid-template-columns:1fr}}.top{{align-items:flex-start;flex-direction:column}}}}@media(max-width:620px){{.creative-card{{grid-template-columns:1fr}}.stats{{grid-template-columns:1fr 1fr}}}}
    </style></head><body><main class='wrap'><section class='top'><div><div class='brand'>LUMEN · CREATIVE FACTORY</div><h1>La fábrica de piezas comerciales</h1><p class='sub'>Cada campaña se convierte en piezas adaptadas por formato, con una sola promesa, evidencia prudente, CTA atribuible y dirección visual.</p></div><a class='btn' href='/command-center'>← Command Center</a></section><section class='stats'><div class='stat'><small>Piezas</small><b>{len(s['assets'])}</b></div><div class='stat'><small>Champions</small><b>{len(s['champions'])}</b></div><div class='stat'><small>Calidad media</small><b>{_f(s['factory'].get('quality_avg')):.0f}</b></div><div class='stat'><small>Render-ready</small><b>{_i(s['factory'].get('render_ready'))}</b></div></section><section class='grid'>{_creative_cards(s['assets'])}</section></main></body></html>"""


def _proof_rows(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<div class='empty'>Todavía no hay entregas preparadas.</div>"
    labels = {
        "verified_published": "PUBLICADA · VERIFICADA",
        "published_owned_channel": "PUBLICADA · CANAL PROPIO",
        "awaiting_authorized_connector": "PREPARADA · FALTA CANAL",
        "awaiting_budget_approval": "PREPARADA · FALTA PRESUPUESTO",
        "ready_for_dispatch": "LISTA PARA ENVIAR",
    }
    out = []
    for row in rows[-120:][::-1]:
        if row.get("external_url"):
            evidence_html = f"<a href='{_e(row.get('external_url'))}' target='_blank' rel='noopener'>Ver publicación externa ↗</a>"
        else:
            evidence_html = "<span>Sin URL externa verificada</span>"
        status = str(row.get("status") or "")
        out.append(f"""
        <div class='proof-row'>
          <div><div class='status {_e(status)}'>{_e(labels.get(status, status))}</div><b>{_e(row.get('campaign_id'))} · {_e(row.get('channel'))}</b><span>{_e(row.get('variant_id'))} · prueba: {_e(row.get('proof_level'))}</span></div>
          <div class='numbers'><span>Proof <b>{_i(row.get('proof_score'))}</b></span><span>Imp. <b>{_i(row.get('impressions'))}</b></span><span>Clicks <b>{_i(row.get('external_clicks')) + _i(row.get('tracked_clicks'))}</b></span><span>Leads <b>{_i(row.get('tracked_leads'))}</b></span></div>
          <div class='evidence'>{evidence_html}<small>{_e(row.get('provider') or '')}</small></div>
        </div>""")
    return "".join(out)


def render_distribution_proof_page(state: Dict[str, Any]) -> str:
    s = snapshot(state)
    d = s["dist"]
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='45'><title>LUMEN · Distribution Proof</title><style>
    :root{{--text:#eef7fb;--muted:#8ea4b1;--line:#294b5e;--lime:#d7ff64;--blue:#9bdcff}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 10% 0,#12364b 0,#061018 38%);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}}.wrap{{max-width:1220px;margin:auto;padding:26px 18px 70px}}.top{{display:flex;justify-content:space-between;gap:14px;align-items:end}}.brand{{color:var(--lime);font-weight:950;letter-spacing:.16em}}h1{{font-size:38px;margin:8px 0}}.sub{{color:var(--muted);max-width:820px;line-height:1.5}}.btn{{text-decoration:none;color:var(--blue);border:1px solid #315467;border-radius:9px;padding:10px 12px;font-weight:900}}.stats{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:20px 0}}.stat{{background:#0a1821;border:1px solid var(--line);border-radius:13px;padding:12px}}.stat small,.stat b{{display:block}}.stat small{{font-size:9px;color:#7893a2;text-transform:uppercase}}.stat b{{font-size:22px;margin-top:3px}}.ledger{{border:1px solid var(--line);border-radius:16px;background:#08161e;padding:6px 14px}}.proof-row{{display:grid;grid-template-columns:1.4fr 1fr .8fr;gap:12px;align-items:center;padding:13px 0;border-bottom:1px solid #173543}}.proof-row:last-child{{border-bottom:0}}.proof-row b,.proof-row span,.evidence small{{display:block}}.proof-row>div>span{{font-size:10px;color:#7994a2;margin-top:4px}}.status{{display:inline-block!important;font-size:9px!important;font-weight:950;letter-spacing:.08em;color:#d7ff64!important;margin:0 0 5px!important}.status.awaiting_authorized_connector,.status.awaiting_budget_approval{{color:#ffca7a!important}}.numbers{{display:grid;grid-template-columns:repeat(4,1fr);gap:5px}}.numbers span{{border:1px solid #21404f;border-radius:8px;padding:6px;font-size:9px!important;color:#76909e!important}.numbers b{{font-size:15px;color:white;margin-top:2px}}.evidence{{text-align:right}}.evidence a{{color:#9bdcff;font-weight:800;text-decoration:none;font-size:11px}}.evidence small{{font-size:9px;color:#6e8795;margin-top:4px}}.empty{{padding:24px;color:#7893a2}}.truth{{margin:17px 0;padding:14px;border:1px solid #5a4f20;border-radius:12px;background:#151306;color:#c5caa8;line-height:1.5}}@media(max-width:900px){{.proof-row{{grid-template-columns:1fr}}.evidence{{text-align:left}}.stats{{grid-template-columns:1fr 1fr 1fr}}.top{{align-items:flex-start;flex-direction:column}}}}@media(max-width:520px){{.stats{{grid-template-columns:1fr 1fr}}.numbers{{grid-template-columns:1fr 1fr}}}}
    </style></head><body><main class='wrap'><section class='top'><div><div class='brand'>LUMEN · DISTRIBUTION PROOF</div><h1>Comprobantes de salida a la red</h1><p class='sub'>¿La pieza fue realmente publicada afuera o solamente quedó preparada? LUMEN exige evidencia antes de contar distribución externa.</p></div><a class='btn' href='/command-center'>← Command Center</a></section><section class='stats'><div class='stat'><small>Externas verificadas</small><b>{_i(d.get('external_verified_published'))}</b></div><div class='stat'><small>Canal propio live</small><b>{_i(d.get('owned_live'))}</b></div><div class='stat'><small>Esperando canal</small><b>{_i(d.get('awaiting_connector'))}</b></div><div class='stat'><small>Impresiones verificadas</small><b>{_i(d.get('external_impressions_verified'))}</b></div><div class='stat'><small>Leads trazados</small><b>{_i(d.get('tracked_campaign_leads'))}</b></div></section><div class='truth'><b>Regla de verdad:</b> preparada ≠ publicada; publicada ≠ vista; vista ≠ interesada. Cada salto necesita evidencia propia.</div><section class='ledger'>{_proof_rows(s['proof'])}</section></main></body></html>"""
