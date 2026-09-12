from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app import app, auth, load_state, DB_STATUS, STATE, ensure_commerce_state
from control_tower import build_control_tower, render_control_tower


@app.get("/health/persistence")
def persistence_health():
    loaded = load_state()
    if not DB_STATUS.get("connected"):
        raise HTTPException(status_code=503, detail={"postgres": DB_STATUS})
    return {"ok": True, "postgres": DB_STATUS, "state_loaded": loaded}


@app.get("/command")
def command_redirect(_=Depends(auth)):
    return RedirectResponse("/command-center", status_code=307)


@app.get("/command-center", response_class=HTMLResponse)
def command_center(_=Depends(auth)):
    loaded = load_state()
    if not loaded and DB_STATUS.get("configured") and not DB_STATUS.get("connected"):
        raise HTTPException(status_code=503, detail={"status": "control_tower_unavailable", "postgres": DB_STATUS})
    ensure_commerce_state(STATE)
    snapshot = build_control_tower(STATE, DB_STATUS)
    return HTMLResponse(render_control_tower(snapshot))


@app.get("/api/control-tower")
def api_control_tower(_=Depends(auth)):
    loaded = load_state()
    if not loaded and DB_STATUS.get("configured") and not DB_STATUS.get("connected"):
        raise HTTPException(status_code=503, detail={"status": "control_tower_unavailable", "postgres": DB_STATUS})
    ensure_commerce_state(STATE)
    return {"control_tower": build_control_tower(STATE, DB_STATUS), "postgres": DB_STATUS}
