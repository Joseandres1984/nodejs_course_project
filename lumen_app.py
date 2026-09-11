from __future__ import annotations
import os, base64, hmac, random, time
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

APP_VERSION='1.2-online'
ADMIN_USER=os.getenv('ADMIN_USERNAME','lumen')
ADMIN_PASS=os.getenv('ADMIN_PASSWORD','')

app=FastAPI(title='LUMEN B2B Autonomous Entrepreneur OS', version=APP_VERSION)

state={
 'autopilot': True,
 'standing_goals':[
  'Find profitable B2B opportunities',
  'Build a high-quality supplier network',
  'Find high-fit buyers',
  'Convert isolated deals into recurring revenue'
 ],
 'buyers':[], 'suppliers':[], 'opportunities':[], 'deals':[], 'tasks':[], 'activity':[],
 'metrics':{'pipeline':0.0,'expected_value':0.0,'gross_margin':0.0,'actions':0,'ticks':0},
}

def now(): return datetime.now(timezone.utc).isoformat()
def log(kind,msg):
 state['activity'].insert(0,{'at':now(),'kind':kind,'message':msg})
 state['activity']=state['activity'][:80]

def seed_demo():
 if state['buyers'] or state['suppliers']: return
 state['buyers']=[
  {'id':'B-001','name':'Andes Industrial','sector':'Industrial Maintenance','fit':96,'demand':['pressure instrumentation','power supplies'],'budget':85000},
  {'id':'B-002','name':'Pampa Process','sector':'Process Industry','fit':91,'demand':['pressure instrumentation','valves'],'budget':120000},
  {'id':'B-003','name':'Sur Energy Services','sector':'Energy','fit':88,'demand':['power supplies','rf components'],'budget':67000},
 ]
 state['suppliers']=[
  {'id':'S-001','name':'Precision Supply Co','categories':['pressure instrumentation','valves'],'score':94,'margin_hint':0.24},
  {'id':'S-002','name':'TechSource LATAM','categories':['power supplies','rf components'],'score':92,'margin_hint':0.21},
  {'id':'S-003','name':'Industrial Direct','categories':['pressure instrumentation','power supplies'],'score':86,'margin_hint':0.18},
 ]
 log('seed','Demo B2B network created')

def opportunity_score(buyer,supplier,category):
 demand=buyer['fit']/100
 supply=supplier['score']/100
 margin=supplier['margin_hint']
 recurrence=0.78 if buyer['sector'] in {'Industrial Maintenance','Energy'} else 0.65
 risk_penalty=max(0,(90-supplier['score'])/250)
 return round(100*(0.30*demand+0.25*supply+0.25*min(1,margin/0.30)+0.20*recurrence-risk_penalty),1)

