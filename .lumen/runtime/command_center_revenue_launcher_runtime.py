from __future__ import annotations

"""Persistent Revenue Cockpit launcher inside the owner Command Center.

UI-only. Adds a visible route back to /revenue-cockpit so the dedicated revenue
view can always be re-entered after navigating away. No spend, send caps,
commercial authority, contracts, payments or state are changed.
"""

from fastapi import Request
from fastapi.responses import Response

from outbound_web import app

VERSION = "1.0-command-center-revenue-launcher"

STYLE = """
<style id="lumen-revenue-launcher-css">
#lumen-revenue-launcher{position:sticky;top:0;z-index:99990;max-width:1480px;margin:0 auto;padding:8px 14px 0;font-family:Inter,ui-sans-serif,system-ui,-apple-system}
#lumen-revenue-launcher .lrl-wrap{display:flex;align-items:center;justify-content:space-between;gap:10px;border:1px solid #31536a;background:rgba(5,18,26,.96);backdrop-filter:blur(10px);border-radius:13px;padding:9px 10px;box-shadow:0 8px 22px #0006}
#lumen-revenue-launcher .lrl-title{font-size:10px;font-weight:900;letter-spacing:.12em;color:#8bd8ff;text-transform:uppercase}
#lumen-revenue-launcher a{display:inline-flex;align-items:center;justify-content:center;text-decoration:none;background:#d7ff64;color:#07100a;border:1px solid #d7ff64;border-radius:10px;padding:9px 12px;font-size:12px;font-weight:950;white-space:nowrap}
@media(max-width:700px){#lumen-revenue-launcher{padding:7px 9px 0}#lumen-revenue-launcher .lrl-title{display:none}#lumen-revenue-launcher .lrl-wrap{padding:7px}#lumen-revenue-launcher a{width:100%;font-size:13px;padding:10px 12px}}
</style>
"""

LAUNCHER = """
<div id="lumen-revenue-launcher"><div class="lrl-wrap"><div class="lrl-title">LUMEN · NAVEGACIÓN COMERCIAL</div><a href="/revenue-cockpit">Abrir Revenue Cockpit →</a></div></div>
"""


def _inject(page: str) -> str:
    if "lumen-revenue-launcher-css" not in page:
        page = page.replace("</head>", STYLE + "</head>", 1)
    if "lumen-revenue-launcher" in page:
        return page
    return page.replace("<body>", "<body>" + LAUNCHER, 1)


@app.middleware("http")
async def command_center_revenue_launcher(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/command-center" or request.method != "GET" or "text/html" not in str(response.headers.get("content-type") or ""):
        return response
    try:
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = _inject(body.decode("utf-8", errors="replace"))
        headers = dict(response.headers)
        headers.pop("content-length", None)
        print({"command_center_revenue_launcher": {"version": VERSION, "status": "applied", "visible": "lumen-revenue-launcher" in text}}, flush=True)
        return Response(content=text, status_code=response.status_code, headers=headers, media_type="text/html")
    except Exception as exc:
        print({"command_center_revenue_launcher": {"version": VERSION, "status": "error", "error": f"{type(exc).__name__}: {str(exc)[:220]}"}}, flush=True)
        return response


print({"command_center_revenue_launcher_runtime": {"version": VERSION, "status": "installed", "route": "/command-center", "target": "/revenue-cockpit", "ui_only": True}}, flush=True)
