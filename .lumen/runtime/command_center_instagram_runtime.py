from __future__ import annotations

"""Add Instagram Operator visibility to the owner Command Center."""

import html
from typing import Any, Dict

from fastapi import Request
from fastapi.responses import Response

import control_tower as _ct
from app import STATE, load_state
from outbound_web import app

VERSION = "1.3-command-center-instagram"
_ORIGINAL_BUILD = _ct.build_control_tower
_ORIGINAL_RENDER = _ct.render_control_tower


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _operator_snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    operator = dict(state.get("instagram_operator", {}) or {})
    return {
        "status": operator.get("status") or "active",
        "inbox_total": _i(operator.get("inbox_total")),
        "pending_review": _i(operator.get("pending_review")),
        "commercial_signals": _i(operator.get("commercial_signals")),
        "leads_total": _i(operator.get("leads_total")),
        "sent_total": _i(operator.get("sent_total")),
        "send_enabled": bool(operator.get("send_enabled")),
        "updated_at": operator.get("updated_at"),
    }


def _instagram_css() -> str:
    return """
<style id="lumen-instagram-cc-css">
.ig-section{margin:0 0 14px}.ig-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}.ig-cta{display:flex;justify-content:space-between;align-items:center;gap:12px}.ig-button{display:inline-block;background:#d7ff64;color:#071018!important;border-radius:9px;padding:10px 14px;font-weight:850;text-decoration:none!important}.ig-state{color:var(--good);font-weight:800}.ig-note{font-size:11px;color:var(--muted);margin-top:4px}.ig-floating{position:fixed;left:14px;bottom:18px;z-index:10050;background:#d7ff64;color:#071018!important;border:1px solid #efffae;border-radius:999px;padding:12px 16px;font-weight:950;text-decoration:none!important;box-shadow:0 10px 34px #0009;letter-spacing:.01em}
@media(max-width:900px){.ig-grid{grid-template-columns:1fr 1fr}.ig-cta{align-items:flex-start;flex-direction:column}}
@media(max-width:620px){.ig-grid{grid-template-columns:1fr 1fr}.ig-floating{left:12px;bottom:76px;padding:11px 14px;font-size:13px}}
</style>
"""


def _instagram_section(ig: Dict[str, Any]) -> str:
    return f"""
<section class="ig-section" id="instagram-operator-card">
  <div class="card">
    <div class="ig-cta">
      <div>
        <div class="label">Canal conectado</div>
        <h2 style="margin:5px 0 0">Instagram Operator</h2>
        <div class="ig-note">Bandeja inteligente, clasificación comercial, CRM y respuestas con aprobación humana.</div>
      </div>
      <a class="ig-button" href="/instagram">Abrir Instagram Operator</a>
    </div>
    <div class="ig-grid" style="margin-top:12px">
      <div><div class="label">Inbox</div><div class="metric">{_i(ig.get('inbox_total'))}</div></div>
      <div><div class="label">Pendientes</div><div class="metric">{_i(ig.get('pending_review'))}</div></div>
      <div><div class="label">Señales comerciales</div><div class="metric lime">{_i(ig.get('commercial_signals'))}</div></div>
      <div><div class="label">Leads</div><div class="metric good">{_i(ig.get('leads_total'))}</div></div>
      <div><div class="label">Enviadas</div><div class="metric">{_i(ig.get('sent_total'))}</div></div>
    </div>
    <div class="ig-note">Estado: <span class="ig-state">{_esc(ig.get('status') or 'active')}</span> · envío automático: no; cada respuesta requiere aprobación.</div>
  </div>
</section>
<a class="ig-floating" id="instagram-operator-floating" href="/instagram">Instagram Operator</a>
"""


def inject_instagram_strip(page: str, state: Dict[str, Any]) -> str:
    if "lumen-instagram-cc-css" not in page:
        page = page.replace("</head>", _instagram_css() + "</head>", 1)
    if "instagram-operator-card" not in page:
        section = _instagram_section(_operator_snapshot(state))
        marker = '<div class="grid hero">'
        if marker in page:
            page = page.replace(marker, section + marker, 1)
        else:
            page = page.replace("</body>", section + "</body>", 1)
    elif "instagram-operator-floating" not in page:
        page = page.replace("</body>", '<a class="ig-floating" id="instagram-operator-floating" href="/instagram">Instagram Operator</a></body>', 1)
    return page


def instagram_build_control_tower(state: Dict[str, Any], db_status: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = dict(_ORIGINAL_BUILD(state, db_status) or {})
    snapshot["instagram_operator"] = _operator_snapshot(state)
    state["control_tower"] = snapshot
    return snapshot


def instagram_render_control_tower(snapshot: Dict[str, Any]) -> str:
    page = _ORIGINAL_RENDER(snapshot)
    ig = dict(snapshot.get("instagram_operator", {}) or {})
    if "lumen-instagram-cc-css" not in page:
        page = page.replace("</head>", _instagram_css() + "</head>", 1)
    if "instagram-operator-card" not in page:
        section = _instagram_section(ig)
        marker = '<div class="grid hero">'
        if marker in page:
            page = page.replace(marker, section + marker, 1)
        else:
            page = page.replace("</body>", section + "</body>", 1)
    return page


_ct.build_control_tower = instagram_build_control_tower
_ct.render_control_tower = instagram_render_control_tower


@app.middleware("http")
async def command_center_instagram_injector(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/command-center":
        return response
    if "text/html" not in str(response.headers.get("content-type") or ""):
        return response

    try:
        load_state()
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8", errors="replace")
        text = inject_instagram_strip(text, STATE)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        print({"command_center_instagram_injector": {"status": "applied", "visible": "instagram-operator-card" in text, "floating": "instagram-operator-floating" in text, "placement": "top"}}, flush=True)
        return Response(content=text, status_code=response.status_code, headers=headers, media_type="text/html")
    except Exception as exc:
        print({"command_center_instagram_injector": {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}}, flush=True)
        return response


print({"command_center_instagram_runtime": {"version": VERSION, "status": "active", "route": "/instagram", "direct_injector": True, "placement": "top", "floating_launcher": True}}, flush=True)
