const VERSION = "1.1-demand-conversion-learning";
const MODEL = "@cf/google/gemma-4-26b-a4b-it";
const EXPLORATION_RATE = 0.20;
const MAX_AI_HYPOTHESES = 3;

export const UNIFIED_BRAIN_POLICY = Object.freeze({
  version: VERSION,
  identity: "LUMEN Unified Economic Brain",
  objective: "maximize_verified_net_revenue_by_discovering_testing_and_learning_from_economic_opportunities",
  cognition: ["OBSERVE","INTERPRET","GENERATE_HYPOTHESES","REASON","CHOOSE","ACT_REVERSIBLY","MEASURE","LEARN"],
  openEndedBusinessModels: true,
  explorationRate: EXPLORATION_RATE,
  rewardOrder: ["VERIFIED_SETTLEMENT","VERIFIED_REVENUE","ORDER_OR_PURCHASE_INTENT","QUOTE_REQUEST","VERIFIED_BUYER_DEMAND","COMMERCIAL_RESPONSE","VERIFIED_DELIVERY","PUBLISHED_OFFER","CLICK","IMPRESSION"],
  learningTarget: "economic_funnel_progress_not_activity",
  sentIsNotSuccess: true,
  demandFirstWhenBuyerEvidenceZero: true,
  persistentFunnelMemory: true,
  strategyMemoryAffectsSelection: true,
  oneGlobalEconomicMission: true,
  autonomousSpendUsd: 0,
  autonomousPurchase: false,
  autonomousContract: false,
  autonomousDebt: false,
  priceMutation: false,
  bindingActionsHumanGated: true,
  revenueTruth: "provider_verified_settlement_only"
});

const EXECUTION_LANES = new Set(["REVENUE","VENTURE","COMMERCE","TRAVEL","DISCOVERY","EXPLORE","HOLD"]);
const FORBIDDEN = /\b(pay|payment|spend|wire|transfer|withdraw|purchase|buy\s+with|sign\s+contract|accept\s+contract|debt|loan|private\s+key|seed\s+phrase|pagar|transferir|comprar\s+con|firmar\s+contrato|aceptar\s+contrato|deuda|pr[eé]stamo)\b/i;
const now = () => new Date().toISOString();
const clean = (v, n=600) => String(v ?? "").replace(/[\u0000-\u001f\u007f]/g," ").replace(/\s+/g," ").trim().slice(0,n);
const num = (v, d=0) => Number.isFinite(Number(v)) ? Number(v) : d;
const clamp = (v, a=0, b=1) => Math.max(a, Math.min(b, num(v,a)));
const parse = (v,d={}) => { try { const x=typeof v === "string" ? JSON.parse(v) : v; return x && typeof x === "object" ? x : d; } catch { return d; } };

function strategyKey(h={}) {
  return `${clean(h.executionLane || h.execution_lane || "EXPLORE",30).toUpperCase()}:${clean(h.businessModel || h.business_model || "unknown",180)}`.slice(0,220);
}

export function isDemandFocusedHypothesis(h={}) {
  const text = `${h.businessModel||h.business_model||""} ${h.hypothesis||""} ${h.target||""} ${h.nextStep||h.next_step||""}`;
  return /\b(demand|buyer|rfq|request for quote|request board|procurement|tender|purchase intent|need statement|demanda|comprador|cotiz|licitaci[oó]n|necesidad)\b/i.test(text);
}

export function detectEconomicBottleneck(f={}) {
  const settlements=Math.max(0,num(f.verifiedSettlements,0));
  const negotiations=Math.max(0,num(f.negotiations,0));
  const responses=Math.max(0,num(f.verifiedResponses,0));
  const sent=Math.max(0,num(f.sent,0));
  const proposals=Math.max(0,num(f.proposals,0));
  const qualified=Math.max(0,num(f.qualifiedCommercialCandidates,0));
  if (settlements>0) return "REPEAT_WINNER";
  if (negotiations>0 || responses>0) return "CLOSE";
  if (sent>0) return "DELIVERY_OR_RESPONSE";
  if (proposals>0) return "OUTBOUND";
  if (qualified>0) return "PROPOSAL";
  return "DEMAND";
}

export function learningAdjustment(h={}, memory={}, context={}) {
  const attempts=Math.max(0,num(memory.attempts,0));
  const averageReward=attempts>0 ? num(memory.reward,0)/attempts : 0;
  let delta=Math.max(-0.14,Math.min(0.18,averageReward/120));
  const bottleneck=clean(context.bottleneck || "",40).toUpperCase();
  const lane=clean(h.executionLane || h.execution_lane || "EXPLORE",30).toUpperCase();
  const demandFocused=isDemandFocusedHypothesis(h);
  if (bottleneck==="DEMAND" && demandFocused) delta+=0.18;
  if (bottleneck==="DEMAND" && ["COMMERCE","TRAVEL","VENTURE"].includes(lane) && !demandFocused) delta-=0.14;
  if (bottleneck==="DELIVERY_OR_RESPONSE" && lane==="REVENUE") delta+=0.12;
  if (bottleneck==="OUTBOUND" && lane==="REVENUE") delta+=0.10;
  if (bottleneck==="PROPOSAL" && (lane==="REVENUE" || demandFocused)) delta+=0.10;
  if (bottleneck==="CLOSE" && lane==="REVENUE") delta+=0.16;
  return Number(Math.max(-0.25,Math.min(0.25,delta)).toFixed(4));
}

