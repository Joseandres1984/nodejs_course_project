import { buildViatorAffiliateUrl } from "./viator-affiliate.js";

const VERSION = "1.0-travel-affiliate-orchestrator";
const MAX_RECOMMENDATIONS = 4;

const TRAVEL_TERMS = [
  "travel","trip","vacation","holiday","tour","activity","activities","excursion","experience","things to do",
  "viaje","viajar","vacaciones","turismo","tour","actividad","actividades","excursion","excursión","experiencia","que hacer","qué hacer"
];

const CATEGORY_RULES = [
  { id:"FOOD", label:"Food & Drink", terms:["food","restaurant","gastronomy","wine","beer","tasting","comida","gastronomia","gastronomía","vino","cerveza","degustacion","degustación"] },
  { id:"ADVENTURE", label:"Outdoor & Adventure", terms:["adventure","hiking","trekking","rafting","kayak","diving","snorkel","outdoor","aventura","senderismo","buceo"] },
  { id:"CULTURE", label:"Culture & Attractions", terms:["museum","history","historic","culture","art","monument","attraction","museo","historia","historico","histórico","cultura","arte","monumento","atraccion","atracción"] },
  { id:"DAY_TRIP", label:"Day Trips", terms:["day trip","full day","nearby","outside city","excursion","excursión","dia completo","día completo"] },
  { id:"NIGHT", label:"Nightlife & Shows", terms:["nightlife","show","concert","night tour","bar","pub","noche","espectaculo","espectáculo","concierto"] },
  { id:"FAMILY", label:"Family", terms:["family","kids","children","familia","niños","ninos"] },
  { id:"TRANSFER", label:"Transfers", terms:["transfer","airport","pickup","transport","traslado","aeropuerto","transporte"] },
  { id:"GENERAL", label:"Top Experiences", terms:[] }
];

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control":"no-store", "x-content-type-options":"nosniff", "access-control-allow-origin":"*" } });
}

function clean(value, limit = 5000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function scrub(text, limit = 1200) {
  return clean(text, 12000)
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[redacted-email]")
    .replace(/\+?\d[\d\s().-]{8,}\d/g, "[redacted-phone]")
    .replace(/\b(?:\d[ -]*?){13,19}\b/g, "[redacted-payment-number]")
    .replace(/\b(passport|pasaporte)\s*(?:no\.?|number|nro\.?|#)?\s*[:=-]?\s*[A-Z0-9-]{5,20}\b/gi, "$1 [redacted]")
    .slice(0, limit);
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

function hasTravelIntent(text) {
  const t = clean(text, 12000).toLowerCase();
  return TRAVEL_TERMS.some(term => t.includes(term));
}

function titleCaseWords(value) {
  return clean(value, 120).split(/\s+/).map(w => w ? w[0].toUpperCase() + w.slice(1) : w).join(" ");
}

function extractDestination(text) {
  const source = clean(text, 3000);
  const patterns = [
    /(?:viaj(?:e|ar|amos|o)|vacaciones|tour|excursi[oó]n)\s+(?:a|en|por)\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’.-]*(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’.-]*){0,3})/,
    /(?:travel|trip|vacation|holiday|tour)\s+(?:to|in|around)\s+([A-Z][A-Za-z'’.-]*(?:\s+[A-Z][A-Za-z'’.-]*){0,3})/,
    /(?:in|to|en|a)\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’.-]*(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’.-]*){0,2})(?=\s+(?:for|por|with|con|from|desde|next|pr[oó]xim|during|durante)|[,.!?]|$)/
  ];
  for (const pattern of patterns) {
    const match = source.match(pattern);
    if (match?.[1]) return titleCaseWords(match[1]);
  }
  return "";
}

function selectedCategories(text) {
  const t = clean(text, 12000).toLowerCase();
  const scored = CATEGORY_RULES
    .filter(rule => rule.id !== "GENERAL")
    .map(rule => ({ ...rule, hits: rule.terms.filter(term => t.includes(term)).length }))
    .filter(rule => rule.hits > 0)
    .sort((a,b) => b.hits - a.hits || a.label.localeCompare(b.label));
  const out = scored.slice(0, MAX_RECOMMENDATIONS - 1);
  out.push(CATEGORY_RULES.find(rule => rule.id === "GENERAL"));
  return out.slice(0, MAX_RECOMMENDATIONS);
}

