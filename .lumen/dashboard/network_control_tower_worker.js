import base from "./control_tower_live_status_worker.js";

async function serviceJson(env, path) {
  try {
    if (!env?.A2A) return null;
    const response = await env.A2A.fetch(new Request(`https://lumen-a2a.internal${path}`, {
      method: "GET",
      headers: { accept: "application/json" }
    }));
    return response.ok ? await response.json() : null;
  } catch { return null; }
}

async function rows(env, sql, binds = []) {
  try {
    let q = env.DB.prepare(sql);
    if (binds.length) q = q.bind(...binds);
    const r = await q.all();
    return r.results || [];
  } catch { return []; }
}

function num(v) { return Number(v || 0); }
function online(v) { return v && typeof v === "object"; }

function moduleRow(id, name, state, metric, detail = "") {
  return { id, name, state, metric, detail };
}

function stateFor(value, active = true) {
  if (!online(value)) return "SIN DATOS";
  return active ? "OPERATIVO" : "LISTO";
}

function bestNetworkAction(data) {
  const economy = data.economy || {};
  const negotiator = data.negotiator || {};
  const council = data.council || {};
  const marketplace = data.marketplace || {};
  const referrals = data.referrals || {};
  const gaps = data.gaps || {};

  if (num(economy.realizedIncomeUsd) > 0) return "Escalar los servicios y combinaciones que ya produjeron ingresos verificados.";
  if (num(negotiator.readyForHumanReview) > 0) return "Revisar la mejor recomendación comercial completa antes de cualquier contratación o gasto.";
  if (num(negotiator.incompleteTerms) > 0) return "Completar precios y plazos comparables del Negotiator sin comprometer fondos.";
  if (num(council.rooms) > 0 && num(council.synthesized) === 0) return "Conseguir la siguiente contribución de calidad y cerrar la primera síntesis multiagente válida.";
  if (num(marketplace?.interests?.matchCandidates) > 0) return "Evaluar candidatos entrantes del Marketplace con Trust y capacidad antes de integrarlos.";
  if (num(referrals.trustedInbound) > 0) return "Calificar el referral entrante confiable y conectarlo al flujo comercial sin perder atribución.";
  if (num(gaps.open) > 0 || num(gaps.weakCoverage) > 0) return "Reclutar para el gap de capacidad de mayor prioridad y reforzar redundancia.";
  return "Seguir descubriendo agentes, midiendo resultados y priorizando combinaciones con valor económico verificable.";
}

