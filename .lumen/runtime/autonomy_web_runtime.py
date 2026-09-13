from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

import journal_main
from app import STATE, auth, load_state
from autonomy_operating_system import build_autonomy_snapshot
from autonomy_panel import inject_autonomy_strip, render_autonomy_page


VERSION = "1.0-autonomy-web-runtime"
_ORIGINAL_INJECT = journal_main.inject_watchdog_strip


def _inject_with_autonomy(page: str, state):
    page = _ORIGINAL_INJECT(page, state)
    return inject_autonomy_strip(page, state)


journal_main.inject_watchdog_strip = _inject_with_autonomy


@journal_main.app.get("/autonomia", response_class=HTMLResponse, include_in_schema=False)
def autonomy_page(_=Depends(auth)):
    load_state()
    snapshot = STATE.get("autonomy_operating_system", {}) or build_autonomy_snapshot(STATE, mutate=False)
    shadow = dict(STATE)
    shadow["autonomy_operating_system"] = snapshot
    return HTMLResponse(render_autonomy_page(shadow))


print({"autonomy_web_runtime": {"status": "active", "version": VERSION, "route": "/autonomia"}}, flush=True)
