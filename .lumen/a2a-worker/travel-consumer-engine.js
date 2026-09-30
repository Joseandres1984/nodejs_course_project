const VERSION = "1.0-travel-consumer-discovery";
const PRICING_MODE = "ESTIMATED_SEED";
const IDEAL_BUDGET_USAGE = 0.88;

const EXPERIENCE_TYPES = new Set([
  "PLAYA", "NATURALEZA", "AVENTURA", "GASTRONOMIA", "CIUDAD",
  "CULTURA", "RELAX", "VIDA_NOCTURNA", "ROMANTICO", "FAMILIAR"
]);

const DESTINATIONS = [
  {
    code: "GIG", city: "Río de Janeiro", country: "Brasil",
    dailyCostUSD: 65, hotelNightUSD: 72, transferPerPersonUSD: 28, activityDailyUSD: 18,
    qualityScore: 8.5, safetyIndex: 6.8, accessibilityScore: 9.0,
    tags: ["PLAYA", "VIDA_NOCTURNA", "GASTRONOMIA", "NATURALEZA"],
    routes: { BUE: { avgFlightUSD: 420, flightTimeHours: 4.5, volatility: 0.25 } },
    climate: { 1:"HIGH",2:"HIGH",3:"SHOULDER",4:"SHOULDER",5:"LOW",6:"LOW",7:"LOW",8:"LOW",9:"SHOULDER",10:"SHOULDER",11:"HIGH",12:"HIGH" }
  },
  {
    code: "BKK", city: "Bangkok / Islas", country: "Tailandia",
    dailyCostUSD: 45, hotelNightUSD: 42, transferPerPersonUSD: 30, activityDailyUSD: 16,
    qualityScore: 9.1, safetyIndex: 8.0, accessibilityScore: 7.5,
    tags: ["PLAYA", "GASTRONOMIA", "AVENTURA", "CULTURA"],
    routes: { BUE: { avgFlightUSD: 920, flightTimeHours: 24, volatility: 0.30 } },
    climate: { 1:"HIGH",2:"SHOULDER",3:"SHOULDER",4:"LOW",5:"LOW",6:"LOW",7:"LOW",8:"LOW",9:"LOW",10:"SHOULDER",11:"HIGH",12:"HIGH" }
  },
  {
    code: "MAD", city: "Madrid", country: "España",
    dailyCostUSD: 110, hotelNightUSD: 105, transferPerPersonUSD: 24, activityDailyUSD: 24,
    qualityScore: 9.5, safetyIndex: 9.2, accessibilityScore: 9.8,
    tags: ["CIUDAD", "CULTURA", "GASTRONOMIA", "VIDA_NOCTURNA"],
    routes: { BUE: { avgFlightUSD: 850, flightTimeHours: 12, volatility: 0.24 } },
    climate: { 1:"LOW",2:"SHOULDER",3:"SHOULDER",4:"HIGH",5:"HIGH",6:"HIGH",7:"HIGH",8:"HIGH",9:"SHOULDER",10:"SHOULDER",11:"LOW",12:"LOW" }
  },
  {
    code: "SCL", city: "Santiago", country: "Chile",
    dailyCostUSD: 72, hotelNightUSD: 70, transferPerPersonUSD: 18, activityDailyUSD: 15,
    qualityScore: 8.4, safetyIndex: 8.2, accessibilityScore: 9.2,
    tags: ["CIUDAD", "GASTRONOMIA", "CULTURA", "NATURALEZA"],
    routes: { BUE: { avgFlightUSD: 260, flightTimeHours: 2.5, volatility: 0.18 } },
    climate: { 1:"HIGH",2:"HIGH",3:"SHOULDER",4:"SHOULDER",5:"LOW",6:"LOW",7:"LOW",8:"SHOULDER",9:"SHOULDER",10:"HIGH",11:"HIGH",12:"HIGH" }
  },
  {
    code: "LIM", city: "Lima", country: "Perú",
    dailyCostUSD: 58, hotelNightUSD: 58, transferPerPersonUSD: 22, activityDailyUSD: 17,
    qualityScore: 8.7, safetyIndex: 7.4, accessibilityScore: 8.7,
    tags: ["GASTRONOMIA", "CULTURA", "CIUDAD", "AVENTURA"],
    routes: { BUE: { avgFlightUSD: 390, flightTimeHours: 5, volatility: 0.22 } },
    climate: { 1:"HIGH",2:"HIGH",3:"HIGH",4:"SHOULDER",5:"SHOULDER",6:"LOW",7:"LOW",8:"LOW",9:"SHOULDER",10:"SHOULDER",11:"HIGH",12:"HIGH" }
  },
  {
    code: "CUN", city: "Cancún", country: "México",
    dailyCostUSD: 82, hotelNightUSD: 92, transferPerPersonUSD: 26, activityDailyUSD: 28,
    qualityScore: 8.8, safetyIndex: 7.5, accessibilityScore: 9.0,
    tags: ["PLAYA", "RELAX", "AVENTURA", "VIDA_NOCTURNA"],
    routes: { BUE: { avgFlightUSD: 760, flightTimeHours: 10, volatility: 0.30 } },
    climate: { 1:"HIGH",2:"HIGH",3:"HIGH",4:"SHOULDER",5:"SHOULDER",6:"LOW",7:"LOW",8:"LOW",9:"LOW",10:"SHOULDER",11:"HIGH",12:"HIGH" }
  },
  {
    code: "MVD", city: "Montevideo", country: "Uruguay",
    dailyCostUSD: 88, hotelNightUSD: 82, transferPerPersonUSD: 20, activityDailyUSD: 15,
    qualityScore: 8.3, safetyIndex: 8.8, accessibilityScore: 9.5,
    tags: ["CIUDAD", "GASTRONOMIA", "RELAX", "CULTURA"],
    routes: { BUE: { avgFlightUSD: 210, flightTimeHours: 1, volatility: 0.16 } },
    climate: { 1:"HIGH",2:"HIGH",3:"SHOULDER",4:"SHOULDER",5:"LOW",6:"LOW",7:"LOW",8:"LOW",9:"SHOULDER",10:"SHOULDER",11:"HIGH",12:"HIGH" }
  },
  {
    code: "GRU", city: "São Paulo", country: "Brasil",
    dailyCostUSD: 68, hotelNightUSD: 67, transferPerPersonUSD: 25, activityDailyUSD: 18,
    qualityScore: 8.6, safetyIndex: 6.9, accessibilityScore: 9.1,
    tags: ["CIUDAD", "GASTRONOMIA", "VIDA_NOCTURNA", "CULTURA"],
    routes: { BUE: { avgFlightUSD: 310, flightTimeHours: 3, volatility: 0.20 } },
    climate: { 1:"HIGH",2:"HIGH",3:"SHOULDER",4:"SHOULDER",5:"LOW",6:"LOW",7:"LOW",8:"SHOULDER",9:"SHOULDER",10:"HIGH",11:"HIGH",12:"HIGH" }
  }
];

