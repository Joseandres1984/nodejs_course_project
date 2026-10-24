// LUMEN Affiliate Sales v1 — read-only, zero-spend campaign planner.
// Sales are never inferred from clicks, impressions, posts or test runs.
// External publishing is separately performed only on authorized connected channels.
export const AFFILIATE_POLICY = Object.freeze({
  version: "1.0-amazon-affiliate-sales-reviewable",
  brand: "LUMEN B2B",
  marketplace: "amazon.com",
  trackingId: "lumenb2b-20",
  channel: "instagram",
  channelHandle: "lumen.b2b",
  intendedMarket: "US",
  outgoingSpendUsd: 0,
  autonomousAds: false,
  autonomousPurchases: false,
  unsolicitedOutreach: false,
  directAffiliateLinkRequired: true,
  noUnverifiedPricesOrInventory: true,
  noFabricatedReviewsOrPurchases: true,
  noRevenueUntilOfficialReport: true,
  noUnverifiedClaimsOrFirstHandTesting: true,
  imageIllustrationsMustBeLabeled: true,
  ownerApprovalForNewChannels: true,
  ownerApprovalForPaidPromotion: true,
  postsFromThisModule: 0
});

export const AFFILIATE_PRODUCTS = Object.freeze([
  Object.freeze({
    id: "ninja-slushi-fs301",
    name: "Ninja SLUSHi Frozen Drink Maker",
    asin: "B0D2LZYQ2M",
    merchant: "Amazon.com",
    brand: "Ninja",
    market: "US",
    features: Object.freeze(["RapidChill technology", "Five preset programs", "No ice required with compatible drinks"]),
    offerCondition: "NOT_VERIFIED",
    livePriceUsd: null,
    confirmedCommissionPct: null,
    recentUnitsVerified: null,
    amazonOfficialSalesReportVerified: false,
    editorialStatus: "REVIEWABLE_CREATIVE",
    evidenceNote: "Amazon Associates link tag confirmed by owner; live listing price, new-condition offer and category commission not independently verified"
  })
]);
export function specialLink(asin, trackingId = AFFILIATE_POLICY.trackingId) {
  if (!/^[A-Z0-9]{10}$/.test(String(asin))) throw Error("invalid_asin");
  if (!/^[a-z0-9-]+-20$/.test(String(trackingId))) throw Error("invalid_tracking_id");
  return "https://www.amazon.com/dp/" + asin + "?tag=" + encodeURIComponent(trackingId);
}
export function qualifyAffiliateProduct(item) {
  const blockers = [];
  if (!item || typeof item !== "object") return {eligible:false, blockers:["invalid_product"]};
  if (!/^[A-Z0-9]{10}$/.test(String(item.asin || ""))) blockers.push("asin_missing");
  if (item.market !== "US") blockers.push("market_not_supported");
  if (!item.brand || !item.name) blockers.push("brand_or_name_missing");
  if (item.offerCondition !== "NEW_VERIFIED") blockers.push("new_condition_unverified");
  if (!Number.isFinite(item.livePriceUsd) || item.livePriceUsd <= 0) blockers.push("live_price_unverified");
  if (!Number.isFinite(item.confirmedCommissionPct) || item.confirmedCommissionPct <= 0) blockers.push("commission_unverified");
  if (!Number.isInteger(item.recentUnitsVerified) || item.recentUnitsVerified < 1) blockers.push("recent_demand_unverified");
  const estimatedCommissionUsd = blockers.length === 0 ?
    Number((item.livePriceUsd * item.confirmedCommissionPct / 100).toFixed(2)) : null;
  return {eligible:blockers.length === 0, blockers, estimatedCommissionUsd};
}

