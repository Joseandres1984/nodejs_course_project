import os, secrets
from datetime import datetime, timezone
from typing import Dict

import psycopg
from psycopg.types.json import Jsonb
from fastapi import FastAPI, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

app = FastAPI(title="LUMEN B2B", version="1.3-persistent")
security = HTTPBasic()

ADMIN_USER = os.getenv("LUMEN_ADMIN_USER", "socio")
ADMIN_PASSWORD = os.getenv("LUMEN_ADMIN_PASSWORD", "change-me")
LIVE_OUTBOUND = os.getenv("LUMEN_LIVE_OUTBOUND", "false").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_STATUS = {"configured": bool(DATABASE_URL), "connected": False, "last_error": None}

def default_state():
    return {
        "buyers": [], "suppliers": [], "opportunities": [], "deals": [], "activity": [],
        "standing_goals": [
            "Encontrar compradores B2B de alto valor",
            "Construir una red sólida de proveedores",
            "Crear negocios rentables y repetibles",
            "Proteger margen, caja y reputación",
        ],
        "ticks": 0, "last_tick": None, "last_tick_origin": None,
    }

STATE: Dict[str, object] = default_state()

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def log(msg: str):
    STATE.setdefault("activity", []).insert(0, {"ts": now(), "msg": msg})
    STATE["activity"] = STATE["activity"][:60]

