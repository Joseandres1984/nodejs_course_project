const VERSION = "2.0-travel-acquisition-conversion-aware";
const MAX_RECOMMENDATIONS = 5;

function clean(v, n = 4000) { return String(v ?? "").trim().replace(/[\r\n\t]+/g, " ").slice(0, n); }
function num(v) { const n = Number(v || 0); return Number.isFinite(n) ? n : 0; }
function json(data, status = 200) { return Response.json(data, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff", "access-control-allow-origin": "*", "access-control-allow-headers": "content-type,x-lumen-admin", "access-control-allow-methods": "GET,POST,OPTIONS" } }); }
function authorized(request, env) { const a = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500); const b = clean(request.headers.get("x-lumen-admin"), 500); return Boolean(a && b && a === b); }
function slug(v, fallback = "travel") { return clean(v, 100).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 55) || fallback; }
function safeViatorUrl(v) { try { const u = new URL(clean(v, 4000)); const h = u.hostname.toLowerCase(); return u.protocol === "https:" && (h === "viator.com" || h.endsWith(".viator.com")) && !u.username && !u.password ? u.toString() : ""; } catch { return ""; } }
async function all(env, sql) { try { return (await env.DB.prepare(sql).all()).results || []; } catch { return []; } }
async function first(env, sql) { try { return await env.DB.prepare(sql).first(); } catch { return null; } }

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_acquisition_campaigns (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,destination TEXT,product_id TEXT,source TEXT,channel TEXT,campaign TEXT,variant TEXT,hook TEXT,body TEXT,cta TEXT,disclosure TEXT,target_url TEXT,tracking_path TEXT,score REAL NOT NULL DEFAULT 0,confidence TEXT NOT NULL,mode TEXT NOT NULL,rationale TEXT NOT NULL,metrics_snapshot_json TEXT NOT NULL,approval_required INTEGER NOT NULL DEFAULT 1,paid_spend_usd REAL NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_travel_acq_status_score ON lumen_travel_acquisition_campaigns(status,score DESC,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_acquisition_runs (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,objective TEXT NOT NULL,recommendation_count INTEGER NOT NULL,exploit_count INTEGER NOT NULL,explore_count INTEGER NOT NULL,confirmed_bookings INTEGER NOT NULL DEFAULT 0,snapshot_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_travel_acq_runs_created ON lumen_travel_acquisition_runs(created_at DESC)")
  ]);
  return true;
}

async function signals(env) {
  const [events, bookings, intents] = await Promise.all([
    all(env, `SELECT COALESCE(NULLIF(destination,''),'') destination,COALESCE(NULLIF(product_id,''),'') product_id,COALESCE(NULLIF(source,''),'organic') source,COALESCE(NULLIF(campaign,''),'') campaign,COALESCE(NULLIF(variant,''),'') variant,SUM(CASE WHEN event_type='impression' THEN 1 ELSE 0 END) impressions,SUM(CASE WHEN event_type='result_shown' THEN 1 ELSE 0 END) result_shown,SUM(CASE WHEN event_type='click' THEN 1 ELSE 0 END) clicks,MAX(CASE WHEN event_type IN ('click','result_shown') AND COALESCE(target_url,'')<>'' THEN target_url ELSE '' END) target_url,MAX(created_at) last_event FROM lumen_travel_events WHERE datetime(created_at)>=datetime('now','-30 days') GROUP BY destination,product_id,source,campaign,variant ORDER BY clicks DESC,result_shown DESC LIMIT 180`),
    all(env, `SELECT COALESCE(NULLIF(campaign_value,''),'unattributed') campaign,COALESCE(NULLIF(product_code,''),'') product_id,SUM(CASE WHEN event_type='CONFIRMATION' THEN 1 ELSE 0 END) confirmations,SUM(CASE WHEN event_type IN ('CANCELLATION','CUSTOMER_CANCELLATION','REJECTION') THEN 1 ELSE 0 END) negative_events,MAX(last_updated) last_booking_event FROM lumen_viator_booking_events GROUP BY COALESCE(NULLIF(campaign_value,''),'unattributed'),COALESCE(NULLIF(product_code,''),'')`),
    all(env, `SELECT destination,best_affiliate_url,updated_at FROM lumen_travel_affiliate_intents WHERE status='READY' ORDER BY updated_at DESC LIMIT 80`)
  ]);
  return { events, bookings, intents };
}

