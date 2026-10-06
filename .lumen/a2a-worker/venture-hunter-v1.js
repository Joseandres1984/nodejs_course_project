const NOW = () => new Date().toISOString();
const VERSION = "1.2-microincome-scale-frontier";
const MAX_ARCHETYPES_PER_SIGNAL = 3;

const ARCHETYPES = [
  { id:"monitoring", family:"recurring_monitoring", priority:92, rx:/monitor|alert|watch|track|price|status|availability|change detection/i, product:"paid monitoring + alert service", build:"watcher/API + scheduled checks + subscription or x402 delivery", revenue:"subscription_or_pay_per_alert", margin:0.88, recurring:true, novelty:0.48 },
  { id:"research", family:"intelligence", priority:86, rx:/research|supplier|vendor|source|market|compare|procure|sourcing|shortlist/i, product:"on-demand research / market intelligence report", build:"research pipeline + evidence pack + paid delivery", revenue:"fixed_fee_report_or_x402", margin:0.90, recurring:false, novelty:0.42 },
  { id:"document", family:"automation_service", priority:82, rx:/document|pdf|invoice|form|extract|convert|summari|ocr|classification/i, product:"document transformation microservice", build:"upload/API + transformation + guarded paid delivery", revenue:"pay_per_document_or_bundle", margin:0.93, recurring:true, novelty:0.44 },
  { id:"lead_intel", family:"sales_intelligence", priority:88, rx:/lead|buyer|prospect|contact|sales|outreach|demand signal|intent/i, product:"buyer-intent / qualified-lead intelligence", build:"signal collector + qualification + paid feed/report", revenue:"subscription_feed_or_per_lead", margin:0.86, recurring:true, novelty:0.52 },
  { id:"tender", family:"procurement_intelligence", priority:96, rx:/tender|bid|rfq|request for quote|procurement notice|licitaci|pliego|purchase order/i, product:"tender / RFQ intelligence and opportunity brief", build:"public-procurement watcher + qualification + deadline/scope brief", revenue:"subscription_or_per_opportunity", margin:0.91, recurring:true, novelty:0.58 },
  { id:"supplier_verify", family:"trust_intelligence", priority:93, rx:/supplier verification|vendor verification|due diligence|verify supplier|background check|factory|distributor/i, product:"supplier verification snapshot", build:"public-source evidence checks + risk summary + paid report/API", revenue:"pay_per_check_or_api_call", margin:0.92, recurring:true, novelty:0.54 },
  { id:"quote_benchmark", family:"pricing_intelligence", priority:95, rx:/quote|quotation|price check|benchmark|overpriced|cost comparison|sanity check|cotiz/i, product:"quote sanity / price benchmarking service", build:"market-reference collector + comparison + evidence report", revenue:"pay_per_quote_check", margin:0.94, recurring:true, novelty:0.56 },
  { id:"export_intel", family:"trade_intelligence", priority:90, rx:/export|importer|distributor|international buyer|trade|customs|market entry|foreign market/i, product:"export-market / importer intelligence brief", build:"trade-signal search + buyer/distributor shortlist + market note", revenue:"fixed_fee_report_or_subscription", margin:0.89, recurring:false, novelty:0.66 },
  { id:"data_api", family:"agent_native_api", priority:97, rx:/api|dataset|data feed|json|endpoint|lookup|enrich|scrape|extract data/i, product:"paid data/API endpoint for agents", build:"single-purpose endpoint + metering + x402 pay-per-call", revenue:"x402_pay_per_call", margin:0.95, recurring:true, novelty:0.78 },
  { id:"agent_utility", family:"agent_native_api", priority:99, rx:/agent|a2a|x402|mcp|tool|utility|function|machine customer|automation agent/i, product:"agent-native paid utility", build:"A2A/API capability + machine-readable catalog + x402 pay-per-use", revenue:"x402_pay_per_call_or_task", margin:0.96, recurring:true, novelty:0.86 },
  { id:"referral", family:"performance_revenue", priority:78, rx:/affiliate|referral|recommend|booking|commission|partner offer|introduced by/i, product:"qualified referral / affiliate routing", build:"intent detection + compliant partner routing + attribution", revenue:"referral_commission", margin:0.84, recurring:true, novelty:0.62 },
  { id:"brokerage", family:"performance_revenue", priority:91, rx:/broker|intermediary|match buyer|match supplier|commission|source supplier|procurement service/i, product:"buyer-supplier brokerage without inventory", build:"verified demand + supplier match + non-binding commercial handoff", revenue:"success_fee_or_commission", margin:0.82, recurring:false, novelty:0.72 },
  { id:"matching", family:"marketplace_matching", priority:84, rx:/match|marketplace|connect buyer|connect vendor|request board|directory|network/i, product:"curated buyer-supplier matching service", build:"two-sided matching + qualification + paid introduction or intelligence", revenue:"paid_introduction_or_subscription", margin:0.83, recurring:true, novelty:0.69 },
  { id:"micro_saas", family:"software_product", priority:85, rx:/workflow|manual process|spreadsheet|repetitive|dashboard|scheduler|reminder|small business/i, product:"narrow micro-SaaS solving one repeated workflow", build:"single-purpose web/API workflow + existing payment rail", revenue:"monthly_subscription_or_usage", margin:0.90, recurring:true, novelty:0.79 },
  { id:"automation", family:"automation_service", priority:87, rx:/automate|automation|manual task|back office|ops|operations|reconcile|reporting/i, product:"workflow automation as a service", build:"bounded automation + audit trail + paid setup/output", revenue:"setup_fee_plus_recurring_service", margin:0.88, recurring:true, novelty:0.64 },
  { id:"local_demand", family:"local_intelligence", priority:80, rx:/local|nearby|store|shop|restaurant|service provider|contractor|regional|city|municipal/i, product:"local demand / supplier intelligence", build:"local signal discovery + qualification + paid lead/report", revenue:"per_lead_or_subscription", margin:0.84, recurring:true, novelty:0.68 },
  { id:"content_data", family:"digital_product", priority:76, rx:/guide|database|directory|list|catalog|content|knowledge base|reference|template/i, product:"curated paid dataset / knowledge product", build:"structured dataset + freshness checks + gated download/API", revenue:"one_time_sale_subscription_or_api", margin:0.94, recurring:true, novelty:0.72 },
  { id:"template", family:"digital_product", priority:68, rx:/template|checklist|playbook|worksheet|prompt|form pack|document pack/i, product:"specialized template / playbook pack", build:"evidence-backed reusable digital asset + guarded checkout", revenue:"one_time_digital_sale", margin:0.97, recurring:false, novelty:0.58 },
  { id:"localization", family:"language_service", priority:70, rx:/translate|translation|localize|localization|language|spanish|english|portuguese/i, product:"specialized translation / localization service", build:"document/API intake + domain-aware transformation + paid delivery", revenue:"pay_per_document_or_word_bundle", margin:0.87, recurring:true, novelty:0.46 },
  { id:"travel", family:"referral_intelligence", priority:72, rx:/travel|hotel|flight|tour|booking|trip|activity/i, product:"travel intelligence / referral service", build:"search + comparison + attributable partner handoff", revenue:"affiliate_or_referral_commission", margin:0.72, recurring:true, novelty:0.50 },
  { id:"commerce", family:"commerce_intelligence", priority:74, rx:/shop|store|product|catalog|stock|inventory|ecommerce|commerce|merchandising/i, product:"commerce intelligence / merchandising service", build:"catalog watcher + market comparison + paid report/API", revenue:"subscription_report_or_api", margin:0.78, recurring:true, novelty:0.48 }
];