async function networkData(env) {
  const [
    partners, recruitment, council, delegation, observed, venture,
    gaps, graph, marketplace, referrals, negotiator, dynamicTeams,
    redundancy, trust, economy
  ] = await Promise.all([
    serviceJson(env, "/partners/stats"),
    serviceJson(env, "/recruitment/stats"),
    serviceJson(env, "/council-runtime/stats"),
    serviceJson(env, "/delegation/stats"),
    serviceJson(env, "/partners/observed-reputation/stats"),
    serviceJson(env, "/venture-council/stats"),
    serviceJson(env, "/capability-gaps/stats"),
    serviceJson(env, "/agent-graph/stats"),
    serviceJson(env, "/partner-marketplace/stats"),
    serviceJson(env, "/referrals/stats"),
    serviceJson(env, "/negotiator/stats"),
    serviceJson(env, "/dynamic-teams/stats"),
    serviceJson(env, "/redundancy/stats"),
    serviceJson(env, "/trust/stats"),
    serviceJson(env, "/agent-economy/stats")
  ]);

  const [topPartners, rooms, tasks, ventures, negotiations, referralRows, gapRows, economyIntents, teams, graphEdges] = await Promise.all([
    rows(env, `SELECT p.id,p.name,p.capabilities_json,p.reputation_score,p.compatibility_score,p.status,
      t.trust_score,t.trust_level,t.signature_status,
      o.score AS observed_score,o.confidence AS observed_confidence,o.reliability_score,o.responsiveness_score
      FROM lumen_partner_agents p
      LEFT JOIN lumen_partner_trust t ON t.partner_id=p.id
      LEFT JOIN lumen_partner_observed_reputation o ON o.partner_id=p.id
      ORDER BY CASE COALESCE(t.trust_level,'UNASSESSED') WHEN 'ALLOW' THEN 0 WHEN 'CAUTION' THEN 1 WHEN 'RESTRICTED' THEN 2 WHEN 'QUARANTINE' THEN 3 ELSE 4 END,
      COALESCE(t.trust_score,0) DESC,COALESCE(o.confidence,0) DESC,p.reputation_score DESC LIMIT 12`),
    rows(env, `SELECT r.id,r.status,r.round_no,r.objective,r.alignment_score,r.external_messages,r.updated_at,
      (SELECT COUNT(*) FROM lumen_council_room_members m WHERE m.room_id=r.id) AS members,
      (SELECT COUNT(*) FROM lumen_council_room_members m WHERE m.room_id=r.id AND m.contribution_text IS NOT NULL AND TRIM(m.contribution_text)<>'') AS contributions
      FROM lumen_council_rooms r ORDER BY r.updated_at DESC LIMIT 8`),
    rows(env, `SELECT id,room_id,partner_name,role,title,status,quality_score,updated_at,error
      FROM lumen_delegation_tasks ORDER BY updated_at DESC LIMIT 10`),
    rows(env, `SELECT id,title,status,readiness_score,coverage_score,gap_count,next_experiment,updated_at
      FROM lumen_venture_cases WHERE status<>'SOURCE_REJECTED' ORDER BY readiness_score DESC,updated_at DESC LIMIT 8`),
    rows(env, `SELECT id,title,status,commercial_score,candidate_count,priced_candidate_count,recommended_partner_name,recommendation_score,recommendation_confidence,decision_mode,updated_at
      FROM lumen_negotiation_cases ORDER BY commercial_score DESC,updated_at DESC LIMIT 8`),
    rows(env, `SELECT id,direction,title,capability,status,origin_partner_name,target_partner_name,trust_level,match_score,settled_revenue_usd,updated_at
      FROM lumen_referrals ORDER BY updated_at DESC LIMIT 10`),
    rows(env, `SELECT capability,priority,status,current_candidates,strong_candidates,observed_confident_candidates,best_partner_name,suggested_search,source_type,updated_at
      FROM lumen_capability_gap_queue WHERE status<>'COVERED' ORDER BY priority DESC,updated_at DESC LIMIT 10`),
    rows(env, `SELECT direction,kind,status,counterparty_name,service_name,amount_usd,approval_status,settlement_status,settled_amount_usd,updated_at
      FROM lumen_agent_economy_intents ORDER BY updated_at DESC LIMIT 12`),
    rows(env, `SELECT id,opportunity_id,status,team_score,coverage_score,member_quality_score,graph_affinity_score,risk_penalty,members_json,updated_at
      FROM lumen_dynamic_teams WHERE status='DRAFT_TEAM' ORDER BY team_score DESC,updated_at DESC LIMIT 6`),
    rows(env, `SELECT e.relation_type,e.contexts,e.successes,e.failures,e.affinity_score,e.shared_capabilities_json,e.updated_at,
      a.name AS source_name,b.name AS target_name
      FROM lumen_agent_graph_edges e
      LEFT JOIN lumen_agent_graph_nodes a ON a.partner_id=e.source_partner_id
      LEFT JOIN lumen_agent_graph_nodes b ON b.partner_id=e.target_partner_id
      ORDER BY e.affinity_score DESC,e.contexts DESC LIMIT 8`)
  ]);

  const modules = [
    moduleRow(1,"Recruitment Engine",stateFor(recruitment || partners),`${num(partners?.total)} agentes descubiertos`,`${num(partners?.strongCandidates)} candidatos fuertes`),
    moduleRow(2,"Sala de Juntas",stateFor(council),`${num(council?.rooms)} salas`,`${num(council?.contributions)} contribuciones`),
    moduleRow(3,"Delegación de tareas",stateFor(delegation),`${num(delegation?.total)} tareas`,`${num(delegation?.completed)} completadas`),
    moduleRow(4,"Reputación observada",stateFor(observed),`${num(observed?.withEvidence)} con evidencia`,`${num(observed?.meaningfulConfidence)} con confidence ≥30`),
    moduleRow(5,"Venture Council",stateFor(venture),`${num(venture?.total)} casos`,`mejor readiness ${num(venture?.bestReadiness)}`),
    moduleRow(6,"Capability Gap Engine",stateFor(gaps),`${num(gaps?.open)} gaps abiertos`,`${num(gaps?.weakCoverage)} cobertura débil`),
    moduleRow(7,"Agent Graph",stateFor(graph),`${num(graph?.nodes)} nodos / ${num(graph?.edges)} vínculos`,`${num(graph?.positiveCombinations)} combinaciones positivas`),
    moduleRow(8,"Partner Marketplace",stateFor(marketplace),`${num(marketplace?.needs?.open)} necesidades abiertas`,`${num(marketplace?.interests?.matchCandidates)} matches entrantes`),
    moduleRow(9,"Referral Network",stateFor(referrals),`${num(referrals?.total)} referrals`,`${num(referrals?.outboundCandidates)} outbound candidates`),
    moduleRow(10,"Economía entre agentes",stateFor(economy),`USD ${num(economy?.potentialIncomeUsd)} potencial`, `USD ${num(economy?.realizedIncomeUsd)} realizado`),
    moduleRow(11,"Negotiator",stateFor(negotiator),`${num(negotiator?.totalCases)} casos`,`${num(negotiator?.readyForHumanReview)} listos para revisión`),
    moduleRow(12,"Equipos dinámicos",stateFor(dynamicTeams),`${num(dynamicTeams?.activeDraftTeams)} equipos activos`, `mejor score ${num(dynamicTeams?.bestTeamScore)}`),
    moduleRow(13,"Redundancia",stateFor(redundancy),`${num(redundancy?.ready || redundancy?.readyFallbacks)} fallbacks listos`, `${num(redundancy?.weak || redundancy?.weakFallbacks)} débiles`),
    moduleRow(14,"Trust Layer",stateFor(trust),`${num(trust?.allow)} ALLOW / ${num(trust?.caution)} CAUTION`,`${num(trust?.quarantine)} cuarentena`),
    moduleRow(15,"Torre de Control de la Red","ONLINE","lectura viva","sin gasto autónomo")
  ];

  const data = {
    version: "1.0-network-control-tower",
    generatedAt: new Date().toISOString(),
    objective: "ORQUESTAR LA RED Y CONVERTIR COLABORACIÓN EN INGRESOS VERIFICADOS",
    partners, recruitment, council, delegation, observed, venture, gaps, graph,
    marketplace, referrals, negotiator, dynamicTeams, redundancy, trust, economy,
    modules,
    topPartners, rooms, tasks, ventures, negotiations, referralRows, gapRows,
    economyIntents, teams, graphEdges,
    guardrails: {
      outgoingBudgetUsd: 0,
      outgoingSpendHardBlocked: economy?.outgoingSpendHardBlocked !== false,
      autonomousOutgoingSpend: false,
      autonomousPurchase: false,
      autonomousContract: false,
      bindingActionsHumanGated: true,
      verifiedSettlementRequiredForIncome: true
    }
  };
  data.bestAction = bestNetworkAction(data);
  return data;
}

