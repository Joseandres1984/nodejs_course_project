const CONTRACT_VERSION = "1.0";
const CURRENCY = "USD";

function clean(value, limit = 400) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function clamp(value, min = 0, max = 1) {
  const n = Number(value);
  if (!Number.isFinite(n)) return min;
  return Math.max(min, Math.min(max, n));
}

function round(value) {
  return Math.max(0, Math.round(Number(value) || 0));
}

function nextYearMonth(targetMonth, now = new Date()) {
  const month = Math.max(1, Math.min(12, Math.round(Number(targetMonth) || 1)));
  const currentMonth = now.getUTCMonth() + 1;
  const year = month < currentMonth ? now.getUTCFullYear() + 1 : now.getUTCFullYear();
  return `${year}-${String(month).padStart(2, "0")}`;
}

function safeJson(value, fallback = {}) {
  if (!value) return fallback;
  try { return JSON.parse(value); } catch { return fallback; }
}

function safeHttps(value) {
  const raw = clean(value, 2400);
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function ddmm(value) {
  const raw = clean(value, 80);
  if (!raw) return "";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "";
  return `${String(date.getUTCDate()).padStart(2, "0")}${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

function aviasalesSearchUrl(input, destination, best = {}) {
  const origin = clean(input?.originCode, 8).toUpperCase();
  const target = clean(destination?.code, 8).toUpperCase();
  const adults = Math.max(1, Math.min(8, Math.round(Number(input?.travelersCount) || 1)));
  if (!origin || !target) return null;

  const departure = ddmm(best?.departure_at);
  const returnDate = ddmm(best?.return_at);
  if (departure) {
    const params = `${origin}${departure}${target}${returnDate}${adults}`;
    return `https://www.aviasales.com/search/${params}`;
  }
  return `https://www.aviasales.com/?params=${origin}${target}${adults}`;
}

function travelpayoutsPartnerLinkConfig(env = {}) {
  const projectId = Number(clean(env?.TRAVELPAYOUTS_PROJECT_ID, 40));
  const marker = Number(clean(env?.TRAVELPAYOUTS_MARKER, 40));
  const token = clean(env?.TRAVELPAYOUTS_API_TOKEN, 500);
  return {
    projectId,
    marker,
    token,
    configured: Boolean(token && Number.isInteger(projectId) && projectId > 0 && Number.isInteger(marker) && marker > 0)
  };
}

async function convertTravelpayoutsPartnerLink(env, fetchImpl, targetUrl, subId) {
  const config = travelpayoutsPartnerLinkConfig(env);
  const url = safeHttps(targetUrl);
  if (!config.configured || !url) return null;

  try {
    const response = await fetchImpl("https://api.travelpayouts.com/links/v1/create", {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        "X-Access-Token": config.token
      },
      body: JSON.stringify({
        trs: config.projectId,
        marker: config.marker,
        shorten: true,
        links: [{ url, sub_id: clean(subId, 80) || "lumen_flight" }]
      })
    });
    if (!response.ok) return null;
    const payload = await response.json().catch(() => ({}));
    const row = payload?.result?.links?.[0];
    if (row?.code !== "success") return null;
    return safeHttps(row?.partner_url);
  } catch {
    return null;
  }
}

function quoteEnvelope(provider, component, amountUSD, unitAmountUSD, quantity, confidence, sourceReference, extras = {}) {
  return {
    component,
    providerId: provider.id,
    providerName: provider.name,
    providerMode: provider.mode,
    contractVersion: CONTRACT_VERSION,
    currency: CURRENCY,
    amountUSD: round(amountUSD),
    unitAmountUSD: round(unitAmountUSD),
    quantity: Number(quantity) || 0,
    confidence: Number(clamp(confidence, 0.25, 0.95).toFixed(2)),
    isRealtime: Boolean(extras.isRealtime),
    bookable: false,
    affiliateEligible: Boolean(extras.affiliateEligible),
    affiliateUrl: extras.affiliateUrl || null,
    retrievedAt: new Date().toISOString(),
    expiresAt: extras.expiresAt || null,
    sourceReference: clean(sourceReference, 300) || null,
    evidence: extras.evidence || null
  };
}

