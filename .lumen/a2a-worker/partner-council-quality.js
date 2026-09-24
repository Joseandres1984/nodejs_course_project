const VERSION = "1.3-partner-council-quality";

const OFFER_NEEDS = {
  "MP-SUPPLIER-SNAPSHOT": ["verification", "sourcing", "research"],
  "MP-QUOTE-SANITY": ["pricing", "research", "verification"],
  "MP-TENDER-SCAN": ["tender", "research"],
  "MP-SOURCING-5": ["sourcing", "verification", "pricing"],
  "MP-BUYER-SIGNALS": ["sales", "research"],
  "MP-EXPORT-PULSE": ["export", "logistics", "research"]
};

const NEED_WORDS = {
  verification: ["verify","verification","evidence","trust","reputation","due diligence","assurance","certification"],
  sourcing: ["sourcing","supplier","vendor","procurement","purchasing","broker"],
  research: ["research","intelligence","analysis","investigation","discovery","data"],
  pricing: ["price","pricing","quote","quotation","cost","benchmark","market"],
  tender: ["tender","bid","rfq","procurement"],
  sales: ["sales","buyer","prospect","lead","demand","intent"],
  export: ["export","import","trade","distributor","customs"],
  logistics: ["logistics","shipping","freight","delivery","transport","warehouse"]
};

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=4000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function parseArray(v){try{const x=JSON.parse(v||"[]");return Array.isArray(x)?x:[];}catch{return[];}}
function authorized(request,env){const a=clean(env?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(request.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
async function bodyJson(request){try{return await request.json();}catch{return{};}}

async function resolveOpportunity(env,id=""){
  if(id)return env.DB.prepare("SELECT o.*,a.commercial_score,a.commercial_fit,a.evidence_strength,a.commercially_actionable,a.synthetic_or_test_only FROM lumen_opportunities o LEFT JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id WHERE o.id=? LIMIT 1").bind(id).first();
  return env.DB.prepare("SELECT o.*,a.commercial_score,a.commercial_fit,a.evidence_strength,a.commercially_actionable,a.synthetic_or_test_only FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id WHERE a.commercially_actionable=1 AND a.synthetic_or_test_only=0 ORDER BY a.commercial_score DESC,o.updated_at DESC LIMIT 1").first();
}

function inferNeeds(opp){
  const exact=OFFER_NEEDS[clean(opp?.revenue_offer_id,100)];
  if(exact?.length)return [...exact];
  const text=clean(`${opp?.name||""} ${opp?.description||""}`,8000).toLowerCase();
  const inferred=[];
  for(const [need,words] of Object.entries(NEED_WORDS))if(words.some(w=>text.includes(w)))inferred.push(need);
  return inferred.length?inferred.slice(0,4):["research"];
}

function specialtyScore(partner,needs){
  const text=clean(`${partner.name||""} ${partner.description||""}`,8000).toLowerCase();
  let hits=0;
  for(const need of needs){const words=NEED_WORDS[need]||[need];if(words.some(w=>text.includes(w)))hits++;}
  return needs.length?hits/needs.length:0;
}

function irrelevantPenalty(partner,needs){
  const text=clean(`${partner.name||""} ${partner.description||""}`,5000).toLowerCase();
  const verticals=[
    ["travel",["travel","trip","fare","hotel","tourism","flight"]],
    ["crypto",["crypto","trading","token","market signal","quant"]],
    ["real_estate",["real estate","property","realtor"]]
  ];
  const broadBusiness=needs.some(n=>["sourcing","verification","pricing","tender","sales","export","logistics"].includes(n));
  if(!broadBusiness)return 0;
  for(const [,words] of verticals)if(words.some(w=>text.includes(w)))return 18;
  return 0;
}

function blendedReputation(partner){
  const declared=Number(partner.reputation_score||0);
  const observed=Number(partner.observed_reputation_score||0);
  const confidence=Number(partner.observed_reputation_confidence||0);
  if(confidence<30||!Number.isFinite(observed))return{declared,observed:null,confidence,weight:0,blended:declared};
  const weight=Math.min(.45,Math.max(0,confidence/100*.45));
  const blended=declared*(1-weight)+observed*weight;
  return{declared,observed,confidence,weight,blended};
}

async function partnerRows(env){
  try{
    return await env.DB.prepare("SELECT p.id,p.name,p.endpoint,p.description,p.protocol_version,p.capabilities_json,p.reputation_score,p.compatibility_score,p.status,o.score AS observed_reputation_score,o.confidence AS observed_reputation_confidence FROM lumen_partner_agents p LEFT JOIN lumen_partner_observed_reputation o ON o.partner_id=p.id WHERE p.status IN ('candidate','strong_candidate') ORDER BY p.reputation_score DESC,p.compatibility_score DESC LIMIT 150").all();
  }catch{
    return env.DB.prepare("SELECT id,name,endpoint,description,protocol_version,capabilities_json,reputation_score,compatibility_score,status,NULL AS observed_reputation_score,0 AS observed_reputation_confidence FROM lumen_partner_agents WHERE status IN ('candidate','strong_candidate') ORDER BY reputation_score DESC,compatibility_score DESC LIMIT 150").all();
  }
}

export async function buildQualityPartnerMatches(env,opportunityId=""){
  const opp=await resolveOpportunity(env,opportunityId);
  if(!opp)return{ok:false,error:"opportunity_not_found",version:VERSION};
  const needs=inferNeeds(opp);
  let result;
  try{result=await partnerRows(env);}
  catch{return{ok:false,error:"partner_registry_not_ready",version:VERSION,opportunity:{id:opp.id,name:opp.name},needs};}
  const matches=[];
  for(const partner of result.results||[]){
    const caps=parseArray(partner.capabilities_json);
    const matched=caps.filter(c=>needs.includes(c));
    if(!matched.length)continue;
    const coverage=matched.length/Math.max(1,needs.length);
    const specialty=specialtyScore(partner,needs);
    const penalty=irrelevantPenalty(partner,needs);
    const rep=blendedReputation(partner);
    const score=Math.max(0,Math.min(100,Math.round(rep.blended*.42+Number(partner.compatibility_score||0)*.23+coverage*25+specialty*10-penalty)));
    if(score<55)continue;
    matches.push({partnerId:partner.id,name:partner.name,endpoint:partner.endpoint,protocolVersion:partner.protocol_version,reputation:rep.declared,observedReputation:rep.observed,observedConfidence:rep.confidence,reputationBlendWeight:Math.round(rep.weight*100),blendedReputation:Math.round(rep.blended),compatibility:Number(partner.compatibility_score||0),matchScore:score,matchedCapabilities:matched,specialty:Math.round(specialty*100),penalty});
  }
  matches.sort((a,b)=>b.matchScore-a.matchScore||b.specialty-a.specialty||b.blendedReputation-a.blendedReputation);
  const now=new Date().toISOString();
  for(const m of matches.slice(0,40)){
    const id=`PQM-${opp.id}-${m.partnerId}`.slice(0,180);
    await env.DB.prepare("INSERT INTO lumen_partner_matches(id,opportunity_id,partner_id,match_score,matched_capabilities_json,reason,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(opportunity_id,partner_id) DO UPDATE SET match_score=excluded.match_score,matched_capabilities_json=excluded.matched_capabilities_json,reason=excluded.reason,status=excluded.status,updated_at=excluded.updated_at")
      .bind(id,opp.id,m.partnerId,m.matchScore,JSON.stringify(m.matchedCapabilities),`quality_v1_3; specialty=${m.specialty}; penalty=${m.penalty}; declared_rep=${m.reputation}; observed_rep=${m.observedReputation??'n/a'}; observed_conf=${m.observedConfidence}; rep_blend_weight=${m.reputationBlendWeight}`,"quality_candidate",now,now).run();
  }
  return{ok:true,version:VERSION,opportunity:{id:opp.id,name:opp.name,offerId:opp.revenue_offer_id,commercialScore:Number(opp.commercial_score||0)},needs,observedReputationPolicy:{minimumConfidence:30,maxBlendWeightPercent:45},matches:matches.slice(0,20)};
}

export async function assembleQualityCouncil(env,opportunityId=""){
  const matched=await buildQualityPartnerMatches(env,opportunityId);
  if(!matched.ok)return matched;
  const selected=[];
  const used=new Set();
  for(const role of matched.needs){
    const candidate=matched.matches.find(m=>!used.has(m.partnerId)&&m.matchedCapabilities.includes(role));
    if(!candidate)continue;
    selected.push({...candidate,role});used.add(candidate.partnerId);
    if(selected.length>=3)break;
  }
  if(selected.length<2){
    for(const candidate of matched.matches){if(used.has(candidate.partnerId))continue;selected.push({...candidate,role:candidate.matchedCapabilities[0]||"specialist"});used.add(candidate.partnerId);if(selected.length>=3)break;}
  }
  if(!selected.length)return{ok:false,error:"no_quality_partners",version:VERSION,opportunity:matched.opportunity,needs:matched.needs};
  const now=new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_partner_councils SET status='SUPERSEDED',updated_at=? WHERE opportunity_id=? AND status='DRAFT_COUNCIL'").bind(now,matched.opportunity.id).run();
  const id=`COUNCIL-${crypto.randomUUID().replaceAll("-","").slice(0,12).toUpperCase()}`;
  const members=[{id:"LUMEN",name:"LUMEN",role:"coordinator",authority:"non_binding_coordination"},...selected.map(x=>({id:x.partnerId,name:x.name,role:x.role,matchScore:x.matchScore,specialty:x.specialty,protocolVersion:x.protocolVersion,endpoint:x.endpoint,observedReputation:x.observedReputation,observedConfidence:x.observedConfidence}))];
  const plan=[
    {step:1,owner:"LUMEN",action:"present_problem_scope_and_nonbinding_rules"},
    ...selected.map((x,i)=>({step:i+2,owner:x.partnerId,action:`contribute_${x.role}_analysis`})),
    {step:selected.length+2,owner:"all_partners",action:"opportunity_round_propose_business_ideas_market_signals_and_agent_combinations"},
    {step:selected.length+3,owner:"LUMEN",action:"score_partner_ideas_evidence_revenue_feasibility_and_network_synergy"},
    {step:selected.length+4,owner:"LUMEN",action:"compare_contributions_detect_disagreement_and_synthesize_plan"},
    {step:selected.length+5,owner:"human_gate",action:"approve_any_hiring_spend_contract_or_binding_commitment"}
  ];
  const goal=`Council for ${matched.opportunity.name}: combine ${selected.map(x=>x.role).join(", ")} expertise under LUMEN coordination and surface new business opportunities`;
  await env.DB.prepare("INSERT INTO lumen_partner_councils(id,opportunity_id,created_at,updated_at,status,goal,members_json,plan_json,binding_allowed,spend_allowed) VALUES(?,?,?,?,?,?,?,?,0,0)").bind(id,matched.opportunity.id,now,now,"DRAFT_COUNCIL",goal,JSON.stringify(members),JSON.stringify(plan)).run();
  return{ok:true,version:VERSION,councilId:id,status:"DRAFT_COUNCIL",opportunity:matched.opportunity,needs:matched.needs,members,plan,opportunityRound:{enabled:true,maxIdeasPerPartner:2,evidenceRequiredForHighConfidence:true},guardrails:{externalInvitesSent:false,bindingAllowed:false,spendAllowed:false,humanApprovalRequiredForHiring:true}};
}

export async function handlePartnerCouncilQuality(request,env){
  const url=new URL(request.url);
  if(request.method==="POST"&&url.pathname==="/partners/match"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    const body=await bodyJson(request);return json(await buildQualityPartnerMatches(env,clean(body?.opportunityId,100)),202);
  }
  if(request.method==="POST"&&url.pathname==="/partners/council"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    const body=await bodyJson(request);return json(await assembleQualityCouncil(env,clean(body?.opportunityId,100)),202);
  }
  return null;
}
