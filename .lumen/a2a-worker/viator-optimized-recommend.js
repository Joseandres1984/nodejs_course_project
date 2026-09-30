import { viatorApiRequest } from "./viator-api.js";
import { recommendViatorProducts } from "./viator-smart-recommend.js";

const VERSION = "1.0-viator-optimized-recommend";
const PUBLIC_A2A_ORIGIN = "https://lumen-zero-a2a.lumen-b2b.workers.dev";
const MIN_CONFIRMATIONS = 3;
const MIN_CLICKS = 20;
const WINNER_SHARE = 0.8;
const CTA_VARIANTS = {
  price_availability_v1: "Ver precio y disponibilidad",
  dates_available_v1: "Ver fechas disponibles"
};

function clean(value, limit = 4000) {
  return String(value ?? "").trim().slice(0, limit);
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

async function rows(env, sql) {
  try {
    const result = await env.DB.prepare(sql).all();
    return result.results || [];
  } catch {
    return [];
  }
}

async function variantPolicy(env) {
  if (!env?.DB) return { winner: null, selected: null, exploration: false, evidence: [] };
  const [bookingRows, clickRows] = await Promise.all([
    rows(env, "SELECT CASE WHEN campaign_value LIKE '%price_availability_v1%' THEN 'price_availability_v1' WHEN campaign_value LIKE '%dates_available_v1%' THEN 'dates_available_v1' ELSE 'other' END variant,SUM(CASE WHEN event_type='CONFIRMATION' THEN 1 ELSE 0 END) confirmations FROM lumen_viator_booking_events GROUP BY variant"),
    rows(env, "SELECT COALESCE(NULLIF(variant,''),'other') variant,COUNT(*) clicks FROM lumen_travel_events WHERE event_type='click' GROUP BY COALESCE(NULLIF(variant,''),'other')")
  ]);
  const clicks = new Map(clickRows.map(row => [String(row.variant), Number(row.clicks || 0)]));
  const evidence = bookingRows
    .filter(row => CTA_VARIANTS[String(row.variant)])
    .map(row => {
      const variant = String(row.variant);
      const confirmations = Number(row.confirmations || 0);
      const clickCount = clicks.get(variant) || 0;
      return {
        variant,
        confirmations,
        clicks: clickCount,
        cvr: clickCount > 0 ? confirmations / clickCount : 0
      };
    })
    .sort((a, b) => b.cvr - a.cvr || b.confirmations - a.confirmations || b.clicks - a.clicks);

  const winner = evidence.find(row => row.confirmations >= MIN_CONFIRMATIONS && row.clicks >= MIN_CLICKS) || null;
  if (!winner) return { winner: null, selected: null, exploration: false, evidence };

  const alternate = Object.keys(CTA_VARIANTS).find(id => id !== winner.variant) || winner.variant;
  const exploration = Math.random() >= WINNER_SHARE;
  return {
    winner: winner.variant,
    selected: exploration ? alternate : winner.variant,
    exploration,
    evidence
  };
}

function providerCampaign(destinationId, variant) {
  return clean(`lumen_travel_${variant}_${destinationId || "generic"}`, 200)
    .replace(/[^A-Za-z0-9_]/g, "_")
    .slice(0, 200);
}

function trackedClickUrl(targetUrl, plan, campaign, variant, productId) {
  try {
    const tracked = new URL("/go/viator", PUBLIC_A2A_ORIGIN);
    tracked.searchParams.set("url", targetUrl);
    tracked.searchParams.set("source", "travel_recommender");
    tracked.searchParams.set("campaign", campaign);
    tracked.searchParams.set("variant", variant);
    tracked.searchParams.set("preserve", "1");
    if (plan?.destination) tracked.searchParams.set("destination", clean(plan.destination, 160));
    if (productId) tracked.searchParams.set("product_id", clean(productId, 180));
    return tracked.toString();
  } catch {
    return targetUrl;
  }
}

function productRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.products)) return data.products;
  return [];
}