function aviasalesProvider(env, fetchImpl) {
  const token = clean(env?.TRAVELPAYOUTS_API_TOKEN, 500);
  if (!token) return null;
  const partnerConfig = travelpayoutsPartnerLinkConfig(env);

  return {
    id: "aviasales-data-v2",
    name: "Aviasales Data + Travelpayouts Deep Links",
    component: "FLIGHT",
    mode: "CACHED_MARKET_DATA",
    supportsRealtime: false,
    supportsBooking: false,
    supportsAffiliate: partnerConfig.configured,
    externalNetworkCalls: true,
    requiresSecret: true,
    async quote({ input, destination }) {
      const month = nextYearMonth(input.targetMonth);
      const url = new URL("https://api.travelpayouts.com/aviasales/v3/grouped_prices");
      url.searchParams.set("currency", "usd");
      url.searchParams.set("origin", input.originCode);
      url.searchParams.set("destination", destination.code);
      url.searchParams.set("group_by", "departure_at");
      url.searchParams.set("departure_at", month);
      url.searchParams.set("direct", "false");
      url.searchParams.set("min_trip_duration", String(input.durationDays));
      url.searchParams.set("max_trip_duration", String(input.durationDays));
      url.searchParams.set("token", token);

      const response = await fetchImpl(url.toString(), { headers: { accept: "application/json" } });
      if (!response.ok) throw new Error(`aviasales_http_${response.status}`);
      const payload = await response.json();
      if (!payload?.success || !payload?.data || typeof payload.data !== "object") throw new Error("aviasales_no_data");

      const offers = Object.values(payload.data)
        .filter(Boolean)
        .map(item => ({ ...item, price: Number(item?.price) }))
        .filter(item => Number.isFinite(item.price) && item.price > 0)
        .sort((a, b) => a.price - b.price);
      if (!offers.length) throw new Error("aviasales_no_offer");

      const best = offers[0];
      const travelers = input.travelersCount;
      const amountUSD = best.price * travelers;
      const searchUrl = aviasalesSearchUrl(input, destination, best);
      const subId = `lumen_flight_${clean(input.originCode, 8).toLowerCase()}_${clean(destination.code, 8).toLowerCase()}`;
      const affiliateUrl = await convertTravelpayoutsPartnerLink(env, fetchImpl, searchUrl, subId);

      return quoteEnvelope(this, this.component, amountUSD, best.price, travelers, 0.8, `aviasales:${input.originCode}-${destination.code}:${month}`, {
        isRealtime: false,
        affiliateEligible: Boolean(affiliateUrl),
        affiliateUrl,
        evidence: {
          departureAt: best.departure_at || null,
          returnAt: best.return_at || null,
          airline: best.airline || null,
          transfers: Number.isFinite(Number(best.transfers)) ? Number(best.transfers) : null,
          returnTransfers: Number.isFinite(Number(best.return_transfers)) ? Number(best.return_transfers) : null,
          cacheWindow: "recent_user_search_data",
          searchUrl,
          routeSpecificSearch: Boolean(ddmm(best?.departure_at)),
          affiliateStrategy: affiliateUrl ? "travelpayouts_partner_links_api" : "registry_fallback",
          affiliateSubId: subId
        }
      });
    },
    buildAffiliateLink() { return null; }
  };
}

