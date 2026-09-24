const VERSION = "1.0-first-cash-revenue-director";
const ENTRY_OFFERS = ["MP-SUPPLIER-SNAPSHOT", "MP-QUOTE-SANITY", "MP-TENDER-SCAN"];
const ALL_OFFERS = ["MP-SUPPLIER-SNAPSHOT","MP-QUOTE-SANITY","MP-TENDER-SCAN","MP-SOURCING-5","MP-BUYER-SIGNALS","MP-EXPORT-PULSE"];

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control":"no-store", "x-content-type-options":"nosniff", "access-control-allow-origin":"*" } });
}
function clean(value, limit = 5000) { return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit); }
function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}
async function ensure(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_revenue_director_state (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,cycle INTEGER NOT NULL DEFAULT 0,no_progress_cycles INTEGER NOT NULL DEFAULT 0,bottleneck TEXT NOT NULL,tactic TEXT NOT NULL,target_metric TEXT NOT NULL,metrics_json TEXT NOT NULL,previous_metrics_json TEXT NOT NULL,preferred_offers_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_revenue_director_offer_focus (offer_id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,priority_adjustment INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL,tactic TEXT NOT NULL,evidence_level TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_revenue_director_focus ON lumen_revenue_director_offer_focus(priority_adjustment DESC,updated_at)")
  ]);
  return true;
}
async function scalar(env, sql, binds = []) {
  try { const q = env.DB.prepare(sql); const row = binds.length ? await q.bind(...binds).first() : await q.first(); return Number(row?.n || 0); } catch { return 0; }
}
async function all(env, sql, binds = []) {
  try { const q = env.DB.prepare(sql); const r = binds.length ? await q.bind(...binds).all() : await q.all(); return r.results || []; } catch { return []; }
}

async function metrics(env) {
  const [settlements, revenue, actionable, proposals, approved, sent, responded, negotiating, blocked] = await Promise.all([
    scalar(env, "SELECT COUNT(*) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'"),
    scalar(env, "SELECT COALESCE(SUM(amount_usd),0) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_opportunity_assessments WHERE commercially_actionable=1 AND synthetic_or_test_only=0"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_proposal_drafts WHERE quality_gate_status='PASS'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_proposal_drafts p LEFT JOIN lumen_outreach_attempts x ON x.proposal_id=p.proposal_id WHERE p.status='APPROVED' AND p.quality_gate_status='PASS' AND x.proposal_id IS NULL"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_outreach_attempts WHERE status IN ('SENT','SENT_TASK','WORKING','RESPONDED','TASK_TERMINAL')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_outreach_attempts WHERE status='RESPONDED'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_sales_pipeline WHERE stage='NEGOTIATING'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_sales_pipeline WHERE stage='BLOCKED'")
  ]);
  return { verifiedSettlements:settlements, realizedRevenueUsd:revenue, actionableOpportunities:actionable, qualityPassProposals:proposals, approvedUnsent:approved, sent, responded, negotiating, blocked };
}

function progressed(previous, current) {
  if (!previous || !Object.keys(previous).length) return false;
  const positiveKeys = ["verifiedSettlements","realizedRevenueUsd","actionableOpportunities","qualityPassProposals","approvedUnsent","sent","responded","negotiating"];
  return positiveKeys.some(k => Number(current[k] || 0) > Number(previous[k] || 0));
}

async function offerRows(env) {
  const rows = await all(env, "SELECT offer_id,opportunities,proposals,sent,responded,verified_settlements,verified_revenue_usd,response_rate,priority_adjustment,evidence_level FROM lumen_offer_performance ORDER BY offer_id");
  const byId = new Map(rows.map(r => [r.offer_id, r]));
  return ALL_OFFERS.map(id => ({
    offerId:id,
    opportunities:Number(byId.get(id)?.opportunities || 0),
    proposals:Number(byId.get(id)?.proposals || 0),
    sent:Number(byId.get(id)?.sent || 0),
    responded:Number(byId.get(id)?.responded || 0),
    verifiedSettlements:Number(byId.get(id)?.verified_settlements || 0),
    verifiedRevenueUsd:Number(byId.get(id)?.verified_revenue_usd || 0),
    responseRate:Number(byId.get(id)?.response_rate || 0),
    profitAdjustment:Number(byId.get(id)?.priority_adjustment || 0),
    evidenceLevel:byId.get(id)?.evidence_level || "COLD"
  }));
}

