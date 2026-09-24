const VERSION = "1.0-agent-graph";

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=8000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function clamp(n,min=0,max=100){return Math.max(min,Math.min(max,Number(n)||0));}
function parseArray(v){try{const x=JSON.parse(v||"[]");return Array.isArray(x)?x:[];}catch{return[];}}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_agent_graph_nodes (partner_id TEXT PRIMARY KEY,name TEXT NOT NULL,capabilities_json TEXT NOT NULL,declared_reputation INTEGER NOT NULL,compatibility INTEGER NOT NULL,observed_score INTEGER,observed_confidence INTEGER,council_passes INTEGER NOT NULL DEFAULT 0,council_rejects INTEGER NOT NULL DEFAULT 0,delegation_passes INTEGER NOT NULL DEFAULT 0,delegation_rejects INTEGER NOT NULL DEFAULT 0,reliability_score INTEGER,responsiveness_score INTEGER,updated_at TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_graph_nodes_rank ON lumen_agent_graph_nodes(observed_confidence DESC,observed_score DESC,declared_reputation DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_agent_graph_edges (id TEXT PRIMARY KEY,source_partner_id TEXT NOT NULL,target_partner_id TEXT NOT NULL,relation_type TEXT NOT NULL,contexts INTEGER NOT NULL DEFAULT 0,successes INTEGER NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,affinity_score INTEGER NOT NULL,shared_capabilities_json TEXT NOT NULL,last_context_id TEXT,updated_at TEXT NOT NULL,engine_version TEXT NOT NULL,UNIQUE(source_partner_id,target_partner_id,relation_type))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_graph_edges_affinity ON lumen_agent_graph_edges(affinity_score DESC,contexts DESC)")
  ]);
  return true;
}

async function safeAll(env,sql,bind=[]){try{const s=env.DB.prepare(sql);const r=bind.length?await s.bind(...bind).all():await s.all();return r.results||[];}catch{return[];}}

async function rebuildNodes(env){
  const partners=await safeAll(env,"SELECT p.id,p.name,p.capabilities_json,p.reputation_score,p.compatibility_score,o.score AS observed_score,o.confidence AS observed_confidence,o.reliability_score,o.responsiveness_score FROM lumen_partner_agents p LEFT JOIN lumen_partner_observed_reputation o ON o.partner_id=p.id WHERE p.status IN ('candidate','strong_candidate','watch') ORDER BY p.name ASC");
  const out=[];
  for(const p of partners){
    const cq=await safeAll(env,"SELECT status FROM lumen_council_contribution_quality WHERE partner_id=?",[p.id]);
    const dq=await safeAll(env,"SELECT q.status FROM lumen_delegation_result_quality q JOIN lumen_delegation_tasks d ON d.id=q.task_id WHERE d.partner_id=?",[p.id]);
    const councilPasses=cq.filter(x=>x.status==='PASS').length,councilRejects=cq.filter(x=>x.status==='REJECT').length;
    const delegationPasses=dq.filter(x=>x.status==='PASS').length,delegationRejects=dq.filter(x=>x.status==='REJECT').length;
    const now=new Date().toISOString();
    await env.DB.prepare("INSERT INTO lumen_agent_graph_nodes(partner_id,name,capabilities_json,declared_reputation,compatibility,observed_score,observed_confidence,council_passes,council_rejects,delegation_passes,delegation_rejects,reliability_score,responsiveness_score,updated_at,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(partner_id) DO UPDATE SET name=excluded.name,capabilities_json=excluded.capabilities_json,declared_reputation=excluded.declared_reputation,compatibility=excluded.compatibility,observed_score=excluded.observed_score,observed_confidence=excluded.observed_confidence,council_passes=excluded.council_passes,council_rejects=excluded.council_rejects,delegation_passes=excluded.delegation_passes,delegation_rejects=excluded.delegation_rejects,reliability_score=excluded.reliability_score,responsiveness_score=excluded.responsiveness_score,updated_at=excluded.updated_at,engine_version=excluded.engine_version")
      .bind(p.id,p.name,p.capabilities_json||"[]",Number(p.reputation_score||0),Number(p.compatibility_score||0),p.observed_score==null?null:Number(p.observed_score),p.observed_confidence==null?null:Number(p.observed_confidence),councilPasses,councilRejects,delegationPasses,delegationRejects,p.reliability_score==null?null:Number(p.reliability_score),p.responsiveness_score==null?null:Number(p.responsiveness_score),now,VERSION).run();
    out.push({partnerId:p.id,name:p.name,councilPasses,councilRejects,delegationPasses,delegationRejects});
  }
  return out;
}

