import { submitPartnerIdea } from "./partner-venture-board.js";

const VERSION = "1.0-venture-suggestion-intake";

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=8000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function sentences(text){return String(text||"").split(/(?<=[.!?])\s+/).map(x=>clean(x,900)).filter(Boolean);}

const EXPLICIT_IDEA=/(business idea|business opportunity|market opportunity|venture idea|new service|new product|could sell|could offer|monetiz|revenue opportunity|buyer need|customer need|commercial opportunity)/i;
const CUSTOMER=/(buyer|customer|client|prospect|demand|need|rfq|procurement|market)/i;
const REVENUE=/(revenue|fee|commission|subscription|paid|price|pricing|charge|sell|sale|margin)/i;
const EVIDENCE=/(evidence|observed|verified|source|signal|request|inquiry|registry|data shows|demand signal)/i;

const CAP_RULES=[
  ["sourcing",/(sourcing|supplier|vendor|procurement|purchasing)/i],
  ["verification",/(verify|verification|evidence|trust|certification|due diligence)/i],
  ["pricing",/(price|pricing|quote|cost|benchmark)/i],
  ["research",/(research|analysis|intelligence|data|investigation)/i],
  ["logistics",/(logistics|shipping|freight|delivery|transport)/i],
  ["export",/(export|import|trade|customs|distributor)/i],
  ["sales",/(sales|buyer|prospect|lead|demand)/i],
  ["tender",/(tender|rfq|bid)/i],
  ["payments",/(payment|checkout|settlement|invoice|x402)/i],
  ["automation",/(automation|workflow|orchestration|agent)/i]
];

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_venture_suggestion_intake (id TEXT PRIMARY KEY,room_id TEXT NOT NULL,partner_id TEXT NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL,explicit_signal INTEGER NOT NULL,idea_id TEXT,excerpt TEXT,reason TEXT,engine_version TEXT NOT NULL,UNIQUE(room_id,partner_id))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_venture_intake_status ON lumen_venture_suggestion_intake(status,created_at)")
  ]);
  return true;
}

function capabilities(text,role){
  const out=[];
  const combined=`${role||""} ${text||""}`;
  for(const [cap,re] of CAP_RULES)if(re.test(combined))out.push(cap);
  if(role&&!out.includes(clean(role,80).toLowerCase()))out.unshift(clean(role,80).toLowerCase());
  return [...new Set(out)].filter(Boolean).slice(0,8);
}

function extractSuggestion(text){
  const ss=sentences(text);
  const explicit=ss.filter(s=>EXPLICIT_IDEA.test(s));
  if(!explicit.length&&!EXPLICIT_IDEA.test(text))return null;
  const relevant=ss.filter(s=>EXPLICIT_IDEA.test(s)||CUSTOMER.test(s)||REVENUE.test(s)||EVIDENCE.test(s)).slice(0,8);
  const summary=clean((relevant.length?relevant:explicit).join(" "),3000);
  const customer=clean(ss.filter(s=>CUSTOMER.test(s)).slice(0,3).join(" "),1400);
  const revenue=clean(ss.filter(s=>REVENUE.test(s)).slice(0,3).join(" "),1400);
  const evidence=clean(ss.filter(s=>EVIDENCE.test(s)).slice(0,3).join(" "),1800);
  const titleSource=explicit[0]||relevant[0]||"Partner business opportunity";
  const title=clean(titleSource.replace(/^[-*\d.)\s]+/,""),180);
  return{title,summary,customer,revenue,evidence};
}