function decide(m, rows, noProgressCycles) {
  if (m.verifiedSettlements > 0) {
    const winners = rows.filter(x => x.verifiedSettlements > 0).sort((a,b)=>b.verifiedRevenueUsd-a.verifiedRevenueUsd || b.verifiedSettlements-a.verifiedSettlements);
    return { bottleneck:"scale_verified_revenue", tactic:"PROFIT_FEEDBACK_AUTHORITY", targetMetric:"verifiedSettlements", preferred:winners.map(x=>x.offerId).slice(0,3), reason:"verified_settlement_exists_profit_feedback_is_authoritative" };
  }
  if (m.negotiating > 0 || m.responded > 0) {
    const engaged = rows.filter(x => x.responded > 0).sort((a,b)=>b.responseRate-a.responseRate || a.sent-b.sent);
    return { bottleneck:"conversion", tactic:"CONVERSION_FIRST", targetMetric:"verifiedSettlements", preferred:engaged.map(x=>x.offerId).slice(0,3), reason:"real_response_exists_prioritize_scope_checkout_and_close" };
  }
  const entry = rows.filter(x => ENTRY_OFFERS.includes(x.offerId));
  if (noProgressCycles >= 6) {
    const rotated = [...entry].sort((a,b)=>a.sent-b.sent || a.proposals-b.proposals || b.opportunities-a.opportunities);
    return { bottleneck:"demand_generation", tactic:"ROTATE_ENTRY_OFFER", targetMetric:"responded", preferred:rotated.map(x=>x.offerId), reason:"repeated_verified_stagnation_rotate_low_friction_offer" };
  }
  if (m.sent > 0) {
    const ranked = [...entry].sort((a,b)=>b.responseRate-a.responseRate || a.sent-b.sent || b.opportunities-a.opportunities);
    return { bottleneck:"response_generation", tactic:"EXPAND_HIGH_INTENT", targetMetric:"responded", preferred:ranked.map(x=>x.offerId), reason:"outreach_exists_without_verified_response_expand_high_intent_low_friction_lane" };
  }
  const ranked = [...entry].sort((a,b)=>b.opportunities-a.opportunities || a.proposals-b.proposals);
  return { bottleneck:"demand_generation", tactic:"FIRST_CASH_DISCOVERY", targetMetric:"sent", preferred:ranked.map(x=>x.offerId), reason:"cold_start_prioritize_low_friction_entry_products" };
}

function focusAdjustments(decision, m, noProgressCycles) {
  const out = new Map(ALL_OFFERS.map(id => [id, { adjustment:0, reason:"neutral" }]));
  if (m.verifiedSettlements > 0) return out;
  const weights = decision.tactic === "ROTATE_ENTRY_OFFER" ? [8,5,3] : decision.tactic === "CONVERSION_FIRST" ? [5,3,1] : [7,4,2];
  decision.preferred.slice(0,3).forEach((id,i)=>out.set(id,{adjustment:weights[i] || 0,reason:`${decision.tactic.toLowerCase()}:rank_${i+1}`}));
  if (noProgressCycles >= 6) {
    const preferredSet = new Set(decision.preferred.slice(0,3));
    for (const id of ENTRY_OFFERS) if (!preferredSet.has(id)) out.set(id,{adjustment:-2,reason:"rotation_deprioritized_after_stagnation"});
  }
  return out;
}