function fallbackQuery(text) {
  const cleaned = scrub(text, 180)
    .replace(/\[[^\]]+\]/g, "")
    .replace(/\b(i|we|need|want|looking|for|a|an|the|to|in|my|our|quiero|queremos|necesito|necesitamos|viaje|viajar|vacaciones|un|una|el|la|los|las|en|a|para)\b/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned || "top travel experiences";
}

function buildViatorSearchUrl(query) {
  const u = new URL("https://www.viator.com/searchResults/all");
  u.searchParams.set("text", clean(query, 220));
  return u.toString();
}

function affiliateConfig(env) {
  return {
    pid: clean(env?.LUMEN_VIATOR_AFFILIATE_PID, 100) || undefined,
    mcid: clean(env?.LUMEN_VIATOR_MCID, 100) || undefined,
    medium: clean(env?.LUMEN_VIATOR_MEDIUM, 100) || undefined,
    mediumVersion: clean(env?.LUMEN_VIATOR_MEDIUM_VERSION, 100) || undefined
  };
}

export function planTravelAffiliateIntent(text, env = {}) {
  const source = clean(text, 5000);
  if (!source) throw new Error("travel_intent_text_required");
  if (!hasTravelIntent(source)) throw new Error("travel_intent_not_detected");

  const destination = extractDestination(source);
  const base = destination || fallbackQuery(source);
  const categories = selectedCategories(source);
  const config = affiliateConfig(env);

  const recommendations = categories.map((category, index) => {
    const searchQuery = category.id === "GENERAL" ? `${base} top experiences` : `${base} ${category.label}`;
    const originalUrl = buildViatorSearchUrl(searchQuery);
    const affiliateUrl = buildViatorAffiliateUrl(originalUrl, config);
    const intentBonus = category.id === "GENERAL" ? 0 : Math.min(18, category.hits * 9);
    const score = Math.max(55, Math.min(98, 78 - index * 5 + intentBonus + (destination ? 5 : 0)));
    return {
      rank: index + 1,
      category: category.id,
      label: category.label,
      searchQuery,
      score,
      provider: "viator",
      productSpecific: false,
      affiliateUrl
    };
  }).sort((a,b) => b.score - a.score || a.rank - b.rank).map((item, index) => ({ ...item, rank:index + 1 }));

  return {
    ok: true,
    version: VERSION,
    travelIntentDetected: true,
    destination: destination || null,
    sourceSummary: scrub(source, 700),
    bestPick: recommendations[0] || null,
    recommendations,
    monetization: {
      model: "viator_affiliate",
      linksMonetized: recommendations.length,
      bookingAuthority: false,
      paymentAuthority: false,
      autonomousSpendUsd: 0
    },
    searchMode: "affiliate_search_fallback",
    note: "Product-level ranking requires Viator Partner API access; this mode creates ranked, intent-specific Viator affiliate search links without scraping."
  };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_affiliate_intents (id TEXT PRIMARY KEY,source_type TEXT NOT NULL,source_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,summary TEXT NOT NULL,destination TEXT,categories_json TEXT NOT NULL,recommendations_json TEXT NOT NULL,best_affiliate_url TEXT,status TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_travel_affiliate_intents_updated ON lumen_travel_affiliate_intents(status,updated_at DESC)")
  ]);
  return true;
}

function stableId(sourceType, sourceId) {
  const suffix = clean(sourceId, 120).replace(/[^A-Za-z0-9_-]/g, "").slice(-70).toUpperCase() || crypto.randomUUID().replace(/-/g, "").slice(0, 18).toUpperCase();
  return `TAF-${clean(sourceType, 20).replace(/[^A-Za-z0-9]/g, "").slice(0,10).toUpperCase()}-${suffix}`;
}

async function persistPlan(env, { sourceType, sourceId, text }) {
  let plan;
  try { plan = planTravelAffiliateIntent(text, env); }
  catch { return null; }
  const now = new Date().toISOString();
  const id = stableId(sourceType, sourceId);
  await env.DB.prepare("INSERT INTO lumen_travel_affiliate_intents(id,source_type,source_id,created_at,updated_at,summary,destination,categories_json,recommendations_json,best_affiliate_url,status,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET updated_at=excluded.updated_at,summary=excluded.summary,destination=excluded.destination,categories_json=excluded.categories_json,recommendations_json=excluded.recommendations_json,best_affiliate_url=excluded.best_affiliate_url,status='READY',engine_version=excluded.engine_version")
    .bind(id, clean(sourceType,40), clean(sourceId,180), now, now, plan.sourceSummary, plan.destination, JSON.stringify(plan.recommendations.map(r => r.category)), JSON.stringify(plan.recommendations), plan.bestPick?.affiliateUrl || null, "READY", VERSION).run();
  return plan;
}

