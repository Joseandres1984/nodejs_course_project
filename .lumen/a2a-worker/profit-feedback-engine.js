const VERSION="1.0-profit-feedback";
const OFFERS=["MP-SUPPLIER-SNAPSHOT","MP-QUOTE-SANITY","MP-TENDER-SCAN","MP-SOURCING-5","MP-BUYER-SIGNALS","MP-EXPORT-PULSE","REV-SOURCING-SUCCESS","REV-TENDER-RADAR-BASIC","REV-TENDER-RADAR-PRO","REV-TENDER-RADAR-PLUS","REV-BUYER-INTENT-FEED"];

function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=5000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function clamp(n,min,max){return Math.max(min,Math.min(max,Number(n)||0));}

async function ensure(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_offer_performance (offer_id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,opportunities INTEGER NOT NULL DEFAULT 0,proposals INTEGER NOT NULL DEFAULT 0,sent INTEGER NOT NULL DEFAULT 0,responded INTEGER NOT NULL DEFAULT 0,verified_settlements INTEGER NOT NULL DEFAULT 0,verified_revenue_usd REAL NOT NULL DEFAULT 0,response_rate REAL NOT NULL DEFAULT 0,settlement_rate REAL NOT NULL DEFAULT 0,revenue_per_sent_usd REAL NOT NULL DEFAULT 0,evidence_level TEXT NOT NULL DEFAULT 'COLD',priority_adjustment INTEGER NOT NULL DEFAULT 0,reason TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_offer_performance_rank ON lumen_offer_performance(priority_adjustment DESC,verified_revenue_usd DESC,verified_settlements DESC)")
  ]);
  return true;
}
async function count(env,sql,bind=[]){try{const s=env.DB.prepare(sql),r=bind.length?await s.bind(...bind).first():await s.first();return Number(r?.n||0);}catch{return 0;}}
async function sum(env,sql,bind=[]){try{const s=env.DB.prepare(sql),r=bind.length?await s.bind(...bind).first():await s.first();return Number(r?.n||0);}catch{return 0;}}

function adjustmentFor(x){
  const {sent,responded,settlements,revenue}=x;
  const responseRate=sent?responded/sent:0,settlementRate=sent?settlements/sent:0,revenuePerSent=sent?revenue/sent:0;
  let adj=0,evidence='COLD',reasons=[];
  if(sent>=1)evidence='EARLY';
  if(settlements>=1){
    evidence=settlements>=3&&sent>=5?'STRONG':'VERIFIED';
    const revenueBoost=Math.min(10,Math.round(Math.log10(1+Math.max(0,revenue))*4));
    const settlementBoost=Math.min(7,settlements*3);
    const responseBoost=Math.min(3,Math.round(responseRate*6));
    adj+=revenueBoost+settlementBoost+responseBoost;
    reasons.push(`verified_settlements=${settlements}`,`verified_revenue_usd=${revenue.toFixed(2)}`);
  }else if(sent>=5){
    const noSettlementPenalty=Math.min(8,2+(sent-5));adj-=noSettlementPenalty;reasons.push(`no_verified_settlement_after_${sent}_sends`);
    if(responded===0){adj-=3;reasons.push('no_responses_after_sufficient_sends');}
    else if(responseRate>=0.25){adj+=2;reasons.push('engagement_without_settlement_yet');}
  }else reasons.push('insufficient_evidence_neutral');
  adj=Math.round(clamp(adj,-12,20));
  return{priorityAdjustment:adj,evidenceLevel:evidence,responseRate,settlementRate,revenuePerSent,reason:reasons.join(';')};
}

