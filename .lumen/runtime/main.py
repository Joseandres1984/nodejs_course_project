from fastapi import HTTPException
from app import app, load_state, DB_STATUS

@app.get("/health/persistence")
def persistence_health():
    loaded = load_state()
    if not DB_STATUS.get("connected"):
        raise HTTPException(status_code=503, detail={"postgres": DB_STATUS})
    return {"ok": True, "postgres": DB_STATUS, "state_loaded": loaded}