function clamp(value, min = 0, max = 100) {
  return Math.max(min, Math.min(max, Number(value) || 0));
}

function clean(value, limit = 500) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function normalizeOrigin(value) {
  const origin = clean(value, 8).toUpperCase();
  if (["EZE", "AEP", "BUE"].includes(origin)) return "BUE";
  return origin;
}

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "content-type",
      "access-control-allow-methods": "GET,POST,OPTIONS"
    }
  });
}

function validateInput(raw = {}) {
  const input = {
    originCode: normalizeOrigin(raw.originCode || raw.origin || ""),
    maxBudgetUSD: Number(raw.maxBudgetUSD ?? raw.maxBudget),
    durationDays: Math.round(Number(raw.durationDays ?? raw.duration)),
    targetMonth: Math.round(Number(raw.targetMonth ?? raw.month)),
    flexibilityDays: Math.max(0, Math.min(21, Math.round(Number(raw.flexibilityDays ?? 3)))),
    travelersCount: Math.max(1, Math.min(8, Math.round(Number(raw.travelersCount ?? 1)))),
    preferences: Array.isArray(raw.preferences)
      ? [...new Set(raw.preferences.map(x => clean(x, 40).toUpperCase()).filter(x => EXPERIENCE_TYPES.has(x)))].slice(0, 6)
      : []
  };

  const errors = [];
  if (!input.originCode) errors.push("origin_required");
  if (!Number.isFinite(input.maxBudgetUSD) || input.maxBudgetUSD < 100 || input.maxBudgetUSD > 100000) errors.push("invalid_budget");
  if (!Number.isInteger(input.durationDays) || input.durationDays < 1 || input.durationDays > 90) errors.push("invalid_duration");
  if (!Number.isInteger(input.targetMonth) || input.targetMonth < 1 || input.targetMonth > 12) errors.push("invalid_month");
  return { input, errors };
}