export async function recomputeProfitFeedback(env){
  if(!(await ensure(env)))return{ok:false,error:'persistence_unavailable',version:VERSION};
  const now=new Date().toISOString(),results=[];
  for(const offerId of OFFERS){
    const opportunities=await count(env,"SELECT COUNT(*) n FROM lumen_opportunities WHERE revenue_offer_id=?",[offerId]);
    const proposals=await count(env,"SELECT COUNT(*) n FROM lumen_proposal_drafts WHERE offer_id=?",[offerId]);
    const sent=await count(env,"SELECT COUNT(*) n FROM lumen_outreach_attempts x JOIN lumen_proposal_drafts p ON p.proposal_id=x.proposal_id WHERE p.offer_id=? AND x.status IN ('SENT','SENT_TASK','WORKING','RESPONDED','TASK_TERMINAL')",[offerId]);
    const responded=await count(env,"SELECT COUNT(*) n FROM lumen_outreach_attempts x JOIN lumen_proposal_drafts p ON p.proposal_id=x.proposal_id WHERE p.offer_id=? AND x.status='RESPONDED'",[offerId]);
    const settlements=await count(env,"SELECT COUNT(*) n FROM lumen_revenue_attributions WHERE offer_id=?",[offerId]);
    const revenue=await sum(env,"SELECT COALESCE(SUM(amount_usd),0) n FROM lumen_revenue_attributions WHERE offer_id=?",[offerId]);
    const perf=adjustmentFor({sent,responded,settlements,revenue});
    await env.DB.prepare("INSERT INTO lumen_offer_performance(offer_id,updated_at,opportunities,proposals,sent,responded,verified_settlements,verified_revenue_usd,response_rate,settlement_rate,revenue_per_sent_usd,evidence_level,priority_adjustment,reason,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(offer_id) DO UPDATE SET updated_at=excluded.updated_at,opportunities=excluded.opportunities,proposals=excluded.proposals,sent=excluded.sent,responded=excluded.responded,verified_settlements=excluded.verified_settlements,verified_revenue_usd=excluded.verified_revenue_usd,response_rate=excluded.response_rate,settlement_rate=excluded.settlement_rate,revenue_per_sent_usd=excluded.revenue_per_sent_usd,evidence_level=excluded.evidence_level,priority_adjustment=excluded.priority_adjustment,reason=excluded.reason,engine_version=excluded.engine_version")
      .bind(offerId,now,opportunities,proposals,sent,responded,settlements,revenue,perf.responseRate,perf.settlementRate,perf.revenuePerSent,perf.evidenceLevel,perf.priorityAdjustment,perf.reason,VERSION).run();
    results.push({offerId,opportunities,proposals,sent,responded,verifiedSettlements:settlements,verifiedRevenueUsd:revenue,responseRate:Number(perf.responseRate.toFixed(4)),settlementRate:Number(perf.settlementRate.toFixed(4)),revenuePerSentUsd:Number(perf.revenuePerSent.toFixed(2)),evidenceLevel:perf.evidenceLevel,priorityAdjustment:perf.priorityAdjustment,reason:perf.reason});
  }
  results.sort((a,b)=>b.priorityAdjustment-a.priorityAdjustment||b.verifiedRevenueUsd-a.verifiedRevenueUsd||b.verifiedSettlements-a.verifiedSettlements);
  return{ok:true,version:VERSION,offers:results.length,ranking:results,guardrails:{verifiedRevenueOnly:true,coldStartNeutral:true,priorityAdjustmentMin:-12,priorityAdjustmentMax:20,noAutonomousPriceChange:true,noAutonomousSpend:true,bindingActionsHumanGated:true}};
}

async function statsData(env){
  await ensure(env);
  let rows=[];try{const r=await env.DB.prepare("SELECT offer_id,opportunities,proposals,sent,responded,verified_settlements,verified_revenue_usd,response_rate,settlement_rate,revenue_per_sent_usd,evidence_level,priority_adjustment,reason,updated_at FROM lumen_offer_performance ORDER BY priority_adjustment DESC,verified_revenue_usd DESC,verified_settlements DESC,offer_id ASC").all();rows=r.results||[];}catch{}
  return{offers:rows.length,winners:rows.filter(x=>Number(x.priority_adjustment)>0).length,penalized:rows.filter(x=>Number(x.priority_adjustment)<0).length,verifiedOffers:rows.filter(x=>Number(x.verified_settlements)>0).length,totalVerifiedRevenueUsd:rows.reduce((a,x)=>a+Number(x.verified_revenue_usd||0),0),ranking:rows.slice(0,15)};
}

export async function handleProfitFeedback(request,env){
  const u=new URL(request.url);
  if(request.method==='GET'&&u.pathname==='/profit-feedback/policy')return json({version:VERSION,name:'LUMEN Profit Feedback Engine',learningTarget:'offer_priority_only',revenueTruth:'verified_payment_settled_only',coldStart:'neutral',priorityAdjustmentRange:[-12,20],autonomousPriceChange:false,autonomousSpend:false,bindingActionsHumanGated:true});
  if(request.method==='GET'&&u.pathname==='/profit-feedback/stats')return json({version:VERSION,...await statsData(env),verifiedRevenueOnly:true,coldStartNeutral:true});
  if(request.method==='POST'&&u.pathname==='/profit-feedback/recompute'){if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);return json(await recomputeProfitFeedback(env),202);}
  return null;
}
