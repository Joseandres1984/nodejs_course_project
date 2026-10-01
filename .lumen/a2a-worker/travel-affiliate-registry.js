const VERSION = "1.1-travel-affiliate-registry";
const DEFAULT_INTUI_AFFILIATE_URL = "https://intui.tpo.lu/bAzIRmam";
const DEFAULT_AIRALO_AFFILIATE_URL = "https://airalo.tpo.lu/iqbQnTg6";

function clean(value, limit = 1400) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function safeUrl(value) {
  const raw = clean(value, 1400);
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (!/^https:$/.test(url.protocol)) return null;
    return url.toString();
  } catch {
    return null;
  }
}

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "content-type",
      "access-control-allow-methods": "GET,OPTIONS"
    }
  });
}

export function listTravelAffiliateOffers(env = {}) {
  const offers = [
    {
      id: "intui-transfer",
      category: "TRANSFER",
      brand: "Intui.travel",
      commissionModel: "AFFILIATE_REWARD",
      publicBenchmark: "Travelpayouts partner program",
      configuredUrl: safeUrl(env?.INTUI_AFFILIATE_URL || DEFAULT_INTUI_AFFILIATE_URL),
      requiresApplication: true,
      bookingOnPartnerSite: true
    },
    {
      id: "airalo-esim",
      category: "ESIM",
      brand: "Airalo",
      commissionModel: "PERCENT_OF_SALE",
      publicBenchmark: "Travelpayouts partner program",
      configuredUrl: safeUrl(env?.AIRALO_AFFILIATE_URL || DEFAULT_AIRALO_AFFILIATE_URL),
      requiresApplication: true,
      bookingOnPartnerSite: true
    },
    {
      id: "qeeq-car-rental",
      category: "CAR_RENTAL",
      brand: "QEEQ",
      commissionModel: "AFFILIATE_REWARD",
      publicBenchmark: "Travelpayouts partner program",
      configuredUrl: safeUrl(env?.QEEQ_AFFILIATE_URL),
      requiresApplication: true,
      bookingOnPartnerSite: true
    },
    {
      id: "safetywing-insurance",
      category: "TRAVEL_INSURANCE",
      brand: "SafetyWing",
      commissionModel: "AFFILIATE_FEE",
      publicBenchmark: "approximately 10% of total premium",
      configuredUrl: safeUrl(env?.SAFETYWING_AMBASSADOR_URL),
      requiresApplication: true,
      bookingOnPartnerSite: true
    },
    {
      id: "discovercars-rental",
      category: "CAR_RENTAL",
      brand: "DiscoverCars",
      commissionModel: "REVENUE_SHARE",
      publicBenchmark: "~USD 20 average commission per booking",
      configuredUrl: safeUrl(env?.DISCOVERCARS_AFFILIATE_URL),
      requiresApplication: true,
      bookingOnPartnerSite: true
    }
  ];

  return offers.map(offer => ({
    ...offer,
    enabled: Boolean(offer.configuredUrl),
    affiliateUrl: offer.configuredUrl || null
  }));
}

export async function handleTravelAffiliateRegistry(request, env) {
  const url = new URL(request.url);

  if (request.method === "OPTIONS" && url.pathname.startsWith("/travel/affiliates")) {
    return new Response(null, {
      status: 204,
      headers: {
        "access-control-allow-origin": "*",
        "access-control-allow-headers": "content-type",
        "access-control-allow-methods": "GET,OPTIONS"
      }
    });
  }

  if (request.method === "GET" && url.pathname === "/travel/affiliates/policy") {
    const offers = listTravelAffiliateOffers(env);
    return json({
      version: VERSION,
      model: "configured_partner_links_only",
      enabledOffers: offers.filter(x => x.enabled).length,
      totalKnownOffers: offers.length,
      noSyntheticAffiliateIds: true,
      noAutomaticEnrollment: true,
      noBookingAuthority: true,
      createsCharge: false,
      autonomousSpend: false
    });
  }

  if (request.method === "GET" && url.pathname === "/travel/affiliates") {
    return json({ version: VERSION, offers: listTravelAffiliateOffers(env) });
  }

  return null;
}
