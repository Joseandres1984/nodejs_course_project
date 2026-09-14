from __future__ import annotations

"""Add Instagram Operator visibility to the owner Command Center."""

import html
from typing import Any, Dict

import control_tower as _ct

VERSION = "1.0-command-center-instagram"
_ORIGINAL_BUILD = _ct.build_control_tower
_ORIGINAL_RENDER = _ct.render_control_tower


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def instagram_build_control_tower(state: Dict[str, Any], db_status: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = dict(_ORIGINAL_BUILD(state, db_status) or {})
    operator = dict(state.get("instagram_operator", {}) or {})
    snapshot["instagram_operator"] = {
        "status": operator.get("status") or "active",
        "inbox_total": _i(operator.get("inbox_total")),
        "pending_review": _i(operator.get("pending_review")),
        "commercial_signals": _i(operator.get("commercial_signals")),
        "leads_total": _i(operator.get("leads_total")),
        "sent_total": _i(operator.get("sent_total")),
        "send_enabled": bool(operator.get("send_enabled")),
        "updated_at": operator.get("updated_at"),
    }
    state["control_tower"] = snapshot
    return snapshot


def instagram_render_control_tower(snapshot: Dict[str, Any]) -> str:
    page = _ORIGINAL_RENDER(snapshot)
    ig = snapshot.get("instagram_operator", {}) or {}

    css = """
<style id="lumen-instagram-cc-css">
.ig-section{margin-top:14px}.ig-link-card{display:block;color:inherit;text-decoration:none}.ig-link-card:hover{border-color:#4f7890}.ig-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}.ig-cta{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:10px}.ig-button{display:inline-block;background:#d7ff64;color:#071018!important;border-radius:9px;padding:10px 14px;font-weight:850;text-decoration:none!important}.ig-state{color:var(--good);font-weight:800}.ig-note{font-size:11px;color:var(--muted);margin-top:4px}
@media(max-width:900px){.ig-grid{grid-template-columns:1fr 1fr}.ig-cta{align-items:flex-start;flex-direction:column}}
@media(max-width:620px){.ig-grid{grid-template-columns:1fr 1fr}}
</style>
"""
    if "lumen-instagram-cc-css" not in page:
        page = page.replace("</head>", css + "</head>", 1)

    section = f"""
<section class="ig-section">
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
"""
    if "Abrir Instagram Operator" not in page:
        page = page.replace("</body>", section + "</body>", 1)
    return page


_ct.build_control_tower = instagram_build_control_tower
_ct.render_control_tower = instagram_render_control_tower
print({"command_center_instagram_runtime": {"version": VERSION, "status": "active", "route": "/instagram"}}, flush=True)
