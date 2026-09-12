import os, secrets
from datetime import datetime, timezone
from typing import Dict

import psycopg
from psycopg.types.json import Jsonb
from fastapi import FastAPI, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from commerce import DEFAULT_POLICIES, approve_and_close, commerce_tick, ensure_commerce_state

app = FastAPI(title="LUMEN B2B", version="1.4-autonomous-commerce")
security = HTTPBasic()
ADMIN_USER = os.getenv("LUMEN_ADMIN_USER", "socio")
ADMIN_PASSWORD = os.getenv("LUMEN_ADMIN_PASSWORD", "change-me")
LIVE_OUTBOUND = os.getenv("LUMEN_LIVE_OUTBOUND", "false").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_STATUS = {"configured": bool(DATABASE_URL), "connected": False, "last_error": None}


def default_state():
    state = {
        "buyers": [], "suppliers": [], "opportunities": [], "deals": [], "activity": [],
        "standing_goals": [
            "Encontrar compradores B2B de alto valor", "Construir una red sólida de proveedores",
            "Crear negocios rentables y repetibles", "Proteger margen, caja y reputación",
        ],
        "ticks": 0, "last_tick": None, "last_tick_origin": None,
        "policies": dict(DEFAULT_POLICIES),
    }
    ensure_commerce_state(state)
    return state


STATE: Dict[str, object] = default_state()


def now(): return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def log(msg: str):
    STATE.setdefault("activity", []).insert(0, {"ts": now(), "msg": msg})
    STATE["activity"] = STATE["activity"][:100]