function viatorProvider(env, fetchImpl) {
  const apiKey = clean(env?.VIATOR_API_KEY, 500);
  const destinationMap = safeJson(env?.VIATOR_DESTINATION_MAP_JSON, {});
  if (!apiKey || !Object.keys(destinationMap).length) return null;

  return {
    id: "viator-basic-affiliate-v1",
    name: "Viator Basic Affiliate API",
    component: "ACTIVITIES",
    mode: "AFFILIATE_CATALOG",
    supportsRealtime: false,
    supportsBooking: false,
    supportsAffiliate: true,
    externalNetworkCalls: true,
    requiresSecret: true,
    async quote({ input, destination }) {
      const destinationRef = clean(destinationMap[destination.code], 40);
      if (!destinationRef) throw new Error("viator_destination_unmapped");
      const campaign = clean(env?.VIATOR_CAMPAIGN_VALUE || "lumen-travel", 120);
      const url = new URL("https://api.viator.com/partner/products/search");
      if (campaign) url.searchParams.set("campaign-value", campaign);

      const response = await fetchImpl(url.toString(), {
        method: "POST",
        headers: {
          "accept-language": "es-AR",
          "content-type": "application/json",
          accept: "application/json;version=2.0",
          "exp-api-key": apiKey
        },
        body: JSON.stringify({
          filtering: { destination: destinationRef },
          sorting: { sort: "PRICE", order: "ASCENDING" },
          pagination: { start: 1, count: 5 },
          currency: "USD"
        })
      });
      if (!response.ok) throw new Error(`viator_http_${response.status}`);
      const payload = await response.json();
      const products = Array.isArray(payload?.products) ? payload.products : [];
      const priced = products
        .map(product => ({
          product,
          price: Number(product?.pricing?.summary?.fromPrice),
          currency: clean(product?.pricing?.currency, 10).toUpperCase()
        }))
        .filter(item => Number.isFinite(item.price) && item.price > 0 && item.currency === "USD")
        .sort((a, b) => a.price - b.price);
      if (!priced.length) throw new Error("viator_no_priced_products");

      const sample = priced.slice(0, 3);
      const median = sample[Math.floor(sample.length / 2)];
      const plannedExperiencesPerTraveler = Math.max(1, Math.min(4, Math.ceil(input.durationDays / 3)));
      const quantity = plannedExperiencesPerTraveler * input.travelersCount;
      const amountUSD = median.price * quantity;
      const productUrl = clean(median.product?.productUrl, 1500) || null;

      return quoteEnvelope(this, this.component, amountUSD, median.price, quantity, 0.72, `viator:${destination.code}:${destinationRef}`, {
        isRealtime: false,
        affiliateEligible: Boolean(productUrl),
        affiliateUrl: productUrl,
        evidence: {
          destinationRef,
          productCode: median.product?.productCode || null,
          title: clean(median.product?.title, 180) || null,
          fromPriceUSD: round(median.price),
          sampledProducts: sample.length,
          plannedExperiencesPerTraveler,
          pricingSemantics: "catalog_from_price_estimate"
        }
      });
    },
    buildAffiliateLink() { return null; }
  };
}

export function createExternalTravelProviders(env = {}, fetchImpl = fetch) {
  return [aviasalesProvider(env, fetchImpl), viatorProvider(env, fetchImpl)].filter(Boolean);
}

export function getExternalTravelProviderStatus(env = {}) {
  const viatorMap = safeJson(env?.VIATOR_DESTINATION_MAP_JSON, {});
  const partnerConfig = travelpayoutsPartnerLinkConfig(env);
  return {
    version: "1.1-external-travel-providers",
    providers: [
      {
        id: "aviasales-data-v2",
        component: "FLIGHT",
        configured: Boolean(clean(env?.TRAVELPAYOUTS_API_TOKEN, 500)),
        mode: "CACHED_MARKET_DATA",
        realTime: false,
        booking: false,
        dynamicDeepLinksConfigured: partnerConfig.configured,
        affiliateLinkConfigured: partnerConfig.configured || Boolean(clean(env?.TRAVELPAYOUTS_AVIASALES_FALLBACK_URL, 1800)),
        genericAffiliateFallbackConfigured: Boolean(clean(env?.TRAVELPAYOUTS_AVIASALES_FALLBACK_URL, 1800))
      },
      {
        id: "viator-basic-affiliate-v1",
        component: "ACTIVITIES",
        configured: Boolean(clean(env?.VIATOR_API_KEY, 500) && Object.keys(viatorMap).length),
        mappedDestinations: Object.keys(viatorMap).length,
        mode: "AFFILIATE_CATALOG",
        realTime: false,
        booking: false,
        affiliateLinkConfigured: Boolean(clean(env?.VIATOR_API_KEY, 500) && Object.keys(viatorMap).length)
      }
    ],
    guardrails: {
      disabledWithoutCredentials: true,
      secretsReturned: false,
      createsBooking: false,
      createsCharge: false,
      autonomousSpend: false
    }
  };
}
