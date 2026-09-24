const VERSION="1.1-partner-marketplace-catalog";
const LUMEN_OFFERS=[
  {id:"verification",name:"Evidence & Supplier Verification"},
  {id:"sourcing",name:"B2B Sourcing"},
  {id:"research",name:"Commercial Research"},
  {id:"pricing",name:"Quote & Price Reasonableness"},
  {id:"tender",name:"Tender / RFQ Analysis"},
  {id:"sales",name:"Buyer Signal Analysis"},
  {id:"export",name:"Export Opportunity Research"},
  {id:"automation",name:"Agentic Workflow Orchestration"}
];
function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=200){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}

async function aggregatedNeeds(env){
  let rows=[];
  try{const r=await env.DB.prepare("SELECT id,capability,priority,source_type,source_id,updated_at FROM lumen_partner_marketplace_needs WHERE status='OPEN' ORDER BY priority DESC,updated_at DESC LIMIT 200").all();rows=r.results||[];}catch{return[];}
  const groups=new Map();
  for(const row of rows){
    const cap=clean(row.capability,80).toLowerCase();if(!cap)continue;
    const g=groups.get(cap)||{capability:cap,representativeNeedId:row.id,priority:Number(row.priority||0),demandCount:0,sourceTypes:new Set(),sampleSourceIds:[],updatedAt:row.updated_at};
    g.demandCount++;
    g.sourceTypes.add(row.source_type);
    if(g.sampleSourceIds.length<5)g.sampleSourceIds.push(row.source_id);
    if(Number(row.priority||0)>g.priority){g.priority=Number(row.priority||0);g.representativeNeedId=row.id;g.updatedAt=row.updated_at;}
    groups.set(cap,g);
  }
  return [...groups.values()].map(g=>({
    needId:g.representativeNeedId,
    capability:g.capability,
    priority:g.priority,
    demandCount:g.demandCount,
    sourceTypes:[...g.sourceTypes],
    sampleSourceIds:g.sampleSourceIds,
    title:`Partner needed: ${g.capability}`,
    description:`LUMEN has ${g.demandCount} active internal need${g.demandCount===1?"":"s"} involving '${g.capability}'. Highest current priority: ${g.priority}/100. This is a non-binding partner-discovery listing; it creates no payment promise, contract, employment, exclusivity or delegation authority.`,
    updatedAt:g.updatedAt
  })).sort((a,b)=>b.priority-a.priority||b.demandCount-a.demandCount||a.capability.localeCompare(b.capability));
}

export async function handlePartnerMarketplacePublicCatalog(request,env){
  const u=new URL(request.url);
  if(request.method!=="GET"||u.pathname!=="/partner-marketplace/catalog")return null;
  const needs=await aggregatedNeeds(env);
  return json({
    version:VERSION,
    marketplace:"LUMEN Partner Marketplace",
    mode:"non_binding_discovery",
    lumenOffers:LUMEN_OFFERS,
    openPartnerNeeds:needs,
    granularNeedCount:needs.reduce((n,x)=>n+Number(x.demandCount||0),0),
    publicListingCount:needs.length,
    interestEndpoint:"/partner-marketplace/interest",
    rules:["public_https_agent_card_required","all_interest_is_non_binding","trust_review_required","no_payment_or_contract_created","no_secret_or_credential_submission"],
    autonomousSpend:false,
    bindingActionsHumanGated:true
  });
}