async function protectedNetworkData(request, env, ctx) {
  const probeUrl = new URL(request.url);
  probeUrl.pathname = "/health";
  probeUrl.search = "";
  const probe = await base.fetch(new Request(probeUrl.toString(), { method: "GET", headers: request.headers }), env, ctx);
  if (!probe.ok) return probe;
  return Response.json(await networkData(env), {
    headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" }
  });
}

const STYLE = `<style id="lumenNetworkTowerStyle">
.ntHero{background:linear-gradient(135deg,#111827,#12253a 52%,#16311f);border-color:#385c73}.ntTitle{font-size:31px;font-weight:950;letter-spacing:-.035em;margin:8px 0}.ntBadge{display:inline-flex;align-items:center;padding:7px 11px;border:1px solid #456b52;border-radius:999px;background:#11291c;color:#cfff85;font-weight:900}.ntGrid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.ntKpi{font-size:25px;font-weight:950;margin-top:5px}.ntMoney{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.ntMoney .card{min-height:112px}.ntModules{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.ntModule{border:1px solid #263a49;background:#0d171f;border-radius:13px;padding:12px}.ntModuleTop{display:flex;gap:9px;align-items:center;justify-content:space-between}.ntModuleNo{display:grid;place-items:center;min-width:30px;height:30px;border-radius:9px;background:#17283a;font-weight:950}.ntModuleState{font-size:11px;font-weight:950;border:1px solid #3c5668;border-radius:999px;padding:4px 7px}.ntModuleState.online,.ntModuleState.operativo{color:#cfff85;border-color:#466b38;background:#142511}.ntModuleState.listo{color:#7ed0ff}.ntModuleState.sin-datos{color:#ffbf7d}.ntSplit{display:grid;grid-template-columns:1fr 1fr;gap:11px}.ntTable{overflow:auto}.ntTable table{min-width:930px}.ntBar{height:8px;border-radius:999px;background:#192834;overflow:hidden;margin-top:6px}.ntBar>span{display:block;height:100%;background:linear-gradient(90deg,#5ea7ff,#b8ff66)}.ntChip{display:inline-flex;border:1px solid #345064;border-radius:999px;padding:3px 7px;font-size:11px;font-weight:900}.ntGood{color:#cfff85;border-color:#496b39}.ntWarn{color:#ffd086;border-color:#6c5531}.ntBad{color:#ff9a9a;border-color:#6d3b3b}.ntEvent{padding:10px 0;border-bottom:1px solid #1f303d}.ntEvent:last-child{border-bottom:0}.ntMuted{color:#8da2b5}.ntGuard{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.ntGuard>div{border:1px solid #263a49;border-radius:12px;padding:11px;background:#0c151d}@media(max-width:1100px){.ntGrid{grid-template-columns:repeat(3,1fr)}.ntModules{grid-template-columns:repeat(2,1fr)}.ntMoney{grid-template-columns:repeat(2,1fr)}}@media(max-width:760px){.ntGrid,.ntMoney,.ntModules,.ntSplit,.ntGuard{grid-template-columns:1fr 1fr}.ntTitle{font-size:25px}}@media(max-width:520px){.ntGrid,.ntMoney,.ntModules,.ntSplit,.ntGuard{grid-template-columns:1fr}}
</style>`;

