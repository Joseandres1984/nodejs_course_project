from __future__ import annotations

"""Dedicated owner Revenue Cockpit.

Keeps the legacy Command Center available while exposing a clean revenue-only view.
Read-only: no spend, outbound caps, pricing authority, contracts or payment authority change.
"""

from fastapi import Depends
from fastapi.responses import HTMLResponse

from app import STATE, auth, load_state
from outbound_web import app
from command_center_revenue_v2_runtime import CSS, _render, _snapshot

VERSION = "2.2-dedicated-revenue-cockpit-back-nav"


@app.get("/revenue-cockpit", response_class=HTMLResponse, include_in_schema=False)
def dedicated_revenue_cockpit(_=Depends(auth)):
    load_state()
    cockpit = _render(_snapshot(STATE))
    shell_css = """
<style id="lumen-revenue-cockpit-shell-v22">
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 12% -8%,#17384b 0,#061018 38%);color:#eef7fb;font-family:Inter,ui-sans-serif,system-ui,-apple-system}.rc-shell{max-width:1480px;margin:0 auto;padding:12px 18px 0}.rc-shellbar{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid #31536a;background:#071720;border-radius:14px;padding:10px 12px}.rc-shellbrandwrap{display:flex;align-items:center;gap:10px;min-width:0}.rc-back{display:inline-flex;align-items:center;justify-content:center;text-decoration:none;color:#07100a;background:#d7ff64;border:1px solid #d7ff64;border-radius:9px;padding:8px 11px;font-size:12px;font-weight:950;white-space:nowrap;cursor:pointer}.rc-back:active{transform:translateY(1px)}.rc-shellbrand{font-size:11px;font-weight:950;letter-spacing:.16em;color:#d7ff64}.rc-shelllinks{display:flex;gap:8px;flex-wrap:wrap}.rc-shelllinks a{text-decoration:none;color:#bfeaff;border:1px solid #2d5063;border-radius:9px;padding:8px 10px;font-size:11px;font-weight:850}.rc-shelllinks a.primary{background:#d7ff64;color:#07100a;border-color:#d7ff64}@media(max-width:700px){.rc-shell{padding:9px 9px 0}.rc-shellbar{align-items:flex-start;flex-direction:column}.rc-shellbrandwrap{width:100%}.rc-shellbrand{font-size:10px;letter-spacing:.11em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.rc-shelllinks{width:100%}.rc-shelllinks a{flex:1;text-align:center}.rc-back{min-height:40px}}
</style>
"""
    nav = """
<div class="rc-shell"><div class="rc-shellbar"><div class="rc-shellbrandwrap"><a class="rc-back" href="/command-center" onclick="if(window.history.length>1){window.history.back();return false;}">← Volver</a><div class="rc-shellbrand">LUMEN · REVENUE COCKPIT 2.2</div></div><div class="rc-shelllinks"><a class="primary" href="/revenue-cockpit">Caja & Conversión</a><a href="/command-center">Command Center completo</a><a href="/services">Servicios</a><a href="/intelligence">Intelligence</a></div></div></div>
"""
    return HTMLResponse(
        "<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='30'><title>LUMEN · Revenue Cockpit</title>"
        + CSS + shell_css + "</head><body>" + nav + cockpit + "</body></html>"
    )


print({
    "revenue_cockpit_dedicated_runtime": {
        "version": VERSION,
        "status": "active",
        "route": "/revenue-cockpit",
        "legacy_command_center_preserved": True,
        "back_navigation": True,
        "back_fallback": "/command-center",
        "read_only": True,
        "spend_changed": False,
        "outbound_caps_changed": False,
        "binding_authority_changed": False,
    }
}, flush=True)