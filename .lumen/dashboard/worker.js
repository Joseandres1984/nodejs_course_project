const STATE_KEY = "global";

function unauthorized() {
  return new Response("LUMEN · acceso restringido", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="LUMEN"', "Cache-Control": "no-store" },
  });
}

function locked() {
  return new Response("LUMEN dashboard todavía no tiene contraseña configurada.", {
    status: 503,
    headers: { "Cache-Control": "no-store" },
  });
}

function authOK(request, env) {
  const password = String(env.LUMEN_DASHBOARD_PASSWORD || "");
  if (!password) return null;
  const header = request.headers.get("Authorization") || "";
  if (!header.startsWith("Basic ")) return false;
  try {
    const decoded = atob(header.slice(6));
    const i = decoded.indexOf(":");
    if (i < 0) return false;
    const user = decoded.slice(0, i);
    const pass = decoded.slice(i + 1);
    return user === String(env.LUMEN_DASHBOARD_USER || "socio") && pass === password;
  } catch {
    return false;
  }
}

async function sha256Hex(bytes) {
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function loadState(env) {
  const manifest = await env.DB.prepare(
    "SELECT encoding, chunk_count, payload_sha256, uncompressed_bytes, updated_at FROM lumen_state_manifest WHERE state_key = ? LIMIT 1"
  ).bind(STATE_KEY).first();
  if (!manifest) throw new Error("state_not_initialized");
  if (manifest.encoding !== "zlib+base64+json") throw new Error("unsupported_state_encoding");

  const rows = await env.DB.prepare(
    "SELECT chunk_no, payload FROM lumen_state_chunks WHERE state_key = ? ORDER BY chunk_no ASC"
  ).bind(STATE_KEY).all();
  const chunks = rows.results || [];
  if (chunks.length !== Number(manifest.chunk_count || 0)) throw new Error("incomplete_state_chunks");

  const encoded = chunks.map((r) => String(r.payload || "")).join("");
  const binary = atob(encoded);
  const compressed = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) compressed[i] = binary.charCodeAt(i);
  const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("deflate"));
  const raw = new Uint8Array(await new Response(stream).arrayBuffer());
  const digest = await sha256Hex(raw);
  if (manifest.payload_sha256 && digest !== manifest.payload_sha256) throw new Error("state_checksum_mismatch");
  return { state: JSON.parse(new TextDecoder().decode(raw)), manifest };
}

const n = (v) => Number(v || 0);
const arr = (v) => Array.isArray(v) ? v : [];
const obj = (v) => v && typeof v === "object" && !Array.isArray(v) ? v : {};
const s = (v, d = "") => String(v ?? d);

function money(v) {
  const x = Number(v || 0);
  return `$${x.toLocaleString("es-AR", { maximumFractionDigits: 0 })}`;
}