function orderedPair(a,b){return a<b?[a,b]:[b,a];}
function sharedCaps(a,b){const aa=new Set(parseArray(a||"[]").map(x=>clean(x,80).toLowerCase()));const bb=new Set(parseArray(b||"[]").map(x=>clean(x,80).toLowerCase()));return [...aa].filter(x=>bb.has(x));}

async function qualityFor(env,roomId,partnerId){
  try{return await env.DB.prepare("SELECT score,status FROM lumen_council_contribution_quality WHERE room_id=? AND partner_id=? LIMIT 1").bind(roomId,partnerId).first();}catch{return null;}
}

async function rebuildCouncilEdges(env){
  const rooms=await safeAll(env,"SELECT id FROM lumen_council_rooms ORDER BY created_at ASC LIMIT 200");
  const aggregates=new Map();
  const capsByPartner=new Map();
  const nodes=await safeAll(env,"SELECT partner_id,capabilities_json FROM lumen_agent_graph_nodes");
  for(const n of nodes)capsByPartner.set(n.partner_id,n.capabilities_json||"[]");
  for(const room of rooms){
    const members=await safeAll(env,"SELECT partner_id,room_status FROM lumen_council_room_members WHERE room_id=? AND partner_id IS NOT NULL ORDER BY partner_id ASC",[room.id]);
    for(let i=0;i<members.length;i++)for(let j=i+1;j<members.length;j++){
      const a=members[i],b=members[j];const [s,t]=orderedPair(a.partner_id,b.partner_id);const key=`${s}|${t}|CO_COUNCIL`;
      const qa=await qualityFor(env,room.id,a.partner_id),qb=await qualityFor(env,room.id,b.partner_id);
      let success=0,failure=0;
      if(qa?.status==='PASS'&&qb?.status==='PASS')success=1;
      if(['REJECT'].includes(qa?.status)||['REJECT'].includes(qb?.status)||['FAILED','REPLACED','LOW_QUALITY_REPLACED'].includes(a.room_status)||['FAILED','REPLACED','LOW_QUALITY_REPLACED'].includes(b.room_status))failure=1;
      const cur=aggregates.get(key)||{source:s,target:t,contexts:0,successes:0,failures:0,lastContextId:null};
      cur.contexts++;cur.successes+=success;cur.failures+=failure;cur.lastContextId=room.id;aggregates.set(key,cur);
    }
  }
  const out=[];
  for(const x of aggregates.values()){
    const base=50+x.successes*18-x.failures*22+Math.min(12,x.contexts*3);
    const affinity=Math.round(clamp(base));
    const shared=sharedCaps(capsByPartner.get(x.source),capsByPartner.get(x.target));
    const id=`EDGE-${x.source}-${x.target}-COUNCIL`.slice(0,240);const now=new Date().toISOString();
    await env.DB.prepare("INSERT INTO lumen_agent_graph_edges(id,source_partner_id,target_partner_id,relation_type,contexts,successes,failures,affinity_score,shared_capabilities_json,last_context_id,updated_at,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_partner_id,target_partner_id,relation_type) DO UPDATE SET contexts=excluded.contexts,successes=excluded.successes,failures=excluded.failures,affinity_score=excluded.affinity_score,shared_capabilities_json=excluded.shared_capabilities_json,last_context_id=excluded.last_context_id,updated_at=excluded.updated_at,engine_version=excluded.engine_version")
      .bind(id,x.source,x.target,"CO_COUNCIL",x.contexts,x.successes,x.failures,affinity,JSON.stringify(shared),x.lastContextId,now,VERSION).run();
    out.push({...x,affinityScore:affinity,sharedCapabilities:shared});
  }
  return out;
}

