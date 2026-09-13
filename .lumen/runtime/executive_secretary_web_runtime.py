from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

import journal_main
from app import STATE, auth, load_state
from executive_secretary import build_secretary_snapshot
from executive_secretary_panel import inject_secretary_strip, render_secretary_page


VERSION = "1.0-executive-secretary-web-runtime"
_ORIGINAL_WATCHDOG_INJECT = journal_main.inject_watchdog_strip


def _inject_with_secretary(page: str, state):
    page = _ORIGINAL_WATCHDOG_INJECT(page, state)
    return inject_secretary_strip(page, state)


journal_main.inject_watchdog_strip = _inject_with_secretary


@journal_main.app.get("/secretaria", response_class=HTMLResponse, include_in_schema=False)
def executive_secretary_page(_=Depends(auth)):
    load_state()
    # Preview current state without consuming the persisted 'new since last brief' memory. The worker
    # owns the official brief cadence and persists a new snapshot at the end of each complete cycle.
    snapshot = STATE.get("executive_secretary", {}) or build_secretary_snapshot(STATE, mutate_memory=False)
    shadow = dict(STATE)
    shadow["executive_secretary"] = snapshot
    return HTMLResponse(render_secretary_page(shadow))


print({"executive_secretary_web_runtime": {"status": "active", "version": VERSION, "route": "/secretaria"}}, flush=True)