function seasonScore(season) {
  if (season === "SHOULDER") return 100;
  if (season === "HIGH") return 86;
  if (season === "LOW") return 62;
  return 70;
}

function budgetFitScore(total, budget) {
  if (total > budget || budget <= 0) return 0;
  const usage = total / budget;
  return clamp(100 - Math.abs(usage - IDEAL_BUDGET_USAGE) * 240);
}

function preferenceScore(preferences, tags) {
  if (!preferences.length) return 85;
  const hits = preferences.filter(x => tags.includes(x)).length;
  return clamp((hits / preferences.length) * 100);
}

function dailyValueScore(dailyCostUSD) {
  return clamp(105 - Math.max(0, dailyCostUSD - 35) * 0.8);
}

function flightStayScore(flightUSD, totalUSD, flightHours, durationDays) {
  const share = totalUSD > 0 ? flightUSD / totalUSD : 1;
  let score = 100;
  if (share > 0.35) score -= (share - 0.35) * 120;
  const hoursPerTravelDay = flightHours / Math.max(1, durationDays);
  if (hoursPerTravelDay > 1.4) score -= (hoursPerTravelDay - 1.4) * 18;
  return clamp(score);
}

function riskScore(volatility) {
  return clamp(100 - clamp(volatility * 100, 0, 100) * 0.9);
}

function calculateConfidence(route, destination) {
  const completeness = [
    route?.avgFlightUSD,
    route?.flightTimeHours,
    destination?.hotelNightUSD,
    destination?.dailyCostUSD,
    destination?.accessibilityScore,
    destination?.qualityScore
  ].filter(x => Number.isFinite(Number(x))).length / 6;

  const sourceReliability = PRICING_MODE === "ESTIMATED_SEED" ? 0.64 : 0.90;
  const volatilityPenalty = Math.min(0.22, Number(route?.volatility || 0.25) * 0.35);
  return Math.max(0.25, Math.min(0.95, Number((sourceReliability * completeness - volatilityPenalty).toFixed(2))));
}

function buildBreakdown(input, destination, route) {
  const travelers = input.travelersCount;
  const nights = Math.max(1, input.durationDays - 1);
  const rooms = Math.max(1, Math.ceil(travelers / 2));
  const flightUSD = route.avgFlightUSD * travelers;
  const accommodationUSD = destination.hotelNightUSD * nights * rooms;
  const transfersUSD = destination.transferPerPersonUSD * travelers;
  const activitiesUSD = destination.activityDailyUSD * input.durationDays * travelers;
  const dailyFoodAndExpensesUSD = destination.dailyCostUSD * 0.55 * input.durationDays * travelers;
  const subtotalUSD = flightUSD + accommodationUSD + transfersUSD + activitiesUSD + dailyFoodAndExpensesUSD;
  const reserveTargetUSD = input.maxBudgetUSD * 0.10;
  const remainingMarginUSD = Math.max(0, input.maxBudgetUSD - subtotalUSD);

  return {
    flightUSD: Math.round(flightUSD),
    accommodationUSD: Math.round(accommodationUSD),
    transfersUSD: Math.round(transfersUSD),
    activitiesUSD: Math.round(activitiesUSD),
    dailyFoodAndExpensesUSD: Math.round(dailyFoodAndExpensesUSD),
    subtotalUSD: Math.round(subtotalUSD),
    reserveTargetUSD: Math.round(reserveTargetUSD),
    remainingMarginUSD: Math.round(remainingMarginUSD),
    totalUSD: Math.round(subtotalUSD)
  };
}

function calculateScore(input, destination, route, breakdown) {
  const metrics = {
    budgetFit: budgetFitScore(breakdown.totalUSD, input.maxBudgetUSD),
    preferenceFit: preferenceScore(input.preferences, destination.tags),
    dailyValue: dailyValueScore(destination.dailyCostUSD),
    flightStayFit: flightStayScore(breakdown.flightUSD, breakdown.totalUSD, route.flightTimeHours, input.durationDays),
    seasonFit: seasonScore(destination.climate[input.targetMonth]),
    destinationQuality: clamp(destination.qualityScore * 10),
    accessibility: clamp(destination.accessibilityScore * 10),
    overrunRisk: riskScore(route.volatility)
  };

  const score =
    metrics.budgetFit * 0.20 +
    metrics.preferenceFit * 0.20 +
    metrics.dailyValue * 0.15 +
    metrics.flightStayFit * 0.15 +
    metrics.seasonFit * 0.10 +
    metrics.destinationQuality * 0.10 +
    metrics.accessibility * 0.05 +
    metrics.overrunRisk * 0.05;

  return { lumenScore: Math.round(clamp(score)), metrics };
}

