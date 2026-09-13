from __future__ import annotations

import html
from typing import Any, Dict

from executive_secretary import build_secretary_snapshot


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _section_rows(items, *, kind: str) -> str:
    if not items:
        return '<div class="sec-empty">Sin pendientes en esta sección.</div>'
    rows = []
    for item in items:
        if kind == "news":
            badge = "NUEVO" if item.get("new_since_last_brief") else "SEGUIMIENTO"
            link = f' · <a href="{_esc(item.get("url"))}" target="_blank" rel="noopener">fuente</a>' if item.get("url") else ""
            meta = f"{_esc(item.get('category') or 'comercial')} · score {_esc(item.get('score'))}{link}"
            body = _esc(item.get("summary"))
            title = _esc(item.get("title"))
        elif kind == "pending":
            badge = _esc(item.get("owner") or "LUMEN")
            meta = f"prioridad {_esc(item.get('priority'))} · {_esc(item.get('risk') or 'riesgo normal')}"
            body = _esc(item.get("reason"))
            title = _esc(item.get("title"))
        elif kind == "decision":
            badge = "JOSÉ"
            meta = _esc(item.get("severity") or "atención")
            body = _esc(item.get("message"))
            recommendation = _esc(item.get("recommendation"))
            if recommendation:
                body += f'<div class="sec-reco">Secretaría: {recommendation}</div>'
            title = _esc(item.get("title"))
        elif kind == "admin":
            badge = _esc(item.get("owner") or "ADMIN")
            meta = f"{_esc(item.get('count'))} pendiente(s)"
            body = _esc(item.get("detail"))
            title = _esc(item.get("title"))
        else:
            badge = "RESUELTO"
            meta = _esc(item.get("ts"))
            body = _esc(item.get("detail"))
            title = _esc(item.get("title"))
        rows.append(
            f'<div class="sec-row"><div class="sec-row-head"><b>{title}</b><span>{badge}</span></div>'
            f'<div class="sec-meta">{meta}</div><p>{body}</p></div>'
        )
    return "".join(rows)


def render_secretary_strip(state: Dict[str, Any]) -> str:
    report = state.get("executive_secretary", {}) or build_secretary_snapshot(state, mutate_memory=False)
    counts = report.get("counts", {}) or {}
    news = report.get("news", []) or []
    new_news = sum(1 for x in news if x.get("new_since_last_brief"))
    return f"""
    <section class="sec-strip">
      <div class="sec-head">
        <div><small>SECRETARÍA EJECUTIVA · LUMEN</small><h2>Tu mesa administrativa</h2><p>{_esc(report.get('brief'))}</p></div>
        <a class="sec-open" href="/secretaria">Abrir Secretaría</a>
      </div>
      <div class="sec-stats">
        <div><small>NOVEDADES</small><b>{new_news}</b><span>desde el último informe</span></div>
        <div><small>PENDIENTES</small><b>{len(report.get('pending', []) or [])}</b><span>priorizados</span></div>
        <div><small>JOSÉ DEBE DECIDIR</small><b>{len(report.get('decisions', []) or [])}</b><span>solo alta autoridad</span></div>
        <div><small>SEÑALES DE COMPRA</small><b>{int(counts.get('public_procurement_signals') or 0)}</b><span>registradas</span></div>
      </div>
    </section>
    """


