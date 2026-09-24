const VERSION="1.0-partner-economic-performance";

function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=5000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function clamp(v,min=0,max=100){return Math.max(min,Math.min(max,Number(v)||0));}

async function ensure(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_economic_performance (partner_id TEXT PRIMARY KEY,partner_name TEXT,updated_at TEXT NOT NULL,economic_score INTEGER NOT NULL DEFAULT 50,economic_confidence INTEGER NOT NULL DEFAULT 0,verified_revenue_usd REAL NOT NULL DEFAULT 0,verified_settlements INTEGER NOT NULL DEFAULT 0,verified_referral_settlements INTEGER NOT NULL DEFAULT 0,revenue_per_settlement_usd REAL NOT NULL DEFAULT 0,evidence_events INTEGER NOT NULL DEFAULT 0,reason TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_partner_economic_rank ON lumen_partner_economic_performance(economic_confidence DESC,economic_score DESC,verified_revenue_usd DESC)")
  ]);
  return true;
}

async function safeAll(env,sql,bind=[]){try{const s=env.DB.prepare(sql),r=bind.length?await s.bind(...bind).all():await s.all();return r.results||[];}catch{return[];}}

function scoreEconomic({revenue,settlements,referrals}){
  if(settlements<=0)return{score:50,confidence:0,reason:"no_verified_partner_attributed_settlement"};
  const revenueSignal=Math.min(25,Math.round(Math.log10(1+Math.max(0,revenue))*12));
  const settlementSignal=Math.min(17,settlements*6);
  const referralSignal=Math.min(8,referrals*4);
  const score=Math.round(clamp(50+revenueSignal+settlementSignal+referralSignal));
  const confidence=Math.round(clamp(settlements*18+referrals*8+Math.min(20,Math.log10(1+Math.max(0,revenue))*10)));
  const reason=`verified_revenue_usd=${revenue.toFixed(2)};verified_settlements=${settlements};verified_referral_settlements=${referrals};direct_attribution_only`;
  return{score,confidence,reason};
}

export async function recomputePartnerEconomicPerformance(env){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const partners=await safeAll(env,"SELECT id,name FROM lumen_partner_agents ORDER BY name ASC");
  const values=await safeAll(env,"SELECT partner_id,partner_name,verified_revenue_influenced_usd,verified_settlements,verified_referral_settlements FROM lumen_partner_commercial_value");
  const byId=new Map(values.map(x=>[x.partner_id,x]));
  const now=new Date().toISOString(),results=[];
  for(const p of partners){
    const v=byId.get(p.id)||{};
    const revenue=Math.max(0,Number(v.verified_revenue_influenced_usd||0));
    const settlements=Math.max(0,Number(v.verified_settlements||0));
    const referrals=Math.max(0,Number(v.verified_referral_settlements||0));
    const perf=scoreEconomic({revenue,settlements,referrals});
    const revenuePerSettlement=settlements?revenue/settlements:0;
    const evidenceEvents=settlements+referrals;
    await env.DB.prepare("INSERT INTO lumen_partner_economic_performance(partner_id,partner_name,updated_at,economic_score,economic_confidence,verified_revenue_usd,verified_settlements,verified_referral_settlements,revenue_per_settlement_usd,evidence_events,reason,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(partner_id) DO UPDATE SET partner_name=excluded.partner_name,updated_at=excluded.updated_at,economic_score=excluded.economic_score,economic_confidence=excluded.economic_confidence,verified_revenue_usd=excluded.verified_revenue_usd,verified_settlements=excluded.verified_settlements,verified_referral_settlements=excluded.verified_referral_settlements,revenue_per_settlement_usd=excluded.revenue_per_settlement_usd,evidence_events=excluded.evidence_events,reason=excluded.reason,engine_version=excluded.engine_version")
      .bind(p.id,p.name||v.partner_name||null,now,perf.score,perf.confidence,revenue,settlements,referrals,revenuePerSettlement,evidenceEvents,perf.reason,VERSION).run();
    results.push({partnerId:p.id,name:p.name,economicScore:perf.score,economicConfidence:perf.confidence,verifiedRevenueUsd:revenue,verifiedSettlements:settlements,verifiedReferralSettlements:referrals,revenuePerSettlementUsd:Number(revenuePerSettlement.toFixed(2)),evidenceEvents,reason:perf.reason});
  }
  results.sort((a,b)=>b.economicConfidence-a.economicConfidence||b.economicScore-a.economicScore||b.verifiedRevenueUsd-a.verifiedRevenueUsd);
  return{ok:true,version:VERSION,partners:results.length,revenueProducingPartners:results.filter(x=>x.verifiedSettlements>0).length,meaningfulEconomicConfidence:results.filter(x=>x.economicConfidence>=30).length,top:results.filter(x=>x.verifiedSettlements>0).slice(0,12),guardrails:{verifiedSettlementsOnly:true,directAttributionOnly:true,noTeamCreditWithoutEvidence:true,noPenaltyForNoRevenue:true,maxObservedReputationWeightPercent:20,autonomousSpend:false,bindingActionsHumanGated:true}};
}

async function statsData(env){
  await ensure(env);
  let rows=[];try{const r=await env.DB.prepare("SELECT partner_id,partner_name,economic_score,economic_confidence,verified_revenue_usd,verified_settlements,verified_referral_settlements,revenue_per_settlement_usd,evidence_events,reason,updated_at FROM lumen_partner_economic_performance ORDER BY economic_confidence DESC,economic_score DESC,verified_revenue_usd DESC LIMIT 100").all();rows=r.results||[];}catch{}
  return{partners:rows.length,revenueProducingPartners:rows.filter(x=>Number(x.verified_settlements)>0).length,meaningfulEconomicConfidence:rows.filter(x=>Number(x.economic_confidence)>=30).length,totalPartnerAttributedRevenueUsd:rows.reduce((a,x)=>a+Number(x.verified_revenue_usd||0),0),top:rows.filter(x=>Number(x.verified_settlements)>0).slice(0,12)};
}

export async function handlePartnerEconomicPerformance(request,env){
  const u=new URL(request.url);
  if(request.method==='GET'&&u.pathname==='/partners/economic-performance/policy')return json({version:VERSION,name:'LUMEN Partner Economic Performance',truthRule:'verified_partner_attributed_payment_settled_only',coldStart:'neutral_50_weight_0',oneSettlementWeight:'low',maxObservedReputationWeightPercent:20,noRevenuePenalty:true,directAttributionOnly:true,autonomousSpend:false,bindingActionsHumanGated:true});
  if(request.method==='GET'&&u.pathname==='/partners/economic-performance/stats')return json({version:VERSION,...await statsData(env),verifiedSettlementsOnly:true,directAttributionOnly:true});
  if(request.method==='POST'&&u.pathname==='/partners/economic-performance/recompute'){if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);return json(await recomputePartnerEconomicPerformance(env),202);}
  if(request.method==='GET'&&u.pathname==='/partners/economic-performance'){if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);await ensure(env);const r=await env.DB.prepare("SELECT * FROM lumen_partner_economic_performance ORDER BY economic_confidence DESC,economic_score DESC,verified_revenue_usd DESC LIMIT 200").all();return json({version:VERSION,partners:r.results||[]});}
  return null;
}