function bookingIndex(rows) {
  const map = new Map();
  for (const r of rows) {
    const campaign = clean(r.campaign, 200);
    const product = clean(r.product_id, 180);
    for (const key of [`${campaign}|${product}`, `${campaign}|`, `|${product}`]) {
      const x = map.get(key) || { confirmations: 0, negativeEvents: 0, lastBookingEvent: null };
      x.confirmations += num(r.confirmations); x.negativeEvents += num(r.negative_events); x.lastBookingEvent = r.last_booking_event || x.lastBookingEvent; map.set(key, x);
    }
  }
  return map;
}

function bookingFor(index, campaign, product) { return index.get(`${campaign}|${product}`) || index.get(`${campaign}|`) || index.get(`|${product}`) || { confirmations:0,negativeEvents:0,lastBookingEvent:null }; }
function confidence(m) { if (m.confirmations >= 3 && m.clicks >= 20) return "HIGH"; if (m.confirmations >= 1 || m.clicks >= 8 || m.resultShown >= 30) return "MEDIUM"; return "LOW"; }
function score(m) {
  const shown = Math.max(1, m.resultShown || m.impressions);
  const ctr = m.clicks / shown;
  const cvr = m.clicks > 0 ? m.confirmations / m.clicks : 0;
  const negativeRate = m.confirmations + m.negativeEvents > 0 ? m.negativeEvents / (m.confirmations + m.negativeEvents) : 0;
  const raw = 15 + Math.min(45, m.confirmations * 15) + Math.min(18, cvr * 300) + Math.min(14, ctr * 100) + Math.min(8, m.clicks * .7) - Math.min(18, negativeRate * 30);
  return { score: Number(Math.max(0, Math.min(100, raw)).toFixed(2)), ctr, cvr, negativeRate };
}
function variant(v, seed) { const x = clean(v, 100); if (x) return x; return [...clean(seed, 200)].reduce((s,c)=>s+c.charCodeAt(0),0)%2 ? "dates_available_v1" : "price_availability_v1"; }
function cta(v) { return String(v).includes("dates") ? "Ver fechas disponibles" : "Ver precio y disponibilidad"; }
function draft(destination, chosenVariant) {
  const place = clean(destination, 120);
  return {
    hook: place ? `¿Viajás a ${place}? Mirá estas experiencias antes de cerrar el itinerario.` : "¿Estás armando un viaje? Compará experiencias antes de reservar.",
    body: place ? `LUMEN seleccionó opciones para ${place} usando señales reales de interés. Revisá detalles, precio y disponibilidad antes de reservar.` : "LUMEN seleccionó experiencias usando señales reales de interés. Revisá detalles, precio y disponibilidad antes de reservar.",
    cta: cta(chosenVariant),
    disclosure: "Enlace de afiliado: LUMEN puede recibir una comisión si reservás, sin costo adicional para vos."
  };
}
function channel(source) { const s = clean(source,100).toLowerCase(); if (s.includes("instagram")) return "instagram_owned"; if (s.includes("web")) return "web_owned"; return "organic_owned"; }
function track(targetUrl, x) { if (!targetUrl) return ""; const p = new URLSearchParams({ url:targetUrl, source:x.source || "organic", campaign:x.campaign || "lumen-travel", variant:x.variant || "price_availability_v1" }); if (x.destination) p.set("destination",x.destination); if (x.productId) p.set("product_id",x.productId); p.set("preserve","1"); return `/go/viator?${p.toString()}`; }