const SECTION = `<section class="page" id="networktower">
<div class="card ntHero"><div class="klabel">LUMEN · #15 TORRE DE CONTROL DE LA RED</div><div class="ntTitle" id="ntObjective">ORQUESTANDO RED MULTIAGENTE</div><div class="ntBadge" id="ntState">CARGANDO RED</div><p class="note" id="ntBestAction">Calculando la mejor acción segura para la red…</p></div>
<div class="ntGrid section"><div class="card"><div class="klabel">Agentes descubiertos</div><div class="ntKpi" id="ntPartners">0</div></div><div class="card"><div class="klabel">Trust ALLOW</div><div class="ntKpi" id="ntAllow">0</div></div><div class="card"><div class="klabel">Salas</div><div class="ntKpi" id="ntRooms">0</div></div><div class="card"><div class="klabel">Tareas</div><div class="ntKpi" id="ntTasks">0</div></div><div class="card"><div class="klabel">Equipos dinámicos</div><div class="ntKpi" id="ntTeams">0</div></div><div class="card"><div class="klabel">Marketplace abierto</div><div class="ntKpi" id="ntNeeds">0</div></div><div class="card"><div class="klabel">Referrals</div><div class="ntKpi" id="ntReferrals">0</div></div><div class="card"><div class="klabel">Negotiator</div><div class="ntKpi" id="ntNegotiations">0</div></div><div class="card"><div class="klabel">Venture cases</div><div class="ntKpi" id="ntVentures">0</div></div><div class="card"><div class="klabel">Gaps abiertos</div><div class="ntKpi" id="ntGaps">0</div></div></div>
<div class="section"><h2>Economía de la red</h2><div class="ntMoney"><div class="card"><div class="klabel">Valor comercial potencial</div><div class="ntKpi" id="ntPotential">USD 0</div><div class="small ntMuted">No cuenta como ingreso.</div></div><div class="card"><div class="klabel">Ingreso realizado verificado</div><div class="ntKpi" id="ntRealized">USD 0</div><div class="small ntMuted">Sólo settlement verificado.</div></div><div class="card"><div class="klabel">Egreso propuesto</div><div class="ntKpi" id="ntExpense">USD 0</div><div class="small ntMuted">Requiere aprobación humana.</div></div><div class="card"><div class="klabel">Presupuesto autónomo saliente</div><div class="ntKpi">USD 0</div><div class="small" id="ntSpendBlock">HARD BLOCK</div></div></div></div>
<div class="card section"><h2>Los 15 sistemas de la red</h2><div class="ntModules" id="ntModules"></div></div>
<div class="card section"><h2>Socios y agentes destacados</h2><div class="ntTable" id="ntPartnersTable"><div class="empty">Cargando agentes…</div></div></div>
<div class="ntSplit section"><div class="card"><h2>Salas de juntas</h2><div id="ntRoomsList"></div></div><div class="card"><h2>Delegaciones</h2><div id="ntTasksList"></div></div></div>
<div class="ntSplit section"><div class="card"><h2>Negotiator</h2><div id="ntNegotiatorList"></div></div><div class="card"><h2>Referrals</h2><div id="ntReferralList"></div></div></div>
<div class="ntSplit section"><div class="card"><h2>Venture Council</h2><div id="ntVentureList"></div></div><div class="card"><h2>Capability Gaps</h2><div id="ntGapList"></div></div></div>
<div class="ntSplit section"><div class="card"><h2>Equipos dinámicos</h2><div id="ntTeamList"></div></div><div class="card"><h2>Agent Graph · mejores combinaciones</h2><div id="ntGraphList"></div></div></div>
<div class="card section"><h2>Intenciones económicas recientes</h2><div class="ntTable" id="ntEconomyList"></div></div>
<div class="card section"><h2>Guardrails permanentes</h2><div class="ntGuard" id="ntGuardrails"></div></div>
</section>`;