const creative = Object.freeze({
  en: Object.freeze({
    title: "Frozen drinks at home — meet Ninja SLUSHi",
    caption: [
      "AD | Looking for frozen drink ideas for your next gathering?",
      "Meet the Ninja SLUSHi Frozen Drink Maker: five presets, RapidChill and no ice needed for compatible drinks.",
      "Check the actual model, condition, price, warranty and delivery options on Amazon before ordering.",
      "Explore the product through the affiliate link in our bio.",
      "Concept artwork generated with AI. Please check product photos and specifications on Amazon.",
      "As an Amazon Associate, I earn from qualifying purchases.",
      "#ad #AmazonAffiliate #NinjaSLUSHi #FrozenDrinks #LUMENB2B"
    ].join("\n"),
    story: "AD | Ninja SLUSHi: frozen drinks for your next gathering. Tap the link sticker to check the product on Amazon. Affiliate link. AI concept artwork."
  }),
  es: Object.freeze({
    title: "Bebidas heladas en casa — conocé Ninja SLUSHi",
    caption: [
      "PUBLICIDAD | ¿Querés preparar bebidas heladas para tu próxima reunión?",
      "Conocé la Ninja SLUSHi: cinco programas, tecnología RapidChill y sin agregar hielo para bebidas compatibles.",
      "Verificá el modelo, la condición, el precio, la garantía y el envío en Amazon antes de comprar.",
      "Conocé el producto desde el enlace de afiliado en nuestra biografía.",
      "Imagen ilustrativa generada con IA. Verificá las fotos y características reales en Amazon.",
      "Como Afiliado de Amazon, gano comisiones por compras que cumplen los requisitos.",
      "#Publicidad #AfiliadoAmazon #NinjaSLUSHi #BebidasHeladas #LUMENB2B"
    ].join("\n"),
    story: "PUBLICIDAD | Ninja SLUSHi: bebidas heladas para tu próxima reunión. Tocá el sticker de enlace para verla en Amazon. Enlace de afiliado. Imagen ilustrativa con IA."
  })
});
export function buildAffiliateCampaign(locale = "en", product = AFFILIATE_PRODUCTS[0]) {
  if (!["en","es"].includes(locale)) throw Error("invalid_locale");
  const q = qualifyAffiliateProduct(product);
  return {
    version: AFFILIATE_POLICY.version,
    campaignId: "ninja-slushi-fs301-" + locale,
    market: "US",
    channel: "instagram",
    account: AFFILIATE_POLICY.channelHandle,
    product: {id:product.id, name:product.name, asin:product.asin, brand:product.brand},
    specialLink: specialLink(product.asin),
    publishing: {
      automatic: false,
      allowedSurfaces: ["instagram_feed_with_link_in_profile", "instagram_story_link_sticker"],
      directExternalMessage: false,
      paidPromotion: false,
      aiArtDisclosureRequired: true,
      affiliateDisclosureRequired: true
    },
    caption: creative[locale].caption,
    storyText: creative[locale].story,
    claimStatus: q,
    pricing: {verifiedLivePriceUsd:product.livePriceUsd, verifiedCategoryCommissionPct:product.confirmedCommissionPct},
    reportedMetrics: {clicks:null, orderedItems:null, shippedItems:null, commissionsUsd:null, source:"official_amazon_associates_report_required"},
    status: q.eligible ? "READY_FOR_CHANNEL_REVIEW" : "CREATIVE_PREPARED_PRODUCT_VERIFICATION_PENDING"
  };
}
const json = (obj,status=200) => Response.json(obj,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff"}});
export async function handleAffiliateSales(request,env) {
  const url = new URL(request.url);
  const path = url.pathname;
  if (!path.startsWith("/affiliate-sales/")) return null;
  if (request.method === "GET" && path === "/affiliate-sales/policy") return json({ok:true,...AFFILIATE_POLICY});
  const expected = String(env?.OPPORTUNITY_ADMIN_TOKEN || "");
  const supplied = String(request.headers.get("x-lumen-admin") || "");
  if (!expected || !supplied || expected !== supplied) return json({ok:false,error:"admin_token_required"},403);
  if (request.method !== "GET") return json({ok:false,error:"method_not_allowed"},405);
  if (path === "/affiliate-sales/campaign") {
    const locale = url.searchParams.get("locale") || "en";
    if (!["en","es"].includes(locale)) return json({ok:false,error:"invalid_locale"},400);
    return json({ok:true,campaign:buildAffiliateCampaign(locale)});
  }
  if (path === "/affiliate-sales/status") return json({
    ok:true,version:AFFILIATE_POLICY.version,
    activeCandidateCount:AFFILIATE_PRODUCTS.length,
    salesVerified:false,
    verifiedRevenueUsd:null,
    attributedOrders:null,
    instagramPublishingFromThisModule:false,
    sourceOfTruth:"Amazon Associates official reports; social publication must be separately confirmed",
    campaigns:AFFILIATE_PRODUCTS.map(item=>({
      id:item.id,asin:item.asin,readiness:qualifyAffiliateProduct(item)
    }))
  });
  return json({ok:false,error:"not_found"},404);
}