async function reattributePlan(env, plan, selectedVariant, optimization) {
  const recommendations = Array.isArray(plan?.recommendations) ? plan.recommendations : [];
  const productCodes = recommendations.map(row => clean(row?.productCode, 160)).filter(Boolean);
  if (!plan?.destinationId || !productCodes.length || recommendations.some(row => row?.productSpecific !== true)) return plan;

  const campaign = providerCampaign(plan.destinationId, selectedVariant);
  try {
    const result = await viatorApiRequest(env, "/products/bulk", {
      method: "POST",
      query: { "campaign-value": campaign },
      body: { productCodes }
    });
    const products = productRows(result.data);
    const byCode = new Map(products.map(row => [clean(row?.productCode, 160), clean(row?.productUrl, 2400)]));
    if (!byCode.size) return plan;

    const updated = recommendations.map(row => {
      const code = clean(row?.productCode, 160);
      const providerUrl = byCode.get(code);
      if (!providerUrl) return row;
      return {
        ...row,
        providerAffiliateUrl: providerUrl,
        affiliateUrl: trackedClickUrl(providerUrl, plan, campaign, selectedVariant, code),
        ctaLabel: CTA_VARIANTS[selectedVariant],
        ctaVariant: selectedVariant
      };
    });

    return {
      ...plan,
      bestPick: updated[0] || plan.bestPick,
      recommendations: updated,
      clickTracking: {
        ...(plan.clickTracking || {}),
        campaign,
        providerCampaign: campaign,
        variant: selectedVariant,
        ctaLabel: CTA_VARIANTS[selectedVariant],
        optimizationMode: optimization.exploration ? "exploration" : "winner_preference",
        winnerVariant: optimization.winner,
        winnerSharePct: Math.round(WINNER_SHARE * 100),
        providerProductUrlPreserved: true
      },
      conversionOptimization: {
        active: true,
        winnerVariant: optimization.winner,
        selectedVariant,
        exploration: optimization.exploration,
        winnerSharePct: Math.round(WINNER_SHARE * 100),
        minimumEvidence: { confirmations: MIN_CONFIRMATIONS, clicks: MIN_CLICKS },
        noFabricatedSignificance: true
      }
    };
  } catch {
    return plan;
  }
}

async function recordDisplayEvents(env, plan) {
  if (!env?.DB || !plan?.clickTracking) return;
  try {
    await env.DB.batch([
      env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_events (id TEXT PRIMARY KEY,event_type TEXT NOT NULL,provider TEXT NOT NULL DEFAULT 'viator',source TEXT,campaign TEXT,variant TEXT,destination TEXT,product_id TEXT,target_url TEXT,created_at TEXT NOT NULL)"),
      env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_travel_events_type_created ON lumen_travel_events(event_type,created_at DESC)"),
      env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_travel_events_product_created ON lumen_travel_events(product_id,created_at DESC)")
    ]);
    const now = new Date().toISOString();
    const statements = [
      env.DB.prepare("INSERT INTO lumen_travel_events(id,event_type,provider,source,campaign,variant,destination,product_id,target_url,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)")
        .bind(crypto.randomUUID(), "impression", "viator", plan.clickTracking.source || "travel_recommender", plan.clickTracking.campaign || "", plan.clickTracking.variant || "", clean(plan.destination, 160), "", "", now)
    ];
    for (const row of (Array.isArray(plan.recommendations) ? plan.recommendations : [])) {
      statements.push(
        env.DB.prepare("INSERT INTO lumen_travel_events(id,event_type,provider,source,campaign,variant,destination,product_id,target_url,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)")
          .bind(crypto.randomUUID(), "result_shown", "viator", plan.clickTracking.source || "travel_recommender", plan.clickTracking.campaign || "", plan.clickTracking.variant || "", clean(plan.destination, 160), clean(row?.productCode, 180), clean(row?.providerAffiliateUrl, 2400), now)
      );
    }
    await env.DB.batch(statements);
  } catch {
    // Measurement remains best-effort and must not block recommendations.
  }
}

async function optimizedPlan(text, env) {
  const base = await recommendViatorProducts(text, env);
  const optimization = await variantPolicy(env);
  let plan = base;
  if (optimization.selected && optimization.selected !== base?.clickTracking?.variant) {
    plan = await reattributePlan(env, base, optimization.selected, optimization);
  } else if (optimization.winner) {
    plan = {
      ...base,
      conversionOptimization: {
        active: true,
        winnerVariant: optimization.winner,
        selectedVariant: base?.clickTracking?.variant || optimization.selected,
        exploration: Boolean(optimization.exploration),
        winnerSharePct: Math.round(WINNER_SHARE * 100),
        minimumEvidence: { confirmations: MIN_CONFIRMATIONS, clicks: MIN_CLICKS },
        noFabricatedSignificance: true
      }
    };
  } else {
    plan = {
      ...base,
      conversionOptimization: {
        active: false,
        policy: "collect_more_evidence",
        minimumEvidence: { confirmations: MIN_CONFIRMATIONS, clicks: MIN_CLICKS },
        noFabricatedSignificance: true
      }
    };
  }
  return plan;
}

export async function handleViatorOptimizedRecommend(request, env) {
  const url = new URL(request.url);
  if (!["/travel/affiliate/recommend", "/travel/affiliate/plan"].includes(url.pathname)) return null;

  if (request.method === "GET" && url.pathname === "/travel/affiliate/recommend") {
    try {
      const plan = await optimizedPlan(url.searchParams.get("text") || "", env);
      await recordDisplayEvents(env, plan);
      return json(plan);
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
      return json(await optimizedPlan(payload?.text || "", env));
    } catch (error) {
      return json({ ok: false, error: clean(error?.message || error, 180), version: VERSION }, Number(error?.status || 400));
    }
  }

  return null;
}
