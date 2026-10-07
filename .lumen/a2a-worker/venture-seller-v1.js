const NOW=()=>new Date().toISOString();
function json(v,f={}){try{return JSON.parse(v||"");}catch{return f;}}
async function schema(db){await db.prepare(`CREATE TABLE IF NOT EXISTS lumen_venture_seller_v1(idea_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,product_key TEXT NOT NULL,offer_packet_json TEXT NOT NULL,policy_json TEXT NOT NULL)`).run();}
function prepareOffer(row){
 const launch=json(row.launch_packet_json), ready=json(row.readiness_json), launchPolicy=json(row.policy_json);
 const eligible=row.status==="AWAITING_EXTERNAL_LAUNCH_APPROVAL"&&ready.pass===true&&launch.nonBindingPreparationComplete===true&&launch.executesExternalAction===false;
 const offer={ideaId:row.idea_id,productKey:row.product_key,state:eligible?"READY_FOR_GOVERNED_SELL":"BLOCKED_NOT_SELLABLE",preparedAt:NOW(),channelMode:"EXISTING_APPROVED_RAILS_ONLY",pricingMode:"EXISTING_APPROVED_PRICE_OR_HUMAN_GATE",checkoutMode:"EXISTING_INFRASTRUCTURE_ONLY",settlementTruth:"settled_verified_only",externalActionExecuted:false,outboundExecuted:false,published:false,contractCreated:false,spendUsd:0,requiredGate:["approved production price mapping","external publication or first outbound","binding commercial action"],sourceLaunchDecision:launch.decision||row.status};
 return {eligible,offer,launchPolicy};
}
export async function runVentureSellerV1(env,{limit=5}={}){
 if(!env?.DB)throw new Error("venture_seller_persistence_required");await schema(env.DB);
 let rows=[];try{rows=(await env.DB.prepare("SELECT * FROM lumen_venture_launches_v1 WHERE status='AWAITING_EXTERNAL_LAUNCH_APPROVAL' ORDER BY updated_at DESC LIMIT ?").bind(limit).all()).results||[];}catch(error){if(!/no such table:/i.test(String(error?.message||error)))throw error;}
 const policy={mode:"GOVERNED_SELL_PREPARATION",autonomousOfferPreparation:true,autonomousChannelSelection:"approved_existing_rails_only",autonomousExternalPublish:false,autonomousOutbound:false,autonomousSpendUsd:0,autonomousContract:false,autonomousPriceChange:false,bindingActionsHumanGated:true,settlementTruth:"settled_verified_only"};
 const offers=[];
 for(const row of rows){const prepared=prepareOffer(row),now=NOW(),status=prepared.offer.state;await env.DB.prepare(`INSERT INTO lumen_venture_seller_v1(idea_id,created_at,updated_at,status,product_key,offer_packet_json,policy_json) VALUES(?,?,?,?,?,?,?) ON CONFLICT(idea_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,product_key=excluded.product_key,offer_packet_json=excluded.offer_packet_json,policy_json=excluded.policy_json`).bind(row.idea_id,now,now,status,row.product_key,JSON.stringify(prepared.offer),JSON.stringify(policy)).run();offers.push(prepared.offer);}
 return {ok:true,engine:"LUMEN Venture Seller v1",examined:rows.length,readyToSell:offers.filter(x=>x.state==="READY_FOR_GOVERNED_SELL").length,blocked:offers.filter(x=>x.state!=="READY_FOR_GOVERNED_SELL").length,offers,policy,kpi:"settled_verified",next:offers.some(x=>x.state==="READY_FOR_GOVERNED_SELL")?"governed_sell_activation":"await_launcher_ready"};
}
