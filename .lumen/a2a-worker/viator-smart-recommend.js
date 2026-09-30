import { getViatorApiStatus, getViatorDestinations, searchViatorProducts } from "./viator-api.js";
import { planTravelAffiliateIntent } from "./travel-affiliate-orchestrator.js";

const VERSION = "1.1-viator-smart-recommend";
const DESTINATION_CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const PRODUCT_SEARCH_COUNT = 30;
const MAX_RECOMMENDATIONS = 4;

let memoryDestinations = { expiresAt: 0, environment: "", rows: [] };

function clean(value, limit = 4000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*"
    }
  });
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

function normalized(value) {
  return clean(value, 300)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function destinationRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.destinations)) return data.destinations;
  return [];
}

async function loadDestinations(env) {
  const status = getViatorApiStatus(env);
  const now = Date.now();
  if (memoryDestinations.environment === status.environment && memoryDestinations.expiresAt > now && memoryDestinations.rows.length) {
    return memoryDestinations.rows;
  }

  const cacheKey = new Request(`https://lumen.internal/cache/viator-destinations/${status.environment}`);
  try {
    if (typeof caches !== "undefined" && caches?.default) {
      const hit = await caches.default.match(cacheKey);
      if (hit) {
        const cached = await hit.json();
        const rows = destinationRows(cached);
        if (rows.length) {
          memoryDestinations = { environment: status.environment, expiresAt: now + DESTINATION_CACHE_TTL_MS, rows };
          return rows;
        }
      }
    }
  } catch {}

  const result = await getViatorDestinations(env);
  const rows = destinationRows(result.data);
  memoryDestinations = { environment: status.environment, expiresAt: now + DESTINATION_CACHE_TTL_MS, rows };

  try {
    if (typeof caches !== "undefined" && caches?.default && rows.length) {
      const response = Response.json({ destinations: rows }, {
        headers: { "cache-control": "public, max-age=604800", "content-type": "application/json; charset=utf-8" }
      });
      await caches.default.put(cacheKey, response);
    }
  } catch {}

  return rows;
}

function destinationTypeWeight(type) {
  const value = clean(type, 80).toUpperCase();
  if (value === "CITY") return 8;
  if (value === "TOWN") return 7;
  if (value === "ISLAND") return 6;
  if (value === "REGION" || value === "PROVINCE" || value === "STATE") return 5;
  if (value === "COUNTRY") return 4;
  return 1;
}

function resolveDestination(rows, destinationName) {
  const needle = normalized(destinationName);
  if (!needle) return null;
  const ranked = rows
    .map(item => {
      const name = normalized(item?.name);
      if (!name) return null;
      let match = 0;
      if (name === needle) match = 100;
      else if (name.startsWith(needle) || needle.startsWith(name)) match = 80;
      else if (name.includes(needle) || needle.includes(name)) match = 60;
      if (!match) return null;
      return { item, score: match + destinationTypeWeight(item?.type) };
    })
    .filter(Boolean)
    .sort((a, b) => b.score - a.score);
  return ranked[0]?.item || null;
}

function queryTerms(text, destination) {
  const stop = new Set([
    "quiero","queremos","viaje","viajar","vacaciones","turismo","tour","actividad","actividades","experiencia","experiencias","excursion","excursión",
    "travel","trip","vacation","holiday","activity","activities","experience","experiences","the","and","with","from","para","por","con","una","uno","un","las","los","del","que","qué","hacer"
  ]);
  const destinationTerms = new Set(normalized(destination).split(/\s+/).filter(Boolean));
  return [...new Set(normalized(text).split(/[^a-z0-9]+/).filter(term => term.length >= 3 && !stop.has(term) && !destinationTerms.has(term)))].slice(0, 10);
}

