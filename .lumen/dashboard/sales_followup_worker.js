import base from "./experiment_worker.js";

const A2A_URL = "https://lumen-zero-a2a.lumen-b2b.workers.dev";

async function scalar(env, sql, binds = []) {
  try {
    let q = env.DB.prepare(sql);
    if (binds.length) q = q.bind(...binds);
    const row = await q.first();
    return Number(row?.n || 0);
  } catch { return 0; }
}

async function rows(env, sql, binds = []) {
  try {
    let q = env.DB.prepare(sql);
    if (binds.length) q = q.bind(...binds);
    const result = await q.all();
    return result.results || [];
  } catch { return []; }
}

async function remote(path) {
  try {
    const r = await fetch(`${A2A_URL}${path}`, { headers: { accept: "application/json" }, cf: { cacheTtl: 0 } });
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

async function towerData(env) {
  const now = new Date().toISOString();
  const [
    opportunities, demand, actionable, highScore, testOnly,
    drafts, approved, sentProposals, respondedProposals,
    qualityPass, qualityFail, outreachSent, outreachResponded, outreachFailed,
    negotiating, waiting, noResponse, lost, dueFollowups, followupsSent,
    settlements
  ] = await Promise.all([
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_opportunities"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_opportunities WHERE demand_signal=1"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_opportunity_assessments WHERE commercially_actionable=1"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_opportunity_assessments WHERE commercial_score>=65 AND synthetic_or_test_only=0"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_opportunity_assessments WHERE synthetic_or_test_only=1"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_proposal_drafts WHERE status='DRAFT'"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_proposal_drafts WHERE status='APPROVED'"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_proposal_drafts WHERE status='SENT'"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_proposal_drafts WHERE status='RESPONDED'"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_proposal_drafts WHERE quality_gate_status='PASS'"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_proposal_drafts WHERE quality_gate_status='FAIL'"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_outreach_attempts WHERE status IN ('SENT','SENT_TASK','WORKING','RESPONDED','TASK_TERMINAL')"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_outreach_attempts WHERE status='RESPONDED'"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_outreach_attempts WHERE status='SEND_FAILED'"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_sales_pipeline WHERE stage='NEGOTIATING'"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_sales_pipeline WHERE stage IN ('WAITING','WAITING_TASK')"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_sales_pipeline WHERE stage='NO_RESPONSE'"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_sales_pipeline WHERE stage='LOST'"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_sales_pipeline WHERE stage='WAITING' AND next_action_at IS NOT NULL AND next_action_at<=?",[now]),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_followups WHERE status IN ('SENT','SENT_TASK','WORKING','RESPONDED')"),
    scalar(env,"SELECT COUNT(*) AS n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'")
  ]);

  let realizedRevenueUsd = 0;
  try {
    const r = await env.DB.prepare("SELECT COALESCE(SUM(amount_usd),0) AS n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'").first();
    realizedRevenueUsd = Number(r?.n || 0);
  } catch {}

  const pipeline = await rows(env,"SELECT proposal_id,opportunity_id,target,offer_name,amount_usd,stage,response_class,last_contact_at,next_action,next_action_at,followup_count,updated_at,notes FROM lumen_sales_pipeline ORDER BY CASE stage WHEN 'NEGOTIATING' THEN 1 WHEN 'RESPONDED' THEN 2 WHEN 'WAITING' THEN 3 WHEN 'WAITING_TASK' THEN 4 WHEN 'APPROVED' THEN 5 ELSE 6 END, COALESCE(next_action_at,updated_at) ASC LIMIT 60");
  const top = await rows(env,"SELECT o.id,o.name,o.revenue_offer_id,a.commercial_score,a.commercial_fit,a.evidence_strength FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id WHERE a.commercially_actionable=1 AND a.synthetic_or_test_only=0 ORDER BY a.commercial_score DESC,o.updated_at DESC LIMIT 8");
  const recent = await rows(env,"SELECT proposal_id,opportunity_id,status,updated_at,task_id,error FROM lumen_outreach_attempts ORDER BY updated_at DESC LIMIT 8");

  const [health, outreachLive, followupLive, revenueLive] = await Promise.all([
    remote("/health"), remote("/outreach/stats"), remote("/followup/stats"), remote("/revenue/loop")
  ]);

  let objective = "GENERAR INGRESOS";
  let bestAction = "Buscar y calificar demanda nueva";
  let actionState = "BUSCANDO";
  if (negotiating > 0) { bestAction = "Priorizar respuestas con intención y llevarlas a checkout"; actionState = "NEGOCIANDO"; }
  else if (dueFollowups > 0) { bestAction = `Ejecutar ${dueFollowups} seguimiento${dueFollowups===1?"":"s"} comercial${dueFollowups===1?"":"es"} vencido${dueFollowups===1?"":"s"}`; actionState = "SIGUIENDO"; }
  else if (waiting > 0) { bestAction = "Esperar cooldowns y seguir prospectando sin duplicar contactos"; actionState = "ESPERANDO RESPUESTAS"; }
  else if (approved > 0 || qualityPass > outreachSent) { bestAction = "Enviar la próxima propuesta aprobada por Quality Gate"; actionState = "EJECUTANDO"; }
  else if (actionable > 0) { bestAction = "Convertir la mejor oportunidad comercial en propuesta"; actionState = "PREPARANDO"; }
  if (settlements > 0) { objective = "ESCALAR INGRESOS VERIFICADOS"; }

  return {
    version:"2.0-control-tower",
    generatedAt:now,
    objective,bestAction,actionState,
    system:{
      a2aOnline:Boolean(health?.ok), x402:health?.x402 || "UNKNOWN",
      outreachAutonomous:outreachLive?.autonomousOutreachEnabled === true,
      followupAutonomous:followupLive?.autonomousFollowupEnabled === true,
      autonomousOutgoingSpend:false, autonomousContract:false,
      cooldownDays:Number(followupLive?.cooldownDays || 4), maxFollowups:Number(followupLive?.maxFollowups || 2)
    },
    funnel:{ opportunities,demand,actionable,highScore,testOnly,drafts,approved,qualityPass,qualityFail,outreachSent,outreachResponded,outreachFailed,sentProposals,respondedProposals,negotiating,waiting,noResponse,lost,dueFollowups,followupsSent,settlements,realizedRevenueUsd },
    revenue: revenueLive?.funnel || { verifiedSettlements:settlements,realizedRevenueUsd },
    pipeline,top,recent
  };
}

async function protectedTowerData(request, env, ctx) {
  const probeUrl = new URL(request.url); probeUrl.pathname = "/health"; probeUrl.search = "";
  const probe = await base.fetch(new Request(probeUrl.toString(), { method:"GET", headers:request.headers }), env, ctx);
  if (!probe.ok) return probe;
  return Response.json(await towerData(env), { headers:{ "cache-control":"no-store", "x-content-type-options":"nosniff" } });
}

const STYLE = `<style id="lumenControlV2Style">
.ctHero{background:linear-gradient(135deg,#111b25,#10202d 55%,#14291d);border-color:#39566f}.ctObjective{font-size:30px;font-weight:950;letter-spacing:-.03em;margin:8px 0}.ctState{display:inline-flex;padding:7px 11px;border:1px solid #496e35;border-radius:999px;background:#162716;color:#d9ff65;font-weight:900}.ctGrid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.ctValue{font-size:26px;font-weight:950;margin-top:6px}.ctSplit{display:grid;grid-template-columns:1.1fr .9fr;gap:11px}.ctFunnel{display:grid;grid-template-columns:repeat(7,1fr);gap:7px}.ctStep{padding:12px;border:1px solid #263a49;border-radius:12px;background:#0c151d;text-align:center}.ctStep strong{display:block;font-size:20px;margin-top:4px}.ctTable{overflow:auto}.ctTable table{min-width:980px}.ctStage{font-weight:900}.ct-negotiating{color:#d9ff65}.ct-waiting,.ct-waiting_task{color:#78c7ff}.ct-no_response,.ct-lost{color:#ff8b8b}.ct-responded{color:#b3ffb3}@media(max-width:1000px){.ctGrid{grid-template-columns:repeat(2,1fr)}.ctFunnel{grid-template-columns:repeat(4,1fr)}.ctSplit{grid-template-columns:1fr}}@media(max-width:560px){.ctGrid,.ctFunnel{grid-template-columns:1fr 1fr}.ctObjective{font-size:24px}}
</style>`;

const SECTION = `<section class="page" id="controlv2"><div class="card ctHero"><div class="klabel">LUMEN · Torre de Control v2</div><div class="ctObjective" id="ctObjective">GENERAR INGRESOS</div><div class="ctState" id="ctState">CARGANDO</div><p class="note" id="ctBestAction">Leyendo la mejor acción económica segura disponible…</p></div><div class="ctGrid section"><div class="card"><div class="klabel">Oportunidades</div><div class="ctValue" id="ctOpp">0</div></div><div class="card"><div class="klabel">Accionables</div><div class="ctValue" id="ctActionable">0</div></div><div class="card"><div class="klabel">Enviadas</div><div class="ctValue" id="ctSent">0</div></div><div class="card"><div class="klabel">Respuestas</div><div class="ctValue" id="ctResponded">0</div></div><div class="card"><div class="klabel">Negociando</div><div class="ctValue" id="ctNegotiating">0</div></div><div class="card"><div class="klabel">Follow-ups enviados</div><div class="ctValue" id="ctFollowups">0</div></div><div class="card"><div class="klabel">Cobros verificados</div><div class="ctValue" id="ctSettlements">0</div></div><div class="card"><div class="klabel">Ingresos verificados</div><div class="ctValue" id="ctRevenue">USD 0</div></div></div><div class="card section"><h2>Embudo de dinero</h2><div class="ctFunnel" id="ctFunnel"></div></div><div class="ctSplit section"><div class="card"><h2>Seguimiento comercial</h2><div id="ctFollowupSummary"></div></div><div class="card"><h2>Autonomía y seguridad</h2><div id="ctSafety"></div></div></div><div class="card section"><h2>Pipeline comercial vivo</h2><div class="ctTable" id="ctPipeline"><div class="empty">Cargando pipeline…</div></div></div><div class="ctSplit section"><div class="card"><h2>Mejores oportunidades</h2><div id="ctTop"></div></div><div class="card"><h2>Actividad A2A reciente</h2><div id="ctRecent"></div></div></div></section>`;

const SCRIPT = `<script id="lumenControlV2Script">(()=>{const e=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])),usd=v=>'USD '+Number(v||0).toLocaleString('es-AR',{maximumFractionDigits:2}),line=(a,b)=>'<div class="statusline"><span>'+esc(a)+'</span><strong>'+b+'</strong></div>',stage=v=>'<span class="ctStage ct-'+esc(String(v||'').toLowerCase())+'">'+esc(v||'—')+'</span>';async function load(){try{const r=await fetch('/api/control-tower-v2',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json(),f=d.funnel||{},s=d.system||{};e('ctObjective').textContent=d.objective||'GENERAR INGRESOS';e('ctState').textContent=d.actionState||'—';e('ctBestAction').textContent='Mejor acción segura ahora: '+(d.bestAction||'—');e('ctOpp').textContent=Number(f.opportunities||0);e('ctActionable').textContent=Number(f.actionable||0);e('ctSent').textContent=Number(f.outreachSent||0);e('ctResponded').textContent=Number(f.outreachResponded||0);e('ctNegotiating').textContent=Number(f.negotiating||0);e('ctFollowups').textContent=Number(f.followupsSent||0);e('ctSettlements').textContent=Number(f.settlements||0);e('ctRevenue').textContent=usd(f.realizedRevenueUsd);const funnel=[['Detectadas',f.opportunities],['Demanda',f.demand],['Accionables',f.actionable],['Quality PASS',f.qualityPass],['Enviadas',f.outreachSent],['Respuestas',f.outreachResponded],['Cobros',f.settlements]];e('ctFunnel').innerHTML=funnel.map(x=>'<div class="ctStep"><span class="small">'+esc(x[0])+'</span><strong>'+Number(x[1]||0)+'</strong></div>').join('');e('ctFollowupSummary').innerHTML=line('Esperando respuesta',Number(f.waiting||0))+line('Follow-up vencidos',Number(f.dueFollowups||0))+line('En negociación',Number(f.negotiating||0))+line('Sin respuesta / límite',Number(f.noResponse||0))+line('Perdidas / no relevantes',Number(f.lost||0))+line('Cooldown',Number(s.cooldownDays||4)+' días')+line('Máximo follow-ups',Number(s.maxFollowups||2));e('ctSafety').innerHTML=line('A2A',s.a2aOnline?'<span class="chip ok">ONLINE</span>':'<span class="chip no">OFFLINE</span>')+line('x402','<span class="chip '+(s.x402==='READY'?'ok':'')+'">'+esc(s.x402||'—')+'</span>')+line('Outreach autónomo',s.outreachAutonomous?'<span class="chip ok">ON</span>':'<span class="chip">OFF</span>')+line('Follow-up autónomo',s.followupAutonomous?'<span class="chip ok">ON</span>':'<span class="chip">OFF</span>')+line('Gasto autónomo','<strong>USD 0</strong>')+line('Contratos automáticos','NO')+line('Quality Gate','OBLIGATORIO')+line('Mensajes externos','Máx. 1 por ciclo');const p=Array.isArray(d.pipeline)?d.pipeline:[];e('ctPipeline').innerHTML=p.length?'<table><thead><tr><th>Target</th><th>Oferta</th><th>USD</th><th>Etapa</th><th>Respuesta</th><th>Follow-ups</th><th>Próxima acción</th><th>Cuándo</th></tr></thead><tbody>'+p.map(x=>'<tr><td>'+esc(x.target||'—')+'</td><td>'+esc(x.offer_name||'—')+'</td><td>'+usd(x.amount_usd)+'</td><td>'+stage(x.stage)+'</td><td>'+esc(x.response_class||'—')+'</td><td>'+Number(x.followup_count||0)+'</td><td>'+esc(x.next_action||'—')+'</td><td class="small">'+esc(x.next_action_at||'—')+'</td></tr>').join('')+'</tbody></table>':'<div class="empty">Todavía no hay pipeline comercial.</div>';const top=Array.isArray(d.top)?d.top:[];e('ctTop').innerHTML=top.length?top.map(x=>'<div class="event"><strong>'+esc(x.name||'—')+'</strong><div class="small">Score '+Number(x.commercial_score||0)+' · '+esc(x.commercial_fit||'—')+' · evidencia '+esc(x.evidence_strength||'—')+'</div><div class="small mono">'+esc(x.revenue_offer_id||'—')+'</div></div>').join(''):'<div class="empty">Sin oportunidades accionables.</div>';const recent=Array.isArray(d.recent)?d.recent:[];e('ctRecent').innerHTML=recent.length?recent.map(x=>'<div class="event"><strong>'+esc(x.status||'—')+'</strong><div class="small mono">'+esc(x.proposal_id||'—')+'</div><div class="small">'+esc(x.updated_at||'')+(x.error?' · '+esc(x.error):'')+'</div></div>').join(''):'<div class="empty">Sin actividad A2A.</div>'}catch(err){if(e('ctBestAction'))e('ctBestAction').textContent='No pude leer Control v2: '+err.message}}load();setInterval(load,30000)})();</script>`;

function inject(html) {
  if (html.includes('id="lumenControlV2Script"')) return html;
  html = html.replace("</head>", STYLE + "</head>");
  const experimentTab = /<button\b[^>]*(?:data-p|data-tab)=["']experiments["'][^>]*>[\s\S]*?<\/button>/i;
  const commercialTab = /<button\b[^>]*(?:data-p|data-tab)=["']commercial["'][^>]*>[\s\S]*?<\/button>/i;
  if (experimentTab.test(html)) html = html.replace(experimentTab, m => m + '<button class="tab" data-p="controlv2">Control v2</button>');
  else if (commercialTab.test(html)) html = html.replace(commercialTab, m => m + '<button class="tab" data-p="controlv2">Control v2</button>');
  else html = html.replace(/(<div\b[^>]*class=["'][^"']*\btabs\b[^"']*["'][^>]*>)/i, m => m + '<button class="tab" data-p="controlv2">Control v2</button>');
  if (html.includes('<section class="page" id="infra">')) html = html.replace('<section class="page" id="infra">', SECTION + '<section class="page" id="infra">');
  else html = html.replace("</body>", SECTION + "</body>");
  return html.replace("</body>", SCRIPT + "</body>");
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/control-tower-v2") return protectedTowerData(request, env, ctx);
    const response = await base.fetch(request, env, ctx);
    if (request.method !== "GET" || response.status !== 200) return response;
    if (!["/", "/index.html", "/full"].includes(url.pathname)) return response;
    if (!String(response.headers.get("content-type") || "").includes("text/html")) return response;
    const html = inject(await response.text());
    const headers = new Headers(response.headers); headers.delete("content-length"); headers.set("cache-control","no-store");
    return new Response(html,{status:response.status,statusText:response.statusText,headers});
  }
};