def ensure_db():
    if not DATABASE_URL:
        return False
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS lumen_state (
                        state_key TEXT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
        DB_STATUS.update({"connected": True, "last_error": None})
        return True
    except Exception as exc:
        DB_STATUS.update({"connected": False, "last_error": str(exc)[:180]})
        return False

def load_state():
    if not ensure_db():
        return False
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM lumen_state WHERE state_key='global'")
                row = cur.fetchone()
        if row and isinstance(row[0], dict):
            current = default_state()
            current.update(row[0])
            STATE.clear(); STATE.update(current)
            DB_STATUS.update({"connected": True, "last_error": None})
            return True
        return False
    except Exception as exc:
        DB_STATUS.update({"connected": False, "last_error": str(exc)[:180]})
        return False

def save_state():
    if not ensure_db():
        return False
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO lumen_state(state_key, payload, updated_at)
                    VALUES ('global', %s, NOW())
                    ON CONFLICT (state_key)
                    DO UPDATE SET payload=EXCLUDED.payload, updated_at=NOW()
                """, (Jsonb(STATE),))
        DB_STATUS.update({"connected": True, "last_error": None})
        return True
    except Exception as exc:
        DB_STATUS.update({"connected": False, "last_error": str(exc)[:180]})
        return False

def auth(c: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(c.username, ADMIN_USER)
    ok_pass = secrets.compare_digest(c.password, ADMIN_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="No autorizado", headers={"WWW-Authenticate": "Basic"})
    return c.username

def opportunity_score(demand, margin, recurrence, fit, risk, complexity):
    return round(max(0, min(100, demand*.24 + margin*.22 + recurrence*.20 + fit*.18 - risk*.10 - complexity*.06)), 1)

def seed_demo():
    if STATE["buyers"]:
        return
    STATE["buyers"] = [
        {"name":"Andes Process SA","sector":"Mantenimiento industrial","need":"instrumentación de presión","fit":94,"budget":86},
        {"name":"Río Sur Ingeniería","sector":"Servicios de energía","need":"fuentes e instrumentación","fit":91,"budget":81},
        {"name":"Pampa Facilities","sector":"MRO","need":"consumibles técnicos","fit":84,"budget":76},
    ]
    STATE["suppliers"] = [
        {"name":"Delta Instrumentos","category":"instrumentación de presión","reliability":92,"price":86,"lead":88},
        {"name":"TecnoSource LATAM","category":"fuentes e instrumentación","reliability":89,"price":90,"lead":81},
        {"name":"Industrial Hub","category":"consumibles técnicos","reliability":82,"price":88,"lead":90},
    ]
    log("Supplier Hunter y Buyer Hunter generaron una red B2B demostrativa.")

def build_opportunities():
    created = 0
    for b in STATE["buyers"]:
        if any(o["buyer"] == b["name"] and o["need"] == b["need"] for o in STATE["opportunities"]):
            continue
        candidates = [s for s in STATE["suppliers"] if s["category"] == b["need"]]
        if not candidates:
            continue
        s = max(candidates, key=lambda x: x["reliability"] + x["price"] + x["lead"])
        demand, recurrence = b["fit"], 82
        margin = min(95, s["price"] + 5)
        risk = max(5, 100-s["reliability"])
        score = opportunity_score(demand, margin, recurrence, b["fit"], risk, 20)
        value = int(12000 + score * 1100)
        margin_value = int(value * (0.12 + score/1000))
        opp = {"id":f"OPP-{len(STATE['opportunities'])+1:04d}","buyer":b["name"],"supplier":s["name"],"need":b["need"],"score":score,"pipeline":value,"margin":margin_value,"status":"calificada" if score >= 70 else "investigación"}
        STATE["opportunities"].append(opp); created += 1
        log(f"Radar de Oportunidades creó {opp['id']} — {b['name']} ↔ {s['name']} (puntaje {score}).")
    return created

def open_deals():
    created = 0
    existing = {d["opportunity_id"] for d in STATE["deals"]}
    for o in STATE["opportunities"]:
        if o["id"] in existing or o["score"] < 70:
            continue
        close_prob = round(min(0.72, 0.18 + o["score"]/180), 2)
        ev = int(o["pipeline"] * close_prob)
        d = {"id":f"DEAL-{len(STATE['deals'])+1:04d}","opportunity_id":o["id"],"buyer":o["buyer"],"supplier":o["supplier"],"stage":"descubrimiento","close_prob":close_prob,"expected_value":ev,"margin":o["margin"],"next_action":"Investigar al comprador y preparar contacto personalizado"}
        STATE["deals"].append(d); created += 1
        log(f"Dealmaker abrió {d['id']} con valor esperado de USD {ev:,}.")
    return created

def autopilot_tick(origin="web"):
    STATE["ticks"] = int(STATE.get("ticks", 0)) + 1
    STATE["last_tick"] = now(); STATE["last_tick_origin"] = origin
    if not STATE["buyers"]:
        seed_demo()
    c1, c2 = build_opportunities(), open_deals()
    if c1 == 0 and c2 == 0:
        if STATE["deals"]:
            d = max(STATE["deals"], key=lambda x: x["expected_value"])
            stages = ["descubrimiento","calificado","propuesta","negociación"]
            idx = stages.index(d["stage"]) if d["stage"] in stages else 0
            if idx < len(stages)-1:
                d["stage"] = stages[idx+1]
                d["close_prob"] = round(min(.82, d["close_prob"] + .08), 2)
                d["expected_value"] = int(next(o["pipeline"] for o in STATE["opportunities"] if o["id"] == d["opportunity_id"]) * d["close_prob"])
                d["next_action"] = "Negociar valor, condiciones y recurrencia" if d["stage"] == "negociación" else "Avanzar la cuenta con un caso de negocio basado en evidencia"
                log(f"LUMEN DRIVE avanzó {d['id']} a {d['stage']} tras repriorizar por valor esperado.")
            else:
                log("Never Idle revisó el pipeline; no encontró una acción segura de mayor valor en este ciclo.")
    saved = save_state()
    return {"ticks":STATE["ticks"],"new_opportunities":c1,"new_deals":c2,"persisted":saved,"origin":origin}

@app.get("/health")
def health():
    return {"ok": True, "service":"lumen-b2b", "version":"1.3-persistent", "time": now(), "postgres": DB_STATUS}

@app.get("/api/state")
def api_state(_=Depends(auth)):
    return {"state": STATE, "postgres": DB_STATUS}

@app.post("/api/autopilot/tick")
def api_tick(_=Depends(auth)):
    load_state()
    return autopilot_tick("dashboard")

@app.post("/api/signal")
def api_signal(company: str = Form(...), need: str = Form(...), fit: int = Form(80), _=Depends(auth)):
    load_state()
    STATE["buyers"].append({"name":company,"sector":"señal humana","need":need,"fit":max(1,min(100,fit)),"budget":75})
    if not any(s["category"] == need for s in STATE["suppliers"]):
        STATE["suppliers"].append({"name":f"Candidato Scout para {need}","category":need,"reliability":72,"price":75,"lead":72})
    log(f"Señal humana recibida: {company} podría necesitar {need}. LUMEN creó un objetivo de investigación.")
    autopilot_tick("señal humana")
    return RedirectResponse("/", status_code=303)

@app.post("/api/demo/reset")
def reset(_=Depends(auth)):
    STATE.clear(); STATE.update(default_state())
    seed_demo(); autopilot_tick("reinicio demo")
    return RedirectResponse("/", status_code=303)

CSS = """
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#071018;color:#eaf2f7;font:14px Inter,ui-sans-serif,system-ui,-apple-system;padding:28px}a{color:#8bd3ff}.wrap{max-width:1280px;margin:auto}.top{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:22px}.logo{font-size:34px;font-weight:800;letter-spacing:.16em}.sub{color:#8ea6b5}.badge{padding:7px 10px;border:1px solid #284658;border-radius:999px;color:#9cddbb;background:#0d2019}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{background:#0c1720;border:1px solid #183343;border-radius:15px;padding:17px;box-shadow:0 12px 28px #0005}.kpi{font-size:29px;font-weight:750;margin-top:7px}.label{color:#89a2b2;text-transform:uppercase;font-size:11px;letter-spacing:.12em}.two{display:grid;grid-template-columns:1.4fr 1fr;gap:12px;margin-top:12px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px 8px;border-bottom:1px solid #17303e}th{color:#7894a5;font-size:11px}.score{font-weight:700;color:#9ce8c5}.activity{max-height:390px;overflow:auto}.event{padding:10px 0;border-bottom:1px solid #17303e}.time{font-size:11px;color:#627f90}.goals{display:flex;gap:8px;flex-wrap:wrap}.goal{background:#101f2a;border:1px solid #234457;border-radius:9px;padding:8px 10px}form{display:flex;gap:8px;flex-wrap:wrap}input{background:#07131b;border:1px solid #254658;color:white;padding:10px;border-radius:8px;min-width:160px}button{background:#d7ff64;border:0;border-radius:8px;padding:10px 14px;font-weight:800;cursor:pointer}.muted{background:#18303e;color:#dce8ee}.section{margin-top:12px}.status{color:#d7ff64}@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}.two{grid-template-columns:1fr}}@media(max-width:520px){body{padding:14px}.grid{grid-template-columns:1fr}.top{align-items:start;flex-direction:column}}
"""

def money(n): return f"USD {n:,.0f}"

@app.get("/", response_class=HTMLResponse)
def dashboard(_=Depends(auth)):
    load_state()
    pipeline = sum(o["pipeline"] for o in STATE["opportunities"])
    ev = sum(d["expected_value"] for d in STATE["deals"])
    margin = sum(d["margin"] for d in STATE["deals"])
    opp_rows = "".join(f"<tr><td>{o['id']}</td><td>{o['buyer']}</td><td>{o['need']}</td><td class='score'>{o['score']}</td><td>{money(o['pipeline'])}</td></tr>" for o in sorted(STATE["opportunities"], key=lambda x:x["score"], reverse=True)[:8]) or "<tr><td colspan=5>Todavía no hay oportunidades</td></tr>"
    deal_rows = "".join(f"<tr><td>{d['id']}</td><td>{d['buyer']}</td><td><span class='status'>{d['stage']}</span></td><td>{int(d['close_prob']*100)}%</td><td>{money(d['expected_value'])}</td></tr>" for d in sorted(STATE["deals"], key=lambda x:x["expected_value"], reverse=True)[:8]) or "<tr><td colspan=5>Todavía no hay negocios</td></tr>"
    events = "".join(f"<div class='event'><div>{e['msg']}</div><div class='time'>{e['ts']}</div></div>" for e in STATE["activity"][:16]) or "<div class='event'>Autopilot listo.</div>"
    goals = "".join(f"<span class='goal'>{g}</span>" for g in STATE["standing_goals"])
    mode = "SALIDA REAL ACTIVADA" if LIVE_OUTBOUND else "SEGURO / SIMULACIÓN"
    db = "POSTGRES ACTIVO" if DB_STATUS["connected"] else "MEMORIA LOCAL"
    last = STATE.get("last_tick") or "sin ejecutar"; origin = STATE.get("last_tick_origin") or "—"
    html=f"""<!doctype html><html lang='es'><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>LUMEN B2B</title><style>{CSS}</style></head><body><div class='wrap'>
    <div class='top'><div><div class='logo'>LUMEN</div><div class='sub'>Sistema Operativo Emprendedor B2B Autónomo · Centro de Comando</div></div><div class='badge'>● AUTOPILOT · {mode} · {db}</div></div>
    <div class='goals'>{goals}</div>
    <div class='grid section'><div class='card'><div class='label'>Pipeline potencial</div><div class='kpi'>{money(pipeline)}</div></div><div class='card'><div class='label'>Valor esperado ajustado</div><div class='kpi'>{money(ev)}</div></div><div class='card'><div class='label'>Margen potencial</div><div class='kpi'>{money(margin)}</div></div><div class='card'><div class='label'>Ciclos autónomos</div><div class='kpi'>{STATE['ticks']}</div></div></div>
    <div class='two'><div><div class='card'><div class='label'>Radar de Oportunidades</div><table><tr><th>ID</th><th>Comprador</th><th>Necesidad</th><th>Puntaje</th><th>Pipeline</th></tr>{opp_rows}</table></div><div class='card section'><div class='label'>Mesa de Negocios</div><table><tr><th>ID</th><th>Comprador</th><th>Etapa</th><th>Cierre</th><th>Valor esperado</th></tr>{deal_rows}</table></div></div>
    <div><div class='card'><div class='label'>Actividad de LUMEN</div><div class='activity'>{events}</div><div class='time section'>Último ciclo: {last} · origen: {origin}</div></div><div class='card section'><div class='label'>Ingresar señal de mercado</div><form method='post' action='/api/signal'><input name='company' placeholder='Empresa' required><input name='need' placeholder='¿Qué podría necesitar?' required><input name='fit' type='number' min='1' max='100' value='85'><button>Dar señal a LUMEN</button></form><form class='section' method='post' action='/api/autopilot/tick'><button class='muted'>Ejecutar un ciclo ahora</button></form><form class='section' method='post' action='/api/demo/reset'><button class='muted'>Reiniciar demostración</button></form></div></div></div>
    <div class='sub section'>Governor activo · Sin compromisos financieros autónomos · Sin contacto real salvo activación explícita.</div></div></body></html>"""
    return HTMLResponse(html)

@app.on_event("startup")
def startup():
    loaded = load_state()
    if not loaded or not STATE.get("buyers"):
        seed_demo(); autopilot_tick("inicio web")