const CUSTOM_ARCHETYPE = {
  id:"custom", family:"open_ended", priority:50,
  product:"narrow paid information/service product",
  build:"single-purpose landing/API + existing payment rail + measurable delivery",
  revenue:"fixed_fee_or_pay_per_use",
  margin:0.85, recurring:false, novelty:0.9
};

const SCALE_PROFILES = {
  monitoring:{ event:"alert_or_check", unitRevenueTargetUsd:1, repeatability:.96, distributionLeverage:.90, marginalCostEfficiency:.94, volumeClass:"HIGH" },
  research:{ event:"paid_report", unitRevenueTargetUsd:7, repeatability:.62, distributionLeverage:.60, marginalCostEfficiency:.82, volumeClass:"MEDIUM" },
  document:{ event:"document_processed", unitRevenueTargetUsd:1, repeatability:.94, distributionLeverage:.90, marginalCostEfficiency:.95, volumeClass:"HIGH" },
  lead_intel:{ event:"qualified_signal_or_lead", unitRevenueTargetUsd:2, repeatability:.90, distributionLeverage:.86, marginalCostEfficiency:.91, volumeClass:"HIGH" },
  tender:{ event:"qualified_tender_or_rfq", unitRevenueTargetUsd:3, repeatability:.86, distributionLeverage:.84, marginalCostEfficiency:.91, volumeClass:"HIGH" },
  supplier_verify:{ event:"supplier_check", unitRevenueTargetUsd:5, repeatability:.88, distributionLeverage:.88, marginalCostEfficiency:.93, volumeClass:"HIGH" },
  quote_benchmark:{ event:"quote_check", unitRevenueTargetUsd:5, repeatability:.90, distributionLeverage:.88, marginalCostEfficiency:.94, volumeClass:"HIGH" },
  export_intel:{ event:"market_or_buyer_brief", unitRevenueTargetUsd:9, repeatability:.72, distributionLeverage:.68, marginalCostEfficiency:.86, volumeClass:"MEDIUM" },
  data_api:{ event:"api_call", unitRevenueTargetUsd:1, repeatability:1, distributionLeverage:1, marginalCostEfficiency:.98, volumeClass:"VERY_HIGH" },
  agent_utility:{ event:"agent_task_or_tool_call", unitRevenueTargetUsd:1, repeatability:1, distributionLeverage:1, marginalCostEfficiency:.98, volumeClass:"VERY_HIGH" },
  referral:{ event:"attributed_conversion", unitRevenueTargetUsd:5, repeatability:.92, distributionLeverage:.94, marginalCostEfficiency:.97, volumeClass:"VERY_HIGH" },
  brokerage:{ event:"closed_match", unitRevenueTargetUsd:25, repeatability:.55, distributionLeverage:.66, marginalCostEfficiency:.86, volumeClass:"MEDIUM" },
  matching:{ event:"qualified_introduction", unitRevenueTargetUsd:5, repeatability:.84, distributionLeverage:.90, marginalCostEfficiency:.92, volumeClass:"HIGH" },
  micro_saas:{ event:"paid_usage_or_active_subscription", unitRevenueTargetUsd:1, repeatability:.98, distributionLeverage:.96, marginalCostEfficiency:.96, volumeClass:"VERY_HIGH" },
  automation:{ event:"automated_task", unitRevenueTargetUsd:1, repeatability:.95, distributionLeverage:.84, marginalCostEfficiency:.92, volumeClass:"HIGH" },
  local_demand:{ event:"qualified_local_lead", unitRevenueTargetUsd:2, repeatability:.86, distributionLeverage:.78, marginalCostEfficiency:.90, volumeClass:"HIGH" },
  content_data:{ event:"dataset_access_or_download", unitRevenueTargetUsd:1, repeatability:.94, distributionLeverage:.93, marginalCostEfficiency:.98, volumeClass:"VERY_HIGH" },
  template:{ event:"digital_sale", unitRevenueTargetUsd:3, repeatability:.82, distributionLeverage:.91, marginalCostEfficiency:.99, volumeClass:"HIGH" },
  localization:{ event:"document_or_text_job", unitRevenueTargetUsd:2, repeatability:.91, distributionLeverage:.86, marginalCostEfficiency:.92, volumeClass:"HIGH" },
  travel:{ event:"attributed_booking_or_partner_conversion", unitRevenueTargetUsd:5, repeatability:.92, distributionLeverage:.96, marginalCostEfficiency:.98, volumeClass:"VERY_HIGH" },
  commerce:{ event:"paid_lookup_or_conversion", unitRevenueTargetUsd:2, repeatability:.84, distributionLeverage:.82, marginalCostEfficiency:.88, volumeClass:"HIGH" },
  custom:{ event:"paid_event", unitRevenueTargetUsd:1, repeatability:.65, distributionLeverage:.58, marginalCostEfficiency:.82, volumeClass:"MEDIUM" }
};

