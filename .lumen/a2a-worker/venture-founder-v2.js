const NOW = () => new Date().toISOString();

function clamp(v,min=0,max=1){const n=Number(v);return Number.isFinite(n)?Math.max(min,Math.min(max,n)):min;}
function safeJson(v,f={}){try{return JSON.parse(v||"");}catch{return f;}}

async function ensureSchema(db){
  await db.prepare(`CREATE TABLE IF NOT EXISTS lumen_venture_founder_v2 (
    idea_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    verdict TEXT NOT NULL, confidence REAL NOT NULL, opportunity_score REAL NOT NULL,
    validation_plan_json TEXT NOT NULL, mvp_plan_json TEXT NOT NULL,
    launch_plan_json TEXT NOT NULL, policy_json TEXT NOT NULL
  )`).run();
}

function evaluate(row){
  const evidence=safeJson(row.evidence_json,{}), base=clamp(row.score);
  const excerpt=String(evidence.excerpt||"");
  const buyerSignal=/need|want|looking|request|buy|quote|urgent|problem|pain/i.test(excerpt)?0.12:0;
  const sourceSignal=row.source_ref?0.08:0;
  const score=clamp(base*0.72+buyerSignal+sourceSignal);
  const verdict=score>=0.72?"MVP_READY":score>=0.60?"VALIDATE":"WATCH";
  return {score:Number(score.toFixed(4)),verdict};
}

export async function runVentureFounderV2(env,{limit=8}={}){
  if(!env?.DB) throw new Error("venture_founder_persistence_required");
  await ensureSchema(env.DB);
  let rows=[];
  try{rows=(await env.DB.prepare("SELECT * FROM lumen_venture_hunter_ideas WHERE status IN ('BUILD_CANDIDATE','VALIDATE') ORDER BY score DESC,created_at DESC LIMIT ?").bind(limit).all()).results||[];}catch{}
  const policy={autonomousResearch:true,autonomousValidationPlanning:true,autonomousCodePreparation:true,autonomousExternalLaunch:false,autonomousSpending:false,autonomousContracting:false,bindingActionsHumanGated:true};
  const ventures=[];
  for(const row of rows){
    const e=evaluate(row);
    const revenueModel=String(row.revenue_model||"existing approved payment model"); const validation={hypothesis:`A buyer will pay for: ${row.product} via ${revenueModel}`,checks:["confirm repeated demand signal","identify reachable buyer or channel","validate the proposed revenue mechanism against buyer behavior","compare existing alternatives","verify deliverable can be produced safely"],success:"real buyer evidence or attributable purchase intent for the proposed value/revenue mechanism",failure:"weak/repeatedly synthetic demand, no reachable buyer, or no evidence the proposed monetization fits"};
    const mvp={product:row.product,revenueModel,buildPlan:row.build_plan,scope:"smallest paid deliverable proving demand",checkout:"reuse existing x402/payment infrastructure where compatible; otherwise preserve existing approved/human-gated collection path",delivery:"reuse guarded LUMEN delivery path",pricing:"do not autonomously change production prices"};
    const launch={mode:"PREPARE_ONLY",steps:["prepare product spec","prepare landing/API contract","prepare checkout mapping","prepare sales artifact","route through existing quality/governor gates"],externalActionRequiresHumanGate:true};
    const now=NOW();
    await env.DB.prepare(`INSERT INTO lumen_venture_founder_v2(idea_id,created_at,updated_at,verdict,confidence,opportunity_score,validation_plan_json,mvp_plan_json,launch_plan_json,policy_json)
      VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(idea_id) DO UPDATE SET updated_at=excluded.updated_at,verdict=excluded.verdict,confidence=excluded.confidence,opportunity_score=excluded.opportunity_score,validation_plan_json=excluded.validation_plan_json,mvp_plan_json=excluded.mvp_plan_json,launch_plan_json=excluded.launch_plan_json,policy_json=excluded.policy_json`)
      .bind(row.id,now,now,e.verdict,e.score,e.score,JSON.stringify(validation),JSON.stringify(mvp),JSON.stringify(launch),JSON.stringify(policy)).run();
    ventures.push({ideaId:row.id,title:row.title,product:row.product,revenueModel,verdict:e.verdict,score:e.score,validation,mvp,launch});
  }
  return {ok:true,engine:"LUMEN Venture Founder v2",examined:rows.length,mvpReady:ventures.filter(v=>v.verdict==="MVP_READY").length,topVenture:ventures[0]||null,ventures,policy,next:ventures.some(v=>v.verdict==="MVP_READY")?"prepare_guarded_mvp":"keep_validating"};
}
