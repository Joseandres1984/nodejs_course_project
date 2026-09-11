import os, secrets, time, random
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import FastAPI, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

app = FastAPI(title="LUMEN B2B", version="1.2-online")
security = HTTPBasic()

ADMIN_USER = os.getenv("LUMEN_ADMIN_USER", "socio")
ADMIN_PASSWORD = os.getenv("LUMEN_ADMIN_PASSWORD", "change-me")
LIVE_OUTBOUND = os.getenv("LUMEN_LIVE_OUTBOUND", "false").lower() == "true"

STATE: Dict[str, object] = {
    "buyers": [], "suppliers": [], "opportunities": [], "deals": [], "activity": [],
    "standing_goals": [
        "Find high-value B2B buyers", "Build strong supplier network",
        "Create profitable repeatable deals", "Protect margin and reputation"
    ],
    "ticks": 0,
}

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def log(msg: str):
    STATE["activity"].insert(0, {"ts": now(), "msg": msg})
    STATE["activity"] = STATE["activity"][:40]

def auth(c: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(c.username, ADMIN_USER)
    ok_pass = secrets.compare_digest(c.password, ADMIN_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return c.username

def opportunity_score(demand, margin, recurrence, fit, risk, complexity):
    return round(max(0, min(100, demand*.24 + margin*.22 + recurrence*.20 + fit*.18 - risk*.10 - complexity*.06)), 1)

def seed_demo():
    if STATE["buyers"]:
        return
    STATE["buyers"] = [
        {"name":"Andes Process SA","sector":"Industrial maintenance","need":"pressure instrumentation","fit":94,"budget":86},
        {"name":"Río Sur Ingeniería","sector":"Energy services","need":"power supplies and instrumentation","fit":91,"budget":81},
        {"name":"Pampa Facilities","sector":"MRO","need":"technical consumables","fit":84,"budget":76},
    ]
    STATE["suppliers"] = [
        {"name":"Delta Instrumentos","category":"pressure instrumentation","reliability":92,"price":86,"lead":88},
        {"name":"TecnoSource LATAM","category":"power supplies and instrumentation","reliability":89,"price":90,"lead":81},
        {"name":"Industrial Hub","category":"technical consumables","reliability":82,"price":88,"lead":90},
    ]
    log("Supplier Hunter and Buyer Hunter seeded a demo B2B network.")

def build_opportunities():
    created = 0
    for b in STATE["buyers"]:
        if any(o["buyer"] == b["name"] and o["need"] == b["need"] for o in STATE["opportunities"]):
            continue
        candidates = [s for s in STATE["suppliers"] if s["category"] == b["need"]]
        if not candidates:
            continue
        s = max(candidates, key=lambda x: x["reliability"] + x["price"] + x["lead"])
        demand = b["fit"]
        margin = min(95, (s["price"] + 5))
        recurrence = 82
        risk = max(5, 100-s["reliability"])
        score = opportunity_score(demand, margin, recurrence, b["fit"], risk, 20)
        value = int(12000 + score * 1100)
        margin_value = int(value * (0.12 + score/1000))
        opp = {"id":f"OPP-{len(STATE['opportunities'])+1:04d}","buyer":b["name"],"supplier":s["name"],"need":b["need"],"score":score,"pipeline":value,"margin":margin_value,"status":"qualified" if score >= 70 else "research"}
        STATE["opportunities"].append(opp)
        created += 1
        log(f"Opportunity Radar created {opp['id']} — {b['name']} ↔ {s['name']} (score {score}).")
    return created

def open_deals():
    created = 0
    existing = {d["opportunity_id"] for d in STATE["deals"]}
    for o in STATE["opportunities"]:
        if o["id"] in existing or o["score"] < 70:
            continue
        close_prob = round(min(0.72, 0.18 + o["score"]/180), 2)
        ev = int(o["pipeline"] * close_prob)
        d = {"id":f"DEAL-{len(STATE['deals'])+1:04d}","opportunity_id":o["id"],"buyer":o["buyer"],"supplier":o["supplier"],"stage":"discovery","close_prob":close_prob,"expected_value":ev,"margin":o["margin"],"next_action":"Research buyer and prepare tailored outreach"}
        STATE["deals"].append(d)
        created += 1
        log(f"Dealmaker opened {d['id']} with expected value USD {ev:,}.")
    return created

def autopilot_tick():
    STATE["ticks"] += 1
    if not STATE["buyers"]:
        seed_demo()
    c1 = build_opportunities()
    c2 = open_deals()
    if c1 == 0 and c2 == 0:
        # Never Idle: improve one deal or research a new angle
        if STATE["deals"]:
            d = max(STATE["deals"], key=lambda x: x["expected_value"])
            stages = ["discovery","qualified","proposal","negotiation"]
            idx = stages.index(d["stage"]) if d["stage"] in stages else 0
            if idx < len(stages)-1:
                d["stage"] = stages[idx+1]
                d["close_prob"] = round(min(.82, d["close_prob"] + .08), 2)
                d["expected_value"] = int(next(o["pipeline"] for o in STATE["opportunities"] if o["id"] == d["opportunity_id"]) * d["close_prob"])
                d["next_action"] = "Negotiate value, terms and recurrence" if d["stage"] == "negotiation" else "Advance account with evidence-based business case"
                log(f"LUMEN DRIVE advanced {d['id']} to {d['stage']} after reprioritizing expected value.")
            else:
                log("Never Idle reviewed the pipeline; no safe higher-value action was available this tick.")
    return {"ticks":STATE["ticks"],"new_opportunities":c1,"new_deals":c2}

@app.get("/health")
def health():
    return {"ok": True, "service":"lumen-b2b", "version":"1.2-online", "time": now()}

@app.get("/api/state")
def api_state(_=Depends(auth)):
    return STATE

@app.post("/api/autopilot/tick")
def api_tick(_=Depends(auth)):
    return autopilot_tick()

@app.post("/api/signal")
def api_signal(company: str = Form(...), need: str = Form(...), fit: int = Form(80), _=Depends(auth)):
    STATE["buyers"].append({"name":company,"sector":"user signal","need":need,"fit":max(1,min(100,fit)),"budget":75})
    if not any(s["category"] == need for s in STATE["suppliers"]):
        STATE["suppliers"].append({"name":f"Scout candidate for {need}","category":need,"reliability":72,"price":75,"lead":72})
    log(f"Human signal received: {company} may need {need}. LUMEN created a research target.")
    autopilot_tick()
    return RedirectResponse("/", status_code=303)

@app.post("/api/demo/reset")
def reset(_=Depends(auth)):
    STATE["buyers"] = []; STATE["suppliers"] = []; STATE["opportunities"] = []; STATE["deals"] = []; STATE["activity"] = []; STATE["ticks"] = 0
    seed_demo(); autopilot_tick()
    return RedirectResponse("/", status_code=303)

CSS = """
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#071018;color:#eaf2f7;font:14px Inter,ui-sans-serif,system-ui,-apple-system;padding:28px}a{color:#8bd3ff}.wrap{max-width:1280px;margin:auto}.top{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:22px}.logo{font-size:34px;font-weight:800;letter-spacing:.16em}.sub{color:#8ea6b5}.badge{padding:7px 10px;border:1px solid #284658;border-radius:999px;color:#9cddbb;background:#0d2019}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{background:#0c1720;border:1px solid #183343;border-radius:15px;padding:17px;box-shadow:0 12px 28px #0005}.kpi{font-size:29px;font-weight:750;margin-top:7px}.label{color:#89a2b2;text-transform:uppercase;font-size:11px;letter-spacing:.12em}.two{display:grid;grid-template-columns:1.4fr 1fr;gap:12px;margin-top:12px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px 8px;border-bottom:1px solid #17303e}th{color:#7894a5;font-size:11px}.score{font-weight:700;color:#9ce8c5}.activity{max-height:390px;overflow:auto}.event{padding:10px 0;border-bottom:1px solid #17303e}.time{font-size:11px;color:#627f90}.goals{display:flex;gap:8px;flex-wrap:wrap}.goal{background:#101f2a;border:1px solid #234457;border-radius:9px;padding:8px 10px}form{display:flex;gap:8px;flex-wrap:wrap}input{background:#07131b;border:1px solid #254658;color:white;padding:10px;border-radius:8px;min-width:160px}button{background:#d7ff64;border:0;border-radius:8px;padding:10px 14px;font-weight:800;cursor:pointer}.muted{background:#18303e;color:#dce8ee}.section{margin-top:12px}.status{color:#d7ff64}@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}.two{grid-template-columns:1fr}}@media(max-width:520px){body{padding:14px}.grid{grid-template-columns:1fr}.top{align-items:start;flex-direction:column}}
"""

def money(n): return f"USD {n:,.0f}"

@app.get("/", response_class=HTMLResponse)
def dashboard(_=Depends(auth)):
    pipeline = sum(o["pipeline"] for o in STATE["opportunities"])
    ev = sum(d["expected_value"] for d in STATE["deals"])
    margin = sum(d["margin"] for d in STATE["deals"])
    opp_rows = "".join(f"<tr><td>{o['id']}</td><td>{o['buyer']}</td><td>{o['need']}</td><td class='score'>{o['score']}</td><td>{money(o['pipeline'])}</td></tr>" for o in sorted(STATE["opportunities"], key=lambda x:x["score"], reverse=True)[:8]) or "<tr><td colspan=5>No opportunities yet</td></tr>"
    deal_rows = "".join(f"<tr><td>{d['id']}</td><td>{d['buyer']}</td><td><span class='status'>{d['stage']}</span></td><td>{int(d['close_prob']*100)}%</td><td>{money(d['expected_value'])}</td></tr>" for d in sorted(STATE["deals"], key=lambda x:x["expected_value"], reverse=True)[:8]) or "<tr><td colspan=5>No deals yet</td></tr>"
    events = "".join(f"<div class='event'><div>{e['msg']}</div><div class='time'>{e['ts']}</div></div>" for e in STATE["activity"][:16]) or "<div class='event'>Autopilot ready.</div>"
    goals = "".join(f"<span class='goal'>{g}</span>" for g in STATE["standing_goals"])
    mode = "LIVE OUTBOUND" if LIVE_OUTBOUND else "SAFE / DRY-RUN"
    html=f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>LUMEN B2B</title><style>{CSS}</style></head><body><div class='wrap'>
    <div class='top'><div><div class='logo'>LUMEN</div><div class='sub'>Autonomous B2B Entrepreneur OS · Command Center</div></div><div class='badge'>● AUTOPILOT · {mode}</div></div>
    <div class='goals'>{goals}</div>
    <div class='grid section'><div class='card'><div class='label'>Pipeline</div><div class='kpi'>{money(pipeline)}</div></div><div class='card'><div class='label'>Risk-adjusted EV</div><div class='kpi'>{money(ev)}</div></div><div class='card'><div class='label'>Potential margin</div><div class='kpi'>{money(margin)}</div></div><div class='card'><div class='label'>Autopilot ticks</div><div class='kpi'>{STATE['ticks']}</div></div></div>
    <div class='two'><div><div class='card'><div class='label'>Opportunity Radar</div><table><tr><th>ID</th><th>Buyer</th><th>Need</th><th>Score</th><th>Pipeline</th></tr>{opp_rows}</table></div><div class='card section'><div class='label'>Deal Desk</div><table><tr><th>ID</th><th>Buyer</th><th>Stage</th><th>Close</th><th>Expected value</th></tr>{deal_rows}</table></div></div>
    <div><div class='card'><div class='label'>LUMEN Activity</div><div class='activity'>{events}</div></div><div class='card section'><div class='label'>Feed a market signal</div><form method='post' action='/api/signal'><input name='company' placeholder='Company' required><input name='need' placeholder='What could they need?' required><input name='fit' type='number' min='1' max='100' value='85'><button>Give LUMEN the signal</button></form><form class='section' method='post' action='/api/demo/reset'><button class='muted'>Reset demo</button></form></div></div></div>
    <div class='sub section'>Governor active · No autonomous financial commitment · No live outbound unless explicitly enabled.</div></div></body></html>"""
    return HTMLResponse(html)

@app.on_event("startup")
def startup():
    seed_demo(); autopilot_tick()
