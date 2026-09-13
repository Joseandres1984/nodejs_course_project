from __future__ import annotations

import html
from typing import Any, Dict


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _state(state: Dict[str, Any]) -> Dict[str, Any]:
    return dict(state.get("social_distribution", {}) or {})


def inject_social_strip(text: str, state: Dict[str, Any]) -> str:
    if "SOCIAL DISTRIBUTION · SALIDA REAL" in text:
        return text
    s = _state(state)
    health = dict(state.get("social_connector_health", {}) or {})
    channels = health.get("facebook", {}), health.get("instagram", {}), health.get("linkedin_company", {})
    ready = sum(1 for x in channels if isinstance(x, dict) and x.get("ready"))
    live = bool(s.get("live_outbound") or health.get("live_outbound"))
    published = int(s.get("verified_published") or 0)
    failed = int(s.get("failed") or 0)
    awaiting = int(s.get("awaiting_connector") or 0)
    badge = "ACTIVO" if live and ready else ("LISTO PARA ACTIVAR" if ready else "FALTA CONECTAR CUENTAS")
    block = f"""
<section style='margin:16px 0;padding:18px;border:1px solid #1e3b47;border-radius:16px;background:#07151c'>
  <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'>
    <div>
      <div style='font-size:12px;letter-spacing:.08em;color:#8ba6b3'>SOCIAL DISTRIBUTION · SALIDA REAL</div>
      <div style='font-size:20px;font-weight:700;margin-top:4px'>{_esc(badge)}</div>
      <div style='margin-top:6px;color:#9eb0b9'>Canales listos: {ready}/3 · Publicaciones verificadas: {published} · Pendientes de conector: {awaiting} · Fallos: {failed}</div>
    </div>
    <a href='/social-distribution' style='display:inline-block;padding:10px 14px;border-radius:10px;background:#b7ff4a;color:#0a1318;text-decoration:none;font-weight:700'>Ver salida social</a>
  </div>
</section>
"""
    marker = "</main>"
    return text.replace(marker, block + marker, 1) if marker in text else block + text


def render_social_distribution_page(state: Dict[str, Any]) -> str:
    s = _state(state)
    health = dict(state.get("social_connector_health", {}) or {})
    jobs = [x for x in state.get("distribution_operator_jobs", []) or [] if x.get("channel") in {"facebook", "instagram", "linkedin_company"}]
    audit = list(state.get("social_dispatch_audit", []) or [])[-100:]

    def channel_card(key: str, title: str) -> str:
        row = dict(health.get(key, {}) or {})
        ready = bool(row.get("ready"))
        missing = ", ".join(row.get("missing", []) or [])
        extra = " · requiere activo visual" if row.get("requires_media_asset") else ""
        return f"<div class='card'><h3>{_esc(title)}</h3><b>{'LISTO' if ready else 'NO CONECTADO'}</b><p>{_esc(missing or 'Credenciales configuradas')}{_esc(extra)}</p></div>"

    rows = "".join(
        f"<tr><td>{_esc(x.get('channel'))}</td><td>{_esc(x.get('audience'))}</td><td>{_esc(x.get('status'))}</td><td>{_esc(x.get('provider'))}</td><td>{_esc(x.get('external_post_id') or x.get('external_url'))}</td><td>{_esc(x.get('last_error'))}</td></tr>"
        for x in jobs[-100:]
    ) or "<tr><td colspan='6'>Todavía no hay trabajos sociales materializados.</td></tr>"
    audit_rows = "".join(
        f"<tr><td>{_esc(x.get('ts'))}</td><td>{_esc(x.get('channel'))}</td><td>{_esc(x.get('status'))}</td><td>{_esc(x.get('provider'))}</td><td>{_esc(x.get('external_post_id') or x.get('external_url'))}</td><td>{_esc(x.get('error'))}</td></tr>"
        for x in reversed(audit)
    ) or "<tr><td colspan='6'>Sin intentos externos todavía.</td></tr>"

    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>LUMEN · Social Distribution</title>
<style>body{{font-family:Arial,sans-serif;background:#061117;color:#e8f0f4;margin:0}}main{{max-width:1200px;margin:auto;padding:24px}}a{{color:#b7ff4a}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}.card{{background:#0b1d25;border:1px solid #23404b;border-radius:14px;padding:16px}}table{{width:100%;border-collapse:collapse;margin-top:12px;font-size:13px}}th,td{{border-bottom:1px solid #213843;padding:9px;text-align:left;vertical-align:top}}th{{color:#9fb2bb}}code{{color:#b7ff4a}}</style></head>
<body><main><p><a href='/command-center'>← Command Center</a></p><h1>Social Distribution</h1>
<p>Estado real de los conectores. LUMEN sólo marca una publicación como verificada cuando el canal devuelve un ID o URL externo.</p>
<div class='grid'><div class='card'><h3>Modo de salida</h3><b>{'ACTIVO' if s.get('live_outbound') else 'DESACTIVADO'}</b><p>Máximo canario/ciclo: {int(s.get('daily_remaining') or 0)} restantes hoy.</p></div>{channel_card('facebook','Facebook')}{channel_card('instagram','Instagram')}{channel_card('linkedin_company','LinkedIn empresa')}</div>
<h2>Trabajos sociales</h2><table><thead><tr><th>Canal</th><th>Audiencia</th><th>Estado</th><th>Proveedor</th><th>Comprobante</th><th>Error</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Auditoría de intentos</h2><table><thead><tr><th>Fecha</th><th>Canal</th><th>Estado</th><th>Proveedor</th><th>Comprobante</th><th>Error</th></tr></thead><tbody>{audit_rows}</tbody></table>
<p><strong>Regla:</strong> preparado ≠ publicado. Publicado sólo existe con comprobante externo real.</p></main></body></html>"""