export function scoreEconomicHypothesis(h={}, context={}) {
  const probability = clamp(h.probabilityOfSale,0,1);
  const evidence = clamp(h.evidenceStrength,0,1);
  const confidence = clamp(h.confidence,0,1);
  const novelty = clamp(h.novelty,0,1);
  const risk = clamp(h.risk,0,1);
  const reversibility = clamp(h.reversibility,0,1);
  const hours = Math.max(1, num(h.timeToCashHours,168));
  const capital = Math.max(0, num(h.capitalRequiredUsd,0));
  const profit = Math.max(0, num(h.expectedProfitUsd,0));
  if (capital > 0 || reversibility < 0.35) return 0;
  const moneySignal = profit > 0 ? Math.min(1, Math.log10(1 + profit) / 3) : 0.28;
  const speed = 1 / (1 + Math.log10(1 + hours));
  const base = moneySignal*0.20 + probability*0.22 + evidence*0.18 + confidence*0.12 + speed*0.12 + reversibility*0.08 + novelty*0.08 - risk*0.16;
  const learned = learningAdjustment(h, context.memory || {}, context);
  return Number(clamp(base + learned).toFixed(4));
}

export function normalizeEconomicHypothesis(raw={}, fallback={}) {
  const text = `${raw.business_model||""} ${raw.hypothesis||""} ${raw.next_step||""}`;
  const unsafe = FORBIDDEN.test(text) || num(raw.capital_required_usd,0) > 0;
  const laneRaw = clean(raw.execution_lane || fallback.executionLane || "EXPLORE",30).toUpperCase();
  const lane = EXECUTION_LANES.has(laneRaw) ? laneRaw : "EXPLORE";
  const h = {
    id: clean(raw.id || fallback.id || crypto.randomUUID(),120),
    businessModel: clean(raw.business_model || fallback.businessModel || "open-ended demand discovery",240),
    hypothesis: clean(raw.hypothesis || fallback.hypothesis || "Find a monetizable demand signal using existing reversible capabilities.",500),
    target: clean(raw.target || fallback.target || "unknown buyer segment",240),
    executionLane: unsafe ? "HOLD" : lane,
    sourceRef: clean(raw.source_ref || fallback.sourceRef || "brain-generated",180),
    expectedProfitUsd: Math.max(0,num(raw.expected_profit_usd ?? fallback.expectedProfitUsd,0)),
    probabilityOfSale: clamp(raw.probability_of_sale ?? fallback.probabilityOfSale ?? 0.2),
    timeToCashHours: Math.max(1,num(raw.time_to_cash_hours ?? fallback.timeToCashHours,168)),
    capitalRequiredUsd: unsafe ? Math.max(0,num(raw.capital_required_usd,0)) : 0,
    risk: clamp(raw.risk ?? fallback.risk ?? 0.35),
    reversibility: clamp(raw.reversibility ?? fallback.reversibility ?? 0.9),
    evidenceStrength: clamp(raw.evidence_strength ?? fallback.evidenceStrength ?? 0.4),
    confidence: clamp(raw.confidence ?? fallback.confidence ?? 0.45),
    novelty: clamp(raw.novelty ?? fallback.novelty ?? 0.5),
    rationaleSummary: clean(raw.rationale_summary || fallback.rationaleSummary || "Bounded hypothesis derived from current economic evidence.",360),
    nextStep: clean(raw.next_step || fallback.nextStep || "Run the smallest reversible validation using an existing LUMEN capability.",360),
    safetyOverride: unsafe ? "requires_human_authority_or_nonzero_capital" : null
  };
  h.score = scoreEconomicHypothesis(h);
  return h;
}

export function chooseEconomicMission(hypotheses=[], cycleKey="", context={}) {
  const safe = hypotheses.filter(h => h && h.executionLane !== "HOLD" && h.capitalRequiredUsd === 0 && h.reversibility >= 0.35);
  if (!safe.length) return normalizeEconomicHypothesis({ execution_lane:"EXPLORE", business_model:"open-ended opportunity discovery", hypothesis:"Search current demand and market evidence for a new zero-capital monetization hypothesis.", novelty:1, evidence_strength:0.25, confidence:0.4, probability_of_sale:0.15, time_to_cash_hours:72 });
  const bottleneck=clean(context.bottleneck || "",40).toUpperCase();
  let pool=safe;
  if (bottleneck==="DEMAND") {
    const demandPool=safe.filter(isDemandFocusedHypothesis);
    if (demandPool.length) pool=demandPool;
  } else if (["DELIVERY_OR_RESPONSE","OUTBOUND","PROPOSAL","CLOSE"].includes(bottleneck)) {
    const revenuePool=safe.filter(h=>h.executionLane==="REVENUE");
    if (revenuePool.length) pool=revenuePool;
  }
  const bucket = [...clean(cycleKey,80)].reduce((sum,ch)=>sum+ch.charCodeAt(0),0) % 5;
  const explore = bucket === 0;
  const ranked = [...pool].sort((x,y) => explore ? (y.novelty-x.novelty || y.score-x.score) : (y.score-x.score || y.evidenceStrength-x.evidenceStrength));
  return { ...ranked[0], selectionMode: explore ? "EXPLORE" : "EXPLOIT" };
}