function scaleProfile(archetype) {
  return SCALE_PROFILES[archetype.id] || SCALE_PROFILES.custom;
}

function textOf(row = {}) {
  return Object.values(row).filter((v) => typeof v === "string").join(" ").slice(0, 7000);
}

function num(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function clean(v, limit=500) {
  return String(v ?? "").replace(/\s+/g," ").trim().slice(0,limit);
}

function archetypesFor(text) {
  const matched = ARCHETYPES.filter((x) => x.rx.test(text));
  if (!matched.length) return [CUSTOM_ARCHETYPE];
  return matched
    .sort((a,b) => b.priority-a.priority || b.novelty-a.novelty)
    .slice(0, MAX_ARCHETYPES_PER_SIGNAL);
}

function scoreSignal(row, text, archetype, saturationCount=0) {
  const demand = Math.min(1,
    0.28 +
    (text.length > 120 ? 0.12 : 0) +
    (/need|want|looking|request|buy|urgent|quote|rfq|tender|seeking|procure|require/i.test(text) ? 0.30 : 0) +
    Math.min(0.30, num(row.score || row.priority_score || row.intent_score) / 350)
  );
  const urgency = /urgent|asap|today|now|deadline|immediate|closing date|due date/i.test(text) ? 0.92 : 0.52;
  const evidence = Math.min(1,
    0.34 +
    (row.url || row.source_url ? 0.20 : 0) +
    (row.buyer || row.company || row.domain ? 0.16 : 0) +
    (text.length > 250 ? 0.15 : 0) +
    (/rfq|tender|request|looking|need|seeking|buy/i.test(text) ? 0.10 : 0)
  );
  const buildEase = archetype.id === "custom" ? 0.52 : (archetype.family === "agent_native_api" ? 0.88 : 0.80);
  const recurrence = archetype.recurring ? 0.88 : 0.58;
  const novelty = num(archetype.novelty,0.5);
  const scale=scaleProfile(archetype);
  const scalePotential=Number(((
    scale.repeatability*.30 +
    scale.distributionLeverage*.28 +
    scale.marginalCostEfficiency*.24 +
    recurrence*.18
  ) * (.35 + evidence*.65)).toFixed(4));
  const saturationPenalty = Math.min(0.14, Math.max(0,saturationCount) * 0.012);
  const score =
    demand * 0.25 +
    urgency * 0.08 +
    evidence * 0.19 +
    buildEase * 0.11 +
    archetype.margin * 0.12 +
    recurrence * 0.07 +
    novelty * 0.06 +
    scalePotential * 0.12 -
    saturationPenalty;
  return {
    demand, urgency, evidence, buildEase,
    margin: archetype.margin,
    recurrence,
    novelty,
    monetizableEvent:scale.event,
    unitRevenueTargetUsd:scale.unitRevenueTargetUsd,
    repeatability:scale.repeatability,
    distributionLeverage:scale.distributionLeverage,
    marginalCostEfficiency:scale.marginalCostEfficiency,
    volumeClass:scale.volumeClass,
    scalePotential,
    tenThousandEventRevenueTargetUsd:Number((scale.unitRevenueTargetUsd*10000).toFixed(2)),
    scaleTruth:"target_scenario_not_realized_revenue",
    saturationPenalty:Number(saturationPenalty.toFixed(4)),
    score: Number(Math.max(0,Math.min(1,score)).toFixed(4))
  };
}

async function ensureSchema(db) {
  if (!db?.prepare) return;
  await db.prepare(`CREATE TABLE IF NOT EXISTS lumen_venture_hunter_ideas (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_ref TEXT,
    title TEXT NOT NULL,
    product TEXT NOT NULL,
    build_plan TEXT NOT NULL,
    revenue_model TEXT,
    monetization_family TEXT,
    score REAL NOT NULL,
    status TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    policy_json TEXT NOT NULL
  )`).run();

  for (const sql of [
    "ALTER TABLE lumen_venture_hunter_ideas ADD COLUMN revenue_model TEXT",
    "ALTER TABLE lumen_venture_hunter_ideas ADD COLUMN monetization_family TEXT"
  ]) {
    try { await db.prepare(sql).run(); }
    catch (error) {
      if (!/duplicate column|already exists/i.test(String(error?.message || error))) throw error;
    }
  }
}

async function readSignals(db, limit = 80) {
  if (!db?.prepare) return [];
  const queries = [
    ["source-intelligence", "SELECT * FROM lumen_source_observations ORDER BY rowid DESC LIMIT ?"],
    ["opportunity", "SELECT * FROM lumen_opportunities ORDER BY rowid DESC LIMIT ?"],
    ["market-hunter", "SELECT * FROM lumen_market_candidates ORDER BY rowid DESC LIMIT ?"],
    ["proposal", "SELECT * FROM lumen_proposals ORDER BY rowid DESC LIMIT ?"],
    ["service-pipeline", "SELECT * FROM lumen_service_sales_pipeline ORDER BY rowid DESC LIMIT ?"]
  ];
  const out = [];
  for (const [kind, sql] of queries) {
    try {
      const res = await db.prepare(sql).bind(limit).all();
      for (const row of res?.results || []) out.push({ kind, row });
    } catch (_) {}
  }
  return out.slice(0, limit);
}

async function recentFamilyCounts(db) {
  const counts = new Map();
  if (!db?.prepare) return counts;
  try {
    const res = await db.prepare("SELECT monetization_family,evidence_json FROM lumen_venture_hunter_ideas ORDER BY created_at DESC LIMIT 160").all();
    for (const row of res?.results || []) {
      let family=clean(row.monetization_family,80);
      if (!family) {
        try { family=clean(JSON.parse(row.evidence_json || "{}")?.monetizationFamily,80); } catch {}
      }
      if (family) counts.set(family,(counts.get(family)||0)+1);
    }
  } catch {}
  return counts;
}

function makeIdea(signal, signalIndex, archetype, variantIndex, saturationCount=0) {
  const text = textOf(signal.row);
  if (!text.trim()) return null;
  const metrics = scoreSignal(signal.row, text, archetype, saturationCount);
  const sourceRef = clean(signal.row.id || signal.row.url || signal.row.source_url || `${signal.kind}-${signalIndex}`,220);
  const slug = `${archetype.id}-${sourceRef}-${variantIndex}`.replace(/[^a-zA-Z0-9_-]/g, "-").slice(0, 110);
  return {
    id: `vh1-${slug}`,
    createdAt: NOW(),
    sourceKind: signal.kind,
    sourceRef,
    title: `Opportunity: ${archetype.product}`,
    product: archetype.product,
    buildPlan: archetype.build,
    revenueModel: archetype.revenue,
    monetizationFamily: archetype.family,
    metrics,
    status: metrics.score >= 0.72 ? "BUILD_CANDIDATE" : metrics.score >= 0.60 ? "VALIDATE" : "WATCH",
    evidence: {
      excerpt: text.slice(0, 900),
      source: signal.kind,
      archetypeId: archetype.id,
      monetizationFamily: archetype.family,
      revenueModel: archetype.revenue,
      recurringPotential:Boolean(archetype.recurring),
      marginAssumption:archetype.margin,
      monetizableEvent:metrics.monetizableEvent,
      unitRevenueTargetUsd:metrics.unitRevenueTargetUsd,
      repeatability:metrics.repeatability,
      distributionLeverage:metrics.distributionLeverage,
      marginalCostEfficiency:metrics.marginalCostEfficiency,
      volumeClass:metrics.volumeClass,
      scalePotential:metrics.scalePotential,
      tenThousandEventRevenueTargetUsd:metrics.tenThousandEventRevenueTargetUsd,
      scaleTruth:metrics.scaleTruth,
      multiArchetypeSignal:true
    },
  };
}

function selectDiverseIdeas(ideas, topK) {
  const ranked=[...ideas].sort((a,b)=>b.metrics.score-a.metrics.score || b.metrics.scalePotential-a.metrics.scalePotential || b.metrics.novelty-a.metrics.novelty);
  const groups=new Map();
  for (const idea of ranked) {
    const key=idea.monetizationFamily || "open_ended";
    if(!groups.has(key)) groups.set(key,[]);
    groups.get(key).push(idea);
  }
  const selected=[];
  const used=new Set();
  const groupEntries=[...groups.entries()].sort((a,b)=>(b[1][0]?.metrics?.score||0)-(a[1][0]?.metrics?.score||0));

  for (const [,group] of groupEntries) {
    if(selected.length>=topK) break;
    const idea=group[0];
    if(idea && !used.has(idea.id)){selected.push(idea);used.add(idea.id);}
  }
  for (const idea of ranked) {
    if(selected.length>=topK) break;
    if(!used.has(idea.id)){selected.push(idea);used.add(idea.id);}
  }
  return selected;
}

async function persist(db, ideas, policy) {
  if (!db?.prepare) return;
  for (const idea of ideas) {
    await db.prepare(`INSERT OR REPLACE INTO lumen_venture_hunter_ideas
      (id, created_at, source_kind, source_ref, title, product, build_plan, revenue_model, monetization_family, score, status, evidence_json, policy_json)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .bind(
        idea.id, idea.createdAt, idea.sourceKind, idea.sourceRef, idea.title, idea.product, idea.buildPlan,
        idea.revenueModel, idea.monetizationFamily, idea.metrics.score, idea.status,
        JSON.stringify(idea.evidence), JSON.stringify(policy)
      ).run();
  }
}

export async function runVentureHunterV1(env, options = {}) {
  const policy = {
    version: VERSION,
    mode: options.mode || "prepare_only",
    autonomousResearch: true,
    autonomousIdeaGeneration: true,
    autonomousBuildPreparation: true,
    multiArchetypePerSignal: true,
    diversityFirstRanking: true,
    eventScaleRanking: true,
    scaleRequiresEvidence: true,
    scaleTargetsAreNotRevenue: true,
    targetScenarioEvents: 10000,
    maxArchetypesPerSignal: MAX_ARCHETYPES_PER_SIGNAL,
    monetizationFamiliesAvailable: [...new Set(ARCHETYPES.map(x=>x.family))].length,
    autonomousExternalLaunch: false,
    autonomousSpending: false,
    autonomousContracting: false,
    bindingActionsHumanGated: true,
  };

  const db = env?.DB || env?.LUMEN_DB || null;
  await ensureSchema(db);
  const familyCounts=await recentFamilyCounts(db);
  const signals = Array.isArray(options.signals)
    ? options.signals.map((row) => ({ kind: "injected", row }))
    : await readSignals(db, options.limit || 80);

  const rawIdeas=[];
  signals.forEach((signal,index)=>{
    const text=textOf(signal.row);
    const archetypes=archetypesFor(text);
    archetypes.forEach((archetype,variantIndex)=>{
      const idea=makeIdea(signal,index,archetype,variantIndex,familyCounts.get(archetype.family)||0);
      if(idea) rawIdeas.push(idea);
    });
  });

  const deduped=[];
  const seen=new Set();
  for(const idea of rawIdeas.sort((a,b)=>b.metrics.score-a.metrics.score)){
    const key=`${idea.sourceRef}|${idea.monetizationFamily}|${idea.product}`;
    if(seen.has(key)) continue;
    seen.add(key);
    deduped.push(idea);
  }

  const topK=Math.max(1,Math.min(30,Number(options.topK)||12));
  const ideas=selectDiverseIdeas(deduped,topK);
  await persist(db, ideas, policy);

  const families=[...new Set(ideas.map(x=>x.monetizationFamily))];
  const revenueModels=[...new Set(ideas.map(x=>x.revenueModel))];
  return {
    ok: true,
    engine: "LUMEN Venture Hunter v1.1",
    version: VERSION,
    generatedAt: NOW(),
    signalsExamined: signals.length,
    rawIdeasGenerated: rawIdeas.length,
    ideasGenerated: ideas.length,
    buildCandidates: ideas.filter((x) => x.status === "BUILD_CANDIDATE").length,
    familiesCovered: families.length,
    monetizationFamilies: families,
    revenueModelsCovered: revenueModels.length,
    revenueModels,
    frontierBreadth: Number((families.length / Math.max(1,policy.monetizationFamiliesAvailable)).toFixed(4)),
    highScaleIdeas: ideas.filter(x=>["HIGH","VERY_HIGH"].includes(x.metrics.volumeClass)).length,
    veryHighScaleIdeas: ideas.filter(x=>x.metrics.volumeClass==="VERY_HIGH").length,
    bestScaleCandidate: [...ideas].sort((a,b)=>b.metrics.scalePotential-a.metrics.scalePotential)[0] || null,
    scaleScenario: {
      targetEvents:10000,
      realizedRevenueClaim:false,
      purpose:"compare repeatable monetizable-event economics without treating projections as revenue"
    },
    topOpportunity: ideas[0] || null,
    ideas,
    policy,
    next: ideas[0]?.status === "BUILD_CANDIDATE" ? "prepare_mvp_and_validation_plan" : "keep_hunting",
  };
}