def run_tick():
 state['metrics']['ticks']+=1
 seed_demo()
 created=0
 for b in state['buyers']:
  for s in state['suppliers']:
   common=sorted(set(b['demand']) & set(s['categories']))
   for category in common:
    key=f"{b['id']}:{s['id']}:{category}"
    if any(o['key']==key for o in state['opportunities']): continue
    score=opportunity_score(b,s,category)
    if score < 72: continue
    est_revenue=round(b['budget']*(0.18+score/500),2)
    margin=round(est_revenue*s['margin_hint'],2)
    close_prob=round(min(.72,.15+score/180),2)
    ev=round(margin*close_prob,2)
    o={'id':str(uuid4()),'key':key,'buyer':b['name'],'supplier':s['name'],'category':category,'score':score,
       'estimated_revenue':est_revenue,'gross_margin':margin,'close_probability':close_prob,'expected_value':ev,'status':'qualified','created_at':now()}
    state['opportunities'].append(o); created+=1
    log('opportunity',f"Qualified {category}: {b['name']} ↔ {s['name']} (score {score})")
    if score>=80:
      d={'id':str(uuid4()),'opportunity_id':o['id'],'buyer':b['name'],'supplier':s['name'],'category':category,
         'value':est_revenue,'margin':margin,'probability':close_prob,'stage':'discovery','next_action':'Research buyer and prepare tailored outreach'}
      state['deals'].append(d)
      state['tasks'].append({'id':str(uuid4()),'priority':1 if score>=88 else 2,'type':'growth','subject':b['name'],'action':d['next_action'],'status':'queued'})
      log('deal',f"Opened deal with {b['name']} for {category}")
 state['metrics']['actions']+=created
 state['metrics']['pipeline']=round(sum(d['value'] for d in state['deals']),2)
 state['metrics']['gross_margin']=round(sum(d['margin'] for d in state['deals']),2)
 state['metrics']['expected_value']=round(sum(d['margin']*d['probability'] for d in state['deals']),2)
 if created==0:
  q=next((t for t in sorted(state['tasks'],key=lambda x:x['priority']) if t['status']=='queued'),None)
  if q:
   q['status']='working'; q['action']='Build account brief, verify fit, formulate outreach angle'
   log('autopilot',f"Working autonomously on {q['subject']}")
   state['metrics']['actions']+=1
  else:
   state['tasks'].append({'id':str(uuid4()),'priority':3,'type':'research','subject':'Market Radar','action':'Scan for new B2B demand/supply signals','status':'queued'})
   log('autopilot','Never Idle: created a new market-radar research task')
 return {'created_opportunities':created,'metrics':state['metrics']}

@app.middleware('http')
async def auth(request:Request, call_next):
 if request.url.path in {'/health','/ready'} or not ADMIN_PASS:
  return await call_next(request)
 hdr=request.headers.get('authorization','')
 if hdr.lower().startswith('basic '):
  try:
   user,pwd=base64.b64decode(hdr.split(' ',1)[1]).decode().split(':',1)
   if hmac.compare_digest(user,ADMIN_USER) and hmac.compare_digest(pwd,ADMIN_PASS): return await call_next(request)
  except Exception: pass
 return Response('Authentication required',401,headers={'WWW-Authenticate':'Basic realm="LUMEN B2B"'})

@app.get('/health')
def health(): return {'status':'ok','product':'LUMEN B2B','version':APP_VERSION}
@app.get('/ready')
def ready(): return {'status':'ready','autopilot':state['autopilot'],'mode':'online-compact'}
@app.get('/api/state')
def get_state(): return state
@app.post('/api/demo/seed')
def api_seed(): seed_demo(); return state
@app.post('/api/autopilot/tick')
def api_tick(): return run_tick()
@app.post('/api/autopilot/{mode}')
def api_auto(mode:str):
 state['autopilot']=mode.lower() in {'on','true','1','start'}; log('system',f"Autopilot {'enabled' if state['autopilot'] else 'disabled'}")
 return {'autopilot':state['autopilot']}