function recommendationReason(input, destination, breakdown, score) {
  const usage = Math.round((breakdown.totalUSD / input.maxBudgetUSD) * 100);
  const preference = Math.round(score.metrics.preferenceFit);
  return `${destination.city} usa aproximadamente ${usage}% del presupuesto estimado y logra ${preference}% de compatibilidad con las preferencias seleccionadas. Los importes son estimaciones de planificación, no tarifas en tiempo real.`;
}

export function calculateTravelOptions(rawInput, destinationDataset = DESTINATIONS) {
  const { input, errors } = validateInput(rawInput);
  if (errors.length) return { ok: false, errors, input, options: [] };

  const options = [];
  for (const destination of destinationDataset) {
    const route = destination.routes?.[input.originCode];
    if (!route) continue;

    const breakdown = buildBreakdown(input, destination, route);
    if (breakdown.totalUSD > input.maxBudgetUSD) continue;

    const score = calculateScore(input, destination, route, breakdown);
    const confidenceLevel = calculateConfidence(route, destination);
    const season = destination.climate[input.targetMonth] || "UNKNOWN";

    const pros = [];
    const cons = [];
    if (score.metrics.preferenceFit >= 75) pros.push("Alta compatibilidad con el estilo de viaje elegido");
    if (breakdown.remainingMarginUSD >= input.maxBudgetUSD * 0.10) pros.push("Conserva un colchón presupuestario de al menos 10%");
    if (season === "SHOULDER") pros.push("Temporada media con buen equilibrio entre demanda y experiencia");
    if (breakdown.flightUSD / breakdown.totalUSD > 0.50) cons.push("El vuelo representa más del 50% del costo estimado");
    if (route.flightTimeHours > 12 && input.durationDays <= 7) cons.push("Tiempo de vuelo alto para una estadía corta");
    if (confidenceLevel < 0.55) cons.push("Estimación de baja confianza: requiere cotización actual antes de decidir");

    options.push({
      destinationCode: destination.code,
      city: destination.city,
      country: destination.country,
      durationDays: input.durationDays,
      travelersCount: input.travelersCount,
      breakdown,
      lumenScore: score.lumenScore,
      scoreBreakdown: score.metrics,
      confidenceLevel,
      pricingMode: PRICING_MODE,
      realTimeFare: false,
      bookingAvailable: false,
      affiliateLinksAvailable: false,
      recommendedWindow: {
        targetMonth: input.targetMonth,
        flexibilityDays: input.flexibilityDays,
        exactDatesAvailable: false
      },
      season,
      tags: destination.tags,
      recommendReason: recommendationReason(input, destination, breakdown, score),
      pros,
      cons
    });
  }

  options.sort((a, b) => b.lumenScore - a.lumenScore || a.breakdown.totalUSD - b.breakdown.totalUSD);
  return { ok: true, errors: [], input, options: options.slice(0, 5) };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_consumer_searches (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,origin_code TEXT NOT NULL,max_budget_usd REAL NOT NULL,duration_days INTEGER NOT NULL,target_month INTEGER NOT NULL,flexibility_days INTEGER NOT NULL,travelers_count INTEGER NOT NULL,preferences_json TEXT NOT NULL,result_count INTEGER NOT NULL,best_destination_code TEXT,best_lumen_score INTEGER,pricing_mode TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_travel_consumer_demand ON lumen_travel_consumer_searches(origin_code,target_month,max_budget_usd,created_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_demand_events (id TEXT PRIMARY KEY,search_id TEXT NOT NULL,created_at TEXT NOT NULL,event_type TEXT NOT NULL,origin_code TEXT NOT NULL,target_month INTEGER NOT NULL,budget_bucket_usd INTEGER NOT NULL,preferences_json TEXT NOT NULL,result_count INTEGER NOT NULL,status TEXT NOT NULL,engine_version TEXT NOT NULL,UNIQUE(search_id,event_type))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_travel_demand_events_status ON lumen_travel_demand_events(status,event_type,created_at DESC)")
  ]);
  return true;
}