async function scanTravelDemands(env) {
  try {
    const result = await env.DB.prepare("SELECT id,summary FROM lumen_travel_demands WHERE status IN ('QUALIFIED','MATCHED','PARTNER_INTEREST') ORDER BY updated_at DESC LIMIT 120").all();
    let planned = 0;
    for (const row of result.results || []) if (await persistPlan(env, { sourceType:"TRAVEL_DEMAND", sourceId:row.id, text:row.summary })) planned += 1;
    return { scanned:(result.results || []).length, planned };
  } catch (error) {
    return { scanned:0, planned:0, error:clean(error?.message || error,180) };
  }
}

async function scanInbound(env) {
  try {
    const result = await env.DB.prepare("SELECT id,text FROM lumen_a2a_inbound WHERE binding_intent=0 ORDER BY received_at DESC LIMIT 180").all();
    let planned = 0;
    for (const row of result.results || []) if (await persistPlan(env, { sourceType:"A2A_INBOUND", sourceId:row.id, text:row.text })) planned += 1;
    return { scanned:(result.results || []).length, planned };
  } catch (error) {
    return { scanned:0, planned:0, error:clean(error?.message || error,180) };
  }
}

export async function runTravelAffiliateOrchestrator(env) {
  const ready = await ensureSchema(env);
  if (!ready) return { ok:false, error:"db_not_bound", version:VERSION };
  const [travelDemands, inbound] = await Promise.all([scanTravelDemands(env), scanInbound(env)]);
  return {
    ok:true,
    version:VERSION,
    travelDemands,
    inbound,
    preparedAffiliatePlans:Number(travelDemands.planned || 0) + Number(inbound.planned || 0),
    externalMessagesCreated:0,
    autonomousBookings:0,
    autonomousSpendUsd:0
  };
}

async function stats(env) {
  if (!env?.DB) return { version:VERSION, total:0, ready:0, destinations:0, dbBound:false };
  await ensureSchema(env);
  const row = await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='READY' THEN 1 ELSE 0 END) ready,COUNT(DISTINCT CASE WHEN destination IS NOT NULL AND destination<>'' THEN destination END) destinations FROM lumen_travel_affiliate_intents").first();
  return { version:VERSION, total:Number(row?.total || 0), ready:Number(row?.ready || 0), destinations:Number(row?.destinations || 0), dbBound:true };
}

export async function handleTravelAffiliateOrchestrator(request, env) {
  const url = new URL(request.url);
  const paths = ["/travel/affiliate/policy","/travel/affiliate/stats","/travel/affiliate/recommend","/travel/affiliate/plan","/travel/affiliate/run"];
  if (!paths.includes(url.pathname)) return null;

  if (request.method === "GET" && url.pathname === "/travel/affiliate/policy") {
    return json({
      version:VERSION,
      name:"LUMEN Travel Affiliate Orchestrator",
      provider:"viator",
      behavior:["detect travel intent","extract destination when present","rank relevant activity categories","generate monetized Viator search links","persist prepared links for qualified travel demand"],
      productLevelRanking:false,
      productLevelRankingRequirement:"Viator Partner API access",
      scraping:false,
      bookingAuthority:false,
      paymentAuthority:false,
      autonomousPurchase:false,
      autonomousSpendUsd:0,
      externalMessagesCreated:0
    });
  }

  if (request.method === "GET" && url.pathname === "/travel/affiliate/stats") return json(await stats(env));

  if (request.method === "GET" && url.pathname === "/travel/affiliate/recommend") {
    try { return json(planTravelAffiliateIntent(url.searchParams.get("text") || "", env)); }
    catch (error) { return json({ ok:false, error:clean(error?.message || error,180), version:VERSION }, 400); }
  }

  if (!authorized(request, env)) return json({ ok:false, error:"unauthorized", version:VERSION }, 401);

  if (request.method === "POST" && url.pathname === "/travel/affiliate/plan") {
    let payload = {};
    try { payload = await request.json(); } catch {}
    try { return json(planTravelAffiliateIntent(payload?.text || "", env)); }
    catch (error) { return json({ ok:false, error:clean(error?.message || error,180), version:VERSION }, 400); }
  }

  if (request.method === "POST" && url.pathname === "/travel/affiliate/run") return json(await runTravelAffiliateOrchestrator(env));

  return json({ ok:false, error:"method_not_allowed", version:VERSION }, 405);
}
