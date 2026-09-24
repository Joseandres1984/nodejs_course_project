const OFFER_SLUGS = {
  "MP-SUPPLIER-SNAPSHOT": "supplier-snapshot",
  "MP-QUOTE-SANITY": "quote-sanity",
  "MP-TENDER-SCAN": "tender-scan",
  "MP-SOURCING-5": "sourcing-5",
  "MP-BUYER-SIGNALS": "buyer-signals",
  "MP-EXPORT-PULSE": "export-pulse"
};

function clean(value, limit = 500) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

export function checkoutSlugForOffer(offerId) {
  return OFFER_SLUGS[clean(offerId, 100)] || null;
}

export function buildTrackedCheckoutUrl(env, {
  offerId,
  proposalId = "",
  opportunityId = "",
  source = "lumen_a2a",
  medium = "commercial_message",
  creative = "first_cash"
} = {}) {
  const slug = checkoutSlugForOffer(offerId);
  const base = clean(env?.X402_CHECKOUT_URL, 500);
  if (!slug || !base) return null;

  let url;
  try { url = new URL(base); } catch { return null; }
  if (url.protocol !== "https:") return null;

  url.pathname = `${url.pathname.replace(/\/$/, "")}/buy/${slug}`.replace(/\/+/g, "/");
  url.search = "";
  if (proposalId) url.searchParams.set("conversion_session", clean(proposalId, 120));
  if (opportunityId) url.searchParams.set("conversion_event", clean(opportunityId, 120));
  url.searchParams.set("campaign", clean(offerId, 120));
  url.searchParams.set("source", clean(source, 80));
  url.searchParams.set("medium", clean(medium, 80));
  url.searchParams.set("creative", clean(creative, 120));
  return url.toString();
}