function summarize(state, manifest) {
  const funnel = obj(state.business_funnel);
  const readiness = obj(state.external_market_readiness);
  const scoutStatus = obj(state.scout_status);
  const scoutBudget = obj(state.scout_budget);
  const demandBudget = obj(state.demand_search_budget);
  const adaptiveBudget = obj(state.adaptive_search_budget);
  const watchdog = obj(state.system_watchdog);
  const workforceRoot = obj(state.agent_workforce);
  const workforce = obj(workforceRoot.last_cycle);
  const moneyEngine = obj(state.money_engine);
  const secretary = obj(state.executive_secretary_private_bridge || state.executive_secretary);
  const policies = obj(state.policies);
  const instagram = obj(state.instagram_publish_control);
  const notification = obj(state.notification_router);

  const opportunities = arr(state.opportunities).slice().sort((a,b)=>n(b.score)-n(a.score)).slice(0,12).map((o)=>({
    id:s(o.id,"—"), buyer:s(o.buyer || o.company || o.account,"—"), need:s(o.need || o.category || o.title,"—"),
    supplier:s(o.supplier,"—"), score:n(o.score), pipeline:n(o.pipeline || o.value || o.amount), status:s(o.status || o.stage,"—"), source:s(o.source,"—")
  }));
  const deals = arr(state.deals).slice().sort((a,b)=>n(b.expected_value || b.pipeline)-n(a.expected_value || a.pipeline)).slice(0,12).map((d)=>({
    id:s(d.id,"—"), buyer:s(d.buyer || d.company || d.account,"—"), stage:s(d.stage || d.status,"—"),
    close_prob:n(d.close_prob), expected_value:n(d.expected_value), pipeline:n(d.pipeline), company_profit:n(d.company_profit), company_share_pct:n(d.company_share_pct), source:s(d.source,"—")
  }));
  const approvals = arr(state.approvals).filter((a)=>s(a.status).toLowerCase()==="pending").slice(0,10).map((a)=>({
    id:s(a.id,"—"), deal_id:s(a.deal_id,"—"), company_profit:n(a.company_profit), company_share_pct:n(a.company_share_pct), reason:s(a.reason || a.kind,"requiere aprobación humana")
  }));
  const outbox = arr(state.outbox).slice(-12).reverse().map((m)=>({
    id:s(m.id,"—"), counterparty:s(m.counterparty || m.to || m.company,"—"), kind:s(m.kind || m.channel || m.type,"—"), status:s(m.status,"—")
  }));
  const offers = [...arr(state.offers), ...arr(state.supplier_quotes), ...arr(state.quotes)].slice(-12).reverse().map((o)=>({
    id:s(o.id,"—"), supplier:s(o.supplier || o.company || o.vendor,"—"), amount:n(o.amount || o.amount_usd || o.total), lead_days:n(o.lead_days || o.delivery_days), source:s(o.source,"—"), status:s(o.status,"—")
  }));
  const activity = arr(state.activity).slice(0,30).map((x)=>({ts:s(x.ts),msg:s(x.msg)}));
  const pending = arr(secretary.pending).slice(0,10).map((x)=>({title:s(x.title,"Pendiente"),reason:s(x.reason),priority:n(x.priority),risk:s(x.risk)}));
  const goals = arr(state.standing_goals).slice(0,8);

  const pipeline = opportunities.reduce((a,o)=>a+n(o.pipeline),0);
  const expectedValue = deals.reduce((a,d)=>a+n(d.expected_value),0);
  const potentialProfit = deals.filter((d)=>!s(d.stage).toLowerCase().includes("cerrado")).reduce((a,d)=>a+n(d.company_profit),0);
  const transactions = arr(state.transactions);
  const registeredProfit = transactions.reduce((a,t)=>a+n(t.company_profit || t.profit || t.amount),0);
  const realizedRevenue = n(moneyEngine.realized_revenue_truth_usd || obj(state.service_growth_pipeline).realized_service_revenue_usd || obj(state.expansion_revenue_runtime).revenue_generated_usd);

  const generalDaily = n(adaptiveBudget.general_pool_daily || scoutBudget.daily_budget || scoutStatus.general_retail_pool_daily);
  const demandDaily = n(adaptiveBudget.demand_reserved_daily || demandBudget.daily_budget || scoutStatus.demand_reserved_daily);
  const hardCap = n(adaptiveBudget.total_daily_cap || scoutStatus.daily_query_budget || scoutBudget.total_daily_cap || generalDaily + demandDaily);
  const generalUsed = n(scoutBudget.queries_used);
  const demandUsed = n(demandBudget.queries_used);
  const totalUsed = Math.min(hardCap || generalUsed + demandUsed, generalUsed + demandUsed);
  const remaining = Math.max(0, hardCap - generalUsed - demandUsed);
  const fleetSize = n(workforce.fleet_size || workforceRoot.roster_count || arr(workforceRoot.roster).length);

  return {
    status:{
      updated_at:manifest.updated_at || state.last_tick || null, ticks:n(state.ticks), last_tick:s(state.last_tick), last_origin:s(state.last_tick_origin,"—"),
      watchdog_score:n(watchdog.score_pct), watchdog_status:s(watchdog.status,"unknown"), fleet_size:fleetSize,
      worker_status:s(workforce.status,fleetSize?"healthy":"unknown"), persistence:"Cloudflare D1", state_bytes:n(manifest.uncompressed_bytes)
    },
    money:{pipeline,expected_value:expectedValue,potential_profit:potentialProfit,registered_profit:registeredProfit,realized_revenue:realizedRevenue,pending_closures:approvals.length},
    goals, opportunities, deals, approvals, outbox, offers, activity, pending,
    policies:{min_share:n(policies.min_company_share_pct),target_share:n(policies.target_company_share_pct),risk_reserve:n(policies.risk_reserve_pct)},
    funnel:{
      leads:n(funnel.research_leads ?? arr(state.research_leads).length), candidates:n(funnel.candidate_accounts ?? arr(state.candidate_accounts).length),
      verified:n(funnel.verified_companies), buyers:n(funnel.verified_buyers), suppliers:n(funnel.verified_suppliers), contacts:n(funnel.verified_commercial_channels || funnel.verified_corporate_emails),
      demand:n(funnel.buyers_with_public_demand), opportunities:n(funnel.evidence_backed_opportunities), proposals:n(funnel.proposals), close_ready:n(funnel.close_ready), outbound_sent:n(funnel.outbound_sent), inbound:n(funnel.inbound_received)
    },
    scout:{provider:s(scoutStatus.provider,"bing_rss_public"),used:totalUsed,remaining,hard_cap:hardCap,general_used:generalUsed,demand_used:demandUsed},
    outbound:{live:Boolean(readiness.outbound_live),mail_ready:Boolean(readiness.mail_transport_ready),mail_provider:s(readiness.mail_provider,"—"),eligible:n(readiness.eligible_external_prospects),blocker:s(readiness.primary_blocker),failed:n(readiness.outbox_failed),instagram:Boolean(instagram.connector_configured),whatsapp:Boolean(notification.delivery_ready)},
    governance:{financial_commitments:false,contracts:"aprobación humana",unverified_contact:"no enviar",live_outbound:Boolean(readiness.outbound_live),automation_disclosed:Boolean(readiness.automation_disclosure || state.disclose_automation)}
  };
}

