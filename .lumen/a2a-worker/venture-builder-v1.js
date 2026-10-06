const NOW=()=>new Date().toISOString();
function safeJson(v,f={}){try{return JSON.parse(v||"");}catch{return f;}}
function slug(v){return String(v||"venture").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"").slice(0,60)||"venture";}
async function schema(db){await db.prepare(`CREATE TABLE IF NOT EXISTS lumen_venture_builds_v1(idea_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,product_key TEXT NOT NULL,artifact_json TEXT NOT NULL,checkout_json TEXT NOT NULL,sales_json TEXT NOT NULL,policy_json TEXT NOT NULL)`).run();}
export async function runVentureBuilderV1(env,{limit=5}={}){
 if(!env?.DB) throw new Error("venture_builder_persistence_required"); await schema(env.DB);
 let rows=[]; try{rows=(await env.DB.prepare(`SELECT f.*,h.title,h.product,h.build_plan,h.revenue_model,h.source_kind,h.source_ref,h.evidence_json FROM lumen_venture_founder_v2 f JOIN lumen_venture_hunter_ideas h ON h.id=f.idea_id WHERE f.verdict='MVP_READY' ORDER BY f.opportunity_score DESC,f.updated_at DESC LIMIT ?`).bind(limit).all()).results||[];}catch{}
 const policy={mode:"PREPARE_ONLY",autonomousBuildPreparation:true,autonomousExternalPublish:false,autonomousOutbound:false,autonomousSpendUsd:0,autonomousContract:false,priceMutation:false,bindingActionsHumanGated:true};
 const builds=[];
 for(const r of rows){const mvp=safeJson(r.mvp_plan_json,{}), revenueModel=String(r.revenue_model||mvp.revenueModel||"existing_approved_or_human_gated"), key=`venture-${slug(r.title)}-${String(r.idea_id).slice(-8)}`;
  const artifact={productKey:key,title:r.title,product:r.product,revenueModel,scope:mvp.scope||"smallest paid deliverable proving demand",buildPlan:r.build_plan,delivery:mvp.delivery||"guarded LUMEN delivery",source:{kind:r.source_kind,ref:r.source_ref},state:"PREPARED_NOT_PUBLISHED"};
  const checkout={mode:"EXISTING_INFRASTRUCTURE_ONLY",productKey:key,revenueModel,paymentRail:/x402|pay_per_call|pay_per_use/i.test(revenueModel)?"x402_when_compatible":"existing_approved_collection_or_human_gate",price:"UNSET_REQUIRES_EXISTING_PRICING_OR_HUMAN_GATE",settlementTruth:"settled_verified_only",enabled:false};
  const sales={offer:{headline:r.title,valueProposition:r.product,revenueModel,cta:"purchase_or_request_scope"},channels:["existing_lumen_b2b","a2a_when_eligible"],outboundEnabled:false,externalPublishEnabled:false,next:"route_to_existing_quality_governor_then_human_gate_for_external_launch"};
  const now=NOW(); await env.DB.prepare(`INSERT INTO lumen_venture_builds_v1(idea_id,created_at,updated_at,status,product_key,artifact_json,checkout_json,sales_json,policy_json) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(idea_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,product_key=excluded.product_key,artifact_json=excluded.artifact_json,checkout_json=excluded.checkout_json,sales_json=excluded.sales_json,policy_json=excluded.policy_json`).bind(r.idea_id,now,now,"READY_FOR_GOVERNED_LAUNCH",key,JSON.stringify(artifact),JSON.stringify(checkout),JSON.stringify(sales),JSON.stringify(policy)).run();
  builds.push({ideaId:r.idea_id,productKey:key,status:"READY_FOR_GOVERNED_LAUNCH",artifact,checkout,sales}); }
 return {ok:true,engine:"LUMEN Venture Builder v1",prepared:builds.length,builds,policy,next:builds.length?"human_or_existing_governor_launch_gate":"await_mvp_ready"};
}