async function persistSearch(env, result) {
  if (!(await ensureSchema(env))) return { stored: false, reason: "persistence_unavailable" };
  const id = `TRVC-${crypto.randomUUID().replaceAll("-", "").slice(0, 18).toUpperCase()}`;
  const now = new Date().toISOString();
  const best = result.options[0] || null;
  const input = result.input;
  await env.DB.prepare("INSERT INTO lumen_travel_consumer_searches(id,created_at,origin_code,max_budget_usd,duration_days,target_month,flexibility_days,travelers_count,preferences_json,result_count,best_destination_code,best_lumen_score,pricing_mode,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(id, now, input.originCode, input.maxBudgetUSD, input.durationDays, input.targetMonth, input.flexibilityDays, input.travelersCount, JSON.stringify(input.preferences), result.options.length, best?.destinationCode || null, best?.lumenScore ?? null, PRICING_MODE, VERSION).run();

  const eventType = result.options.length ? "TRAVEL_SEARCH_SERVED" : "TRAVEL_DEMAND_UNMET";
  const bucket = Math.max(100, Math.round(input.maxBudgetUSD / 100) * 100);
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_travel_demand_events(id,search_id,created_at,event_type,origin_code,target_month,budget_bucket_usd,preferences_json,result_count,status,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
    .bind(`TDE-${id.slice(5)}`, id, now, eventType, input.originCode, input.targetMonth, bucket, JSON.stringify(input.preferences), result.options.length, "NEW", VERSION).run();
  return { stored: true, searchId: id, demandEvent: eventType };
}

async function stats(env) {
  if (!(await ensureSchema(env))) return { version: VERSION, searches: 0, unmetDemand: 0, persistence: false };
  const row = await env.DB.prepare("SELECT COUNT(*) searches,SUM(CASE WHEN result_count=0 THEN 1 ELSE 0 END) unmet,AVG(best_lumen_score) avg_best_score FROM lumen_travel_consumer_searches").first();
  const top = await env.DB.prepare("SELECT origin_code,target_month,budget_bucket_usd,COUNT(*) demand_count FROM lumen_travel_demand_events WHERE event_type='TRAVEL_DEMAND_UNMET' GROUP BY origin_code,target_month,budget_bucket_usd ORDER BY demand_count DESC LIMIT 10").all();
  return {
    version: VERSION,
    searches: Number(row?.searches || 0),
    unmetDemand: Number(row?.unmet || 0),
    averageBestScore: row?.avg_best_score == null ? null : Math.round(Number(row.avg_best_score)),
    topUnmetDemand: top.results || [],
    persistence: true,
    storesIpAddress: false,
    storesUserAgent: false
  };
}

export async function handleTravelConsumerEngine(request, env) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS" && url.pathname.startsWith("/travel/discovery/")) return new Response(null, { status: 204, headers: { "access-control-allow-origin":"*", "access-control-allow-headers":"content-type", "access-control-allow-methods":"GET,POST,OPTIONS" } });

  if (request.method === "GET" && url.pathname === "/travel/discovery/policy") {
    return json({
      version: VERSION,
      name: "LUMEN Travel Discovery",
      proposition: "Find the best travel experience that fits the user's total budget",
      pricingMode: PRICING_MODE,
      realTimeFares: false,
      exactDatesClaimed: false,
      createsBooking: false,
      createsCharge: false,
      storesPaymentData: false,
      storesPassportData: false,
      storesIpAddress: false,
      autonomousSpend: false,
      autonomousPurchase: false,
      bindingActionsHumanGated: true,
      supportedOriginAliases: ["BUE", "EZE", "AEP"]
    });
  }

  if (request.method === "GET" && url.pathname === "/travel/discovery/stats") return json(await stats(env));

  if (request.method === "POST" && url.pathname === "/travel/discovery/search") {
    let body = {};
    try { body = await request.json(); } catch { return json({ ok:false, error:"invalid_json" }, 400); }
    const result = calculateTravelOptions(body);
    if (!result.ok) return json({ ...result, version: VERSION }, 400);
    let persistence = { stored:false, reason:"not_attempted" };
    try { persistence = await persistSearch(env, result); } catch (error) { persistence = { stored:false, reason: clean(error?.message || error, 160) || "storage_error" }; }
    return json({
      ...result,
      version: VERSION,
      persistence,
      guardrails: {
        recommendationOnly: true,
        pricingIsEstimated: true,
        realTimeFareClaim: false,
        bookingCreated: false,
        chargeCreated: false,
        autonomousSpend: false,
        bindingActionsHumanGated: true
      }
    });
  }

  return null;
}

export const TRAVEL_CONSUMER_DESTINATIONS = DESTINATIONS;
