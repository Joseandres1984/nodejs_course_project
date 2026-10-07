const VERSION = "1.1-domain-verified-tender-match";
const MAX_TENDERS = 80;
const MAX_SUPPLIERS = 180;
const MAX_MATCHES_PER_RUN = 6;
const MIN_MATCH_SCORE = 78;

const STOPWORDS = new Set([
  "about","after","against","also","analysis","and","are","areas","buyer","client","company","contract","contracts",
  "cross","data","deadline","deliver","documents","existing","for","from","have","https","into","market","notice",
  "official","our","procurement","project","providing","public","recovery","request","required","scheme","service",
  "services","supplier","tender","that","the","their","this","through","which","will","with","you","your"
]);

// High-precision capability words only. Generic terms such as data, industrial,
// consulting, technology and equipment are deliberately excluded because they
// created false supplier/tender matches in production.
const HIGH_SIGNAL_TERMS = new Set([
  "automation","automotive","battery","cable","cables","chemical","chemicals","compressor","compressors",
  "cybersecurity","electrical","electric","electronics","fire","freight","generator","generators","hardware",
  "instrumentation","laboratory","logistics","maintenance","mechanical","motor","motors","network","piping",
  "plc","pump","pumps","safety","scada","security","sensor","sensors","software","switchgear","telecom",
  "transformer","transformers","transport","valve","valves","water","welding"
]);

const DOMAIN_BUCKETS = Object.freeze({
  AUTOMATION: ["automation","plc","scada","control","controls","sensor","sensors","instrumentation"],
  ELECTRICAL: ["electrical","electric","electronics","switchgear","transformer","transformers","cable","cables","battery","generator","generators"],
  MECHANICAL: ["mechanical","pump","pumps","valve","valves","compressor","compressors","motor","motors","piping","welding","spare","parts"],
  SOFTWARE: ["software","cybersecurity","security","network","cloud","api","database","digital"],
  LOGISTICS: ["logistics","freight","transport","shipping","warehouse","warehousing"],
  SAFETY: ["safety","fire","ppe","protection","protective"],
  LAB: ["laboratory","instrumentation","measurement","calibration","testing"],
  WATER: ["water","wastewater","sewage","drainage","pump","pumps","piping"],
  CHEMICAL: ["chemical","chemicals","reagent","reagents","solvent","solvents"],
  AUTOMOTIVE: ["automotive","vehicle","vehicles","battery","motor","motors"]
});

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(value,limit=5000){return String(value??"").trim().replace(/\s+/g," ").slice(0,limit);}
function authorized(request,env){const expected=clean(env?.OPPORTUNITY_ADMIN_TOKEN,500);const supplied=clean(request.headers.get("x-lumen-admin"),500);return Boolean(expected&&supplied&&expected===supplied);}
function isHttps(value){try{return new URL(value).protocol==="https:";}catch{return false;}}
function safeParse(value,fallback={}){try{return JSON.parse(value||"");}catch{return fallback;}}
async function sha256(text){const bytes=new TextEncoder().encode(String(text));const digest=await crypto.subtle.digest("SHA-256",bytes);return [...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,"0")).join("");}
async function safeAll(env,sql,bind=[]){try{const q=env.DB.prepare(sql);const r=bind.length?await q.bind(...bind).all():await q.all();return r.results||[];}catch{return [];}}

function tokens(value){
  return clean(value,12000).toLowerCase().split(/[^a-z0-9áéíóúñü-]+/i)
    .map(x=>x.replace(/^-+|-+$/g,""))
    .filter(x=>x.length>=4&&!STOPWORDS.has(x));
}
function unique(values){return [...new Set(values)];}
function futureDeadline(raw){
  const value=clean(raw?.deadline,120);
  if(!value) return {value:null,future:true,days:null};
  const ms=Date.parse(value);
  if(!Number.isFinite(ms)) return {value,future:true,days:null};
  const days=(ms-Date.now())/86400000;
  return {value,future:days>=0,days:Number(days.toFixed(1))};
}
function bucketSet(value){
  const text=clean(value,16000).toLowerCase();
  const found=[];
  for(const [bucket,terms] of Object.entries(DOMAIN_BUCKETS)){
    if(terms.some(term=>text.includes(term))) found.push(bucket);
  }
  return new Set(found);
}
function supplierLike(row){
  const text=clean(`${row.name||""} ${row.description||""} ${row.tags_json||""}`,12000).toLowerCase();
  const commercialRole=/(supplier|vendor|manufacturer|manufacturing|distributor|sourcing|integrator|contractor|provider|solutions|services)/i.test(text);
  const capabilityBuckets=bucketSet(text);
  return commercialRole && capabilityBuckets.size>0;
}
function matchScore(tender,supplier){
  const tenderRaw=safeParse(tender.raw_json,{});
  const deadline=futureDeadline(tenderRaw);
  if(!deadline.future) return null;

  const tenderText=`${tender.name||""} ${tender.description||""}`;
  const supplierText=`${supplier.name||""} ${supplier.description||""} ${supplier.tags_json||""}`;
  const tenderBuckets=bucketSet(tenderText);
  const supplierBuckets=bucketSet(supplierText);
  const sharedBuckets=[...tenderBuckets].filter(bucket=>supplierBuckets.has(bucket));
  if(!sharedBuckets.length) return null;

  const tt=unique(tokens(tenderText));
  const st=new Set(unique(tokens(supplierText)));
  const overlap=tt.filter(t=>st.has(t));
  const strong=overlap.filter(t=>HIGH_SIGNAL_TERMS.has(t));

  // A shared broad category is not enough. At least one exact high-signal
  // capability term must appear in both the tender and supplier profile.
  if(strong.length===0) return null;

  let score=64;
  score+=Math.min(20,strong.length*10);
  score+=Math.min(8,Math.max(0,sharedBuckets.length-1)*4);
  score+=Math.min(5,Math.max(0,Number(tender.score||0)-60)*0.2);
  score+=Math.min(4,Math.max(0,Number(supplier.score||0)-40)*0.08);
  if(deadline.days!=null&&deadline.days<=30) score+=4;
  return {
    score:Math.min(98,Math.round(score)),
    overlap:overlap.slice(0,8),
    strong:strong.slice(0,6),
    sharedBuckets:sharedBuckets.slice(0,4),
    deadline
  };
}