const SCRIPT = `<script id="lumenNetworkTowerScript">(()=>{
const e=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])), n=v=>Number(v||0), usd=v=>'USD '+n(v).toLocaleString('es-AR',{maximumFractionDigits:2}), pct=v=>Math.max(0,Math.min(100,n(v))), chip=(v,kind='')=>'<span class="ntChip '+kind+'">'+esc(v)+'</span>', event=(title,sub,more='')=>'<div class="ntEvent"><strong>'+esc(title||'—')+'</strong><div class="small ntMuted">'+esc(sub||'')+'</div>'+(more?'<div class="small">'+esc(more)+'</div>':'')+'</div>';
function caps(raw){try{const x=JSON.parse(raw||'[]');return Array.isArray(x)?x.slice(0,4).join(', '):''}catch{return''}}
function members(raw){try{const x=JSON.parse(raw||'[]');return Array.isArray(x)?x.slice(0,4).map(m=>(m.name||'agente')+' · '+(m.role||'rol')).join(' | '):''}catch{return''}}
function stateClass(v){return String(v||'').toLowerCase().replace(/[^a-z0-9]+/g,'-')}
async function load(){try{
 const r=await fetch('/api/network-control-v1',{cache:'no-store'}); if(!r.ok)throw new Error('HTTP '+r.status); const d=await r.json();
 const p=d.partners||{},t=d.trust||{},c=d.council||{},dg=d.delegation||{},m=d.marketplace||{},rf=d.referrals||{},ng=d.negotiator||{},vt=d.venture||{},gp=d.gaps||{},dt=d.dynamicTeams||{},eco=d.economy||{},g=d.guardrails||{};
 e('ntObjective').textContent=d.objective||'ORQUESTAR LA RED'; e('ntState').textContent='RED '+(n(p.total)||0)+' AGENTES · '+(n(t.allow)||0)+' TRUST ALLOW'; e('ntBestAction').textContent='Mejor acción segura ahora: '+(d.bestAction||'—');
 e('ntPartners').textContent=n(p.total); e('ntAllow').textContent=n(t.allow); e('ntRooms').textContent=n(c.rooms); e('ntTasks').textContent=n(dg.total); e('ntTeams').textContent=n(dt.activeDraftTeams); e('ntNeeds').textContent=n(m?.needs?.open); e('ntReferrals').textContent=n(rf.total); e('ntNegotiations').textContent=n(ng.totalCases); e('ntVentures').textContent=n(vt.total); e('ntGaps').textContent=n(gp.open)+n(gp.weakCoverage);
 e('ntPotential').textContent=usd(eco.potentialIncomeUsd); e('ntRealized').textContent=usd(eco.realizedIncomeUsd); e('ntExpense').textContent=usd(eco.proposedExpenseUsd); e('ntSpendBlock').innerHTML=g.outgoingSpendHardBlocked?chip('HARD BLOCK ACTIVO','ntGood'):chip('REVISAR','ntBad');
 const mods=Array.isArray(d.modules)?d.modules:[]; e('ntModules').innerHTML=mods.map(x=>'<div class="ntModule"><div class="ntModuleTop"><div style="display:flex;gap:8px;align-items:center"><span class="ntModuleNo">'+n(x.id)+'</span><strong>'+esc(x.name)+'</strong></div><span class="ntModuleState '+stateClass(x.state)+'">'+esc(x.state)+'</span></div><div class="small" style="margin-top:8px">'+esc(x.metric||'')+'</div><div class="small ntMuted">'+esc(x.detail||'')+'</div></div>').join('');
 const tp=Array.isArray(d.topPartners)?d.topPartners:[]; e('ntPartnersTable').innerHTML=tp.length?'<table><thead><tr><th>Agente</th><th>Trust</th><th>Reputación declarada</th><th>Observada</th><th>Confidence</th><th>Reliability</th><th>Capacidades</th></tr></thead><tbody>'+tp.map(x=>'<tr><td><strong>'+esc(x.name||'—')+'</strong></td><td>'+chip((x.trust_level||'UNASSESSED')+' '+n(x.trust_score),x.trust_level==='ALLOW'?'ntGood':x.trust_level==='CAUTION'?'ntWarn':'')+'</td><td>'+n(x.reputation_score)+'</td><td>'+((x.observed_score??null)===null?'—':n(x.observed_score))+'</td><td>'+n(x.observed_confidence)+'</td><td>'+((x.reliability_score??null)===null?'—':n(x.reliability_score))+'</td><td class="small">'+esc(caps(x.capabilities_json)||'—')+'</td></tr>').join('')+'</tbody></table>':'<div class="empty">Todavía no hay agentes registrados.</div>';
 const rooms=Array.isArray(d.rooms)?d.rooms:[]; e('ntRoomsList').innerHTML=rooms.length?rooms.map(x=>event(x.id+' · '+x.status,'Ronda '+n(x.round_no)+' · '+n(x.contributions)+'/'+n(x.members)+' contribuciones','Alineación '+(x.alignment_score==null?'—':n(x.alignment_score))+' · mensajes externos '+n(x.external_messages))).join(''):'<div class="empty">Sin salas creadas.</div>';
 const tasks=Array.isArray(d.tasks)?d.tasks:[]; e('ntTasksList').innerHTML=tasks.length?tasks.map(x=>event((x.partner_name||'Agente')+' · '+(x.role||'rol'),x.status+' · '+(x.title||''),(x.quality_score==null?'':'Quality '+n(x.quality_score))+(x.error?' · '+x.error:''))).join(''):'<div class="empty">Sin tareas de delegación todavía.</div>';
 const ne=Array.isArray(d.negotiations)?d.negotiations:[]; e('ntNegotiatorList').innerHTML=ne.length?ne.map(x=>event(x.title,x.status+' · '+n(x.candidate_count)+' candidatos · '+n(x.priced_candidate_count)+' precios','Recomendado: '+(x.recommended_partner_name||'aún no')+' · confidence '+n(x.recommendation_confidence))).join(''):'<div class="empty">Sin casos de negociación.</div>';
 const rr=Array.isArray(d.referralRows)?d.referralRows:[]; e('ntReferralList').innerHTML=rr.length?rr.map(x=>event(x.title,(x.direction||'')+' · '+(x.status||''),((x.target_partner_name||x.origin_partner_name)?'Agente: '+(x.target_partner_name||x.origin_partner_name)+' · ':'')+'match '+n(x.match_score)+' · settled '+usd(x.settled_revenue_usd))).join(''):'<div class="empty">Sin referrals.</div>';
 const vv=Array.isArray(d.ventures)?d.ventures:[]; e('ntVentureList').innerHTML=vv.length?vv.map(x=>event(x.title,x.status+' · readiness '+n(x.readiness_score)+' · coverage '+n(x.coverage_score),'gaps '+n(x.gap_count)+' · '+(x.next_experiment||''))).join(''):'<div class="empty">Todavía no hay Venture Cases maduros.</div>';
 const gaps=Array.isArray(d.gapRows)?d.gapRows:[]; e('ntGapList').innerHTML=gaps.length?gaps.map(x=>event(x.capability,'Prioridad '+n(x.priority)+' · '+x.status,'Candidatos '+n(x.current_candidates)+' · fuertes '+n(x.strong_candidates)+' · mejor '+(x.best_partner_name||'ninguno'))).join(''):'<div class="empty">No hay gaps abiertos.</div>';
 const teams=Array.isArray(d.teams)?d.teams:[]; e('ntTeamList').innerHTML=teams.length?teams.map(x=>event(x.id,'Score '+n(x.team_score)+' · coverage '+n(x.coverage_score)+' · affinity '+n(x.graph_affinity_score),members(x.members_json))).join(''):'<div class="empty">Sin equipos dinámicos activos.</div>';
 const edges=Array.isArray(d.graphEdges)?d.graphEdges:[]; e('ntGraphList').innerHTML=edges.length?edges.map(x=>event((x.source_name||'Agente')+' + '+(x.target_name||'Agente'),x.relation_type+' · affinity '+n(x.affinity_score),'contextos '+n(x.contexts)+' · éxitos '+n(x.successes)+' · fallas '+n(x.failures))).join(''):'<div class="empty">Sin historial conjunto suficiente.</div>';
 const intents=Array.isArray(d.economyIntents)?d.economyIntents:[]; e('ntEconomyList').innerHTML=intents.length?'<table><thead><tr><th>Dirección</th><th>Servicio</th><th>Contraparte</th><th>USD</th><th>Estado</th><th>Aprobación</th><th>Settlement</th></tr></thead><tbody>'+intents.map(x=>'<tr><td>'+chip(x.direction,x.direction==='INCOME'?'ntGood':'ntWarn')+'</td><td>'+esc(x.service_name||x.kind||'—')+'</td><td>'+esc(x.counterparty_name||'—')+'</td><td>'+usd(x.amount_usd)+'</td><td>'+esc(x.status||'—')+'</td><td>'+esc(x.approval_status||'—')+'</td><td>'+esc(x.settlement_status||'—')+(n(x.settled_amount_usd)>0?' · '+usd(x.settled_amount_usd):'')+'</td></tr>').join('')+'</tbody></table>':'<div class="empty">Sin intenciones económicas registradas.</div>';
 e('ntGuardrails').innerHTML='<div><strong>Gasto autónomo</strong><div class="ntKpi">USD 0</div><div class="small">hard-blocked</div></div><div><strong>Contratos automáticos</strong><div class="ntKpi">NO</div><div class="small">human-gated</div></div><div><strong>Compras autónomas</strong><div class="ntKpi">NO</div><div class="small">human-gated</div></div><div><strong>Ingreso realizado</strong><div class="ntKpi">SETTLED</div><div class="small">sólo pago verificado</div></div><div><strong>Trust</strong><div class="ntKpi">OBLIGATORIO</div><div class="small">antes de acciones externas sensibles</div></div><div><strong>Calidad</strong><div class="ntKpi">GATES</div><div class="small">juntas, tareas, resultados y propuestas</div></div>';
 }catch(err){if(e('ntBestAction'))e('ntBestAction').textContent='No pude leer la Torre de la Red: '+err.message}}
}
load();setInterval(load,30000);
})();</script>`;