export async function recomputeRevenueDirector(env) {
  if (!(await ensure(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  const current = await metrics(env);
  const old = await env.DB.prepare("SELECT cycle,no_progress_cycles,metrics_json FROM lumen_revenue_director_state WHERE id='FIRST_CASH' LIMIT 1").first();
  let previous = {}; try { previous = JSON.parse(old?.metrics_json || "{}"); } catch {}
  const didProgress = progressed(previous, current);
  const cycle = Number(old?.cycle || 0) + 1;
  const noProgressCycles = didProgress ? 0 : Math.max(0, Number(old?.no_progress_cycles || 0) + (old ? 1 : 0));
  const rows = await offerRows(env);
  const decision = decide(current, rows, noProgressCycles);
  const focus = focusAdjustments(decision, current, noProgressCycles);
  const now = new Date().toISOString();

  for (const id of ALL_OFFERS) {
    const x = focus.get(id) || { adjustment:0, reason:"neutral" };
    await env.DB.prepare("INSERT INTO lumen_revenue_director_offer_focus(offer_id,updated_at,priority_adjustment,reason,tactic,evidence_level,engine_version) VALUES(?,?,?,?,?,?,?) ON CONFLICT(offer_id) DO UPDATE SET updated_at=excluded.updated_at,priority_adjustment=excluded.priority_adjustment,reason=excluded.reason,tactic=excluded.tactic,evidence_level=excluded.evidence_level,engine_version=excluded.engine_version")
      .bind(id,now,Math.max(-4,Math.min(8,Number(x.adjustment||0))),x.reason,decision.tactic,current.verifiedSettlements>0?"VERIFIED":"COLD_START",VERSION).run();
  }
  await env.DB.prepare("INSERT INTO lumen_revenue_director_state(id,updated_at,cycle,no_progress_cycles,bottleneck,tactic,target_metric,metrics_json,previous_metrics_json,preferred_offers_json,engine_version) VALUES('FIRST_CASH',?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,cycle=excluded.cycle,no_progress_cycles=excluded.no_progress_cycles,bottleneck=excluded.bottleneck,tactic=excluded.tactic,target_metric=excluded.target_metric,metrics_json=excluded.metrics_json,previous_metrics_json=excluded.previous_metrics_json,preferred_offers_json=excluded.preferred_offers_json,engine_version=excluded.engine_version")
    .bind(now,cycle,noProgressCycles,decision.bottleneck,decision.tactic,decision.targetMetric,JSON.stringify(current),JSON.stringify(previous),JSON.stringify(decision.preferred),VERSION).run();

  return { ok:true, version:VERSION, cycle, verifiedProgress:didProgress, noProgressCycles, bottleneck:decision.bottleneck, tactic:decision.tactic, targetMetric:decision.targetMetric, preferredOffers:decision.preferred, reason:decision.reason, metrics:current, focus:[...focus.entries()].map(([offerId,x])=>({offerId,priorityAdjustment:Math.max(-4,Math.min(8,Number(x.adjustment||0))),reason:x.reason})), guardrails:{selectionPriorityOnly:true,priorityAdjustmentRange:[-4,8],priceChanges:false,externalMessagesAddedPerCycle:0,autonomousSpend:false,autonomousContract:false,bindingActionsHumanGated:true} };
}

async function state(env) {
  await ensure(env);
  const row = await env.DB.prepare("SELECT * FROM lumen_revenue_director_state WHERE id='FIRST_CASH' LIMIT 1").first();
  const focus = await all(env,"SELECT offer_id,priority_adjustment,reason,tactic,evidence_level,updated_at FROM lumen_revenue_director_offer_focus ORDER BY priority_adjustment DESC,offer_id");
  if (!row) return { version:VERSION, initialized:false, focus };
  const parse=(v,f)=>{try{return JSON.parse(v||"");}catch{return f;}};
  return { version:VERSION, initialized:true, updatedAt:row.updated_at, cycle:Number(row.cycle||0), noProgressCycles:Number(row.no_progress_cycles||0), bottleneck:row.bottleneck, tactic:row.tactic, targetMetric:row.target_metric, metrics:parse(row.metrics_json,{}), previousMetrics:parse(row.previous_metrics_json,{}), preferredOffers:parse(row.preferred_offers_json,[]), focus };
}

export async function handleRevenueDirector(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/revenue-director/policy") return json({ version:VERSION, name:"LUMEN First-Cash Revenue Director", objective:"maximize_probability_of_first_verified_settlement_with_bounded_reversible_tactics", coldStartFocus:ENTRY_OFFERS, progressRule:"only_observed_funnel_progress_resets_stagnation", verifiedSettlementRule:"after_first_verified_settlement_profit_feedback_becomes_authoritative", selectionPriorityOnly:true, priorityAdjustmentRange:[-4,8], addsExternalMessages:false, autonomousPriceChange:false, autonomousSpend:false, autonomousContract:false, bindingActionsHumanGated:true });
  if (request.method === "GET" && url.pathname === "/revenue-director/state") return json(await state(env));
  if (request.method === "POST" && url.pathname === "/revenue-director/recompute") {
    if (!authorized(request, env)) return json({ ok:false, error:"admin_token_required" },403);
    return json(await recomputeRevenueDirector(env),202);
  }
  return null;
}