async function ensureSchema(env){
  if(!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_tender_supplier_matches (match_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,tender_opportunity_id TEXT NOT NULL,supplier_opportunity_id TEXT NOT NULL,match_opportunity_id TEXT NOT NULL UNIQUE,match_score INTEGER NOT NULL,matched_terms_json TEXT NOT NULL,status TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_lumen_tender_supplier_pair ON lumen_tender_supplier_matches(tender_opportunity_id,supplier_opportunity_id)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_tender_supplier_rank ON lumen_tender_supplier_matches(status,match_score DESC,updated_at DESC)")
  ]);
  return true;
}

async function runTenderSupplierMatch(env){
  if(!(await ensureSchema(env))) return {ok:false,error:"persistence_unavailable",version:VERSION};
  const tenders=await safeAll(env,`SELECT id,source,remote_id,name,endpoint,description,score,evidence,raw_json,updated_at
    FROM lumen_opportunities
    WHERE source IN ('ted_eu_public_procurement','uk_contracts_finder')
    ORDER BY updated_at DESC,score DESC LIMIT ${MAX_TENDERS}`);
  const suppliers=(await safeAll(env,`SELECT id,remote_id,name,endpoint,description,tags_json,score,raw_json,updated_at
    FROM lumen_opportunities
    WHERE source='global_a2a_registry' AND endpoint IS NOT NULL AND endpoint LIKE 'https://%'
    ORDER BY updated_at DESC,score DESC LIMIT ${MAX_SUPPLIERS}`)).filter(supplierLike);

  const candidates=[];
  for(const tender of tenders){
    for(const supplier of suppliers){
      const matched=matchScore(tender,supplier);
      if(!matched||matched.score<MIN_MATCH_SCORE) continue;
      candidates.push({tender,supplier,...matched});
    }
  }
  candidates.sort((a,b)=>b.score-a.score || Number(b.tender.score||0)-Number(a.tender.score||0) || Number(b.supplier.score||0)-Number(a.supplier.score||0));

  const usedTender=new Set(),usedSupplier=new Set();
  const selected=[];
  for(const item of candidates){
    if(selected.length>=MAX_MATCHES_PER_RUN) break;
    if(usedTender.has(item.tender.id)||usedSupplier.has(item.supplier.id)) continue;
    const prior=await env.DB.prepare("SELECT match_id,status FROM lumen_tender_supplier_matches WHERE tender_opportunity_id=? AND supplier_opportunity_id=? LIMIT 1").bind(item.tender.id,item.supplier.id).first();
    if(prior) continue;
    usedTender.add(item.tender.id);
    usedSupplier.add(item.supplier.id);
    selected.push(item);
  }

  const now=new Date().toISOString();
  const created=[];
  for(const item of selected){
    const digest=await sha256(`${item.tender.id}|${item.supplier.id}`);
    const matchId=`TM-${digest.slice(0,18).toUpperCase()}`;
    const oppId=`OPP-TM-${digest.slice(0,16).toUpperCase()}`;
    const tenderRaw=safeParse(item.tender.raw_json,{});
    const buyer=clean(tenderRaw?.buyer,240);
    const value=Number(tenderRaw?.value||0);
    const sourceLabel=item.tender.source==="ted_eu_public_procurement"?"TED EU":"UK Contracts Finder";
    const terms=item.strong;
    const deadlineText=item.deadline.value?` Bid deadline: ${item.deadline.value}.`:"";
    const buyerText=buyer?` Buyer: ${buyer}.`:"";
    const valueText=value>0?` Published value: ${value}.`:"";
    const description=clean(
      `Active public procurement tender matched to this supplier profile. Tender: ${item.tender.name}. Official source: ${sourceLabel}.${buyerText}${deadlineText}${valueText} Supplier-fit terms: ${terms.join(", ")}. This is a current tender/bid opportunity; LUMEN can deliver a Tender Hot Lead with the official notice, deadline and fit summary.`,
      2400
    );
    const raw={
      tender_supplier_match:true,
      tender:{id:item.tender.id,source:item.tender.source,remoteId:item.tender.remote_id,name:item.tender.name,evidence:item.tender.evidence,deadline:item.deadline.value,buyer,value},
      supplier:{id:item.supplier.id,remoteId:item.supplier.remote_id,name:item.supplier.name,endpoint:item.supplier.endpoint},
      match:{score:item.score,terms,sharedBuckets:item.sharedBuckets},
      engineVersion:VERSION
    };
    await env.DB.batch([
      env.DB.prepare("INSERT INTO lumen_opportunities(id,discovered_at,updated_at,source,remote_id,name,endpoint,description,tags_json,score,fit,demand_signal,revenue_offer_id,status,evidence,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,remote_id) DO UPDATE SET updated_at=excluded.updated_at,description=excluded.description,score=MAX(lumen_opportunities.score,excluded.score),demand_signal=1,revenue_offer_id=excluded.revenue_offer_id,evidence=excluded.evidence,raw_json=excluded.raw_json")
        .bind(oppId,now,now,"tender_supplier_match",matchId,item.supplier.name,item.supplier.endpoint,description,JSON.stringify(["tender-match","public-demand","first-dollar"]),item.score,item.score>=86?"A":"B",1,"MP-TENDER-LEAD","SOURCE_SIGNAL",item.tender.evidence,JSON.stringify(raw)),
      env.DB.prepare("INSERT INTO lumen_tender_supplier_matches(match_id,created_at,updated_at,tender_opportunity_id,supplier_opportunity_id,match_opportunity_id,match_score,matched_terms_json,status,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?)")
        .bind(matchId,now,now,item.tender.id,item.supplier.id,oppId,item.score,JSON.stringify(terms),"CREATED",VERSION)
    ]);
    created.push({matchId,opportunityId:oppId,tender:item.tender.name,supplier:item.supplier.name,score:item.score,terms,sharedBuckets:item.sharedBuckets,deadline:item.deadline.value,evidence:item.tender.evidence});
  }

  return {
    ok:true,
    version:VERSION,
    tendersConsidered:tenders.length,
    suppliersConsidered:suppliers.length,
    candidatePairs:candidates.length,
    created:created.length,
    matches:created,
    guardrails:{
      publicProcurementEvidenceRequired:true,
      supplierEndpointMustBeHttps:true,
      oneTenderPerSupplierPerRun:true,
      maxMatchesPerRun:MAX_MATCHES_PER_RUN,
      autonomousSpendUsd:0,
      autonomousPurchase:false,
      autonomousContract:false,
      bindingActionsHumanGated:true,
      verifiedSettlementOnly:true
    }
  };
}