function numberValue(...values) {
  for (const value of values) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function bestImage(product) {
  const images = Array.isArray(product?.images) ? product.images : [];
  const candidates = [];
  for (const image of images) {
    if (clean(image?.url, 1000)) candidates.push({ url: clean(image.url, 1000), width: numberValue(image?.width) || 0 });
    const variants = Array.isArray(image?.variants) ? image.variants : [];
    for (const variant of variants) {
      const url = clean(variant?.url, 1000);
      if (url) candidates.push({ url, width: numberValue(variant?.width) || 0 });
    }
  }
  candidates.sort((a, b) => b.width - a.width);
  return candidates[0]?.url || null;
}

function safeProductUrl(value) {
  const raw = clean(value, 2000);
  if (!raw) return null;
  try {
    const url = new URL(raw);
    const host = url.hostname.toLowerCase();
    if (url.protocol !== "https:" || !(host === "viator.com" || host.endsWith(".viator.com"))) return null;
    return url.toString();
  } catch {
    return null;
  }
}

function normalizeProduct(product, index, terms, currency) {
  const title = clean(product?.title, 500);
  const description = clean(product?.description, 1200);
  const haystack = normalized(`${title} ${description}`);
  const termHits = terms.filter(term => haystack.includes(term)).length;
  const rating = numberValue(
    product?.reviews?.combinedAverageRating,
    product?.reviews?.averageRating,
    product?.reviewSummary?.combinedAverageRating,
    product?.rating
  );
  const reviewCount = numberValue(
    product?.reviews?.totalReviews,
    product?.reviews?.reviewCount,
    product?.reviewSummary?.totalReviews,
    product?.reviewCount
  );
  const fromPrice = numberValue(
    product?.pricing?.summary?.fromPrice,
    product?.pricing?.fromPrice,
    product?.fromPrice
  );
  const flags = Array.isArray(product?.flags) ? product.flags.map(v => clean(v, 80)).filter(Boolean) : [];
  const durationMinutes = numberValue(
    product?.duration?.fixedDurationInMinutes,
    product?.duration?.variableDurationFromMinutes,
    product?.itineraryDuration?.fixedDurationInMinutes
  );
  const productUrl = safeProductUrl(product?.productUrl);

  const ratingScore = rating === null ? 25 : Math.max(0, Math.min(50, rating * 10));
  const reviewScore = reviewCount === null ? 0 : Math.min(20, Math.log10(reviewCount + 1) * 6);
  const intentScore = Math.min(24, termHits * 8);
  const commercialScore = flags.includes("FREE_CANCELLATION") ? 3 : 0;
  const featuredScore = Math.max(0, 3 - index * 0.15);
  const score = Math.round(Math.max(1, Math.min(100, ratingScore + reviewScore + intentScore + commercialScore + featuredScore)));

  return {
    productCode: clean(product?.productCode, 120) || null,
    title: title || null,
    description: description || null,
    imageUrl: bestImage(product),
    rating,
    reviewCount,
    fromPrice,
    currency: clean(product?.pricing?.currency, 20) || clean(currency, 20) || "USD",
    durationMinutes,
    flags,
    provider: "viator",
    productSpecific: true,
    affiliateUrl: productUrl,
    score
  };
}

function fallbackPlan(text, env, reason, apiStatus) {
  const fallback = planTravelAffiliateIntent(text, env);
  return {
    ...fallback,
    version: VERSION,
    apiConfigured: Boolean(apiStatus?.configured),
    apiEnvironment: apiStatus?.environment || "sandbox",
    productLevelRanking: false,
    searchMode: "affiliate_search_fallback",
    apiFallbackReason: clean(reason, 220) || "viator_api_unavailable"
  };
}

export async function recommendViatorProducts(text, env = {}) {
  const apiStatus = getViatorApiStatus(env);
  let basePlan;
  try {
    basePlan = planTravelAffiliateIntent(text, env);
  } catch (error) {
    error.status = 400;
    throw error;
  }

  if (!apiStatus.configured) return fallbackPlan(text, env, "viator_api_key_not_configured", apiStatus);
  if (!basePlan.destination) return fallbackPlan(text, env, "destination_not_resolved", apiStatus);

  try {
    const destinations = await loadDestinations(env);
    const destination = resolveDestination(destinations, basePlan.destination);
    if (!destination?.destinationId) return fallbackPlan(text, env, "viator_destination_not_found", apiStatus);

    const currency = clean(env?.VIATOR_API_CURRENCY, 20) || "USD";
    const payload = {
      filtering: { destination: String(destination.destinationId) },
      sorting: { sort: "DEFAULT", order: "ASCENDING" },
      pagination: { start: 1, count: PRODUCT_SEARCH_COUNT },
      currency
    };
    const result = await searchViatorProducts(env, payload);
    const products = Array.isArray(result?.data?.products) ? result.data.products : [];
    const terms = queryTerms(text, basePlan.destination);
    const recommendations = products
      .map((product, index) => normalizeProduct(product, index, terms, currency))
      .filter(item => item.productCode && item.title && item.affiliateUrl)
      .sort((a, b) => b.score - a.score || (b.reviewCount || 0) - (a.reviewCount || 0))
      .slice(0, MAX_RECOMMENDATIONS)
      .map((item, index) => ({ ...item, rank: index + 1 }));

    if (!recommendations.length) return fallbackPlan(text, env, "viator_search_returned_no_attributed_products", apiStatus);

    return {
      ok: true,
      version: VERSION,
      travelIntentDetected: true,
      destination: clean(destination?.name, 200) || basePlan.destination,
      destinationId: destination.destinationId,
      sourceSummary: basePlan.sourceSummary,
      bestPick: recommendations[0],
      recommendations,
      apiConfigured: true,
      apiEnvironment: apiStatus.environment,
      productLevelRanking: true,
      searchMode: "viator_partner_api_products_search",
      affiliateAttributionSource: "viator_productUrl",
      trackingId: result.trackingId || null,
      rateLimitRemaining: result.rateLimitRemaining || null,
      monetization: {
        model: "viator_affiliate_api",
        linksMonetized: recommendations.length,
        bookingAuthority: false,
        paymentAuthority: false,
        autonomousSpendUsd: 0
      },
      note: "Product recommendations are retrieved from Viator Partner API and checkout remains on Viator."
    };
  } catch (error) {
    return fallbackPlan(text, env, clean(error?.message || error, 220), apiStatus);
  }
}

export async function handleViatorSmartRecommend(request, env) {
  const url = new URL(request.url);
  if (!["/travel/affiliate/policy", "/travel/affiliate/recommend", "/travel/affiliate/plan"].includes(url.pathname)) return null;

  const apiStatus = getViatorApiStatus(env);

  if (request.method === "GET" && url.pathname === "/travel/affiliate/policy") {
    return json({
      version: VERSION,
      name: "LUMEN Travel Affiliate API Recommender",
      provider: "viator",
      apiConfigured: apiStatus.configured,
      apiEnvironment: apiStatus.environment,
      behavior: [
        "detect travel intent",
        "resolve Viator destination",
        "retrieve product summaries with Partner API",
        "rank product-level recommendations",
        "use Viator productUrl for affiliate attribution",
        "fall back to affiliate search links when API is unavailable"
      ],
      productLevelRanking: apiStatus.configured,
      searchMode: apiStatus.configured ? "viator_partner_api_products_search" : "affiliate_search_fallback",
      affiliateAttributionSource: apiStatus.configured ? "viator_productUrl" : "selector_deep_link",
      scraping: false,
      bookingAuthority: false,
      paymentAuthority: false,
      autonomousPurchase: false,
      autonomousSpendUsd: 0,
      externalMessagesCreated: 0
    });
  }

  if (request.method === "GET" && url.pathname === "/travel/affiliate/recommend") {
    try {
      return json(await recommendViatorProducts(url.searchParams.get("text") || "", env));
    } catch (error) {
      return json({ ok: false, error: clean(error?.message || error, 180), version: VERSION }, Number(error?.status || 400));
    }
  }

  if (url.pathname === "/travel/affiliate/plan") {
    if (!authorized(request, env)) return json({ ok: false, error: "unauthorized", version: VERSION }, 401);
    if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed", version: VERSION }, 405);
    let payload = {};
    try { payload = await request.json(); } catch {}
    try {
      return json(await recommendViatorProducts(payload?.text || "", env));
    } catch (error) {
      return json({ ok: false, error: clean(error?.message || error, 180), version: VERSION }, Number(error?.status || 400));
    }
  }

  return null;
}