def render_secretary_page(state: Dict[str, Any]) -> str:
    r = state.get("executive_secretary", {}) or build_secretary_snapshot(state, mutate_memory=False)
    deadlines = r.get("deadlines", []) or []
    deadlines_html = "".join(
        f'<div class="sec-row"><div class="sec-row-head"><b>{_esc(x.get("title"))}</b><span>{_esc(x.get("when"))}</span></div><div class="sec-meta">{_esc(x.get("kind"))} · {_esc(x.get("id"))}</div></div>'
        for x in deadlines
    ) or '<div class="sec-empty">No hay vencimientos estructurados registrados.</div>'
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LUMEN · Secretaría Ejecutiva</title>{css()}</head>
    <body><main class="sec-page"><a class="back" href="/command-center">← Centro de Control</a>
      <div class="sec-title"><small>SECRETARÍA EJECUTIVA</small><h1>Buenos días, José.</h1><p>{_esc(r.get('brief'))}</p><span>Actualizado {_esc(r.get('updated_at'))}</span></div>
      <div class="sec-columns">
        <section><h2>Noticias y novedades comerciales</h2>{_section_rows(r.get('news', []), kind='news')}</section>
        <section><h2>Pendientes de hoy</h2>{_section_rows(r.get('pending', []), kind='pending')}</section>
      </div>
      <div class="sec-columns">
        <section class="decision-zone"><h2>José debe decidir</h2>{_section_rows(r.get('decisions', []), kind='decision')}</section>
        <section><h2>Administración y seguimiento</h2>{_section_rows(r.get('admin_attention', []), kind='admin')}</section>
      </div>
      <div class="sec-columns">
        <section><h2>Próximos vencimientos</h2>{deadlines_html}</section>
        <section><h2>Resuelto / actualizado por LUMEN</h2>{_section_rows(r.get('resolved', []), kind='resolved')}</section>
      </div>
      <div class="sec-policy">La Secretaría ordena, resume, persigue pendientes y prepara información. No firma contratos, no paga, no compra y no acepta términos vinculantes.</div>
    </main></body></html>"""


def inject_secretary_strip(page: str, state: Dict[str, Any]) -> str:
    if "SECRETARÍA EJECUTIVA · LUMEN" in page:
        return page
    block = css() + render_secretary_strip(state)
    marker = '<div class="grid hero">'
    if marker in page:
        return page.replace(marker, block + marker, 1)
    marker = '<div class="hero grid">'
    if marker in page:
        return page.replace(marker, block + marker, 1)
    marker = '<main>'
    if marker in page:
        return page.replace(marker, marker + block, 1)
    return page + block


def css() -> str:
    return """<style>
    .sec-strip{margin:0 0 12px;padding:17px;border:1px solid #4b5c28;border-radius:18px;background:linear-gradient(135deg,#111a0a,#17230d 52%,#0b1715);box-shadow:0 12px 32px #0004}.sec-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}.sec-head small,.sec-title small{font-size:10px;letter-spacing:.16em;color:#d7ff64}.sec-head h2{font-size:20px;margin:5px 0 4px}.sec-head p{margin:0;color:#b9c9b2;line-height:1.45}.sec-open{white-space:nowrap;background:#d7ff64;color:#071008!important;padding:9px 12px;border-radius:999px;font-weight:800}.sec-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:14px}.sec-stats>div{border:1px solid #364d26;background:#101b0e;border-radius:12px;padding:10px}.sec-stats small{display:block;color:#91a984;font-size:9px}.sec-stats b{display:block;color:#d7ff64;font-size:22px;margin-top:3px}.sec-stats span{display:block;color:#84937e;font-size:9px;margin-top:2px}
    body{background:#061018;color:#eef7fb;font:14px Inter,ui-sans-serif,system-ui,-apple-system;margin:0}.sec-page{max-width:1280px;margin:auto;padding:22px}.back{color:#80cfff;text-decoration:none}.sec-title{margin:22px 0;padding:22px;border:1px solid #425527;border-radius:20px;background:linear-gradient(135deg,#101a0b,#17240f)}.sec-title h1{font-size:32px;margin:5px 0}.sec-title p{font-size:16px;color:#c7d5bf;max-width:900px}.sec-title span{font-size:10px;color:#81917a}.sec-columns{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:12px 0}.sec-columns>section{background:#0b1822;border:1px solid #1a3a4b;border-radius:17px;padding:16px}.sec-columns h2{margin:0 0 10px;font-size:17px}.decision-zone{border-color:#60471d!important}.sec-row{padding:11px 0;border-bottom:1px solid #17303e}.sec-row:last-child{border-bottom:0}.sec-row-head{display:flex;justify-content:space-between;gap:10px}.sec-row-head>b{font-size:13px}.sec-row-head>span{font-size:9px;border:1px solid #45602d;border-radius:999px;padding:3px 7px;color:#d7ff64;white-space:nowrap}.sec-meta{font-size:9px;color:#7892a2;margin-top:3px}.sec-row p{margin:5px 0 0;color:#b9cbd5;font-size:12px;line-height:1.45}.sec-reco{margin-top:7px;padding:7px;border-left:2px solid #d7ff64;color:#d7dfc7}.sec-empty{padding:13px;border:1px dashed #315d48;border-radius:10px;color:#8eb2a0}.sec-policy{margin:14px 0;padding:12px;border-radius:12px;background:#0b1519;color:#8299a6;font-size:11px}
    @media(max-width:760px){.sec-head{flex-direction:column}.sec-stats,.sec-columns{grid-template-columns:1fr 1fr}.sec-title h1{font-size:26px}}@media(max-width:520px){.sec-stats,.sec-columns{grid-template-columns:1fr}.sec-open{width:100%;text-align:center;box-sizing:border-box}}
    </style>"""