HTML='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LUMEN B2B</title><style>
:root{--bg:#080b12;--card:#101622;--line:#202a3b;--text:#f2f5fa;--muted:#91a0b8;--accent:#77e3b5;--blue:#7db6ff}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 25% 0,#162034 0,#080b12 42%);color:var(--text);font-family:Inter,ui-sans-serif,system-ui;padding:26px}.wrap{max-width:1250px;margin:auto}.top{display:flex;justify-content:space-between;align-items:end;gap:20px}.brand{font-size:38px;font-weight:850;letter-spacing:.18em}.sub{color:var(--muted);margin-top:6px}.pill{border:1px solid #245f50;color:var(--accent);padding:8px 12px;border-radius:999px;font-size:13px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0}.card{background:linear-gradient(180deg,#111826,#0d131e);border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:0 12px 30px #0004}.k{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.11em}.v{font-size:26px;font-weight:760;margin-top:8px}.two{display:grid;grid-template-columns:1.25fr .75fr;gap:14px}.list{margin-top:12px;display:flex;flex-direction:column;gap:8px}.item{border:1px solid var(--line);border-radius:12px;padding:12px;background:#0b1019}.row{display:flex;justify-content:space-between;gap:10px}.score{color:var(--accent);font-weight:700}.muted{color:var(--muted);font-size:13px}.btns{display:flex;gap:10px;margin:18px 0}.btn{background:#172235;border:1px solid #2b3b55;color:white;padding:10px 15px;border-radius:10px;cursor:pointer}.btn.primary{background:#164c3d;border-color:#2d886e}@media(max-width:850px){.grid{grid-template-columns:repeat(2,1fr)}.two{grid-template-columns:1fr}.top{align-items:start;flex-direction:column}}
</style></head><body><div class="wrap"><div class="top"><div><div class="brand">LUMEN</div><div class="sub">Autonomous B2B Entrepreneur OS · Command Center</div></div><div class="pill" id="status">AUTOPILOT</div></div><div class="btns"><button class="btn primary" onclick="tick()">Run Autopilot</button><button class="btn" onclick="seed()">Seed Demo Network</button><button class="btn" onclick="load()">Refresh</button></div><div class="grid"><div class="card"><div class="k">Pipeline</div><div class="v" id="pipeline">—</div></div><div class="card"><div class="k">Expected Value</div><div class="v" id="ev">—</div></div><div class="card"><div class="k">Gross Margin</div><div class="v" id="margin">—</div></div><div class="card"><div class="k">Autonomous Actions</div><div class="v" id="actions">—</div></div></div><div class="two"><div class="card"><div class="k">Best Opportunities</div><div id="opps" class="list"></div></div><div class="card"><div class="k">Autonomous Queue</div><div id="tasks" class="list"></div></div></div><div class="two" style="margin-top:14px"><div class="card"><div class="k">Active Deals</div><div id="deals" class="list"></div></div><div class="card"><div class="k">Activity</div><div id="activity" class="list"></div></div></div></div><script>
const usd=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(n||0);async function req(u,o){let r=await fetch(u,o);return r.json()}async function load(){let s=await req('/api/state');document.getElementById('status').textContent=s.autopilot?'AUTOPILOT ACTIVE':'AUTOPILOT OFF';pipeline.textContent=usd(s.metrics.pipeline);ev.textContent=usd(s.metrics.expected_value);margin.textContent=usd(s.metrics.gross_margin);actions.textContent=s.metrics.actions;opps.innerHTML=s.opportunities.sort((a,b)=>b.score-a.score).slice(0,8).map(x=>`<div class=item><div class=row><b>${x.category}</b><span class=score>${x.score}</span></div><div class=muted>${x.buyer} ↔ ${x.supplier}</div><div class=muted>EV ${usd(x.expected_value)} · margin ${usd(x.gross_margin)}</div></div>`).join('')||'<div class=muted>No opportunities yet.</div>';tasks.innerHTML=s.tasks.slice(0,8).map(x=>`<div class=item><div class=row><b>${x.subject}</b><span>${x.status}</span></div><div class=muted>${x.action}</div></div>`).join('')||'<div class=muted>Queue empty.</div>';deals.innerHTML=s.deals.slice(0,8).map(x=>`<div class=item><div class=row><b>${x.buyer}</b><span class=score>${Math.round(x.probability*100)}%</span></div><div class=muted>${x.category} · ${usd(x.value)} · ${x.stage}</div></div>`).join('')||'<div class=muted>No deals yet.</div>';activity.innerHTML=s.activity.slice(0,9).map(x=>`<div class=item><b>${x.kind}</b><div class=muted>${x.message}</div></div>`).join('')||'<div class=muted>No activity.</div>'}async function tick(){await req('/api/autopilot/tick',{method:'POST'});load()}async function seed(){await req('/api/demo/seed',{method:'POST'});load()}load();</script></body></html>'''

@app.get('/',response_class=HTMLResponse)
def home(): return HTML