def ensure_db():
    if not DATABASE_URL: return False
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS lumen_state (
                    state_key TEXT PRIMARY KEY, payload JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        DB_STATUS.update({"connected": True, "last_error": None}); return True
    except Exception as exc:
        DB_STATUS.update({"connected": False, "last_error": str(exc)[:180]}); return False


def load_state():
    if not ensure_db(): return False
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM lumen_state WHERE state_key='global'"); row = cur.fetchone()
        if row and isinstance(row[0], dict):
            current = default_state(); current.update(row[0]); ensure_commerce_state(current)
            STATE.clear(); STATE.update(current)
            DB_STATUS.update({"connected": True, "last_error": None}); return True
        return False
    except Exception as exc:
        DB_STATUS.update({"connected": False, "last_error": str(exc)[:180]}); return False


def save_state():
    if not ensure_db(): return False
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO lumen_state(state_key,payload,updated_at) VALUES ('global',%s,NOW())
                    ON CONFLICT (state_key) DO UPDATE SET payload=EXCLUDED.payload,updated_at=NOW()""", (Jsonb(STATE),))
        DB_STATUS.update({"connected": True, "last_error": None}); return True
    except Exception as exc:
        DB_STATUS.update({"connected": False, "last_error": str(exc)[:180]}); return False


def auth(c: HTTPBasicCredentials = Depends(security)):
    if not (secrets.compare_digest(c.username, ADMIN_USER) and secrets.compare_digest(c.password, ADMIN_PASSWORD)):
        raise HTTPException(status_code=401, detail="No autorizado", headers={"WWW-Authenticate": "Basic"})
    return c.username


def opportunity_score(demand, margin, recurrence, fit, risk, complexity):
    return round(max(0, min(100, demand*.24 + margin*.22 + recurrence*.20 + fit*.18 - risk*.10 - complexity*.06)), 1)


def seed_demo():
    if STATE["buyers"]: return
    STATE["buyers"] = [
        {"name":"Andes Process SA","sector":"Mantenimiento industrial","need":"instrumentación de presión","fit":94,"budget":86,"email":None,"email_verified":False,"source":"demo"},
        {"name":"Río Sur Ingeniería","sector":"Servicios de energía","need":"fuentes e instrumentación","fit":91,"budget":81,"email":None,"email_verified":False,"source":"demo"},
        {"name":"Pampa Facilities","sector":"MRO","need":"consumibles técnicos","fit":84,"budget":76,"email":None,"email_verified":False,"source":"demo"},
    ]
    STATE["suppliers"] = [
        {"name":"Delta Instrumentos","category":"instrumentación de presión","reliability":92,"price":86,"lead":88,"email":None,"email_verified":False,"source":"demo"},
        {"name":"TecnoSource LATAM","category":"fuentes e instrumentación","reliability":89,"price":90,"lead":81,"email":None,"email_verified":False,"source":"demo"},
        {"name":"Industrial Hub","category":"consumibles técnicos","reliability":82,"price":88,"lead":90,"email":None,"email_verified":False,"source":"demo"},
    ]
    log("Buyer Hunter y Supplier Hunter cargaron una red B2B demostrativa.")


def build_opportunities():
    created = 0
    for b in STATE["buyers"]:
        if any(o["buyer"] == b["name"] and o["need"] == b["need"] for o in STATE["opportunities"]): continue
        candidates = [s for s in STATE["suppliers"] if s["category"] == b["need"]]
        if not candidates: continue
        s = max(candidates, key=lambda x: x["reliability"] + x["price"] + x["lead"])
        score = opportunity_score(b["fit"], min(95,s["price"]+5), 82, b["fit"], max(5,100-s["reliability"]), 20)
        value = int(12000 + score * 1100)
        opp = {"id":f"OPP-{len(STATE['opportunities'])+1:04d}","buyer":b["name"],"supplier":s["name"],"need":b["need"],"score":score,"pipeline":value,"status":"calificada" if score>=70 else "investigación","source":"demo" if b.get("source")=="demo" else "real"}
        STATE["opportunities"].append(opp); created += 1
        log(f"Radar de Oportunidades creó {opp['id']} — {b['name']} ↔ {s['name']} (puntaje {score}).")
    return created


def open_deals():
    created = 0; existing = {d["opportunity_id"] for d in STATE["deals"]}
    for o in STATE["opportunities"]:
        if o["id"] in existing or o["score"] < 70: continue
        cp = round(min(.72,.18+o["score"]/180),2); ev = int(o["pipeline"]*cp)
        d = {"id":f"DEAL-{len(STATE['deals'])+1:04d}","opportunity_id":o["id"],"buyer":o["buyer"],"supplier":o["supplier"],"need":o["need"],"pipeline":o["pipeline"],"stage":"descubrimiento","close_prob":cp,"expected_value":ev,"company_profit":0.0,"company_share_pct":0.0,"next_action":"Investigar al comprador y preparar contacto personalizado","source":o.get("source","demo")}
        STATE["deals"].append(d); created += 1; log(f"Dealmaker abrió {d['id']} con valor esperado de USD {ev:,}.")
    return created


def autopilot_tick(origin="web"):
    STATE["ticks"] = int(STATE.get("ticks",0))+1; STATE["last_tick"] = now(); STATE["last_tick_origin"] = origin
    ensure_commerce_state(STATE)
    if not STATE["buyers"]: seed_demo()
    c1,c2 = build_opportunities(),open_deals(); commerce = commerce_tick(STATE)
    if c1==0 and c2==0 and not any(commerce.values()): log("Never Idle revisó el portfolio; no encontró una acción autónoma segura de mayor valor en este ciclo.")
    saved = save_state()
    return {"ticks":STATE["ticks"],"new_opportunities":c1,"new_deals":c2,"commerce":commerce,"persisted":saved,"origin":origin}


@app.get("/health")
def health(): return {"ok":True,"service":"lumen-b2b","version":"1.4-autonomous-commerce","time":now(),"postgres":DB_STATUS}

@app.get("/health/persistence")
def health_persistence():
    if not ensure_db(): raise HTTPException(status_code=503,detail={"ok":False,"postgres":DB_STATUS})
    return {"ok":True,"postgres":DB_STATUS}

@app.get("/api/state")
def api_state(_=Depends(auth)):
    load_state(); ensure_commerce_state(STATE); return {"state":STATE,"postgres":DB_STATUS}

@app.post("/api/autopilot/tick")
def api_tick(_=Depends(auth)):
    load_state(); return autopilot_tick("dashboard")

@app.post("/api/signal")
def api_signal(company:str=Form(...),need:str=Form(...),fit:int=Form(80),email:str=Form(""),_=Depends(auth)):
    load_state(); ensure_commerce_state(STATE)
    STATE["buyers"].append({"name":company,"sector":"señal humana","need":need,"fit":max(1,min(100,fit)),"budget":75,"email":email.strip() or None,"email_verified":False,"source":"human"})
    if not any(s["category"]==need for s in STATE["suppliers"]): STATE["suppliers"].append({"name":f"Candidato Scout para {need}","category":need,"reliability":72,"price":75,"lead":72,"email":None,"email_verified":False,"source":"scout_pending"})
    log(f"Señal recibida: {company} podría necesitar {need}. LUMEN creó un objetivo comercial."); autopilot_tick("señal humana")
    return RedirectResponse("/",status_code=303)

@app.post("/api/supplier")
def add_supplier(name:str=Form(...),category:str=Form(...),email:str=Form(""),reliability:int=Form(80),_=Depends(auth)):
    load_state(); ensure_commerce_state(STATE)
    STATE["suppliers"].append({"name":name,"category":category,"reliability":max(1,min(100,reliability)),"price":80,"lead":80,"email":email.strip() or None,"email_verified":False,"source":"human"})
    log(f"Supplier Hunter incorporó {name} como candidato para {category}."); save_state(); return RedirectResponse("/",status_code=303)

@app.post("/api/policies")
def update_policies(min_share:float=Form(...),target_share:float=Form(...),risk_reserve:float=Form(...),_=Depends(auth)):
    load_state(); ensure_commerce_state(STATE); p=STATE["policies"]
    p["min_company_share_pct"]=max(0,min(60,float(min_share))); p["target_company_share_pct"]=max(p["min_company_share_pct"],min(70,float(target_share))); p["risk_reserve_pct"]=max(0,min(20,float(risk_reserve)))
    log(f"Governor actualizó economía: mínimo nuestro {p['min_company_share_pct']:.1f}%, objetivo {p['target_company_share_pct']:.1f}%, reserva {p['risk_reserve_pct']:.1f}%."); save_state(); return RedirectResponse("/",status_code=303)

@app.post("/api/approve-close")
def approve_close(approval_id:str=Form(...),_=Depends(auth)):
    load_state(); ensure_commerce_state(STATE)
    try: approve_and_close(STATE,approval_id)
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc))
    save_state(); return RedirectResponse("/",status_code=303)

@app.post("/api/demo/reset")
def reset(_=Depends(auth)):
    STATE.clear(); STATE.update(default_state()); seed_demo(); autopilot_tick("reinicio demo"); return RedirectResponse("/",status_code=303)

CSS=""":root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#071018;color:#eaf2f7;font:14px Inter,ui-sans-serif,system-ui,-apple-system;padding:26px}.wrap{max-width:1380px;margin:auto}.top{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:20px}.logo{font-size:34px;font-weight:800;letter-spacing:.16em}.sub{color:#8ea6b5}.badge{padding:7px 10px;border:1px solid #284658;border-radius:999px;color:#9cddbb;background:#0d2019}.grid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.card{background:#0c1720;border:1px solid #183343;border-radius:15px;padding:16px;box-shadow:0 12px 28px #0005}.kpi{font-size:27px;font-weight:750;margin-top:7px}.label{color:#89a2b2;text-transform:uppercase;font-size:11px;letter-spacing:.12em}.two{display:grid;grid-template-columns:1.35fr 1fr;gap:12px;margin-top:12px}.three{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:12px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px 7px;border-bottom:1px solid #17303e}th{color:#7894a5;font-size:11px}.score,.profit{font-weight:700;color:#9ce8c5}.activity{max-height:390px;overflow:auto}.event{padding:9px 0;border-bottom:1px solid #17303e}.time{font-size:11px;color:#627f90}.goals{display:flex;gap:8px;flex-wrap:wrap}.goal{background:#101f2a;border:1px solid #234457;border-radius:9px;padding:8px 10px}form{display:flex;gap:8px;flex-wrap:wrap}input{background:#07131b;border:1px solid #254658;color:white;padding:10px;border-radius:8px;min-width:130px}button{background:#d7ff64;border:0;border-radius:8px;padding:10px 14px;font-weight:800;cursor:pointer}.section{margin-top:12px}.status{color:#d7ff64}.tiny{font-size:12px;color:#7894a5}@media(max-width:1050px){.grid{grid-template-columns:1fr 1fr 1fr}.three,.two{grid-template-columns:1fr}}@media(max-width:600px){body{padding:12px}.grid{grid-template-columns:1fr 1fr}.top{align-items:start;flex-direction:column}}"""

def money(n):
    try:return f"USD {float(n):,.0f}"
    except:return "USD 0"

@app.get("/",response_class=HTMLResponse)
def dashboard(_=Depends(auth)):
    load_state(); ensure_commerce_state(STATE)
    pipeline=sum(float(o.get("pipeline",0)) for o in STATE["opportunities"]); ev=sum(float(d.get("expected_value",0)) for d in STATE["deals"])
    our_profit=sum(float(d.get("company_profit",0)) for d in STATE["deals"] if d.get("stage")!="cerrado (simulación)"); closed_profit=sum(float(t.get("company_profit",0)) for t in STATE["transactions"])
    pending=[a for a in STATE["approvals"] if a.get("status")=="pending"]
    opp_rows="".join(f"<tr><td>{o['id']}</td><td>{o['buyer']}</td><td>{o['need']}</td><td class='score'>{o['score']}</td><td>{money(o['pipeline'])}</td></tr>" for o in sorted(STATE["opportunities"],key=lambda x:x["score"],reverse=True)[:8]) or "<tr><td colspan=5>Todavía no hay oportunidades</td></tr>"
    deal_rows="".join(f"<tr><td>{d['id']}</td><td>{d['buyer']}</td><td><span class='status'>{d['stage']}</span></td><td>{int(float(d.get('close_prob',0))*100)}%</td><td class='profit'>{money(d.get('company_profit',0))} ({float(d.get('company_share_pct',0)):.1f}%)</td></tr>" for d in sorted(STATE["deals"],key=lambda x:x.get("expected_value",0),reverse=True)[:10]) or "<tr><td colspan=5>Todavía no hay negocios</td></tr>"
    out_rows="".join(f"<tr><td>{m['id']}</td><td>{m['counterparty']}</td><td>{m['kind']}</td><td>{m['status']}</td></tr>" for m in STATE["outbox"][-8:][::-1]) or "<tr><td colspan=4>Sin comunicaciones todavía</td></tr>"
    offer_rows="".join(f"<tr><td>{o['id']}</td><td>{o['supplier']}</td><td>{money(o['amount'])}</td><td>{o['lead_days']} días</td><td>{o['source']}</td></tr>" for o in STATE["offers"][-8:][::-1]) or "<tr><td colspan=5>Sin ofertas todavía</td></tr>"
    approval_rows="".join(f"<tr><td>{a['id']}</td><td>{a['deal_id']}</td><td>{money(a.get('company_profit',0))}</td><td>{float(a.get('company_share_pct',0)):.1f}%</td><td><form method='post' action='/api/approve-close'><input type='hidden' name='approval_id' value='{a['id']}'><button>Aprobar cierre</button></form></td></tr>" for a in pending[:8]) or "<tr><td colspan=5>No hay cierres esperando aprobación</td></tr>"
    events="".join(f"<div class='event'><div>{e['msg']}</div><div class='time'>{e['ts']}</div></div>" for e in STATE["activity"][:18]) or "<div class='event'>Autopilot listo.</div>"
    goals="".join(f"<span class='goal'>{g}</span>" for g in STATE["standing_goals"]); mode="SALIDA REAL ACTIVADA" if LIVE_OUTBOUND else "SEGURO / SIMULACIÓN"; db="POSTGRES ACTIVO" if DB_STATUS["connected"] else "POSTGRES DESCONECTADO"; last=STATE.get("last_tick") or "sin ejecutar"; origin=STATE.get("last_tick_origin") or "—"; p=STATE["policies"]
    html=f"""<!doctype html><html lang='es'><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>LUMEN B2B</title><style>{CSS}</style></head><body><div class='wrap'><div class='top'><div><div class='logo'>LUMEN</div><div class='sub'>Sistema Operativo B2B Autónomo · Centro de Comando v1.4</div></div><div class='badge'>● AUTOPILOT · {mode} · {db}</div></div><div class='goals'>{goals}</div><div class='grid section'><div class='card'><div class='label'>Pipeline</div><div class='kpi'>{money(pipeline)}</div></div><div class='card'><div class='label'>Valor esperado</div><div class='kpi'>{money(ev)}</div></div><div class='card'><div class='label'>Ganancia nuestra potencial</div><div class='kpi'>{money(our_profit)}</div></div><div class='card'><div class='label'>Ganancia registrada</div><div class='kpi'>{money(closed_profit)}</div></div><div class='card'><div class='label'>Cierres pendientes</div><div class='kpi'>{len(pending)}</div></div></div><div class='two'><div><div class='card'><div class='label'>Radar de oportunidades</div><table><tr><th>ID</th><th>Comprador</th><th>Necesidad</th><th>Puntaje</th><th>Pipeline</th></tr>{opp_rows}</table></div><div class='card section'><div class='label'>Mesa de negocios</div><table><tr><th>ID</th><th>Comprador</th><th>Etapa</th><th>Cierre</th><th>Queda para nosotros</th></tr>{deal_rows}</table></div><div class='card section'><div class='label'>Cierres que requieren decisión humana</div><table><tr><th>ID</th><th>Deal</th><th>Ganancia</th><th>% nuestro</th><th>Acción</th></tr>{approval_rows}</table></div></div><div><div class='card'><div class='label'>Actividad autónoma</div><div class='activity'>{events}</div><div class='tiny section'>Último ciclo: {last} · origen: {origin}</div></div><div class='card section'><div class='label'>Política económica</div><div class='tiny'>LUMEN no debe avanzar un cierre por debajo del mínimo configurado.</div><form class='section' method='post' action='/api/policies'><input name='min_share' type='number' step='.1' value='{p['min_company_share_pct']}'><input name='target_share' type='number' step='.1' value='{p['target_company_share_pct']}'><input name='risk_reserve' type='number' step='.1' value='{p['risk_reserve_pct']}'><button>Guardar política</button></form><div class='tiny section'>Mínimo nuestro · Objetivo nuestro · Reserva de riesgo</div></div><div class='card section'><div class='label'>Dar una señal de comprador</div><form method='post' action='/api/signal'><input name='company' placeholder='Empresa' required><input name='need' placeholder='Qué podría necesitar' required><input name='email' placeholder='Email (opcional)'><input name='fit' type='number' min='1' max='100' value='85'><button>Crear objetivo</button></form></div><div class='card section'><div class='label'>Agregar proveedor</div><form method='post' action='/api/supplier'><input name='name' placeholder='Proveedor' required><input name='category' placeholder='Categoría' required><input name='email' placeholder='Email (opcional)'><input name='reliability' type='number' min='1' max='100' value='80'><button>Incorporar</button></form></div><form class='section' method='post' action='/api/autopilot/tick'><button>Ejecutar ciclo ahora</button></form></div></div><div class='three'><div class='card'><div class='label'>Comunicaciones preparadas</div><table><tr><th>ID</th><th>Contraparte</th><th>Tipo</th><th>Estado</th></tr>{out_rows}</table></div><div class='card'><div class='label'>Ofertas recibidas / cargadas</div><table><tr><th>ID</th><th>Proveedor</th><th>Importe</th><th>Entrega</th><th>Fuente</th></tr>{offer_rows}</table></div><div class='card'><div class='label'>Gobernanza</div><div class='event'>Compromiso financiero real: <b>DESHABILITADO</b></div><div class='event'>Contratos: aprobación humana</div><div class='event'>Contacto no verificado: no enviar</div><div class='event'>Salida real: {'ACTIVA' if LIVE_OUTBOUND else 'INACTIVA'}</div></div></div><div class='sub section'>LUMEN calcula nuestra participación sobre cada operación. Cifras de demo no representan negocios reales ni beneficio garantizado.</div></div></body></html>"""
    return HTMLResponse(html)

@app.on_event("startup")
def startup():
    loaded=load_state()
    if not loaded: STATE.clear(); STATE.update(default_state()); seed_demo(); autopilot_tick("startup")