export function specialistPlanForMission(mission={}) {
  const lane = clean(mission.executionLane || "EXPLORE",30).toUpperCase();
  return {
    lane,
    revenue: lane === "REVENUE" || lane === "DISCOVERY" || lane === "EXPLORE",
    venture: lane === "VENTURE" || lane === "DISCOVERY" || lane === "EXPLORE",
    commerce: lane === "COMMERCE" || lane === "EXPLORE",
    travel: lane === "TRAVEL" || lane === "EXPLORE",
    growthDiscovery: lane === "DISCOVERY" || lane === "VENTURE" || lane === "EXPLORE",
    learning: true
  };
}

async function ensureSchema(env) {
  if (!env?.DB) throw new Error("brain_persistence_required");
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_brain_missions (id TEXT PRIMARY KEY,cycle_key TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,selection_mode TEXT NOT NULL,execution_lane TEXT NOT NULL,business_model TEXT NOT NULL,hypothesis TEXT NOT NULL,target TEXT,source_ref TEXT,score REAL NOT NULL,confidence REAL NOT NULL,expected_profit_usd REAL NOT NULL DEFAULT 0,probability_sale REAL NOT NULL DEFAULT 0,time_to_cash_hours REAL NOT NULL DEFAULT 0,evidence_strength REAL NOT NULL DEFAULT 0,novelty REAL NOT NULL DEFAULT 0,risk REAL NOT NULL DEFAULT 0,reversibility REAL NOT NULL DEFAULT 1,rationale_summary TEXT NOT NULL,next_step TEXT NOT NULL,evidence_json TEXT NOT NULL,outcome_json TEXT,reward REAL NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_brain_missions_created ON lumen_brain_missions(created_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_brain_hypotheses (id TEXT PRIMARY KEY,cycle_key TEXT NOT NULL,created_at TEXT NOT NULL,execution_lane TEXT NOT NULL,business_model TEXT NOT NULL,hypothesis TEXT NOT NULL,source_ref TEXT,score REAL NOT NULL,novelty REAL NOT NULL,evidence_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_brain_leases (cycle_key TEXT PRIMARY KEY,claimed_at TEXT NOT NULL,owner TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_brain_learning (strategy_key TEXT PRIMARY KEY,attempts INTEGER NOT NULL DEFAULT 0,verified_settlements INTEGER NOT NULL DEFAULT 0,commercial_responses INTEGER NOT NULL DEFAULT 0,published_offers INTEGER NOT NULL DEFAULT 0,reward REAL NOT NULL DEFAULT 0,updated_at TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_brain_funnel_memory (cycle_key TEXT PRIMARY KEY,created_at TEXT NOT NULL,qualified_candidates INTEGER NOT NULL DEFAULT 0,proposals INTEGER NOT NULL DEFAULT 0,sent INTEGER NOT NULL DEFAULT 0,verified_responses INTEGER NOT NULL DEFAULT 0,negotiations INTEGER NOT NULL DEFAULT 0,verified_settlements INTEGER NOT NULL DEFAULT 0,delivered INTEGER NOT NULL DEFAULT 0,verified_revenue_usd REAL NOT NULL DEFAULT 0,bottleneck TEXT NOT NULL,evidence_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_brain_funnel_created ON lumen_brain_funnel_memory(created_at DESC)"),
  ]);
}

async function rows(env, sql, binds=[]) {
  try { const r = await env.DB.prepare(sql).bind(...binds).all(); return r?.results || []; } catch { return []; }
}

async function scalar(env, sql, field="n") {
  const result=await rows(env,sql);
  return num(result?.[0]?.[field],0);
}

async function collectFunnel(env) {
  const [qualified,proposals,sent,responses,negotiations,settlements,delivered,revenue] = await Promise.all([
    scalar(env,"SELECT COUNT(*) n FROM lumen_revenue_loop_v5 WHERE stage IN ('QUALIFIED','PROPOSAL_READY','SENT','REPLIED','NEGOTIATING','PAID','DELIVERED')"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_proposal_drafts WHERE UPPER(COALESCE(status,'')) NOT IN ('REJECTED','DISCARDED')"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_revenue_loop_v5 WHERE stage IN ('SENT','REPLIED','NEGOTIATING','PAID','DELIVERED')"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_revenue_loop_v5 WHERE stage IN ('REPLIED','NEGOTIATING','PAID','DELIVERED')"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_revenue_loop_v5 WHERE stage IN ('NEGOTIATING','PAID','DELIVERED')"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_x402_receipts WHERE status='settled_verified'"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_paid_deliveries WHERE LOWER(COALESCE(status,''))='delivered'"),
    scalar(env,"SELECT COALESCE(SUM(amount_usd),0) n FROM lumen_x402_revenue_bridge WHERE bridge_status IN ('ATTRIBUTABLE','REFERRAL_ATTRIBUTABLE')")
  ]);
  const funnel={
    qualifiedCommercialCandidates:qualified,
    proposals,
    sent,
    verifiedResponses:responses,
    negotiations,
    verifiedSettlements:settlements,
    delivered,
    verifiedRevenueUsd:Number(revenue.toFixed ? revenue.toFixed(2) : revenue)
  };
  funnel.bottleneck=detectEconomicBottleneck(funnel);
  funnel.sentIsNotSuccess=true;
  return funnel;
}

async function persistFunnelSnapshot(env, cycleKey, funnel) {
  await env.DB.prepare("INSERT OR REPLACE INTO lumen_brain_funnel_memory(cycle_key,created_at,qualified_candidates,proposals,sent,verified_responses,negotiations,verified_settlements,delivered,verified_revenue_usd,bottleneck,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(cycleKey,now(),funnel.qualifiedCommercialCandidates,funnel.proposals,funnel.sent,funnel.verifiedResponses,funnel.negotiations,funnel.verifiedSettlements,funnel.delivered,funnel.verifiedRevenueUsd,funnel.bottleneck,JSON.stringify({sentIsNotSuccess:true})).run();
}

async function collectObservation(env) {
  const [ideas, proposals, supplier, settlements, launches, sources] = await Promise.all([
    rows(env,"SELECT id,title,product,build_plan,score,status,evidence_json FROM lumen_venture_hunter_ideas ORDER BY score DESC,created_at DESC LIMIT 12"),
    rows(env,"SELECT proposal_id,status,quality_gate_status,created_at FROM lumen_proposal_drafts ORDER BY created_at DESC LIMIT 20"),
    rows(env,"SELECT sku,title,projected_profit,projected_margin_pct,rank_score,state,blockers_json FROM lumen_supplier_launch_queue ORDER BY rank_score DESC,updated_at DESC LIMIT 12"),
    rows(env,"SELECT b.proposal_id,r.id receipt_id,r.status FROM lumen_x402_revenue_bridge b JOIN lumen_x402_receipts r ON r.id=b.receipt_id WHERE r.status='settled_verified' ORDER BY b.created_at DESC LIMIT 20"),
    rows(env,"SELECT sku,state,projected_profit,projected_margin_pct,created_at FROM lumen_supplier_launches ORDER BY created_at DESC LIMIT 15"),
    rows(env,"SELECT * FROM lumen_source_observations ORDER BY rowid DESC LIMIT 12")
  ]);
  const funnel=await collectFunnel(env);
  const learningMemory=await rows(env,"SELECT * FROM lumen_brain_learning ORDER BY updated_at DESC LIMIT 200");
  return {
    at: now(), verifiedSettlementCount: Math.max(settlements.length,funnel.verifiedSettlements), funnel, learningMemory,
    ventureIdeas: ideas.map(x=>({id:x.id,title:clean(x.title,180),product:clean(x.product,180),buildPlan:clean(x.build_plan,240),score:num(x.score),status:x.status,evidence:parse(x.evidence_json,{})})),
    proposals: proposals.map(x=>({id:x.proposal_id,status:x.status,quality:x.quality_gate_status,createdAt:x.created_at})),
    supplierQueue: supplier.map(x=>({sku:x.sku,title:clean(x.title,180),profit:num(x.projected_profit),margin:num(x.projected_margin_pct),rank:num(x.rank_score),state:x.state,blockers:parse(x.blockers_json,[])})),
    recentSupplierLaunches: launches,
    recentVerifiedSettlements: settlements,
    rawDemandSignals: sources.map(x=>Object.fromEntries(Object.entries(x).filter(([,v])=>typeof v==="string"||typeof v==="number").slice(0,12))),
    authority: UNIFIED_BRAIN_POLICY
  };
}

function deterministicHypotheses(obs) {
  const out=[];
  const bottleneck=obs?.funnel?.bottleneck || "DEMAND";
  if (bottleneck==="DEMAND") out.push(normalizeEconomicHypothesis({
    id:"funnel-demand-gap",business_model:"verified buyer demand acquisition",hypothesis:"Find a current public buyer need, RFQ, tender, request board post or explicit sourcing requirement before expanding cold company lists.",target:"buyer with current verifiable need",execution_lane:"DISCOVERY",source_ref:"funnel-demand-gap",
    probability_of_sale:.42,time_to_cash_hours:36,evidence_strength:.92,confidence:.9,novelty:.45,risk:.08,reversibility:.99,
    rationale_summary:"The commercial funnel lacks downstream buyer evidence, so demand must be proven before more supply-side activity.",
    next_step:"Prioritize recent buyer-specific demand evidence with company, need, recency and reachable contact; reject generic directory leads."
  }));
  if (bottleneck==="DELIVERY_OR_RESPONSE") out.push(normalizeEconomicHypothesis({
    id:"funnel-delivery-response-gap",business_model:"verified outbound-to-conversation conversion",hypothesis:"Turn already-sent commercial outreach into verified delivery and a buyer response before generating more low-signal outreach.",target:"existing sent commercial pipeline",execution_lane:"REVENUE",source_ref:"funnel-delivery-response-gap",
    probability_of_sale:.48,time_to_cash_hours:24,evidence_strength:.96,confidence:.92,novelty:.28,risk:.07,reversibility:.99,
    rationale_summary:"Messages marked sent have not yet produced sufficient downstream delivery or response evidence.",
    next_step:"Verify deliverability, prioritize the best existing buyer thread, and only count response, quote/order intent or settlement as progress."
  }));
  if (bottleneck==="OUTBOUND") out.push(normalizeEconomicHypothesis({
    id:"funnel-outbound-gap",business_model:"proposal-to-verified-contact conversion",hypothesis:"Move the strongest prepared proposal through the existing quality and sender gates to a verifiable buyer touch.",target:"approved proposal inventory",execution_lane:"REVENUE",source_ref:"funnel-outbound-gap",
    probability_of_sale:.4,time_to_cash_hours:30,evidence_strength:.88,confidence:.84,novelty:.22,risk:.08,reversibility:.98,
    rationale_summary:"Prepared proposals exist but the funnel has not advanced into verifiable outbound conversation.",
    next_step:"Use the highest-evidence proposal and preserve all existing sender and human-binding gates."
  }));
  if (bottleneck==="PROPOSAL") out.push(normalizeEconomicHypothesis({
    id:"funnel-proposal-gap",business_model:"verified demand to proposal",hypothesis:"Convert the strongest qualified commercial candidate into one precise non-binding proposal instead of widening discovery.",target:"strongest qualified buyer evidence",execution_lane:"REVENUE",source_ref:"funnel-proposal-gap",
    probability_of_sale:.46,time_to_cash_hours:36,evidence_strength:.86,confidence:.82,novelty:.2,risk:.08,reversibility:.99,
    rationale_summary:"Commercial candidates exist but the funnel is not producing a proposal close enough to transact.",
    next_step:"Prepare one evidence-grounded offer with explicit outcome, scope and existing fixed price."
  }));
  if (bottleneck==="CLOSE") out.push(normalizeEconomicHypothesis({
    id:"funnel-close-gap",business_model:"buyer-response-to-cash",hypothesis:"Prioritize the strongest verified buyer response and reduce it to the shortest truthful path to checkout and settlement.",target:"existing responding buyer",execution_lane:"REVENUE",source_ref:"funnel-close-gap",
    probability_of_sale:.68,time_to_cash_hours:12,evidence_strength:.98,confidence:.92,novelty:.12,risk:.08,reversibility:.98,
    rationale_summary:"The funnel already contains downstream buyer evidence, so closing dominates additional discovery.",
    next_step:"Resolve the buyer's exact scope or question and present the existing checkout path without changing price or binding terms."
  }));
  if (bottleneck==="REPEAT_WINNER") out.push(normalizeEconomicHypothesis({
    id:"funnel-repeat-winner",business_model:"replicate verified economic winner",hypothesis:"Use settlement and conversion memory to replicate the highest-performing proven offer against similar current demand.",target:"similar verified buyer demand",execution_lane:"REVENUE",source_ref:"funnel-repeat-winner",
    probability_of_sale:.72,time_to_cash_hours:18,evidence_strength:1,confidence:.94,novelty:.16,risk:.06,reversibility:.98,
    rationale_summary:"Verified settlement evidence exists, so the brain should exploit a proven path while retaining bounded exploration.",
    next_step:"Rank strategies by realized reward per attempt and target the nearest matching verified demand."
  }));
  for (const x of obs.ventureIdeas || []) out.push(normalizeEconomicHypothesis({id:`venture-${x.id}`,business_model:x.product,hypothesis:`Validate and package ${x.product} against the observed demand evidence, then expose the smallest sellable version through existing LUMEN channels.`,target:x.title,execution_lane:"VENTURE",source_ref:x.id,probability_of_sale:Math.min(.75,.2+num(x.score)*.55),time_to_cash_hours:72,evidence_strength:Math.min(1,num(x.score)),confidence:Math.min(.85,.3+num(x.score)*.55),novelty:.78,risk:.28,reversibility:.95,rationale_summary:"Venture Hunter found evidence-backed demand outside the current fixed offer set.",next_step:"Use Founder/Builder/Launcher to prepare a zero-capital reversible market test."}));
  for (const x of obs.supplierQueue || []) if ((!Array.isArray(x.blockers)||x.blockers.length===0) && x.profit>0) out.push(normalizeEconomicHypothesis({id:`commerce-${x.sku}`,business_model:"connected-supplier intermediary resale",hypothesis:`Expose supplier item ${x.title||x.sku} using live stock/cost/price validation without purchasing inventory.`,target:x.title||x.sku,execution_lane:"COMMERCE",source_ref:x.sku,expected_profit_usd:0,probability_of_sale:.3,time_to_cash_hours:48,evidence_strength:Math.min(1,.45+x.rank/200),confidence:.62,novelty:.35,risk:.22,reversibility:.92,rationale_summary:"A connected supplier candidate has positive projected economics and no stored blockers.",next_step:"Revalidate live supplier economics and publish only if existing bounded launch policy passes."}));
  const hot=(obs.proposals||[]).find(x=>x.status==="RESPONDED") || (obs.proposals||[]).find(x=>x.status==="SENT"||x.status==="APPROVED");
  if (hot) out.push(normalizeEconomicHypothesis({id:`revenue-${hot.id}`,business_model:"close existing qualified demand",hypothesis:`Convert existing proposal ${hot.id} toward a verified settlement before expanding low-signal activity.`,target:hot.id,execution_lane:"REVENUE",source_ref:hot.id,probability_of_sale:hot.status==="RESPONDED"?.62:.36,time_to_cash_hours:24,evidence_strength:hot.status==="RESPONDED"?.85:.65,confidence:.78,novelty:.15,risk:.12,reversibility:.96,rationale_summary:"Existing downstream commercial inventory is closer to verified revenue than cold discovery.",next_step:"Run Revenue Loop/Response Closer in non-binding mode and preserve human gates."}));
  out.push(normalizeEconomicHypothesis({id:"explore-open",business_model:"open-ended market discovery",hypothesis:"Combine current demand signals, distribution channels and LUMEN capabilities to discover a monetization path not represented by the existing catalog.",target:"new external demand",execution_lane:"EXPLORE",source_ref:"open-exploration",probability_of_sale:.16,time_to_cash_hours:96,evidence_strength:.28,confidence:.42,novelty:1,risk:.3,reversibility:.97,rationale_summary:"Deliberate exploration prevents the system from only optimizing yesterday's business models.",next_step:"Search, formulate and test one zero-capital hypothesis with measurable buyer feedback."}));
  return out;
}

function extractText(r){ if(typeof r==="string")return r; if(typeof r?.response==="string")return r.response; if(typeof r?.result==="string")return r.result; return r?.choices?.[0]?.message?.content || ""; }
function parseJson(text){ const s=String(text||"").replace(/^```(?:json)?\s*/i,"").replace(/\s*```$/,""); const a=s.indexOf("{"); const b=s.lastIndexOf("}"); if(a<0||b<=a) throw new Error("brain_model_json_missing"); return JSON.parse(s.slice(a,b+1)); }

async function aiHypotheses(env, obs) {
  if (!env?.AI?.run) return [];
  const prompt = `You are LUMEN's single economic strategy brain. Current commercial funnel bottleneck: ${obs?.funnel?.bottleneck || "UNKNOWN"}. Generate up to ${MAX_AI_HYPOTHESES} concrete monetization hypotheses from the supplied evidence and currently available capabilities. Attack the current bottleneck first unless stronger downstream evidence already exists. Sending or preparing a message alone is NOT economic progress: prefer verified demand, verified delivery, buyer response, quote/order intent and verified settlement. BUSINESS MODEL IS OPEN ENDED: do not limit yourself to the existing catalog or named archetypes. You may combine demand, information, brokerage, commerce, APIs, x402, services, referrals or genuinely new patterns when evidence supports them. Do not invent evidence, buyers, settlements, prices or capabilities. Every autonomous test must require zero outgoing capital, be reversible, non-binding and legal. Never propose purchases, payments, debt, contracts, secret access or price mutation. execution_lane is only the existing specialist tool family that can validate the hypothesis: REVENUE|VENTURE|COMMERCE|TRAVEL|DISCOVERY|EXPLORE|HOLD. Return ONLY JSON {"hypotheses":[{business_model,hypothesis,target,execution_lane,source_ref,expected_profit_usd,probability_of_sale,time_to_cash_hours,capital_required_usd,risk,reversibility,evidence_strength,confidence,novelty,rationale_summary,next_step}]}. Do not output chain-of-thought; rationale_summary must be one evidence-based sentence.`;
  try {
    const r=await env.AI.run(MODEL,{messages:[{role:"system",content:prompt},{role:"user",content:JSON.stringify(obs).slice(0,18000)}],temperature:.35,max_completion_tokens:580,chat_template_kwargs:{enable_thinking:false}});
    const data=parseJson(extractText(r));
    return (Array.isArray(data?.hypotheses)?data.hypotheses:[]).slice(0,MAX_AI_HYPOTHESES).map((x,i)=>normalizeEconomicHypothesis({...x,id:`ai-${Date.now()}-${i}`}));
  } catch { return []; }
}

async function persistHypotheses(env, cycleKey, hypotheses) {
  for (const h of hypotheses) await env.DB.prepare("INSERT OR REPLACE INTO lumen_brain_hypotheses(id,cycle_key,created_at,execution_lane,business_model,hypothesis,source_ref,score,novelty,evidence_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
    .bind(h.id,cycleKey,now(),h.executionLane,h.businessModel,h.hypothesis,h.sourceRef,h.score,h.novelty,JSON.stringify({confidence:h.confidence,evidenceStrength:h.evidenceStrength,risk:h.risk,reversibility:h.reversibility,nextStep:h.nextStep}),VERSION).run();
}

async function persistMission(env, cycleKey, mission, observation) {
  const id=`brain-${cycleKey}`.replace(/[^a-zA-Z0-9_-]/g,"-");
  await env.DB.prepare("INSERT OR REPLACE INTO lumen_brain_missions(id,cycle_key,created_at,updated_at,status,selection_mode,execution_lane,business_model,hypothesis,target,source_ref,score,confidence,expected_profit_usd,probability_sale,time_to_cash_hours,evidence_strength,novelty,risk,reversibility,rationale_summary,next_step,evidence_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(id,cycleKey,now(),now(),"ACTIVE",mission.selectionMode||"EXPLOIT",mission.executionLane,mission.businessModel,mission.hypothesis,mission.target,mission.sourceRef,mission.score,mission.confidence,mission.expectedProfitUsd,mission.probabilityOfSale,mission.timeToCashHours,mission.evidenceStrength,mission.novelty,mission.risk,mission.reversibility,mission.rationaleSummary,mission.nextStep,JSON.stringify({verifiedSettlementCount:observation.verifiedSettlementCount,proposalCount:observation.proposals.length,ventureIdeaCount:observation.ventureIdeas.length,supplierCandidateCount:observation.supplierQueue.length,funnel:observation.funnel,strategyKey:strategyKey(mission)}),VERSION).run();
  await env.DB.prepare("INSERT INTO lumen_brain_learning(strategy_key,attempts,updated_at) VALUES(?,1,?) ON CONFLICT(strategy_key) DO UPDATE SET attempts=attempts+1,updated_at=excluded.updated_at").bind(strategyKey(mission),now()).run();
  return id;
}

async function evaluatePreviousMission(env, excludeCycleKey="") {
  const m=await env.DB.prepare("SELECT * FROM lumen_brain_missions WHERE status='ACTIVE' AND cycle_key<>? ORDER BY created_at DESC LIMIT 1").bind(excludeCycleKey).first().catch(()=>null);
  if(!m) return null;
  const current=await collectFunnel(env);
  const baseline=parse(m.evidence_json,{}).funnel || {};
  const delta={
    qualifiedCommercialCandidates:Math.max(0,current.qualifiedCommercialCandidates-num(baseline.qualifiedCommercialCandidates,0)),
    proposals:Math.max(0,current.proposals-num(baseline.proposals,0)),
    sent:Math.max(0,current.sent-num(baseline.sent,0)),
    verifiedResponses:Math.max(0,current.verifiedResponses-num(baseline.verifiedResponses,0)),
    negotiations:Math.max(0,current.negotiations-num(baseline.negotiations,0)),
    verifiedSettlements:Math.max(0,current.verifiedSettlements-num(baseline.verifiedSettlements,0)),
    delivered:Math.max(0,current.delivered-num(baseline.delivered,0)),
    verifiedRevenueUsd:Math.max(0,current.verifiedRevenueUsd-num(baseline.verifiedRevenueUsd,0))
  };
  let reward=delta.verifiedSettlements*100 + Math.min(60,delta.verifiedRevenueUsd) + delta.negotiations*45 + delta.verifiedResponses*28 + delta.delivered*12 + delta.proposals*3 + delta.qualifiedCommercialCandidates*2;
  const outcome={funnelBefore:baseline,funnelAfter:current,funnelDelta:delta,sentIsNotSuccess:true,currentBottleneck:current.bottleneck};
  if(m.execution_lane==="REVENUE" && m.source_ref && !String(m.source_ref).startsWith("funnel-")){
    const settled=await env.DB.prepare("SELECT r.id receipt_id FROM lumen_x402_revenue_bridge b JOIN lumen_x402_receipts r ON r.id=b.receipt_id WHERE b.proposal_id=? AND r.status='settled_verified' LIMIT 1").bind(m.source_ref).first().catch(()=>null);
    const p=await env.DB.prepare("SELECT status FROM lumen_proposal_drafts WHERE proposal_id=? LIMIT 1").bind(m.source_ref).first().catch(()=>null);
    if(settled){ reward=Math.max(reward,100); outcome.verifiedSettlement=true; outcome.receiptId=settled.receipt_id; }
    else if(p?.status==="RESPONDED"){ reward=Math.max(reward,28); outcome.commercialResponse=true; }
    else if(p?.status==="SENT"){ outcome.proposalSent=true; }
  } else if(m.execution_lane==="COMMERCE" && m.source_ref && !String(m.source_ref).startsWith("funnel-")){
    const launch=await env.DB.prepare("SELECT state FROM lumen_supplier_launches WHERE sku=? ORDER BY created_at DESC LIMIT 1").bind(m.source_ref).first().catch(()=>null);
    if(launch){
      const sold=/SOLD|PAID|ORDER/i.test(String(launch.state));
      reward=Math.max(reward,sold?80:4);
      outcome.supplierLaunchState=launch.state;
    }
  }
  if(reward<=0){ reward=-2; outcome.stagnant=true; outcome.learning="No downstream economic progress; reduce this strategy unless new evidence appears."; }
  await env.DB.prepare("UPDATE lumen_brain_missions SET status='MEASURED',reward=?,outcome_json=?,updated_at=? WHERE id=?").bind(reward,JSON.stringify(outcome),now(),m.id).run();
  const key=`${m.execution_lane}:${m.business_model}`.slice(0,220);
  await env.DB.prepare("UPDATE lumen_brain_learning SET reward=reward+?,verified_settlements=verified_settlements+?,commercial_responses=commercial_responses+?,published_offers=published_offers+?,updated_at=? WHERE strategy_key=?")
    .bind(reward,delta.verifiedSettlements,outcome.commercialResponse?Math.max(1,delta.verifiedResponses):delta.verifiedResponses,outcome.supplierLaunchState?1:0,now(),key).run();
  return {missionId:m.id,reward,outcome};
}

export async function runUnifiedEconomicBrain(env, options={}) {
  await ensureSchema(env);
  const scheduled=Number(options.scheduledTime||Date.now());
  const cycleKey=clean(options.cycleKey || `${Math.floor(scheduled/3600000)}`,80);
  const existing=await env.DB.prepare("SELECT * FROM lumen_brain_missions WHERE cycle_key=? LIMIT 1").bind(cycleKey).first();
  if(existing) return {ok:true,reused:true,version:VERSION,mission:rowToMission(existing),plan:specialistPlanForMission({executionLane:existing.execution_lane}),funnel:await collectFunnel(env)};
  const claim=await env.DB.prepare("INSERT OR IGNORE INTO lumen_brain_leases(cycle_key,claimed_at,owner) VALUES(?,?,?)").bind(cycleKey,now(),clean(options.trigger||"scheduled",80)).run();
  if(Number(claim?.meta?.changes)!==1){
    const winner=await env.DB.prepare("SELECT * FROM lumen_brain_missions WHERE cycle_key=? LIMIT 1").bind(cycleKey).first();
    return winner?{ok:true,reused:true,version:VERSION,mission:rowToMission(winner),plan:specialistPlanForMission({executionLane:winner.execution_lane}),funnel:await collectFunnel(env)}:{ok:false,reason:"brain_cycle_already_claimed"};
  }
  const measuredPrevious=await evaluatePreviousMission(env,cycleKey);
  const observation=await collectObservation(env);
  await persistFunnelSnapshot(env,cycleKey,observation.funnel);
  const deterministic=deterministicHypotheses(observation);
  const generated=await aiHypotheses(env,observation);
  const memoryByKey=new Map((observation.learningMemory||[]).map(x=>[clean(x.strategy_key,220),x]));
  const context={bottleneck:observation.funnel.bottleneck};
  const hypotheses=[...generated,...deterministic].map(h=>{
    const memory=memoryByKey.get(strategyKey(h)) || {};
    const adjustment=learningAdjustment(h,memory,context);
    return {...h,score:scoreEconomicHypothesis(h,{...context,memory}),learningAdjustment:adjustment,priorAttempts:num(memory.attempts,0),priorReward:num(memory.reward,0)};
  });
  await persistHypotheses(env,cycleKey,hypotheses);
  const mission=chooseEconomicMission(hypotheses,cycleKey,context);
  const missionId=await persistMission(env,cycleKey,mission,observation);
  return {ok:true,version:VERSION,mission:{...mission,id:missionId},plan:specialistPlanForMission(mission),hypothesesConsidered:hypotheses.length,aiHypotheses:generated.length,measuredPrevious,observationSummary:{verifiedSettlements:observation.verifiedSettlementCount,ventureIdeas:observation.ventureIdeas.length,proposals:observation.proposals.length,supplierCandidates:observation.supplierQueue.length,funnel:observation.funnel}};
}

function rowToMission(r){ return {id:r.id,cycleKey:r.cycle_key,status:r.status,selectionMode:r.selection_mode,executionLane:r.execution_lane,businessModel:r.business_model,hypothesis:r.hypothesis,target:r.target,sourceRef:r.source_ref,score:num(r.score),confidence:num(r.confidence),expectedProfitUsd:num(r.expected_profit_usd),probabilityOfSale:num(r.probability_sale),timeToCashHours:num(r.time_to_cash_hours),evidenceStrength:num(r.evidence_strength),novelty:num(r.novelty),risk:num(r.risk),reversibility:num(r.reversibility),rationaleSummary:r.rationale_summary,nextStep:r.next_step,reward:num(r.reward),outcome:parse(r.outcome_json,null),updatedAt:r.updated_at}; }

export async function getUnifiedBrainStatus(env) {
  await ensureSchema(env);
  const current=await env.DB.prepare("SELECT * FROM lumen_brain_missions ORDER BY created_at DESC LIMIT 1").first();
  const history=await rows(env,"SELECT id,created_at,status,selection_mode,execution_lane,business_model,score,reward,rationale_summary,outcome_json FROM lumen_brain_missions ORDER BY created_at DESC LIMIT 12");
  const learning=await rows(env,"SELECT * FROM lumen_brain_learning ORDER BY reward DESC,attempts DESC LIMIT 12");
  const funnel=await collectFunnel(env);
  const funnelHistory=await rows(env,"SELECT cycle_key,created_at,qualified_candidates,proposals,sent,verified_responses,negotiations,verified_settlements,delivered,verified_revenue_usd,bottleneck FROM lumen_brain_funnel_memory ORDER BY created_at DESC LIMIT 24");
  return {ok:true,version:VERSION,policy:UNIFIED_BRAIN_POLICY,currentMission:current?rowToMission(current):null,currentFunnel:funnel,history:history.map(x=>({...x,outcome:parse(x.outcome_json,null)})),learning,funnelHistory};
}