function inject(html) {
  if (html.includes('id="lumenNetworkTowerScript"')) return html;
  html = html.replace("</head>", STYLE + "</head>");
  const controlTab = /<button\b[^>]*(?:data-p|data-tab)=["']controlv2["'][^>]*>[\s\S]*?<\/button>/i;
  const experimentTab = /<button\b[^>]*(?:data-p|data-tab)=["']experiments["'][^>]*>[\s\S]*?<\/button>/i;
  const tab = '<button class="tab" data-tab="networktower">Red de Agentes</button>';
  if (controlTab.test(html)) html = html.replace(controlTab, m => m + tab);
  else if (experimentTab.test(html)) html = html.replace(experimentTab, m => m + tab);
  else html = html.replace(/(<div\b[^>]*class=["'][^"']*\btabs\b[^"']*["'][^>]*>)/i, m => m + tab);
  if (html.includes('<section class="page" id="infra">')) html = html.replace('<section class="page" id="infra">', SECTION + '<section class="page" id="infra">');
  else html = html.replace("</body>", SECTION + "</body>");
  return html.replace("</body>", SCRIPT + "</body>");
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/network-control-v1") return protectedNetworkData(request, env, ctx);
    const response = await base.fetch(request, env, ctx);
    if (request.method !== "GET" || response.status !== 200) return response;
    if (!["/", "/index.html", "/full"].includes(url.pathname)) return response;
    if (!String(response.headers.get("content-type") || "").includes("text/html")) return response;
    const html = inject(await response.text());
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("cache-control", "no-store");
    return new Response(html, { status: response.status, statusText: response.statusText, headers });
  }
};