function candidates(sig) {
  const bi = bookingIndex(sig.bookings); const out = [];
  for (const r of sig.events) {
    const destination=clean(r.destination,160), productId=clean(r.product_id,180), source=clean(r.source,120)||"organic";
    const campaign=clean(r.campaign,200)||`lumen-travel-${slug(destination)}`; const chosenVariant=variant(r.variant,`${destination}|${campaign}`);
    const b=bookingFor(bi,campaign,productId); const m={impressions:num(r.impressions),resultShown:num(r.result_shown),clicks:num(r.clicks),confirmations:b.confirmations,negativeEvents:b.negativeEvents};
    const s=score(m); const conf=confidence(m); const d=draft(destination,chosenVariant); const targetUrl=safeViatorUrl(r.target_url);
    out.push({destination,productId,source,campaign,variant:chosenVariant,channel:channel(source),targetUrl,...m,...s,confidence:conf,mode:(m.confirmations>0||m.clicks>=8)?"EXPLOIT":"EXPLORE",rationale:m.confirmations>0?"Prioridad por reservas confirmadas reales de Viator; clics y exposición actúan como señales secundarias.":m.clicks>=8?"Todavía sin reserva atribuida; prioridad provisional por intención medida mediante clics.":m.clicks>0?"Exploración con intención inicial medida, todavía sin evidencia suficiente para explotar.":"Exposición observada sin clics; mantener en exploración y conservar el enlace accionable.",...d});
  }
  const seen=new Set(out.map(x=>x.destination.toLowerCase()).filter(Boolean));
  for (const r of sig.intents) {
    const destination=clean(r.destination,160); if (!destination||seen.has(destination.toLowerCase())) continue; const targetUrl=safeViatorUrl(r.best_affiliate_url); if(!targetUrl) continue;
    const chosenVariant=variant("",destination); const d=draft(destination,chosenVariant); out.push({destination,productId:"",source:"organic-intent",campaign:`lumen-travel-${slug(destination)}`,variant:chosenVariant,channel:"organic_owned",targetUrl,impressions:0,resultShown:0,clicks:0,confirmations:0,negativeEvents:0,score:15,ctr:0,cvr:0,negativeRate:0,confidence:"LOW",mode:"EXPLORE",rationale:"Nueva intención Travel detectada; se propone como exploración medible.",...d});
  }
  const dedup=new Map(); for(const x of out){const k=`${x.destination}|${x.productId}|${x.source}|${x.variant}`.toLowerCase(); if(!dedup.has(k)||dedup.get(k).score<x.score)dedup.set(k,x);}
  const sorted=[...dedup.values()].sort((a,b)=>b.score-a.score||b.confirmations-a.confirmations||b.clicks-a.clicks); const exploit=sorted.filter(x=>x.mode==="EXPLOIT").slice(0,4); const explore=sorted.filter(x=>x.mode==="EXPLORE"); const chosen=[...exploit]; if(chosen.length<MAX_RECOMMENDATIONS&&explore.length)chosen.push(explore[0]); for(const x of sorted){if(chosen.length>=MAX_RECOMMENDATIONS)break;if(!chosen.includes(x))chosen.push(x);} return chosen;
}
async function idFor(x){const raw=`${x.destination}|${x.productId}|${x.source}|${x.campaign}|${x.variant}`;const d=new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(raw)));return `TACQ-${[...d].map(b=>b.toString(16).padStart(2,"0")).join("").slice(0,24).toUpperCase()}`;}

export async function runTravelAcquisitionEngine(env){
  if(!await ensureSchema(env))return{ok:false,error:"db_not_bound",version:VERSION}; const sig=await signals(env); const selected=candidates(sig); const now=new Date().toISOString();
  for(const x of selected){const id=await idFor(x); const metrics={impressions:x.impressions,resultShown:x.resultShown,clicks:x.clicks,confirmations:x.confirmations,negativeEvents:x.negativeEvents,ctr:x.ctr,cvr:x.cvr}; await env.DB.prepare(`INSERT INTO lumen_travel_acquisition_campaigns(id,created_at,updated_at,status,destination,product_id,source,channel,campaign,variant,hook,body,cta,disclosure,target_url,tracking_path,score,confidence,mode,rationale,metrics_snapshot_json,approval_required,paid_spend_usd,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,score=excluded.score,confidence=excluded.confidence,mode=excluded.mode,rationale=excluded.rationale,metrics_snapshot_json=excluded.metrics_snapshot_json,target_url=excluded.target_url,tracking_path=excluded.tracking_path,engine_version=excluded.engine_version,status=CASE WHEN lumen_travel_acquisition_campaigns.status IN ('APPROVED','PUBLISHED') THEN lumen_travel_acquisition_campaigns.status ELSE 'RECOMMENDED' END`).bind(id,now,now,"RECOMMENDED",x.destination,x.productId,x.source,x.channel,x.campaign,x.variant,x.hook,x.body,x.cta,x.disclosure,x.targetUrl,track(x.targetUrl,x),x.score,x.confidence,x.mode,x.rationale,JSON.stringify(metrics),1,0,VERSION).run();}
  const exploitCount=selected.filter(x=>x.mode==="EXPLOIT").length, exploreCount=selected.filter(x=>x.mode==="EXPLORE").length, confirmedBookings=selected.reduce((s,x)=>s+x.confirmations,0); const runId=`TARUN-${Date.now()}-${crypto.randomUUID().slice(0,8)}`;
  await env.DB.prepare("INSERT INTO lumen_travel_acquisition_runs(id,created_at,objective,recommendation_count,exploit_count,explore_count,confirmed_bookings,snapshot_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?)").bind(runId,now,"confirmed_bookings_then_click_intent_then_controlled_exploration",selected.length,exploitCount,exploreCount,confirmedBookings,JSON.stringify({eventGroups:sig.events.length,bookingGroups:sig.bookings.length,readyIntents:sig.intents.length}),VERSION).run();
  return{ok:true,version:VERSION,runId,recommendationCount:selected.length,exploitCount,exploreCount,confirmedBookings,publicationAuthority:false,paidAds:false,autonomousSpendUsd:0,bindingActionsHumanGated:true};
}

