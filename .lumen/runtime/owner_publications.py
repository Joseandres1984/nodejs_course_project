from __future__ import annotations

import html
import re
import urllib.parse
from typing import Any, Dict, List


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _i(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def inject_publication_navigation(text: str) -> str:
    """Make owner publication counters navigable without changing customer-facing Market HTML."""
    if "/market-owner/publications" in text:
        return text

    # Command Center strip.
    pattern = re.compile(r"<span><small>Publicadas</small><b>([^<]*)</b></span>", re.I)
    text = pattern.sub(
        r"<a href='/market-owner/publications' style='display:block;text-decoration:none;color:inherit;border:1px solid #1f3d4c;border-radius:10px;background:#07141c;padding:8px'><small style='display:block;font-size:9px;color:#718d9d;text-transform:uppercase;letter-spacing:.08em'>Publicadas</small><b style='display:block;font-size:17px;margin-top:2px'>\1</b><em style='display:block;font-style:normal;font-size:9px;color:#8bd8ff;margin-top:4px'>Ver qué se publicó →</em></a>",
        text,
        count=1,
    )

    # Full owner Market page.
    pattern2 = re.compile(r"<div class='stat'><small>Publicaciones</small><b>([^<]*)</b></div>", re.I)
    text = pattern2.sub(
        r"<a class='stat' href='/market-owner/publications' style='display:block;text-decoration:none;color:inherit'><small>Publicaciones</small><b>\1</b><span style='display:block;color:#8bd8ff;font-size:10px;margin-top:5px'>Auditar publicaciones →</span></a>",
        text,
        count=1,
    )
    return text


def _proof(row: Dict[str, Any]) -> str:
    evidence = row.get("evidence", {}) or {}
    proof: List[str] = []
    if _i(evidence.get("verified_suppliers")):
        proof.append(f"{_i(evidence.get('verified_suppliers'))} proveedor(es) verificado(s)")
    if _i(evidence.get("demand_signals")):
        proof.append(f"{_i(evidence.get('demand_signals'))} señal(es) de demanda")
    if _i(evidence.get("real_offers")):
        proof.append(f"{_i(evidence.get('real_offers'))} cotización(es) real(es)")
    return " · ".join(proof[:3]) or "Sourcing B2B activo"


def _preview_card(row: Dict[str, Any]) -> str:
    listing_id = str(row.get("id") or "")
    title = str(row.get("title") or row.get("category") or "Oportunidad B2B")
    summary = str(row.get("summary") or "")
    category = str(row.get("category") or "")
    concierge = "/market/concierge?listing_id=" + urllib.parse.quote(listing_id)
    evidence = row.get("evidence", {}) or {}
    return f"""
    <article class='audit-row'>
      <section class='customer-preview'>
        <div class='preview-label'>VISTA DEL CLIENTE · ASÍ SE ESTÁ VENDIENDO</div>
        <div class='market-card'>
          <div class='listing-id'>{_e(listing_id)}</div>
          <h2>{_e(title)}</h2>
          <p>{_e(summary)}</p>
          <div class='proof'>{_e(_proof(row))}</div>
          <p class='disclaimer'>Disponibilidad, precio, plazo y condiciones se confirman para cada requerimiento. LUMEN actúa como intermediario comercial; comprador y proveedor operan directamente entre sí.</p>
          <a class='cta' href='{_e(concierge)}' target='_blank' rel='noopener'>Hablar con LUMEN</a>
        </div>
      </section>
      <aside class='audit-panel'>
        <div class='audit-label'>AUDITORÍA DEL DUEÑO</div>
        <h3>{_e(title)}</h3>
        <div class='kv'><span>ID</span><b>{_e(listing_id)}</b></div>
        <div class='kv'><span>Categoría</span><b>{_e(category or '—')}</b></div>
        <div class='kv'><span>Estado</span><b>{_e(row.get('status') or '—')}</b></div>
        <div class='kv'><span>Score publicación</span><b>{_f(row.get('score')):.0f}/100</b></div>
        <div class='kv'><span>Proveedores verificados</span><b>{_i(evidence.get('verified_suppliers'))}</b></div>
        <div class='kv'><span>Señales de demanda</span><b>{_i(evidence.get('demand_signals'))}</b></div>
        <div class='kv'><span>Cotizaciones reales</span><b>{_i(evidence.get('real_offers'))}</b></div>
        <div class='selling'><small>MENSAJE DE VENTA</small><p><b>Titular:</b> {_e(title)}</p><p><b>Propuesta:</b> {_e(summary or 'Sin resumen comercial cargado.')}</p><p><b>Prueba/confianza:</b> {_e(_proof(row))}</p><p><b>CTA:</b> Hablar con LUMEN</p></div>
        <div class='row-actions'><a href='{_e(concierge)}' target='_blank' rel='noopener'>Probar conversación ↗</a><a href='/market' target='_blank' rel='noopener'>Ver Market completo ↗</a></div>
      </aside>
    </article>
    """


def render_publications_page(state: Dict[str, Any]) -> str:
    rows = [x for x in state.get("autonomous_listings", []) or [] if x.get("status") == "published"]
    rows.sort(key=lambda x: _f(x.get("score")), reverse=True)
    cards = "".join(_preview_card(x) for x in rows)
    if not cards:
        cards = "<div class='empty'>Todavía no hay publicaciones activas para auditar.</div>"
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='45'><title>LUMEN · Publicaciones activas</title><style>
    :root{{--bg:#061018;--panel:#0b1b26;--line:#214356;--muted:#8ca5b4;--text:#eef7fb;--lime:#d7ff64;--blue:#8bd8ff}}
    *{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 10% 0,#12334a 0,#061018 36%);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}}.wrap{{max-width:1180px;margin:auto;padding:24px 18px 70px}}.top{{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;margin-bottom:20px}}.brand{{font-weight:950;letter-spacing:.16em;color:var(--lime)}}h1{{font-size:34px;margin:8px 0 5px}}.sub{{margin:0;color:var(--muted);max-width:790px;line-height:1.5}}.actions{{display:flex;gap:8px;flex-wrap:wrap}}.btn{{text-decoration:none;font-weight:900;border-radius:9px;padding:10px 13px}}.primary{{background:var(--lime);color:#07100a}}.secondary{{border:1px solid #315467;color:var(--blue)}}.audit-row{{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr);gap:14px;margin:14px 0}}.customer-preview,.audit-panel{{border:1px solid var(--line);border-radius:18px;padding:16px;background:linear-gradient(180deg,#0d1f2b,#081720)}}.preview-label,.audit-label{{font-size:10px;font-weight:950;letter-spacing:.13em;color:var(--blue);margin-bottom:10px}}.market-card{{background:linear-gradient(180deg,#0d1f2b,#091720);border:1px solid #214054;border-radius:18px;padding:22px;min-height:330px}}.listing-id{{font:12px ui-monospace,monospace;color:var(--blue)}}.market-card h2{{font-size:23px;margin:8px 0 12px}}.market-card p{{color:#b8c9d3;line-height:1.55}}.proof{{color:var(--lime);font-size:12px;font-weight:800;margin:16px 0}}.disclaimer{{font-size:12px}}.cta{{display:inline-block;margin-top:9px;background:var(--lime);color:#0a1008;text-decoration:none;font-weight:900;padding:11px 14px;border-radius:9px}}.audit-panel h3{{margin:3px 0 12px;font-size:20px}}.kv{{display:grid;grid-template-columns:1fr auto;gap:12px;padding:8px 0;border-bottom:1px solid #173442}}.kv span{{color:#7894a4;font-size:11px}}.kv b{{font-size:12px;text-align:right}}.selling{{margin-top:14px;padding:12px;border-radius:12px;background:#07141c;border:1px solid #1f3d4c}}.selling small{{font-size:9px;color:#7894a4;letter-spacing:.1em}}.selling p{{font-size:11px;line-height:1.45;color:#b7c8d1;margin:8px 0}}.row-actions{{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}}.row-actions a{{text-decoration:none;border:1px solid #315467;border-radius:8px;padding:8px 10px;color:var(--blue);font-size:11px;font-weight:900}}.empty{{padding:30px;border:1px dashed #315467;border-radius:16px;color:#7894a4;text-align:center}}.note{{margin:16px 0 0;color:#668392;font-size:11px}}@media(max-width:860px){{.audit-row{{grid-template-columns:1fr}}.top{{align-items:flex-start;flex-direction:column}}}}
    </style></head><body><main class='wrap'><section class='top'><div><div class='brand'>LUMEN · PUBLICATION REVIEW</div><h1>Qué está viendo el cliente</h1><p class='sub'>Acá podés corroborar cada publicación activa: estética, texto comercial, evidencia usada y llamada a la acción. La columna izquierda reproduce la experiencia de venta; la derecha te muestra por qué y con qué respaldo se publicó.</p></div><div class='actions'><a class='btn secondary' href='/market-owner'>← Panel comercial</a><a class='btn primary' href='/market' target='_blank' rel='noopener'>Ver Market público ↗</a></div></section>{cards}<div class='note'>Actualización automática cada 45 s · No se modifica ninguna publicación desde esta pantalla.</div></main></body></html>"""
