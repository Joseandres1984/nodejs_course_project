const VERSION = "1.0-tender-supplier-match-first-dollar";
const MAX_TENDERS = 80;
const MAX_SUPPLIERS = 180;
const MAX_MATCHES_PER_RUN = 6;
const MIN_MATCH_SCORE = 72;

const STOPWORDS = new Set([
  "about","after","against","also","and","are","buyer","contract","contracts","deadline","from","have","into",
  "notice","procurement","public","request","service","services","supplier","tender","that","the","their","this",
  "with","your","for","our","you","company","business","market","project","published","official"
]);

const SIGNAL_TERMS = new Set([
  "automation","automotive","cable","cables","chemical","chemicals","compressor","compressors","consulting",
  "control","controls","data","digital","electrical","electric","electronics","energy","engineering","equipment",
  "fire","freight","generator","generators","hardware","industrial","instrumentation","laboratory","logistics",
  "maintenance","manufacturing","mechanical","motor","motors","network","piping","plant","plc","pump","pumps",
  "safety","scada","security","sensor","sensors","software","switchgear","technology","telecom","transformer",
  "transformers","transport","valve","valves","water","welding"
]);

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
function supplierLike(row){
  const text=clean(`${row.name||""} ${row.description||""} ${row.tags_json||""}`,12000).toLowerCase();
  return /(supplier|vendor|manufacturer|manufacturing|distributor|sourcing|industrial|engineering|automation|equipment|logistics|freight|software|technology|consulting|data)/i.test(text);
}
function matchScore(tender,supplier){
  const tenderRaw=safeParse(tender.raw_json,{});
  const deadline=futureDeadline(tenderRaw);
  if(!deadline.future) return null;
  const tt=unique(tokens(`${tender.name||""} ${tender.description||""}`));
  const st=new Set(unique(tokens(`${supplier.name||""} ${supplier.description||""} ${supplier.tags_json||""}`)));
  const overlap=tt.filter(t=>st.has(t));
  const strong=overlap.filter(t=>SIGNAL_TERMS.has(t));
  if(strong.length===0 && overlap.length<2) return null;
  let score=52;
  score+=Math.min(24,strong.length*8);
  score+=Math.min(12,Math.max(0,overlap.length-strong.length)*3);
  score+=Math.min(8,Math.max(0,Number(tender.score||0)-60)*0.25);
  score+=Math.min(6,Math.max(0,Number(supplier.score||0)-40)*0.12);
  if(deadline.days!=null&&deadline.days<=30) score+=5;
  return {score:Math.min(98,Math.round(score)),overlap:overlap.slice(0,8),strong:strong.slice(0,6),deadline};
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
    const terms=item.strong.length?item.strong:item.overlap;
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
      match:{score:item.score,terms},
      engineVersion:VERSION
    };
    await env.DB.batch([
      env.DB.prepare("INSERT INTO lumen_opportunities(id,discovered_at,updated_at,source,remote_id,name,endpoint,description,tags_json,score,fit,demand_signal,revenue_offer_id,status,evidence,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,remote_id) DO UPDATE SET updated_at=excluded.updated_at,description=excluded.description,score=MAX(lumen_opportunities.score,excluded.score),demand_signal=1,revenue_offer_id=excluded.revenue_offer_id,evidence=excluded.evidence,raw_json=excluded.raw_json")
        .bind(oppId,now,now,"tender_supplier_match",matchId,item.supplier.name,item.supplier.endpoint,description,JSON.stringify(["tender-match","public-demand","first-dollar"]),item.score,item.score>=86?"A":"B",1,"MP-TENDER-LEAD","SOURCE_SIGNAL",item.tender.evidence,JSON.stringify(raw)),
      env.DB.prepare("INSERT INTO lumen_tender_supplier_matches(match_id,created_at,updated_at,tender_opportunity_id,supplier_opportunity_id,match_opportunity_id,match_score,matched_terms_json,status,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?)")
        .bind(matchId,now,now,item.tender.id,item.supplier.id,oppId,item.score,JSON.stringify(terms),"CREATED",VERSION)
    ]);
    created.push({matchId,opportunityId:oppId,tender:item.tender.name,supplier:item.supplier.name,score:item.score,terms,deadline:item.deadline.value,evidence:item.tender.evidence});
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

export const __test={tokens,supplierLike,matchScore,futureDeadline};