const HTML = `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#071018"><title>LUMEN · Centro de Comando</title><style>
:root{color-scheme:dark;--bg:#071018;--card:#0c1720;--line:#183343;--muted:#89a2b2;--lime:#d7ff64;--good:#9ce8c5;--bad:#ff9898;--warn:#ffd36e;--blue:#78d7ff}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 95% 0,#12313e 0,#071018 38%) fixed;color:#eaf2f7;font:14px Inter,system-ui,-apple-system;padding:18px}.wrap{max-width:1380px;margin:auto}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;margin-bottom:16px}.logo{font-size:34px;font-weight:900;letter-spacing:.16em}.sub{color:var(--muted);margin-top:4px}.badge{padding:8px 11px;border:1px solid #2a5163;border-radius:999px;color:var(--good);background:#0d2019;font-size:12px}.goals{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.goal{background:#101f2a;border:1px solid #234457;border-radius:9px;padding:8px 10px}.grid5{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.two{display:grid;grid-template-columns:1.35fr 1fr;gap:12px;margin-top:12px}.three{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:12px}.card{background:linear-gradient(180deg,#0e1b24,#0a151d);border:1px solid var(--line);border-radius:15px;padding:16px;box-shadow:0 12px 28px #0005;overflow:auto}.label{color:var(--muted);text-transform:uppercase;font-size:10px;letter-spacing:.13em;font-weight:800}.kpi{font-size:27px;font-weight:850;margin-top:7px}.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}.blue{color:var(--blue)}.tiny{font-size:12px;color:var(--muted);line-height:1.45}.section{margin-top:12px}table{width:100%;border-collapse:collapse;min-width:520px}th,td{text-align:left;padding:9px 7px;border-bottom:1px solid #17303e;vertical-align:top}th{color:#7894a5;font-size:10px;text-transform:uppercase;letter-spacing:.08em}.score,.profit{font-weight:800;color:var(--good)}.status{color:var(--lime)}.source{font-size:10px;color:var(--muted)}.activity{max-height:500px;overflow:auto}.event{padding:10px 0;border-bottom:1px solid #17303e}.time{font-size:11px;color:#627f90;margin-top:3px}.row{display:flex;justify-content:space-between;gap:10px;padding:10px 0;border-bottom:1px solid #17303e}.bar{height:8px;background:#071018;border:1px solid #173241;border-radius:999px;overflow:hidden;margin-top:9px}.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--lime),var(--good));width:0}.btn{background:var(--lime);color:#071018;border:0;border-radius:10px;padding:10px 13px;font-weight:900;cursor:pointer}.topactions{display:flex;gap:8px;align-items:center}.pill{border:1px solid #284658;border-radius:999px;padding:8px 10px;color:var(--good);background:#0d2019;font-size:12px}.note{padding:12px 13px;border:1px solid #294451;border-radius:12px;background:#0a151d;color:#a6bdc8;line-height:1.5}@media(max-width:1050px){.grid5{grid-template-columns:repeat(3,1fr)}.grid4{grid-template-columns:repeat(2,1fr)}.two,.three{grid-template-columns:1fr}}@media(max-width:620px){body{padding:12px}.top{align-items:flex-start;flex-direction:column}.logo{font-size:28px}.grid5,.grid4{grid-template-columns:1fr 1fr}.kpi{font-size:24px}.topactions{width:100%;justify-content:space-between}.pill{font-size:10px;padding:7px 8px}.card{padding:14px}}@media(max-width:390px){.grid5,.grid4{grid-template-columns:1fr}}
</style></head><body><div class="wrap"><div class="top"><div><div class="logo">LUMEN</div><div class="sub">Sistema Operativo B2B Autónomo · Centro de Comando Zero</div></div><div class="topactions"><span class="pill" id="updated">Cargando…</span><button class="btn" onclick="load()">Actualizar</button></div></div>
<div class="goals" id="goals"></div>
<div class="grid5"><div class="card"><div class="label">Pipeline registrado</div><div class="kpi" id="pipeline">–</div></div><div class="card"><div class="label">Valor esperado</div><div class="kpi" id="ev">–</div></div><div class="card"><div class="label">Ganancia potencial</div><div class="kpi" id="potential">–</div></div><div class="card"><div class="label">Ingresos realizados</div><div class="kpi good" id="realized">–</div></div><div class="card"><div class="label">Cierres pendientes</div><div class="kpi" id="pendingClosures">–</div></div></div>
<div class="grid4 section"><div class="card"><div class="label">Watchdog</div><div class="kpi" id="watchdog">–</div><div class="bar"><i id="watchbar"></i></div></div><div class="card"><div class="label">Scout</div><div class="kpi" id="scout">–</div><div class="tiny" id="scoutDetail"></div></div><div class="card"><div class="label">Email</div><div class="kpi" id="email">–</div><div class="tiny" id="emailDetail"></div></div><div class="card"><div class="label">Fuerza digital</div><div class="kpi" id="fleet">–</div><div class="tiny" id="fleetDetail"></div></div></div>
<div class="two"><div><div class="card"><div class="label">Radar de oportunidades</div><table><thead><tr><th>ID</th><th>Comprador</th><th>Necesidad</th><th>Puntaje</th><th>Pipeline</th><th>Fuente</th></tr></thead><tbody id="oppRows"></tbody></table></div><div class="card section"><div class="label">Mesa de negocios</div><table><thead><tr><th>ID</th><th>Comprador</th><th>Etapa</th><th>Cierre</th><th>Valor esperado</th><th>Queda para nosotros</th></tr></thead><tbody id="dealRows"></tbody></table></div><div class="card section"><div class="label">Cierres que requieren decisión humana</div><table><thead><tr><th>ID</th><th>Deal</th><th>Ganancia</th><th>% nuestro</th><th>Motivo</th></tr></thead><tbody id="approvalRows"></tbody></table></div></div><div><div class="card"><div class="label">Actividad autónoma</div><div class="activity" id="activity"></div><div class="tiny section" id="lastCycle"></div></div><div class="card section"><div class="label">Política económica</div><div id="policyRows"></div><div class="note section">Este panel conserva el modo seguro: muestra el estado real, pero no modifica políticas ni ejecuta cierres desde el navegador.</div></div><div class="card section"><div class="label">Embudo comercial real</div><div id="funnel"></div></div><div class="card section"><div class="label">Pendientes prioritarios</div><div id="pending"></div></div></div></div>
<div class="three"><div class="card"><div class="label">Comunicaciones preparadas</div><table><thead><tr><th>ID</th><th>Contraparte</th><th>Tipo</th><th>Estado</th></tr></thead><tbody id="outRows"></tbody></table></div><div class="card"><div class="label">Ofertas / cotizaciones</div><table><thead><tr><th>ID</th><th>Proveedor</th><th>Importe</th><th>Entrega</th><th>Fuente</th></tr></thead><tbody id="offerRows"></tbody></table></div><div class="card"><div class="label">Gobernanza y canales</div><div id="governance"></div></div></div>
<div class="sub section">Todos los números son los registros actualmente persistidos en LUMEN Zero. El panel no inventa negocios ni convierte datos demo en ingresos reales.</div></div><script>
const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const money=v=>'$'+Number(v||0).toLocaleString('es-AR',{maximumFractionDigits:0});
function empty(cols,text){return '<tr><td colspan="'+cols+'" class="tiny">'+esc(text)+'</td></tr>'}
function rows(items){return items.map(([a,b])=>'<div class="row"><span>'+esc(a)+'</span><b>'+esc(b)+'</b></div>').join('')}
async function load(){try{const r=await fetch('/api/summary',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();$('updated').textContent='Estado: '+(d.status.updated_at||'sin fecha');$('goals').innerHTML=d.goals.length?d.goals.map(g=>'<span class="goal">'+esc(g)+'</span>').join(''):'<span class="goal">Encontrar compradores B2B de alto valor</span><span class="goal">Crear negocios rentables y repetibles</span>';$('pipeline').textContent=money(d.money.pipeline);$('ev').textContent=money(d.money.expected_value);$('potential').textContent=money(d.money.potential_profit);$('realized').textContent=money(d.money.realized_revenue);$('pendingClosures').textContent=d.money.pending_closures;$('watchdog').textContent=Number(d.status.watchdog_score||0).toFixed(1)+'%';$('watchbar').style.width=Math.max(0,Math.min(100,d.status.watchdog_score||0))+'%';$('scout').textContent=d.scout.remaining+'/'+d.scout.hard_cap;$('scoutDetail').textContent=d.scout.provider+' · usadas '+d.scout.used+' · general '+d.scout.general_used+' · demanda '+d.scout.demand_used;$('email').textContent=d.outbound.mail_ready&&d.outbound.live?'OPERATIVO':'EN ESPERA';$('email').className='kpi '+(d.outbound.mail_ready&&d.outbound.live?'good':'warn');$('emailDetail').textContent=d.outbound.mail_provider+' · elegibles '+d.outbound.eligible+(d.outbound.blocker?' · '+d.outbound.blocker:'');$('fleet').textContent=d.status.fleet_size;$('fleetDetail').textContent=d.status.worker_status+' · ticks '+d.status.ticks;
$('oppRows').innerHTML=d.opportunities.length?d.opportunities.map(o=>'<tr><td>'+esc(o.id)+'</td><td>'+esc(o.buyer)+'</td><td>'+esc(o.need)+'</td><td class="score">'+esc(o.score)+'</td><td>'+money(o.pipeline)+'</td><td class="source">'+esc(o.source)+'</td></tr>').join(''):empty(6,'Todavía no hay oportunidades registradas.');
$('dealRows').innerHTML=d.deals.length?d.deals.map(x=>'<tr><td>'+esc(x.id)+'</td><td>'+esc(x.buyer)+'</td><td><span class="status">'+esc(x.stage)+'</span></td><td>'+Math.round(Number(x.close_prob||0)*100)+'%</td><td>'+money(x.expected_value)+'</td><td class="profit">'+money(x.company_profit)+' ('+Number(x.company_share_pct||0).toFixed(1)+'%)</td></tr>').join(''):empty(6,'Todavía no hay negocios abiertos.');
$('approvalRows').innerHTML=d.approvals.length?d.approvals.map(a=>'<tr><td>'+esc(a.id)+'</td><td>'+esc(a.deal_id)+'</td><td>'+money(a.company_profit)+'</td><td>'+Number(a.company_share_pct||0).toFixed(1)+'%</td><td>'+esc(a.reason)+'</td></tr>').join(''):empty(5,'No hay cierres esperando aprobación.');
$('activity').innerHTML=d.activity.length?d.activity.map(e=>'<div class="event"><div>'+esc(e.msg)+'</div><div class="time">'+esc(e.ts)+'</div></div>').join(''):'<div class="event">Autopilot listo.</div>';$('lastCycle').textContent='Último ciclo: '+(d.status.last_tick||'sin ejecutar')+' · origen: '+d.status.last_origin+' · persistencia: '+d.status.persistence;
$('policyRows').innerHTML=rows([['Mínimo nuestro',Number(d.policies.min_share||0).toFixed(1)+'%'],['Objetivo nuestro',Number(d.policies.target_share||0).toFixed(1)+'%'],['Reserva de riesgo',Number(d.policies.risk_reserve||0).toFixed(1)+'%']]);
$('funnel').innerHTML=rows([['Leads de investigación',d.funnel.leads],['Cuentas candidatas',d.funnel.candidates],['Empresas verificadas',d.funnel.verified],['Compradores verificados',d.funnel.buyers],['Proveedores verificados',d.funnel.suppliers],['Contactos verificados',d.funnel.contacts],['Demanda pública',d.funnel.demand],['Oportunidades',d.funnel.opportunities],['Propuestas',d.funnel.proposals],['Close ready',d.funnel.close_ready],['Outbound enviados',d.funnel.outbound_sent],['Inbound recibidos',d.funnel.inbound]]);
$('pending').innerHTML=d.pending.length?d.pending.map(p=>'<div class="event"><b>'+esc(p.title)+'</b><div class="tiny">'+esc(p.reason)+'</div></div>').join(''):'<div class="tiny section">Sin pendientes prioritarios.</div>';
$('outRows').innerHTML=d.outbox.length?d.outbox.map(m=>'<tr><td>'+esc(m.id)+'</td><td>'+esc(m.counterparty)+'</td><td>'+esc(m.kind)+'</td><td>'+esc(m.status)+'</td></tr>').join(''):empty(4,'Sin comunicaciones preparadas todavía.');
$('offerRows').innerHTML=d.offers.length?d.offers.map(o=>'<tr><td>'+esc(o.id)+'</td><td>'+esc(o.supplier)+'</td><td>'+money(o.amount)+'</td><td>'+(o.lead_days?esc(o.lead_days)+' días':'—')+'</td><td>'+esc(o.source)+'</td></tr>').join(''):empty(5,'Sin ofertas o cotizaciones registradas.');
$('governance').innerHTML=rows([['Compromiso financiero real','DESHABILITADO'],['Contratos','Aprobación humana'],['Contacto no verificado','No enviar'],['Salida real',d.governance.live_outbound?'ACTIVA':'INACTIVA'],['Email',d.outbound.mail_ready?'OPERATIVO':'EN ESPERA'],['Instagram',d.outbound.instagram?'CONECTADO':'NO CONFIGURADO'],['WhatsApp',d.outbound.whatsapp?'LISTO':'NO DISPONIBLE'],['Persistencia',d.status.persistence]]);
}catch(e){$('updated').textContent='Error leyendo estado';console.error(e)}}load();setInterval(load,30000);
</script></body></html>`;

export default {
  async fetch(request, env) {
    const auth = authOK(request, env);
    if (auth === null) return locked();
    if (!auth) return unauthorized();
    const url = new URL(request.url);
    if (url.pathname === "/health") return Response.json({ok:true,service:"lumen-zero-dashboard",backend:"cloudflare-worker+d1"},{headers:{"Cache-Control":"no-store"}});
    if (url.pathname === "/api/summary") {
      try { const {state,manifest}=await loadState(env); return Response.json(summarize(state,manifest),{headers:{"Cache-Control":"no-store"}}); }
      catch (e) { return Response.json({ok:false,error:String(e?.message||e)},{status:503,headers:{"Cache-Control":"no-store"}}); }
    }
    if (url.pathname === "/" || url.pathname === "/index.html") return new Response(HTML,{headers:{"Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store","X-Frame-Options":"DENY","Referrer-Policy":"no-referrer","X-Content-Type-Options":"nosniff"}});
    return new Response("Not found",{status:404});
  }
};