async function rebuildDelegationEdges(env){
  const tasks=await safeAll(env,"SELECT d.partner_id,d.room_id,d.status,q.status AS quality_status FROM lumen_delegation_tasks d LEFT JOIN lumen_delegation_result_quality q ON q.task_id=d.id WHERE d.partner_id IS NOT NULL AND d.room_id IS NOT NULL");
  const byRoom=new Map();
  for(const t of tasks){if(!byRoom.has(t.room_id))byRoom.set(t.room_id,[]);byRoom.get(t.room_id).push(t);}
  const out=[];
  for(const [roomId,rows] of byRoom){
    for(let i=0;i<rows.length;i++)for(let j=i+1;j<rows.length;j++){
      const [s,t]=orderedPair(rows[i].partner_id,rows[j].partner_id);
      const success=(rows[i].quality_status==='PASS'&&rows[j].quality_status==='PASS')?1:0;
      const failure=(rows[i].quality_status==='REJECT'||rows[j].quality_status==='REJECT'||rows[i].status==='FAILED'||rows[j].status==='FAILED')?1:0;
      const affinity=Math.round(clamp(50+success*24-failure*28));
      const id=`EDGE-${s}-${t}-DELEGATION`.slice(0,240);const now=new Date().toISOString();
      await env.DB.prepare("INSERT INTO lumen_agent_graph_edges(id,source_partner_id,target_partner_id,relation_type,contexts,successes,failures,affinity_score,shared_capabilities_json,last_context_id,updated_at,engine_version) VALUES(?,?,?,?,1,?,?,?,?,?,?,?) ON CONFLICT(source_partner_id,target_partner_id,relation_type) DO UPDATE SET contexts=contexts+1,successes=successes+excluded.successes,failures=failures+excluded.failures,affinity_score=excluded.affinity_score,last_context_id=excluded.last_context_id,updated_at=excluded.updated_at,engine_version=excluded.engine_version")
        .bind(id,s,t,"CO_DELEGATION",success,failure,affinity,"[]",roomId,now,VERSION).run();
      out.push({source:s,target:t,roomId,success,failure,affinityScore:affinity});
    }
  }
  return out;
}

export async function recomputeAgentGraph(env){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const nodes=await rebuildNodes(env);
  const councilEdges=await rebuildCouncilEdges(env);
  const delegationEdges=await rebuildDelegationEdges(env);
  const positive=councilEdges.filter(x=>x.affinityScore>=70).length+delegationEdges.filter(x=>x.affinityScore>=70).length;
  const risky=councilEdges.filter(x=>x.affinityScore<40).length+delegationEdges.filter(x=>x.affinityScore<40).length;
  return{ok:true,version:VERSION,nodes:nodes.length,edges:councilEdges.length+delegationEdges.length,positiveCombinations:positive,riskyCombinations:risky,guardrails:{graphIsObservational:true,noAutonomousContract:true,noAutonomousSpend:true}};
}

async function stats(env){
  await ensureSchema(env);
  const n=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN observed_confidence>=30 THEN 1 ELSE 0 END) confident FROM lumen_agent_graph_nodes").first();
  const e=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN affinity_score>=70 THEN 1 ELSE 0 END) positive,SUM(CASE WHEN affinity_score<40 THEN 1 ELSE 0 END) risky,COALESCE(MAX(affinity_score),0) best FROM lumen_agent_graph_edges").first();
  return json({version:VERSION,nodes:Number(n?.total||0),confidentNodes:Number(n?.confident||0),edges:Number(e?.total||0),positiveCombinations:Number(e?.positive||0),riskyCombinations:Number(e?.risky||0),bestAffinity:Number(e?.best||0),observationalOnly:true,autonomousSpend:false});
}

export async function handleAgentGraph(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/agent-graph/stats")return stats(env);
  if(request.method==="POST"&&url.pathname==="/agent-graph/recompute"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    return json(await recomputeAgentGraph(env),202);
  }
  if(request.method==="GET"&&url.pathname==="/agent-graph"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    await ensureSchema(env);
    const nodes=await env.DB.prepare("SELECT * FROM lumen_agent_graph_nodes ORDER BY observed_confidence DESC,observed_score DESC,declared_reputation DESC LIMIT 150").all();
    const edges=await env.DB.prepare("SELECT * FROM lumen_agent_graph_edges ORDER BY affinity_score DESC,contexts DESC LIMIT 300").all();
    return json({version:VERSION,nodes:nodes.results||[],edges:(edges.results||[]).map(x=>({...x,sharedCapabilities:parseArray(x.shared_capabilities_json)}))});
  }
  return null;
}
