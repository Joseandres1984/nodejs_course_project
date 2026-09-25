const VERSION = "0.1-business-factory";

const BLUEPRINTS = [
  { id:"BF-SOURCING", name:"Procurement Hunter", offer:"MP-SOURCING-5", words:["sourcing","supplier","vendor","procurement","purchase"], basePrice:19 },
  { id:"BF-RFQ", name:"RFQ Autopilot", offer:"MP-QUOTE-SANITY", words:["rfq","quote","quotation","pricing","proposal"], basePrice:15 },
  { id:"BF-TENDER", name:"Tender Hunter", offer:"MP-TENDER-SCAN", words:["tender","bid","public procurement"], basePrice:12 },
  { id:"BF-BUYER", name:"Buyer Signal Pack", offer:"MP-BUYER-SIGNALS", words:["buyer","lead","prospect","demand","intent"], basePrice:9 },
  { id:"BF-EXPORT", name:"Export Matchmaker", offer:"MP-EXPORT-PULSE", words:["export","import","importer","distributor"], basePrice:25 },
  { id:"BF-VERIFY", name:"Supplier Snapshot", offer:"MP-SUPPLIER-SNAPSHOT", words:["verification","verify","due diligence","trust"], basePrice:10 }
];

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","access-control-allow-origin":"*"}})}
function clean(v,n=3000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n)}

async function ensureSchema(env){
  if(!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_business_experiments (id TEXT PRIMARY KEY, blueprint_id TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL, evidence_count INTEGER NOT NULL DEFAULT 0, avg_opportunity_score REAL NOT NULL DEFAULT 0, suggested_price_usd REAL NOT NULL DEFAULT 0, economic_score REAL NOT NULL DEFAULT 0, offer_id TEXT, rationale TEXT, autonomous_spend INTEGER NOT NULL DEFAULT 0)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_business_experiments_rank ON lumen_business_experiments(status,economic_score,updated_at)")
  ]);
  return true;
}

function matches(text,b){return b.words.some(w=>text.includes(w))}

export async function runBusinessFactory(env){
  if(!(await ensureSchema(env))) return {ok:false,error:"persistence_unavailable"};
  const rows=(await env.DB.prepare("SELECT id,name,description,tags_json,score,revenue_offer_id,status FROM lumen_opportunities WHERE score>=45 AND status IN ('new','watching','qualified') ORDER BY score DESC,updated_at DESC LIMIT 120").all()).results||[];
  const now=new Date().toISOString();
  const experiments=[];
  for(const b of BLUEPRINTS){
    const relevant=rows.filter(r=>matches(clean([r.name,r.description,r.tags_json,r.revenue_offer_id].join(' '),9000).toLowerCase(),b));
    if(!relevant.length) continue;
    const avg=relevant.reduce((n,r)=>n+Number(r.score||0),0)/relevant.length;
    const demand=Math.min(100,relevant.length*12);
    const economic=Math.round((avg*0.65+demand*0.35)*100)/100;
    const price=Math.round((b.basePrice*(1+Math.min(0.75,relevant.length*0.05)))*100)/100;
    const id=`${b.id}-V1`;
    const rationale=`Observed ${relevant.length} qualified opportunity signals; average opportunity score ${avg.toFixed(1)}. Candidate microservice generated for validation only.`;
    await env.DB.prepare("INSERT INTO lumen_business_experiments(id,blueprint_id,name,created_at,updated_at,status,evidence_count,avg_opportunity_score,suggested_price_usd,economic_score,offer_id,rationale,autonomous_spend) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,evidence_count=excluded.evidence_count,avg_opportunity_score=excluded.avg_opportunity_score,suggested_price_usd=excluded.suggested_price_usd,economic_score=excluded.economic_score,rationale=excluded.rationale")
      .bind(id,b.id,b.name,now,now,economic>=65?"candidate":"observing",relevant.length,avg,price,economic,b.offer,rationale).run();
    experiments.push({id,name:b.name,evidenceCount:relevant.length,avgOpportunityScore:Number(avg.toFixed(1)),suggestedPriceUsd:price,economicScore:economic,status:economic>=65?"candidate":"observing"});
  }
  experiments.sort((a,b)=>b.economicScore-a.economicScore);
  return {ok:true,version:VERSION,generated:experiments.length,experiments,guardrails:{autonomousSpend:false,autonomousPurchase:false,autonomousContract:false,publishWithoutValidation:false}};
}

export async function handleBusinessFactory(request,env){
  const url=new URL(request.url);
  if(url.pathname==="/business-factory/run" && request.method==="POST") return json(await runBusinessFactory(env));
  if(url.pathname==="/business-factory" && request.method==="GET"){
    if(!(await ensureSchema(env))) return json({ok:false,error:"persistence_unavailable"},503);
    const rows=(await env.DB.prepare("SELECT * FROM lumen_business_experiments ORDER BY economic_score DESC,updated_at DESC LIMIT 50").all()).results||[];
    return json({ok:true,version:VERSION,experiments:rows,guardrails:{autonomousSpend:false,publishWithoutValidation:false}});
  }
  return null;
}