async function status(env){await ensureSchema(env);const s=await first(env,"SELECT COUNT(*) total,SUM(CASE WHEN status='RECOMMENDED' THEN 1 ELSE 0 END) recommended,SUM(CASE WHEN mode='EXPLOIT' THEN 1 ELSE 0 END) exploit,SUM(CASE WHEN mode='EXPLORE' THEN 1 ELSE 0 END) explore,MAX(updated_at) last_updated FROM lumen_travel_acquisition_campaigns");const r=await first(env,"SELECT id,created_at,recommendation_count,exploit_count,explore_count,confirmed_bookings FROM lumen_travel_acquisition_runs ORDER BY created_at DESC LIMIT 1");return{ok:true,version:VERSION,campaigns:{total:num(s?.total),recommended:num(s?.recommended),exploit:num(s?.exploit),explore:num(s?.explore),lastUpdated:s?.last_updated||null},latestRun:r||null,publicationAuthority:false,paidAds:false,autonomousSpendUsd:0};}
async function recommendations(env){await ensureSchema(env);const rows=await all(env,"SELECT id,status,destination,product_id,source,channel,campaign,variant,hook,body,cta,disclosure,target_url,tracking_path,score,confidence,mode,rationale,metrics_snapshot_json,approval_required,paid_spend_usd,updated_at FROM lumen_travel_acquisition_campaigns WHERE status IN ('RECOMMENDED','APPROVED') ORDER BY score DESC,updated_at DESC LIMIT 20");return rows.map(r=>({...r,approval_required:Boolean(r.approval_required),paid_spend_usd:num(r.paid_spend_usd),metrics:(()=>{try{return JSON.parse(r.metrics_snapshot_json||"{}");}catch{return{};}})()}));}

export async function handleTravelAcquisitionEngine(request,env){const u=new URL(request.url);const p=u.pathname;if(!["/travel/acquisition/policy","/travel/acquisition/status","/travel/acquisition/recommendations","/travel/acquisition/run"].includes(p))return null;if(request.method==="OPTIONS")return new Response(null,{status:204,headers:{"access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"}});if(request.method==="GET"&&p==="/travel/acquisition/policy")return json({ok:true,version:VERSION,name:"LUMEN Travel Acquisition Engine",objective:"prioritize real Viator confirmations, then measured buyer intent, while keeping controlled exploration",channels:["instagram_owned","web_owned","organic_owned"],paidAds:false,autonomousSpendUsd:0,publicationAuthority:false,unsolicitedMassMessaging:false,storesPersonalData:false,bookingAuthority:false,paymentAuthority:false,autonomousPurchase:false,bindingActionsHumanGated:true});if(request.method==="GET"&&p==="/travel/acquisition/status")return json(await status(env));if(!authorized(request,env))return json({ok:false,error:"unauthorized",version:VERSION},401);if(request.method==="GET"&&p==="/travel/acquisition/recommendations")return json({ok:true,version:VERSION,recommendations:await recommendations(env)});if(request.method==="POST"&&p==="/travel/acquisition/run")return json(await runTravelAcquisitionEngine(env));return json({ok:false,error:"method_not_allowed",version:VERSION},405);}