async function state(env){
  await ensureSchema(env);
  const rows=await safeAll(env,"SELECT match_id,created_at,updated_at,tender_opportunity_id,supplier_opportunity_id,match_opportunity_id,match_score,matched_terms_json,status FROM lumen_tender_supplier_matches ORDER BY created_at DESC LIMIT 50");
  const total=await env.DB.prepare("SELECT COUNT(*) n FROM lumen_tender_supplier_matches").first();
  return {ok:true,version:VERSION,total:Number(total?.n||0),recent:rows.map(r=>({...r,matched_terms:safeParse(r.matched_terms_json,[])}))};
}

export async function handleTenderSupplierMatch(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/tender-match/policy") return json({
    version:VERSION,
    objective:"turn verified public procurement demand into paid tender-intelligence offers for reachable supplier agents",
    offerId:"MP-TENDER-LEAD",
    priceUsd:1,
    matchingPolicy:"shared_domain_bucket_plus_exact_high_signal_capability_term",
    maxMatchesPerRun:MAX_MATCHES_PER_RUN,
    sourceEvidence:["ted_eu_public_procurement","uk_contracts_finder"],
    autonomousSpendUsd:0,
    autonomousPurchase:false,
    autonomousContract:false,
    bindingActionsHumanGated:true,
    verifiedSettlementOnly:true
  });
  if(request.method==="GET"&&url.pathname==="/tender-match/state"){
    if(!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403);
    return json(await state(env));
  }
  if(request.method==="POST"&&url.pathname==="/tender-match/run"){
    if(!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403);
    return json(await runTenderSupplierMatch(env),202);
  }
  return null;
}

export const __test={tokens,bucketSet,supplierLike,matchScore,futureDeadline};