export async function ingestCouncilVentureSuggestions(env){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  let rows=[];
  try{
    const r=await env.DB.prepare("SELECT m.room_id,m.partner_id,m.name,m.role,m.contribution_text,r.council_id,r.opportunity_id FROM lumen_council_room_members m JOIN lumen_council_rooms r ON r.id=m.room_id LEFT JOIN lumen_venture_suggestion_intake i ON i.room_id=m.room_id AND i.partner_id=m.partner_id WHERE m.contribution_text IS NOT NULL AND TRIM(m.contribution_text)<>'' AND i.id IS NULL ORDER BY m.last_response_at ASC LIMIT 30").all();
    rows=r.results||[];
  }catch{return{ok:false,error:"council_runtime_not_ready",version:VERSION};}
  const results=[];
  for(const row of rows){
    const now=new Date().toISOString();
    const iid=`VINT-${row.room_id}-${row.partner_id}`.slice(0,220);
    const suggestion=extractSuggestion(row.contribution_text);
    if(!suggestion){
      await env.DB.prepare("INSERT OR IGNORE INTO lumen_venture_suggestion_intake(id,room_id,partner_id,created_at,status,explicit_signal,idea_id,excerpt,reason,engine_version) VALUES(?,?,?,?, 'NO_EXPLICIT_IDEA',0,NULL,?,?,?)")
        .bind(iid,row.room_id,row.partner_id,now,clean(row.contribution_text,1200),"no_explicit_business_opportunity_language",VERSION).run();
      results.push({partnerId:row.partner_id,name:row.name,ingested:false,reason:"no_explicit_idea"});
      continue;
    }
    const caps=capabilities(suggestion.summary,row.role);
    const submitted=await submitPartnerIdea(env,{
      partnerId:row.partner_id,
      councilId:row.council_id,
      opportunityId:row.opportunity_id,
      title:suggestion.title||`${row.name} venture suggestion`,
      summary:suggestion.summary,
      customerSignal:suggestion.customer,
      revenueModel:suggestion.revenue,
      evidence:suggestion.evidence||`Explicit business suggestion in council contribution from ${row.name}.`,
      requiredCapabilities:caps,
      estimatedRevenueUsd:0,
      estimatedCostUsd:0,
      source:"council_explicit_partner_suggestion"
    });
    const status=submitted?.ok?"INGESTED":"INGEST_FAILED";
    await env.DB.prepare("INSERT OR REPLACE INTO lumen_venture_suggestion_intake(id,room_id,partner_id,created_at,status,explicit_signal,idea_id,excerpt,reason,engine_version) VALUES(?,?,?,?,?,1,?,?,?,?)")
      .bind(iid,row.room_id,row.partner_id,now,status,submitted?.ideaId||null,clean(suggestion.summary,1600),submitted?.ok?"explicit_partner_idea_grounded_in_contribution":clean(submitted?.error||"submit_failed",500),VERSION).run();
    results.push({partnerId:row.partner_id,name:row.name,ingested:Boolean(submitted?.ok),ideaId:submitted?.ideaId||null,ideaStatus:submitted?.status||null,totalScore:submitted?.totalScore??null});
  }
  return{ok:true,version:VERSION,reviewed:rows.length,ingested:results.filter(x=>x.ingested).length,results,policy:{explicitPartnerLanguageRequired:true,inventMissingCustomer:false,inventMissingRevenue:false,autonomousSpend:false}};
}

async function stats(env){
  await ensureSchema(env);
  const r=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='INGESTED' THEN 1 ELSE 0 END) ingested,SUM(CASE WHEN status='NO_EXPLICIT_IDEA' THEN 1 ELSE 0 END) no_explicit,SUM(CASE WHEN status='INGEST_FAILED' THEN 1 ELSE 0 END) failed FROM lumen_venture_suggestion_intake").first();
  return json({version:VERSION,totalReviewed:Number(r?.total||0),ingested:Number(r?.ingested||0),noExplicitIdea:Number(r?.no_explicit||0),failed:Number(r?.failed||0),explicitPartnerLanguageRequired:true,autonomousSpend:false,bindingActionsHumanGated:true});
}

export async function handleVentureSuggestionIntake(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/venture-intake/stats")return stats(env);
  if(request.method==="POST"&&url.pathname==="/venture-intake/run"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    return json(await ingestCouncilVentureSuggestions(env),202);
  }
  return null;
}
